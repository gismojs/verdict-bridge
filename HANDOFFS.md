# Structured Handoffs — Verdict Bridge v1.1

Report-bearing message kinds (`ready_for_test`, `finding`, `fix_ready`,
`test_result`) use a structured JSON body validated against
`handoff-contract-v1.schema.json`.

Free-text bodies remain valid for `note`, `question`, and `answer`.

---

## Why structured handoffs?

Prose reports are ambiguous. "Looks fixed" is not evidence.
Structured handoffs require:

- explicit commit SHA (matched against the outer field)
- per-finding change records with file paths and functions
- per-check evidence artefacts and declared limitations
- a machine-verifiable verdict

The broker validates structure. **It does not verify git objects, runtime
artefacts, or claim truth** — that remains the independent tester's job.

---

## Enabling enforcement

Create `handoff-policy.json` next to `bridge.py`:

```json
{
  "enforced_agents": ["developer", "tester"],
  "effective_after": "2026-10-10T00:00:00+00:00"
}
```

`effective_after` gives in-flight free-text messages a grace window.
Exact retries of already-stored messages are always preserved.

---

## Body schema

```json
{
  "protocol": "verdict-handoff/v1",
  "task_id": "your-task-id",
  "commit_sha": "<full 40-char SHA>",
  "summary": "One-sentence description of what changed.",
  "findings": ["FIND-001", "FIND-002"],
  "changes": [
    {
      "path": "src/api/bookings.py",
      "function": "create_booking",
      "finding_ids": ["FIND-001"]
    }
  ],
  "checks": [
    {
      "scenario_id": "booking-happy-path",
      "level": "ui",
      "status": "passed",
      "evidence": ["screenshots/booking-flow-2026-10-10.png"],
      "limitations": []
    },
    {
      "scenario_id": "booking-db-consistency",
      "level": "database",
      "status": "passed",
      "evidence": ["query-results/booking-rows.json"],
      "limitations": []
    }
  ],
  "remaining": [],
  "next_owner": "tester",
  "verdict": "ready_for_independent_test",
  "closed_findings": []
}
```

### Verdict values

| Verdict | Meaning |
|---|---|
| `progress` | Work in progress, not ready for test |
| `needs_changes` | Tester rejected — developer must act |
| `ready_for_independent_test` | Developer done, tester's turn |
| `accepted` | Tester independently confirmed all findings closed |

### Check levels

| Level | What it means |
|---|---|
| `source` | Code review only |
| `memory` | Agent memory / prior session knowledge |
| `api` | HTTP/RPC response checked |
| `database` | Row-level query executed |
| `ui` | Full browser / UI flow exercised |
| `concurrency` | Parallel execution tested |

Passing or failing checks **must** include at least one evidence artefact
reference. Limitations (if any) are free-text strings.

### Acceptance rules

Only the **independent tester's** `test_result` with `verdict: "accepted"` may
close findings. The following are required:

- `closed_findings` ⊆ `findings`
- At least one `ui` check and one `database` check, both `passed`
- No check with `status` ≠ `passed`
- No limitations on any check
- `remaining` must be empty

---

## Receipt shortcut

For pure acknowledgements (no model response needed), use:

```json
{
  "protocol": "verdict-receipt/v1",
  "receipt_only": true,
  "message_id": "<UUID of the received message>"
}
```

Send as `note` or `answer` with `reply_to` set to that message's UUID.
No additional fields allowed.

---

*This is a protocol specification, not a verified handoff example.*
