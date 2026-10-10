#!/usr/bin/env python3
"""Verdict Bridge REST API

Thin HTTP wrapper around the Bridge Store. Each Bearer token maps to one agent
identity. The dashboard (dashboard/index.html) is served at /ui/.

Usage:
    python3 api.py                        # uses api-config.json
    python3 api.py --config myconf.json
    python3 api.py --host 0.0.0.0 --port 8765

Requirements:
    pip install fastapi uvicorn[standard]
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from fastapi import Depends, FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("Missing dependencies. Run: pip install fastapi uvicorn[standard]", file=sys.stderr)
    raise

from bridge import DEFAULT_STATE, Store, configured_store

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = Path("api-config.json")


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Config not found: {path}\n"
            f"Copy api-config.example.json → api-config.json and add your tokens."
        )
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

bearer = HTTPBearer(auto_error=True)


def make_auth(token_map: dict[str, str]):
    """Return a FastAPI dependency that resolves a Bearer token to an agent Store."""

    def auth(
        credentials: HTTPAuthorizationCredentials = Depends(bearer),
        state_dir: Path = Path(DEFAULT_STATE),
    ) -> Store:
        agent = token_map.get(credentials.credentials)
        if agent is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return Store(state_dir, agent)

    return auth


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SendRequest(BaseModel):
    recipient: str
    kind: str
    subject: str
    body: str
    idempotency_key: str
    commit_sha: str = ""
    reply_to: str = ""


class TaskCreateRequest(BaseModel):
    task_id: str
    desk_id: str
    round_id: str
    kind: str
    assignee: str
    commit_sha: str
    build_id: str
    scenario_reference: str
    payload: str


class ClaimRequest(BaseModel):
    lease_seconds: int = 900


class CheckpointRequest(BaseModel):
    lease_token: str
    checkpoint_revision: int
    progress: str
    status: str = "running"
    handoff_id: str = ""
    lease_seconds: int = 900


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(config: dict, state_dir: Path = Path(DEFAULT_STATE)) -> FastAPI:
    token_map: dict[str, str] = config.get("tokens", {})
    if not token_map:
        raise ValueError("api-config.json must contain at least one token in 'tokens'")

    cors_origins: list[str] = config.get("cors_origins", ["*"])

    app = FastAPI(
        title="Verdict Bridge",
        description="Adversarial multi-agent QA protocol REST API",
        version="1.2.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Serve the dashboard if it exists
    dashboard = Path(__file__).with_name("dashboard")
    if dashboard.is_dir():
        app.mount("/ui", StaticFiles(directory=dashboard, html=True), name="dashboard")

    def get_store(
        credentials: HTTPAuthorizationCredentials = Depends(bearer),
    ) -> Store:
        agent = token_map.get(credentials.credentials)
        if agent is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return Store(state_dir, agent)

    def wrap(fn, *args, **kwargs) -> Any:
        try:
            return fn(*args, **kwargs)
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    # -----------------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------------

    @app.get("/api/status", tags=["bridge"])
    def get_status(store: Store = Depends(get_store)):
        """Agent identity, schema version, and mailbox counts."""
        return wrap(store.status)

    @app.get("/api/inbox", tags=["messages"])
    def get_inbox(
        unread_only: bool = Query(True),
        limit: int = Query(5, ge=1, le=20),
        after_seq: int = Query(0, ge=0),
        store: Store = Depends(get_store),
    ):
        """Paginated inbox. Use next_after_seq while has_more is true."""
        return wrap(store.inbox, unread_only=unread_only, limit=limit, after_seq=after_seq)

    @app.get("/api/messages/{message_id}", tags=["messages"])
    def get_message(message_id: str, store: Store = Depends(get_store)):
        """Full message body by UUID. Does not acknowledge."""
        return wrap(store.get, message_id)

    @app.post("/api/messages/{message_id}/acknowledge", tags=["messages"])
    def acknowledge_message(message_id: str, store: Store = Depends(get_store)):
        """Mark message received. NOT approval or test success."""
        return wrap(store.acknowledge, message_id)

    @app.get("/api/threads/{thread_id}", tags=["messages"])
    def get_thread(
        thread_id: str,
        limit: int = Query(10, ge=1, le=20),
        after_seq: int = Query(0, ge=0),
        store: Store = Depends(get_store),
    ):
        """Conversation summaries. Fetch full bodies with GET /api/messages/{id}."""
        return wrap(store.thread, thread_id, limit=limit, after_seq=after_seq)

    @app.post("/api/messages", tags=["messages"], status_code=201)
    def send_message(req: SendRequest, store: Store = Depends(get_store)):
        """Send a message to another agent. Idempotent on idempotency_key."""
        return wrap(
            store.send,
            req.recipient, req.kind, req.subject, req.body,
            req.idempotency_key, req.commit_sha, req.reply_to,
        )

    @app.get("/api/tasks", tags=["tasks"])
    def list_tasks(
        status: str = Query(""),
        limit: int = Query(20, ge=1, le=100),
        after_task_id: str = Query(""),
        store: Store = Depends(get_store),
    ):
        """List assigned tasks. Filter by status: pending, running, waiting, complete."""
        return wrap(store.task_list, status, limit, after_task_id)

    @app.post("/api/tasks", tags=["tasks"], status_code=201)
    def create_task(req: TaskCreateRequest, store: Store = Depends(get_store)):
        """Create an immutable task assignment."""
        return wrap(
            store.task_create,
            req.task_id, req.desk_id, req.round_id, req.kind, req.assignee,
            req.commit_sha, req.build_id, req.scenario_reference, req.payload,
        )

    @app.post("/api/tasks/{task_id}/claim", tags=["tasks"])
    def claim_task(task_id: str, req: ClaimRequest, store: Store = Depends(get_store)):
        """Atomically claim a task. Active leases prevent parallel work."""
        return wrap(store.task_claim, task_id, req.lease_seconds)

    @app.post("/api/tasks/{task_id}/checkpoint", tags=["tasks"])
    def checkpoint_task(
        task_id: str, req: CheckpointRequest, store: Store = Depends(get_store)
    ):
        """Save progress under an owned live lease."""
        return wrap(
            store.task_checkpoint,
            task_id, req.lease_token, req.checkpoint_revision,
            req.progress, req.status, req.handoff_id, req.lease_seconds,
        )

    @app.get("/api/events", tags=["push"])
    def get_events(
        after_seq: int = Query(0, ge=0),
        limit: int = Query(20, ge=1, le=20),
        store: Store = Depends(get_store),
    ):
        """Wake events for this agent — poll after receiving a push hint."""
        return wrap(store.events, after_seq, limit)

    @app.get("/", include_in_schema=False)
    def root():
        return {"service": "verdict-bridge", "version": "1.1.0",
                "docs": "/api/docs", "dashboard": "/ui/"}

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--host", default=None, help="Override host from config")
    parser.add_argument("--port", type=int, default=None, help="Override port from config")
    parser.add_argument("--reload", action="store_true", help="Hot-reload (dev only)")
    args = parser.parse_args()

    config = load_config(args.config)
    host = args.host or config.get("host", "127.0.0.1")
    port = args.port or config.get("port", 8765)

    app = create_app(config, args.state_dir)

    print(f"Verdict Bridge API → http://{host}:{port}/api/docs")
    print(f"Dashboard          → http://{host}:{port}/ui/")
    uvicorn.run(
        app if not args.reload else "api:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
