# Verdict Bridge — Web App Template

Drop this into the root of your web application project.

## Setup

```bash
# 1. Copy bridge files into your project
cp path/to/verdict-bridge/bridge.py .
cp path/to/verdict-bridge/handoff_contract.py .
cp path/to/verdict-bridge/handoff-contract-v1.schema.json .
cp path/to/verdict-bridge/api-config.example.json api-config.json

# 2. Edit api-config.json — replace tokens with long random secrets
#    python3 -c "import secrets; print(secrets.token_hex(32))"

# 3. Install deps
pip install fastapi uvicorn[standard] mcp==1.9.4 websockets==16.1

# 4. Enable structured handoffs (optional but recommended)
cp path/to/verdict-bridge/handoff-policy.example.json handoff-policy.json
# Edit effective_after to a timestamp ~5 minutes from now

# 5. Start the REST API (developer uses /api endpoint, tester uses theirs)
python3 path/to/verdict-bridge/api.py

# 6. Open the dashboard
open http://localhost:8765/ui/
```

## Typical QA cycle

### Developer side
```bash
# After fixing a bug:
git commit -m "Fix: session expiry on logout"
SHA=$(git rev-parse HEAD)

# Post fix_ready (or use MCP / REST API)
python3 bridge.py --agent developer send \
  --to tester --kind fix_ready \
  --subject "Fix: session expiry" \
  --body '{"protocol":"verdict-handoff/v1","task_id":"TASK-1","commit_sha":"'$SHA'","summary":"Fixed logout handler","findings":["FIND-001"],"changes":[{"path":"src/auth.py","function":"logout","finding_ids":["FIND-001"]}],"checks":[{"scenario_id":"logout-flow","level":"source","status":"passed","evidence":["review-notes.md"],"limitations":["No browser test yet"]}],"remaining":["Full browser flow"],"next_owner":"tester","verdict":"progress","closed_findings":[]}' \
  --key "fix-session-expiry-$(date +%s)" \
  --commit "$SHA"
```

### Tester side
```bash
# Check inbox
python3 bridge.py --agent tester inbox

# After successful full browser + DB test, post test_result
SHA=$(git rev-parse origin/main)
python3 bridge.py --agent tester send \
  --to developer --kind test_result \
  --subject "ACCEPTED: session expiry" \
  --body '{"protocol":"verdict-handoff/v1","task_id":"TASK-1","commit_sha":"'$SHA'","summary":"All flows pass","findings":["FIND-001"],"changes":[],"checks":[{"scenario_id":"logout-flow","level":"ui","status":"passed","evidence":["screenshots/logout-20261010.png"],"limitations":[]},{"scenario_id":"session-db","level":"database","status":"passed","evidence":["query/sessions-empty.json"],"limitations":[]}],"remaining":[],"next_owner":"developer","verdict":"accepted","closed_findings":["FIND-001"]}' \
  --key "result-session-expiry-$(date +%s)" \
  --commit "$SHA"
```

## Protocol invariants for web apps

- Every UI flow test must exercise: input → save → page reload → fresh context → dependent module → business outcome
- A screenshot of a passing state is not proof without a DB query showing the data
- The bridge logs everything — your audit trail is automatic
- Humans merge. The bridge never touches your deployment.
