"""Optional additive durable wake transport for Verdict Bridge.

Wake hints are disposable; SQLite is the authoritative source of truth.
A missed datagram means the recipient polls on its next cycle — no data loss.

The bridge_wake_events table is append-only and never modifies the messages
schema. It can be added to an existing v3 database without migration.
"""
import json
import os
import socket
import stat
from datetime import datetime, timezone

# Must match handoff_contract.RECEIPT_PROTOCOL
_RECEIPT_PROTOCOL = "verdict-receipt/v1"


def ensure_schema(db):
    """Idempotently create wake-event table, indexes, and triggers.

    Safe to call on every Store.__init__ — all statements use IF NOT EXISTS.
    Requires SQLite with json_valid() support (3.38+).
    """
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    # Smoke-test JSON support so we fail closed rather than silently.
    db.execute("SELECT json_valid('{}')").fetchone()
    db.execute("""
        CREATE TABLE IF NOT EXISTS bridge_wake_events (
            event_seq        INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient        TEXT NOT NULL,
            kind             TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            source_message_id TEXT
        )
    """)
    # Back-fill column if table was created before source_message_id existed.
    existing_cols = {r[1] for r in db.execute("PRAGMA table_info(bridge_wake_events)")}
    if "source_message_id" not in existing_cols:
        db.execute("ALTER TABLE bridge_wake_events ADD COLUMN source_message_id TEXT")
    db.execute("""
        CREATE INDEX IF NOT EXISTS bridge_wake_recipient
            ON bridge_wake_events(recipient, event_seq)
    """)
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS bridge_wake_source_message
            ON bridge_wake_events(source_message_id)
    """)
    # Automatic wake event on every new message, except receipt-only bodies.
    # Receipt bodies (verdict-receipt/v1 with receipt_only=true) carry no new
    # work — suppressing them avoids spurious model wake-ups.
    db.execute(f"""
        CREATE TRIGGER IF NOT EXISTS bridge_wake_message_v1
        AFTER INSERT ON messages
        WHEN COALESCE(
            CASE WHEN json_valid(NEW.body) THEN
                json_type(NEW.body) = 'object'
                AND json_extract(NEW.body, '$.protocol') = '{_RECEIPT_PROTOCOL}'
                AND json_type(NEW.body, '$.receipt_only') = 'true'
                AND json_type(NEW.body, '$.message_id') = 'text'
                AND json_extract(NEW.body, '$.message_id') = NEW.reply_to
                AND NEW.reply_to IS NOT NULL
                AND NEW.kind IN ('note', 'answer')
                AND (SELECT COUNT(*) FROM json_each(NEW.body)) = 3
            ELSE 0 END,
        0) = 0
        BEGIN
            INSERT OR IGNORE INTO bridge_wake_events
                (recipient, kind, created_at, source_message_id)
            VALUES (NEW.recipient, 'message', NEW.created_at, NEW.id);
        END
    """)
    # Suppress redundant NULL-source events from older writers that still call
    # append_event() manually after the trigger already fired.
    db.execute("""
        CREATE TRIGGER IF NOT EXISTS bridge_wake_legacy_hook_v1
        BEFORE INSERT ON bridge_wake_events
        WHEN NEW.kind = 'message' AND NEW.source_message_id IS NULL
          AND EXISTS (
              SELECT 1 FROM bridge_wake_events
              WHERE source_message_id = (
                  SELECT id FROM messages
                  WHERE recipient = NEW.recipient
                  ORDER BY seq DESC LIMIT 1
              )
          )
        BEGIN
            SELECT RAISE(IGNORE);
        END
    """)


def append_event(db, recipient: str, kind: str, *,
                 body: str | None = None,
                 source_message_id: str | None = None) -> int | None:
    """Insert a wake event; returns event_seq or None for suppressed receipts."""
    if body is not None:
        try:
            receipt = json.loads(body)
        except (TypeError, ValueError):
            receipt = None
        if (isinstance(receipt, dict)
                and receipt.get("protocol") == _RECEIPT_PROTOCOL
                and receipt.get("receipt_only") is True):
            return None
    cur = db.execute(
        "INSERT OR IGNORE INTO bridge_wake_events"
        " (recipient, kind, created_at, source_message_id) VALUES (?,?,?,?)",
        (recipient, kind, datetime.now(timezone.utc).isoformat(), source_message_id),
    )
    if source_message_id:
        row = db.execute(
            "SELECT event_seq FROM bridge_wake_events WHERE source_message_id=?",
            (source_message_id,),
        ).fetchone()
        return row[0] if row else None
    return cur.lastrowid


def notify_hint(state_dir, recipient: str) -> None:
    """Send a non-blocking UDP datagram to the recipient's Unix socket.

    Called only after a successful commit. The datagram carries no payload,
    no secret, and no model instructions. A missed send is harmless — the
    recipient will catch up on its next polling cycle.
    """
    try:
        parent = state_dir.stat()
        path = state_dir / f"wake-{recipient}.sock"
        info = path.lstat()
        # Security checks: no symlinks, owner-private directory and socket.
        if (
            state_dir.is_symlink()
            or parent.st_uid != os.getuid()
            or parent.st_mode & 0o077
            or not stat.S_ISSOCK(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
        ):
            return
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            sock.sendto(b"wake", str(path))
    except OSError:
        pass


def events_for(db, recipient: str, after_seq: int, limit: int) -> list[dict]:
    """Return wake events for *recipient* after *after_seq*, oldest first."""
    rows = db.execute(
        "SELECT event_seq, recipient, kind, created_at"
        " FROM bridge_wake_events"
        " WHERE recipient=? AND event_seq>?"
        " ORDER BY event_seq LIMIT ?",
        (recipient, after_seq, limit),
    ).fetchall()
    return [dict(r) for r in rows]
