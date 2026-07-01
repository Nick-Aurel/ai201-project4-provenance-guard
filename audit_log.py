import json
import os
from datetime import datetime, timezone
from typing import Optional

AUDIT_LOG_PATH = os.path.join(os.path.dirname(__file__), "audit_log.json")


def _load_entries() -> list:
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_entries(entries: list) -> None:
    with open(AUDIT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def append_entry(entry: dict) -> dict:
    """Append a structured audit log entry and return it."""
    entries = _load_entries()
    if "timestamp" not in entry:
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    entries.append(entry)
    _save_entries(entries)
    return entry


def get_log(limit: int = 50) -> list:
    """Return the most recent audit log entries."""
    entries = _load_entries()
    return entries[-limit:]


def update_entry_for_appeal(content_id: str, appeal_reasoning: str) -> Optional[dict]:
    """Update the audit log entry for a submission with appeal details."""
    entries = _load_entries()
    for entry in reversed(entries):
        if entry.get("content_id") == content_id:
            entry["status"] = "under_review"
            entry["appeal_reasoning"] = appeal_reasoning
            entry["appeal_timestamp"] = datetime.now(timezone.utc).isoformat()
            _save_entries(entries)
            return entry
    return None
