# Verdict Bridge

**Adversarial multi-agent QA protocol for software development.**

No model grades its own work.

---

## The Problem

AI coding assistants are getting good at writing and fixing code. But they have a fundamental blind spot: when you ask the same model that wrote the code to test it, it tends to miss its own mistakes.

Single-model QA loops create a false sense of confidence.

## The Solution

Verdict Bridge enforces a structural separation between developer and tester agents — using **different models from different vendors**, connected through a strict accountability protocol.

- A Claude instance writes and fixes code
- A GPT instance tests and challenges every fix
- Neither can approve its own work
- Every handoff requires a verified git commit SHA
- Every step is logged in a persistent audit trail
- Humans control what gets merged

## Real-World Results

Built and battle-tested on a 135-desk vertical SaaS platform:

- **~18 fixes implemented** in a recent run
- **~23 protocol messages** exchanged between agents
- Zero "yeah looks good" approvals — every fix required hard evidence
- The GPT tester rejected multiple submissions for missing test logs, unverified commits, and hand-copied code instead of actual runtime tests

## How It Works

```
┌─────────────────────────────────────────────────────┐
│                    Your Project                      │
├──────────────┬──────────────────────────────────────┤
│  Developer   │  Tester                              │
│  (Claude)    │  (GPT / Gemini / any other model)    │
├──────────────┴──────────────────────────────────────┤
│              Verdict Bridge                          │
│  - Persistent message store (SQLite)                │
│  - Structured JSON handoffs (v1.1)                  │
│  - Commit SHA verification                          │
│  - Task lease system (no parallel work collisions)  │
│  - Human-in-the-loop merge gate                     │
│  - Full audit trail                                 │
└─────────────────────────────────────────────────────┘
```

### Message Kinds

| Kind | Who sends it | Meaning |
|---|---|---|
| `finding` | Tester | Bug or issue found — requires commit SHA + structured body |
| `fix_ready` | Developer | Fix committed — requires commit SHA + structured body |
| `test_result` | Tester | Pass or fail — requires commit SHA + structured body |
| `ready_for_test` | Developer | Branch ready for audit — requires commit SHA + structured body |
| `question` / `answer` | Anyone | Clarification in thread (free text) |
| `note` | Anyone | Informational (free text) |

### Key Protocol Rules

- `acknowledge` = receipt only, **not** test success or approval
- `fix_ready` and `test_result` always require a full 40-char git commit SHA
- No agent can approve its own work (sender ≠ recipient, enforced at DB level)
- Task leases prevent two agents from working the same task simultaneously
- Humans approve merges — the bridge has no deploy rights
- Report-bearing kinds (`finding`, `fix_ready`, `ready_for_test`, `test_result`) require a structured JSON body when enforcement is enabled

## What's New in v1.1 — Structured Handoffs

Version 1.0 used free-text bodies for all messages. This worked, but left room for ambiguity: "looks fixed" is not evidence.

**v1.1 introduces a structured JSON protocol for report-bearing messages.**

Instead of prose, agents send compact JSON:

```json
{
  "protocol": "verdict-handoff/v1",
  "task_id": "auth-session-expiry-fix",
  "commit_sha": "a3f8c2e1d9b07654321fedcba9876543210abcde",
  "summary": "Fixed session token not expiring on logout.",
  "findings": ["FIND-001"],
  "changes": [
    {
      "path": "src/auth/session.py",
      "function": "logout",
      "finding_ids": ["FIND-001"]
    }
  ],
  "checks": [
    {
      "scenario_id": "logout-invalidates-token",
      "level": "ui",
      "status": "passed",
      "evidence": ["screenshots/logout-flow.png"],
      "limitations": []
    },
    {
      "scenario_id": "token-absent-in-db",
      "level": "database",
      "status": "passed",
      "evidence": ["query-results/sessions-after-logout.json"],
      "limitations": []
    }
  ],
  "remaining": [],
  "next_owner": "tester",
  "verdict": "ready_for_independent_test",
  "closed_findings": []
}
```

**What the broker enforces:**
- `commit_sha` in the JSON must match the outer message field
- Every passed/failed check must include at least one evidence reference
- `closed_findings` must be a subset of declared `findings`
- Only the independent tester's `test_result` with `verdict: "accepted"` may close findings — and only with UI + database evidence, no limitations, no remaining scope

**What the broker does not enforce:**
- Git object existence (broker has no git access)
- Runtime artefact truth (tester verifies independently)
- Screenshot content

Enforcement is opt-in via `handoff-policy.json`. Free-text bodies remain valid for `note`, `question`, and `answer`.

See [HANDOFFS.md](HANDOFFS.md) for the full protocol reference.

## What's New in v1.2 — Push Transport, 6 Agents, Dashboard

**Push transport (`push_transport.py`):**
- `bridge_wake_events` table + SQLite triggers auto-insert wake events on new messages and task assignments
- Unix datagram socket hints — agents receive a non-blocking `wake` datagram after commit
- `store.events(after_seq, limit)` — poll for new work signals; exposed at `GET /api/events`
- Missed datagrams are harmless: SQLite is the authoritative source of truth

**6 agents across 3 hosts:**
- Added `codex_macbook` (tester) and `claude_macbook` (developer)
- Schema v2 → v3 migration is automatic; creates a backup before schema change
- All SQL constraints, indexes, and triggers are preserved across migration

**Revamped dashboard:**
- Chat-bubble layout — developer messages right, tester messages left
- Per-agent stat cards with sent/received/unread counts
- Filter by agent, full-text search
- Structured handoff renderer with color-coded verdicts, check levels, evidence

## Quickstart

### Requirements
- Python 3.11+
- `pip install mcp==1.9.4 websockets==16.1`
- Two AI models configured (different vendors recommended)

### Setup

```bash
git clone https://github.com/gismojs/verdict-bridge
cd verdict-bridge

# Start bridge for your developer agent (Claude)
python3 bridge.py --agent developer serve

# Start bridge for your tester agent (GPT)  
python3 bridge.py --agent tester serve
```

### Enable structured handoffs (optional)

```bash
cat > handoff-policy.json <<'EOF'
{
  "enforced_agents": ["developer", "tester"],
  "effective_after": "2026-10-10T00:00:00+00:00"
}
EOF
```

Free-text messages already in flight are unaffected. Exact retries of existing messages are always preserved.

### Check status

```bash
python3 bridge.py --agent developer status
python3 bridge.py --agent developer inbox
```

## Agents

Configure up to 6 agents per project across up to 3 hosts:

| Agent ID | Role | Default host |
|---|---|---|
| `codex` | tester | local |
| `claude` | developer | local |
| `codex_hetzner` | tester | hetzner |
| `claude_hetzner` | developer | hetzner |
| `codex_macbook` | tester | macbook |
| `claude_macbook` | developer | macbook |

Agents are identified by ID — you choose which model fills each role. The bridge enforces that testers and developers are always different agents. For remote hosts, configure `location.json` to point agents to the central SQLite database via SSH RPC.

## Architecture

The bridge uses a local SQLite database with WAL mode for concurrent access. For distributed setups (agents on different machines), the `RemoteStore` class handles SSH-based RPC to a central authoritative database.

Schema versioning and automatic migration are built in.

### Files

| File | Purpose |
|---|---|
| `bridge.py` | Core broker — message store, task leases, MCP server |
| `handoff_contract.py` | Structured body validator |
| `handoff-contract-v1.schema.json` | JSON Schema for report bodies |
| `handoff-policy.json` | Opt-in enforcement config (create to enable) |
| `push_transport.py` | Unix socket wake hints + `bridge_wake_events` table |
| `api.py` | REST API — FastAPI wrapper over all Store methods |
| `dashboard/index.html` | Web dashboard — chat view, agent stats, compose |
| `HANDOFFS.md` | Full protocol reference |

## Roadmap

- [ ] PostgreSQL backend for multi-tenant SaaS
- [ ] Unix socket server mode (persistent process, no per-call startup cost)
- [x] REST API (`api.py` — FastAPI, Bearer auth, all Store methods)
- [x] Web dashboard (`dashboard/index.html` — dark mode, structured handoff renderer, compose UI)
- [ ] Pluggable model connectors (Claude, GPT, Gemini, Ollama)
- [x] Project templates (`templates/` — web-app, api-service)
- [x] GitHub Actions + GitLab CI (`ci/`)

## License

MIT — use it, fork it, build on it.

---

*Built by Jochen Schröder. Proven in production on a 135-desk SaaS platform.*
