# Verdict Bridge

**Adversarial multi-agent QA protocol for software development.**

No model grades its own work.

---

## The Problem

AI coding assistants are getting good at writing and fixing code. But they have a fundamental blind spot: when you ask the same model that wrote the code to test it, it tends to miss its own mistakes.

Single-model QA loops create a false sense of confidence.

## The Solution

Verdict enforces a structural separation between developer and tester agents — using **different models from different vendors**, connected through a strict accountability protocol.

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
│  - Commit SHA verification                          │
│  - Task lease system (no parallel work collisions)  │
│  - Human-in-the-loop merge gate                     │
│  - Full audit trail                                 │
└─────────────────────────────────────────────────────┘
```

### Message Kinds

| Kind | Who sends it | Meaning |
|---|---|---|
| `finding` | Tester | Bug or issue found — requires commit SHA |
| `fix_ready` | Developer | Fix committed — requires verified SHA |
| `test_result` | Tester | Pass or fail on a specific fix |
| `ready_for_test` | Developer | Branch ready for audit round |
| `question` / `answer` | Anyone | Clarification in thread |
| `note` | Anyone | Informational |

### Key Protocol Rules

- `acknowledge` = receipt only, **not** test success or approval
- `fix_ready` and `test_result` always require a full 40-char git commit SHA
- No agent can approve its own work (sender ≠ recipient, enforced at DB level)
- Task leases prevent two agents from working the same task simultaneously
- Humans approve merges — the bridge has no deploy rights

## Quickstart

### Requirements
- Python 3.11+
- `pip install mcp==1.9.4 websockets==16.1`
- Two AI models configured (different vendors recommended)

### Setup

```bash
git clone https://github.com/your-org/verdict-bridge
cd verdict-bridge

# Start bridge for your developer agent (Claude)
python3 bridge.py --agent developer serve

# Start bridge for your tester agent (GPT)  
python3 bridge.py --agent tester serve
```

### Check status

```bash
python3 bridge.py --agent developer status
python3 bridge.py --agent developer inbox
```

## Agents

Configure up to 4 agents per project (2 developers, 2 testers). Agents are identified by role — you choose which model fills each role. The bridge enforces that testers and developers are always different agents.

## Architecture

The bridge uses a local SQLite database with WAL mode for concurrent access. For distributed setups (agents on different machines), the `RemoteStore` class handles SSH-based RPC to a central authoritative database.

Schema versioning and automatic migration are built in.

## Roadmap

- [ ] PostgreSQL backend for multi-tenant SaaS
- [ ] REST API (currently stdio/SSH RPC)
- [ ] Web dashboard with live thread view and merge gate
- [ ] Pluggable model connectors (Claude, GPT, Gemini, Ollama)
- [ ] Project templates (Web app, API, Microservice)
- [ ] GitHub/GitLab CI integration

## License

MIT — use it, fork it, build on it.

---

*Built by Jochen Schröder. Proven in production on a 135-desk SaaS platform.*  
