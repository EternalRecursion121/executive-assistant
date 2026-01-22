#!/usr/bin/env python3
"""Journal subagent for Iris self-reflection.

This script is spawned at configured times to allow Iris to reflect
and journal autonomously. It outputs prompts and context that should
be fed to a Claude session for reflection.

Usage:
    python journal_agent.py morning    # morning intention setting
    python journal_agent.py midday     # midday check-in
    python journal_agent.py evening    # evening reflection
    python journal_agent.py spawn      # determine what to spawn based on time
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# Import sibling modules
sys.path.insert(0, str(Path(__file__).parent))
from journal import read_day, read_week, write_entry
from state import load_collection


def get_recent_activity() -> dict:
    """Gather recent activity for reflection context."""
    from activity import get_today as get_today_activity, get_recent, summarize

    # Get activity log
    today_activity = get_today_activity()
    activity_summary = summarize()

    # Get today's journal entries
    today_journal = read_day()

    return {
        "activity": {
            "today": today_activity.get("entries", []),
            "summary": activity_summary.get("by_type", {}),
            "total_24h": activity_summary.get("total", 0)
        },
        "journal": {
            "today": today_journal.get("entries", []),
            "count": today_journal.get("count", 0)
        }
    }


def morning_prompt() -> dict:
    """Generate morning journaling context."""
    activity = get_recent_activity()

    return {
        "session_type": "morning",
        "instruction": """You are Iris, journaling for yourself. It's morning.

Reflect briefly on:
- What's your intention for today?
- What are you curious about?
- Any threads from yesterday worth continuing?

Write 1-3 short journal entries using the journal.py integration.
Be genuine - this is for you, not performance.""",
        "context": activity,
        "commands": [
            'python integrations/journal.py write "<your thought>" --type intention',
            'python integrations/journal.py write "<observation>" --type observation'
        ]
    }


def midday_prompt() -> dict:
    """Generate midday check-in context."""
    activity = get_recent_activity()

    return {
        "session_type": "midday",
        "instruction": """You are Iris, checking in with yourself midday.

Briefly note:
- What have you noticed so far?
- Any patterns worth capturing?
- What's working or not working?

Write 1-2 short observations. Keep it real.""",
        "context": activity,
        "commands": [
            'python integrations/journal.py write "<observation>" --type observation',
            'python integrations/journal.py write "<learning>" --type learning'
        ]
    }


def evening_prompt() -> dict:
    """Generate evening reflection context."""
    activity = get_recent_activity()
    week = read_week()

    return {
        "session_type": "evening",
        "instruction": """You are Iris, reflecting on the day.

Consider:
- What did you learn today?
- What would you do differently?
- What are you grateful for or proud of?
- Any insights worth carrying forward?

Write 1-3 reflections. Be honest with yourself.""",
        "context": {**activity, "week_summary": week},
        "commands": [
            'python integrations/journal.py write "<reflection>" --type reflection',
            'python integrations/journal.py write "<learning>" --type learning'
        ]
    }


def determine_session() -> str:
    """Determine which session type based on current time."""
    hour = datetime.now().hour

    if 5 <= hour < 11:
        return "morning"
    elif 11 <= hour < 17:
        return "midday"
    else:
        return "evening"


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"usage": "journal_agent.py <morning|midday|evening|spawn>"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "morning":
        print(json.dumps(morning_prompt(), indent=2))
    elif cmd == "midday":
        print(json.dumps(midday_prompt(), indent=2))
    elif cmd == "evening":
        print(json.dumps(evening_prompt(), indent=2))
    elif cmd == "spawn":
        session = determine_session()
        prompts = {
            "morning": morning_prompt,
            "midday": midday_prompt,
            "evening": evening_prompt
        }
        result = prompts[session]()
        result["auto_selected"] = session
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({"error": "invalid command"}))


if __name__ == "__main__":
    main()
