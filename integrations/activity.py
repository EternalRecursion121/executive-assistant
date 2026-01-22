#!/usr/bin/env python3
"""Activity logging for Iris.

Captures meaningful events for later reflection. Call this throughout
operation to build context for journaling subagents.

Usage:
    python3 activity.py log <type> "<description>" [--meta '<json>']
    python3 activity.py recent [hours]        # recent activity (default: 24h)
    python3 activity.py today                 # today's activity
    python3 activity.py summary               # summarize recent activity
    python3 activity.py types                 # list activity types

Activity types:
    conversation  - interaction with a user
    task          - something completed
    integration   - external service used
    error         - something went wrong
    decision      - choice made (and why)
    feedback      - user reaction (positive/negative)
    modification  - code/config changed
    observation   - something noticed
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

STATE_DIR = Path("/home/executive-assistant/workspace/state")
ACTIVITY_FILE = STATE_DIR / "activity.json"

ACTIVITY_TYPES = [
    "conversation",
    "task",
    "integration",
    "error",
    "decision",
    "feedback",
    "modification",
    "observation"
]


def ensure_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_activity() -> list[dict]:
    if not ACTIVITY_FILE.exists():
        return []
    try:
        return json.loads(ACTIVITY_FILE.read_text())
    except:
        return []


def save_activity(entries: list[dict]) -> None:
    ensure_dir()
    ACTIVITY_FILE.write_text(json.dumps(entries, indent=2))


def log_activity(activity_type: str, description: str, meta: dict = None) -> dict:
    """Log an activity event."""
    if activity_type not in ACTIVITY_TYPES:
        return {"error": f"unknown type '{activity_type}'", "valid_types": ACTIVITY_TYPES}

    entry = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M"),
        "type": activity_type,
        "description": description
    }

    if meta:
        entry["meta"] = meta

    entries = load_activity()
    entries.append(entry)

    # Keep last 1000 entries
    if len(entries) > 1000:
        entries = entries[-1000:]

    save_activity(entries)
    return {"logged": entry}


def get_recent(hours: int = 24) -> dict:
    """Get activity from the last N hours."""
    cutoff = datetime.now() - timedelta(hours=hours)
    entries = load_activity()

    recent = [
        e for e in entries
        if datetime.fromisoformat(e["timestamp"]) > cutoff
    ]

    return {
        "hours": hours,
        "count": len(recent),
        "entries": recent
    }


def get_today() -> dict:
    """Get today's activity."""
    today = datetime.now().strftime("%Y-%m-%d")
    entries = load_activity()

    today_entries = [e for e in entries if e.get("date") == today]

    return {
        "date": today,
        "count": len(today_entries),
        "entries": today_entries
    }


def summarize() -> dict:
    """Summarize recent activity by type."""
    recent = get_recent(24)
    entries = recent["entries"]

    by_type = {}
    for e in entries:
        t = e.get("type", "unknown")
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(e["description"])

    return {
        "period": "last 24 hours",
        "total": len(entries),
        "by_type": {k: {"count": len(v), "items": v} for k, v in by_type.items()}
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"usage": "activity.py <log|recent|today|summary|types>"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "log" and len(sys.argv) >= 4:
        activity_type = sys.argv[2]
        description = sys.argv[3]
        meta = None
        if "--meta" in sys.argv:
            idx = sys.argv.index("--meta")
            if idx + 1 < len(sys.argv):
                try:
                    meta = json.loads(sys.argv[idx + 1])
                except:
                    meta = {"raw": sys.argv[idx + 1]}
        print(json.dumps(log_activity(activity_type, description, meta), indent=2))

    elif cmd == "recent":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        print(json.dumps(get_recent(hours), indent=2))

    elif cmd == "today":
        print(json.dumps(get_today(), indent=2))

    elif cmd == "summary":
        print(json.dumps(summarize(), indent=2))

    elif cmd == "types":
        print(json.dumps({"types": ACTIVITY_TYPES}, indent=2))

    else:
        print(json.dumps({"error": "invalid command"}))


if __name__ == "__main__":
    main()
