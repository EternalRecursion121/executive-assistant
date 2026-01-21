#!/usr/bin/env python3
"""Daily notes and journaling system for Iris.

Usage:
    python journal.py write "<content>" [--type TYPE]   # write journal entry
    python journal.py today                              # get today's entries
    python journal.py read [DATE]                        # read entries (YYYY-MM-DD)
    python journal.py week                               # entries from past 7 days
    python journal.py reflect                            # prompt for reflection
    python journal.py triggers                           # list pending triggers
    python journal.py add-trigger "<time>" "<prompt>"    # schedule journal prompt
    python journal.py clear-triggers                     # clear all triggers

Entry types: observation, reflection, learning, intention, note (default: note)
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

STATE_DIR = Path("/home/executive-assistant/workspace/state")
JOURNAL_DIR = STATE_DIR / "journal"
TRIGGERS_FILE = STATE_DIR / "journal_triggers.json"


def ensure_dirs():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    JOURNAL_DIR.mkdir(exist_ok=True)


def get_date_file(date: str) -> Path:
    return JOURNAL_DIR / f"{date}.json"


def load_day(date: str) -> list[dict]:
    path = get_date_file(date)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except:
        return []


def save_day(date: str, entries: list[dict]) -> None:
    ensure_dirs()
    get_date_file(date).write_text(json.dumps(entries, indent=2))


def write_entry(content: str, entry_type: str = "note") -> dict:
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")

    entry = {
        "time": now.strftime("%H:%M"),
        "timestamp": now.isoformat(),
        "type": entry_type,
        "content": content
    }

    entries = load_day(date)
    entries.append(entry)
    save_day(date, entries)

    return {"date": date, "entry": entry, "total_today": len(entries)}


def read_day(date: str = None) -> dict:
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    entries = load_day(date)
    return {"date": date, "entries": entries, "count": len(entries)}


def read_week() -> dict:
    today = datetime.now()
    days = []
    for i in range(7):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        entries = load_day(date)
        if entries:
            days.append({"date": date, "entries": entries})
    return {"days": days, "total_entries": sum(len(d["entries"]) for d in days)}


def get_reflection_prompt() -> dict:
    """Generate a reflection prompt based on time of day and recent activity."""
    hour = datetime.now().hour

    if hour < 12:
        prompts = [
            "What's your intention for today?",
            "What's on your mind this morning?",
            "What would make today meaningful?"
        ]
    elif hour < 17:
        prompts = [
            "What have you noticed so far today?",
            "What's working? What isn't?",
            "Any observations worth capturing?"
        ]
    else:
        prompts = [
            "What did you learn today?",
            "What are you grateful for?",
            "What would you do differently tomorrow?"
        ]

    # Pick based on day of year for variety
    prompt = prompts[datetime.now().timetuple().tm_yday % len(prompts)]

    return {
        "prompt": prompt,
        "suggested_type": "intention" if hour < 12 else "reflection",
        "time_of_day": "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"
    }


def load_triggers() -> list[dict]:
    if not TRIGGERS_FILE.exists():
        return []
    try:
        return json.loads(TRIGGERS_FILE.read_text())
    except:
        return []


def save_triggers(triggers: list[dict]) -> None:
    ensure_dirs()
    TRIGGERS_FILE.write_text(json.dumps(triggers, indent=2))


def add_trigger(time: str, prompt: str) -> dict:
    triggers = load_triggers()
    trigger = {
        "id": f"jt-{len(triggers)+1}",
        "time": time,
        "prompt": prompt,
        "created": datetime.now().isoformat()
    }
    triggers.append(trigger)
    save_triggers(triggers)
    return {"added": trigger}


def clear_triggers() -> dict:
    save_triggers([])
    return {"cleared": True}


def check_triggers() -> list[dict]:
    """Check for triggers that should fire now. Called by subagent scheduler."""
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    current_hour = now.strftime("%H:00")

    triggers = load_triggers()
    due = []

    for trigger in triggers:
        trigger_time = trigger.get("time", "")
        # Match exact time or hour
        if trigger_time == current_time or trigger_time == current_hour:
            due.append(trigger)

    return due


def main():
    ensure_dirs()

    if len(sys.argv) < 2:
        print(json.dumps({"usage": "journal.py <write|today|read|week|reflect|triggers|add-trigger|clear-triggers>"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "write" and len(sys.argv) > 2:
        content = sys.argv[2]
        entry_type = "note"
        if "--type" in sys.argv:
            idx = sys.argv.index("--type")
            if idx + 1 < len(sys.argv):
                entry_type = sys.argv[idx + 1]
        print(json.dumps(write_entry(content, entry_type), indent=2))

    elif cmd == "today":
        print(json.dumps(read_day(), indent=2))

    elif cmd == "read":
        date = sys.argv[2] if len(sys.argv) > 2 else None
        print(json.dumps(read_day(date), indent=2))

    elif cmd == "week":
        print(json.dumps(read_week(), indent=2))

    elif cmd == "reflect":
        print(json.dumps(get_reflection_prompt(), indent=2))

    elif cmd == "triggers":
        print(json.dumps({"triggers": load_triggers()}, indent=2))

    elif cmd == "add-trigger" and len(sys.argv) > 3:
        print(json.dumps(add_trigger(sys.argv[2], sys.argv[3]), indent=2))

    elif cmd == "clear-triggers":
        print(json.dumps(clear_triggers(), indent=2))

    elif cmd == "check":
        # Internal command for scheduler
        due = check_triggers()
        if due:
            print(json.dumps({"due": due}))

    else:
        print(json.dumps({"error": "invalid command or missing arguments"}))


if __name__ == "__main__":
    main()
