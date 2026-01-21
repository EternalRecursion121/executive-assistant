#!/usr/bin/env python3
"""Reminder system with natural language time parsing.

Usage:
    python reminders.py add <user_id> "<message>" "<time>"
    python reminders.py list [user_id]
    python reminders.py remove <reminder_id>
    python reminders.py check  # Returns JSON of due reminders (for bot)

Time formats:
    - "in 2 hours", "in 30 minutes"
    - "tomorrow at 9am", "tomorrow 3pm"
    - "next monday 2pm"
    - "2024-01-15 14:00"
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import re
import uuid

from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

STATE_FILE = Path("/home/executive-assistant/workspace/state/reminders.json")
PERMISSIONS_FILE = Path("/home/executive-assistant/workspace/state/permissions.json")


def check_permission(user_id: str, capability: str = "reminders") -> bool:
    """Check if user has permission for this capability."""
    if not PERMISSIONS_FILE.exists():
        return True  # No permissions file = allow all

    try:
        perms = json.loads(PERMISSIONS_FILE.read_text())
    except json.JSONDecodeError:
        return True

    user = perms.get("users", {}).get(str(user_id))
    if not user:
        default_role = perms.get("default", "none")
        if default_role == "none":
            return False
        role = perms.get("roles", {}).get(default_role, {})
    else:
        role = perms.get("roles", {}).get(user.get("role", "none"), {})

    allow = set(user.get("allow", []) if user else role.get("allow", []))
    deny = set(user.get("deny", []) if user else role.get("deny", []))

    if "*" in allow and capability not in deny:
        return True
    return capability in allow and capability not in deny


def load_reminders() -> list[dict]:
    """Load reminders from state file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            return []
    return []


def save_reminders(reminders: list[dict]) -> None:
    """Save reminders to state file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(reminders, indent=2, default=str))


def parse_time(time_str: str) -> Optional[datetime]:
    """Parse natural language time string into datetime."""
    now = datetime.now()
    time_str = time_str.lower().strip()

    # Handle relative times: "in X hours/minutes/days"
    relative_match = re.match(
        r"in\s+(\d+)\s+(minute|hour|day|week)s?",
        time_str,
        re.IGNORECASE,
    )
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2).lower()
        if unit == "minute":
            return now + timedelta(minutes=amount)
        elif unit == "hour":
            return now + timedelta(hours=amount)
        elif unit == "day":
            return now + timedelta(days=amount)
        elif unit == "week":
            return now + timedelta(weeks=amount)

    # Handle "tomorrow at X"
    if time_str.startswith("tomorrow"):
        time_part = time_str.replace("tomorrow", "").replace("at", "").strip()
        try:
            parsed_time = date_parser.parse(time_part)
            return (now + timedelta(days=1)).replace(
                hour=parsed_time.hour,
                minute=parsed_time.minute,
                second=0,
                microsecond=0,
            )
        except Exception:
            return now + timedelta(days=1)

    # Handle "next monday/tuesday/etc"
    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    for day_name, day_num in weekdays.items():
        if f"next {day_name}" in time_str:
            days_ahead = day_num - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target_date = now + timedelta(days=days_ahead)

            # Extract time if specified
            time_part = time_str.replace(f"next {day_name}", "").replace("at", "").strip()
            if time_part:
                try:
                    parsed_time = date_parser.parse(time_part)
                    target_date = target_date.replace(
                        hour=parsed_time.hour,
                        minute=parsed_time.minute,
                        second=0,
                        microsecond=0,
                    )
                except Exception:
                    pass
            return target_date

    # Try standard date parsing as fallback
    try:
        parsed = date_parser.parse(time_str, fuzzy=True)
        # If no date specified but time is in the past, assume tomorrow
        if parsed < now and parsed.date() == now.date():
            parsed += timedelta(days=1)
        return parsed
    except Exception:
        return None


def add_reminder(user_id: str, message: str, time_str: str) -> dict:
    """Add a new reminder."""
    if not check_permission(user_id, "reminders"):
        return {"error": "Permission denied: reminders not allowed for this user"}

    due_at = parse_time(time_str)
    if not due_at:
        return {"error": f"Could not parse time: {time_str}"}

    reminders = load_reminders()

    reminder = {
        "id": str(uuid.uuid4())[:8],
        "user_id": user_id,
        "message": message,
        "due_at": due_at.isoformat(),
        "created_at": datetime.now().isoformat(),
    }

    reminders.append(reminder)
    save_reminders(reminders)

    return {
        "success": True,
        "id": reminder["id"],
        "message": message,
        "due_at": due_at.strftime("%Y-%m-%d %H:%M"),
    }


def list_reminders(user_id: Optional[str] = None) -> list[dict]:
    """List reminders, optionally filtered by user."""
    reminders = load_reminders()

    if user_id:
        reminders = [r for r in reminders if r.get("user_id") == user_id]

    # Sort by due date
    reminders.sort(key=lambda r: r.get("due_at", ""))

    return [
        {
            "id": r["id"],
            "message": r["message"],
            "due_at": r["due_at"],
        }
        for r in reminders
    ]


def remove_reminder(reminder_id: str) -> dict:
    """Remove a reminder by ID."""
    reminders = load_reminders()
    original_count = len(reminders)

    reminders = [r for r in reminders if r.get("id") != reminder_id]

    if len(reminders) == original_count:
        return {"error": f"Reminder {reminder_id} not found"}

    save_reminders(reminders)
    return {"success": True, "removed": reminder_id}


def check_due_reminders() -> list[dict]:
    """Check for due reminders and remove them. Returns JSON for the bot."""
    reminders = load_reminders()
    now = datetime.now()

    due = []
    remaining = []

    for reminder in reminders:
        try:
            due_at = datetime.fromisoformat(reminder["due_at"])
            if due_at <= now:
                due.append(reminder)
            else:
                remaining.append(reminder)
        except Exception:
            remaining.append(reminder)

    if due:
        save_reminders(remaining)

    return due


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: reminders.py <command> [args]")
        print("Commands: add, list, remove, check")
        sys.exit(1)

    command = sys.argv[1]

    if command == "add":
        if len(sys.argv) < 5:
            print("Usage: reminders.py add <user_id> <message> <time>")
            sys.exit(1)
        result = add_reminder(sys.argv[2], sys.argv[3], sys.argv[4])
        print(json.dumps(result, indent=2))

    elif command == "list":
        user_id = sys.argv[2] if len(sys.argv) > 2 else None
        result = list_reminders(user_id)
        print(json.dumps(result, indent=2))

    elif command == "remove":
        if len(sys.argv) < 3:
            print("Usage: reminders.py remove <reminder_id>")
            sys.exit(1)
        result = remove_reminder(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif command == "check":
        # Output JSON for bot to parse
        result = check_due_reminders()
        print(json.dumps(result))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
