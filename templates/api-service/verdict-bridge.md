# Verdict Bridge — API Service Template

For REST APIs, microservices, and backend-only projects.

## Key differences from web-app template

- No UI-level checks required (no browser)
- Focus on `api` and `database` check levels
- CI integration recommended (see `/ci/github-actions.yml`)

## Acceptance criteria for APIs

Tester must independently verify:
1. **API check**: POST/GET/PATCH returns expected status codes and response shapes
2. **Database check**: row-level query confirms the DB state after the API call
3. No limitations on either check
4. `remaining` is empty

A passing API test alone is **not** enough to close a finding — DB state must be verified independently.

## Setup (same as web-app — see web-app/verdict-bridge.md)

## Typical task payload for API audits

```json
{
  "endpoints": ["/api/v1/bookings", "/api/v1/bookings/{id}"],
  "scenarios": [
    "booking-create-happy-path",
    "booking-create-duplicate-rejection",
    "booking-get-not-found"
  ],
  "contract": "contracts/bookings-v2.json"
}
```

## Minimal passing test_result for API service

```json
{
  "protocol": "verdict-handoff/v1",
  "task_id": "your-task-id",
  "commit_sha": "<40-char SHA>",
  "summary": "All booking API scenarios pass; DB rows confirmed.",
  "findings": ["API-001"],
  "changes": [],
  "checks": [
    {
      "scenario_id": "booking-create-happy-path",
      "level": "api",
      "status": "passed",
      "evidence": ["curl-results/booking-create.json"],
      "limitations": []
    },
    {
      "scenario_id": "booking-db-row",
      "level": "database",
      "status": "passed",
      "evidence": ["query-results/bookings-after-create.json"],
      "limitations": []
    }
  ],
  "remaining": [],
  "next_owner": "developer",
  "verdict": "accepted",
  "closed_findings": ["API-001"]
}
```
