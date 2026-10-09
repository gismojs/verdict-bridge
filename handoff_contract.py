"""Structured JSON handoff validation for Verdict Bridge.

Report-bearing message kinds (ready_for_test, finding, fix_ready, test_result)
use a structured JSON body validated against the handoff schema.
Free-text bodies are still accepted for note/question/answer.

Schema: handoff-contract-v1.schema.json
Policy: handoff-policy.json  (optional — if absent, schema validation is opt-in)
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import re

PROTOCOL = "verdict-handoff/v1"
RECEIPT_PROTOCOL = "verdict-receipt/v1"
REPORT_KINDS = {"ready_for_test", "finding", "fix_ready", "test_result"}
SCHEMA_PATH = Path(__file__).with_name("handoff-contract-v1.schema.json")
POLICY_PATH = Path(__file__).with_name("handoff-policy.json")


# ---------------------------------------------------------------------------
# Minimal schema validator (no external deps — only stdlib)
# ---------------------------------------------------------------------------

def _validate(value, rule, path="$"):
    expected = rule.get("type")
    types = {"object": dict, "array": list, "string": str}
    if expected and not isinstance(value, types[expected]):
        raise ValueError(f"{path} must be {expected}")
    if "const" in rule and value != rule["const"]:
        raise ValueError(f"{path} must equal {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        raise ValueError(f"{path} unsupported value {value!r}")
    if isinstance(value, str):
        min_len = rule.get("minLength", 0)
        max_len = rule.get("maxLength", 100_000)
        if len(value.strip()) < min_len or len(value) > max_len:
            raise ValueError(f"{path} invalid text length")
        if "pattern" in rule and not re.fullmatch(rule["pattern"], value):
            raise ValueError(f"{path} invalid format")
    if isinstance(value, dict):
        missing = set(rule.get("required", [])) - value.keys()
        if missing:
            raise ValueError(f"{path} missing fields: {', '.join(sorted(missing))}")
        props = rule.get("properties", {})
        if rule.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError(f"{path} unexpected fields: {value.keys() - props.keys()}")
        for key, child in props.items():
            if key in value:
                _validate(value[key], child, f"{path}.{key}")
    if isinstance(value, list):
        if len(value) < rule.get("minItems", 0):
            raise ValueError(f"{path} requires at least {rule['minItems']} item(s)")
        if rule.get("uniqueItems") and len(
            {json.dumps(x, sort_keys=True) for x in value}
        ) != len(value):
            raise ValueError(f"{path} contains duplicates")
        for index, item in enumerate(value):
            _validate(item, rule.get("items", {}), f"{path}[{index}]")
    for condition in rule.get("allOf", []):
        try:
            _validate(value, condition["if"], path)
        except ValueError:
            continue
        _validate(value, condition["then"], path)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def structured_body(body: str):
    """Return parsed dict if body is a valid JSON object with 'protocol', else None."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and "protocol" in data else None


def reports_enforced(agent: str) -> bool:
    """Return True if structured reports are mandatory for *agent* right now."""
    if not POLICY_PATH.exists():
        return False
    policy = json.loads(POLICY_PATH.read_text())
    if policy.get("effective_after"):
        activation = datetime.fromisoformat(policy["effective_after"])
        if activation.tzinfo is None:
            raise ValueError("handoff-policy.json: effective_after needs a timezone")
        if datetime.now(timezone.utc) < activation:
            return False
    return agent in policy.get("enforced_agents", [])


def validate_report(body: str, kind: str, commit_sha: str, sender: str,
                    db=None, reply_to: str = ""):
    """Validate body when it contains a structured JSON report.

    - Free-text bodies are accepted without error (returns None).
    - If a policy file mandates structured reports for *sender*, free-text
      bodies in REPORT_KINDS raise ValueError.
    - Receipt-only bodies (verdict-receipt/v1) are validated strictly.
    - Full handoff reports are validated against the JSON schema.

    *db* is an open sqlite3 connection used to verify task_id/desk_id
    consistency.  Pass None to skip database cross-checks.
    """
    data = structured_body(body)
    if data is None:
        if kind in REPORT_KINDS and reports_enforced(sender):
            raise ValueError(
                f"Structured body required for {kind}. "
                f"Use protocol {PROTOCOL!r}; schema: {SCHEMA_PATH}"
            )
        return None

    # --- Receipt shortcut ---
    if data["protocol"] == RECEIPT_PROTOCOL:
        allowed_keys = {"protocol", "receipt_only", "message_id"}
        if (
            set(data) != allowed_keys
            or data.get("receipt_only") is not True
            or kind not in {"note", "answer"}
            or not reply_to
            or data.get("message_id") != reply_to
        ):
            raise ValueError(
                "verdict-receipt/v1 body must contain exactly "
                "{protocol, receipt_only=true, message_id=<replied-to UUID>} "
                "and be sent as note/answer replying to that message."
            )
        return data

    # --- Full handoff report ---
    if data["protocol"] != PROTOCOL:
        raise ValueError(f"Unsupported protocol {data['protocol']!r}")

    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")
    _validate(data, json.loads(SCHEMA_PATH.read_text()))

    if data["commit_sha"] != commit_sha:
        raise ValueError(
            f"Report commit_sha {data['commit_sha']!r} differs from "
            f"outer message commit_sha {commit_sha!r}"
        )

    findings = set(data["findings"])
    if not set(data["closed_findings"]) <= findings:
        raise ValueError("closed_findings must reference declared findings")
    for change in data["changes"]:
        if not set(change["finding_ids"]) <= findings:
            raise ValueError("change.finding_ids must reference declared findings")

    # Acceptance gate: only independent tester test_result can close findings
    if data["closed_findings"] or data["verdict"] == "accepted":
        if sender != "tester" or kind != "test_result" or data["verdict"] != "accepted":
            raise ValueError(
                "Only an independent tester's test_result with verdict='accepted' "
                "may close findings."
            )
        levels = {c["level"] for c in data["checks"] if c["status"] == "passed"}
        if (
            not {"ui", "database"} <= levels
            or any(
                c["status"] != "passed" or c["limitations"]
                for c in data["checks"]
            )
            or data["remaining"]
        ):
            raise ValueError(
                "Acceptance requires evidenced UI and database passes, "
                "no failed/blocked/not_run checks, no limitations, "
                "and empty remaining scope."
            )

    # Optional DB cross-check
    if db is not None:
        task = db.execute(
            "SELECT * FROM tasks WHERE task_id=?", (data["task_id"],)
        ).fetchone()
        if task is None or task["desk_id"] != data["desk_id"]:
            raise ValueError("Report task_id/desk_id does not match an existing task")
        if sender not in {task["assignee"], task["created_by"]}:
            raise ValueError("Report sender is not the task assignee or coordinator")

    return data
