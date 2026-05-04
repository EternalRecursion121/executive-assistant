#!/usr/bin/env python3
"""Flexible accountability system with configurable escalation pathways.

Supports various accountability patterns:
- Meditation reminders with escalating pings
- Work check-ins during focus blocks
- Habit tracking with confirmation requirements
- Custom pathways with arbitrary escalation rules

Usage:
    python accountability.py create "<name>" "<prompt>" --trigger "<time>" [options]
    python accountability.py list
    python accountability.py show <pathway_id>
    python accountability.py remove <pathway_id>
    python accountability.py pause <pathway_id> [hours]
    python accountability.py resume <pathway_id>
    python accountability.py confirm <pathway_id> [response]
    python accountability.py check  # Called by bot/cron to process due items
    python accountability.py status  # Current state of all active pathways

Options:
    --escalate <minutes>       Minutes between escalation pings (default: 10)
    --max-escalations <n>      Max number of escalations before giving up (default: 6)
    --confirm-words "<words>"  Comma-separated words that count as confirmation
    --escalate-tone "<tone>"   How tone changes: gentle, firm, urgent (default: firm)
    --active-hours "<range>"   When to run, e.g. "7-22" (default: always)
    --user "<user>"            User to ping (default: samuel)
    --recurring "<pattern>"    daily, weekdays, or cron expression

Examples:
    # Morning meditation with 10-min escalation
    python accountability.py create "meditation" "Time to meditate" \\
        --trigger "7am" --escalate 10 --confirm-words "done,meditated,sat" \\
        --recurring daily --escalate-tone firm

    # Focus block check-ins
    python accountability.py create "focus-block" "What are you working on?" \\
        --trigger "in 5 minutes" --escalate 30 --max-escalations 3

    # Confirm meditation completed
    python accountability.py confirm meditation "done"
"""

import json
import sys
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

sys.path.insert(0, str(Path(__file__).parent))
from config import STATE_DIR, now_local, TIMEZONE

STATE_FILE = STATE_DIR / "accountability_pathways.json"

# Escalation message templates by tone
ESCALATION_TEMPLATES = {
    "gentle": [
        "Hey, gentle reminder: {prompt}",
        "Still waiting on this: {prompt}",
        "Checking in again: {prompt}",
        "Another nudge: {prompt}",
        "Still here, still hoping: {prompt}",
        "Last gentle ping: {prompt}",
    ],
    "firm": [
        "{prompt}",
        "You haven't responded yet. {prompt}",
        "Still waiting. {prompt}",
        "This is escalation #{n}. {prompt}",
        "Getting persistent: {prompt}",
        "Final warning before I stop asking: {prompt}",
    ],
    "urgent": [
        "{prompt}",
        "No response. {prompt}",
        "{prompt} (escalation #{n})",
        "PING: {prompt}",
        "Still nothing. {prompt}",
        "Last attempt: {prompt}",
    ],
}


@dataclass
class Pathway:
    """An accountability pathway with escalation rules."""
    id: str
    name: str
    prompt: str
    user: str
    trigger_time: str  # ISO format for next trigger
    escalate_minutes: int
    max_escalations: int
    confirm_words: list[str]
    escalate_tone: str
    active_hours: Optional[str]  # "7-22" format
    recurring: Optional[str]  # daily, weekdays, or None

    # State
    status: str  # pending, active, paused, completed, expired
    current_escalation: int
    last_ping: Optional[str]  # ISO format
    created_at: str
    confirmed_at: Optional[str]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Pathway":
        return cls(**d)


def load_pathways() -> list[Pathway]:
    """Load all pathways from state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            return [Pathway.from_dict(p) for p in data]
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def save_pathways(pathways: list[Pathway]) -> None:
    """Save pathways to state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps([p.to_dict() for p in pathways], indent=2))


def parse_time(time_str: str) -> Optional[datetime]:
    """Parse natural language time string."""
    from dateutil import parser as date_parser
    now = now_local()
    time_str = time_str.lower().strip()

    # Relative: "in X minutes/hours"
    rel = re.match(r"in\s+(\d+)\s+(minute|hour|day)s?", time_str)
    if rel:
        amt = int(rel.group(1))
        unit = rel.group(2)
        delta = {"minute": timedelta(minutes=amt),
                 "hour": timedelta(hours=amt),
                 "day": timedelta(days=amt)}[unit]
        return now + delta

    # Tomorrow
    if time_str.startswith("tomorrow"):
        time_part = time_str.replace("tomorrow", "").replace("at", "").strip()
        try:
            parsed = date_parser.parse(time_part)
            return (now + timedelta(days=1)).replace(
                hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
            )
        except:
            return now + timedelta(days=1)

    # Standard parsing
    try:
        parsed = date_parser.parse(time_str, fuzzy=True)
        # Handle timezone
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TIMEZONE)
        # If time is past, assume tomorrow
        if parsed <= now and parsed.date() == now.date():
            parsed += timedelta(days=1)
        return parsed
    except:
        return None


def parse_active_hours(hours_str: str) -> tuple[int, int]:
    """Parse active hours string like '7-22'."""
    if not hours_str:
        return (0, 24)
    parts = hours_str.split("-")
    if len(parts) == 2:
        return (int(parts[0]), int(parts[1]))
    return (0, 24)


def is_in_active_hours(pathway: Pathway) -> bool:
    """Check if current time is within pathway's active hours."""
    if not pathway.active_hours:
        return True
    start, end = parse_active_hours(pathway.active_hours)
    hour = now_local().hour
    return start <= hour < end


def get_escalation_message(pathway: Pathway) -> str:
    """Get the appropriate escalation message."""
    templates = ESCALATION_TEMPLATES.get(pathway.escalate_tone, ESCALATION_TEMPLATES["firm"])
    idx = min(pathway.current_escalation, len(templates) - 1)
    template = templates[idx]
    return template.format(prompt=pathway.prompt, n=pathway.current_escalation + 1)


def calculate_next_trigger(pathway: Pathway, from_time: datetime) -> datetime:
    """Calculate next trigger time for recurring pathways."""
    # Parse the original trigger time to get hour:minute
    try:
        orig = datetime.fromisoformat(pathway.trigger_time)
        target_hour = orig.hour
        target_minute = orig.minute
    except:
        target_hour = 7
        target_minute = 0

    if pathway.recurring == "daily":
        next_day = from_time + timedelta(days=1)
        return next_day.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

    elif pathway.recurring == "weekdays":
        next_day = from_time + timedelta(days=1)
        while next_day.weekday() >= 5:  # Skip weekends
            next_day += timedelta(days=1)
        return next_day.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)

    return None


def create_pathway(
    name: str,
    prompt: str,
    trigger: str,
    escalate_minutes: int = 10,
    max_escalations: int = 6,
    confirm_words: str = "done,yes,confirmed",
    escalate_tone: str = "firm",
    active_hours: Optional[str] = None,
    user: str = "samuel",
    recurring: Optional[str] = None,
) -> dict:
    """Create a new accountability pathway."""
    trigger_time = parse_time(trigger)
    if not trigger_time:
        return {"error": f"Could not parse trigger time: {trigger}"}

    pathways = load_pathways()

    # Check for duplicate names
    existing = [p for p in pathways if p.name == name and p.status in ("pending", "active")]
    if existing:
        return {"error": f"Pathway '{name}' already exists and is active"}

    pathway = Pathway(
        id=str(uuid.uuid4())[:8],
        name=name,
        prompt=prompt,
        user=user,
        trigger_time=trigger_time.isoformat(),
        escalate_minutes=escalate_minutes,
        max_escalations=max_escalations,
        confirm_words=[w.strip().lower() for w in confirm_words.split(",")],
        escalate_tone=escalate_tone,
        active_hours=active_hours,
        recurring=recurring,
        status="pending",
        current_escalation=0,
        last_ping=None,
        created_at=now_local().isoformat(),
        confirmed_at=None,
    )

    pathways.append(pathway)
    save_pathways(pathways)

    return {
        "success": True,
        "id": pathway.id,
        "name": name,
        "trigger_at": trigger_time.strftime("%Y-%m-%d %H:%M"),
        "escalate_every": f"{escalate_minutes} minutes",
        "max_escalations": max_escalations,
        "recurring": recurring or "once",
    }


def list_pathways() -> list[dict]:
    """List all pathways."""
    pathways = load_pathways()
    return [
        {
            "id": p.id,
            "name": p.name,
            "status": p.status,
            "trigger": p.trigger_time,
            "escalation": f"{p.current_escalation}/{p.max_escalations}",
            "recurring": p.recurring or "once",
        }
        for p in pathways
    ]


def show_pathway(pathway_id: str) -> dict:
    """Show details of a pathway."""
    pathways = load_pathways()
    for p in pathways:
        if p.id == pathway_id or p.name == pathway_id:
            return p.to_dict()
    return {"error": f"Pathway not found: {pathway_id}"}


def remove_pathway(pathway_id: str) -> dict:
    """Remove a pathway."""
    pathways = load_pathways()
    original = len(pathways)
    pathways = [p for p in pathways if p.id != pathway_id and p.name != pathway_id]

    if len(pathways) == original:
        return {"error": f"Pathway not found: {pathway_id}"}

    save_pathways(pathways)
    return {"success": True, "removed": pathway_id}


def pause_pathway(pathway_id: str, hours: Optional[int] = None) -> dict:
    """Pause a pathway, optionally for a specific number of hours."""
    pathways = load_pathways()
    for p in pathways:
        if p.id == pathway_id or p.name == pathway_id:
            p.status = "paused"
            save_pathways(pathways)
            return {"success": True, "paused": pathway_id}
    return {"error": f"Pathway not found: {pathway_id}"}


def resume_pathway(pathway_id: str) -> dict:
    """Resume a paused pathway."""
    pathways = load_pathways()
    for p in pathways:
        if p.id == pathway_id or p.name == pathway_id:
            if p.status == "paused":
                p.status = "active" if p.current_escalation > 0 else "pending"
                save_pathways(pathways)
                return {"success": True, "resumed": pathway_id}
            return {"error": f"Pathway '{pathway_id}' is not paused (status: {p.status})"}
    return {"error": f"Pathway not found: {pathway_id}"}


def confirm_pathway(pathway_id: str, response: str = "") -> dict:
    """Confirm completion of a pathway's current cycle."""
    pathways = load_pathways()
    now = now_local()

    for p in pathways:
        if p.id == pathway_id or p.name == pathway_id:
            if p.status not in ("active", "pending"):
                return {"error": f"Pathway '{pathway_id}' is not active (status: {p.status})"}

            p.confirmed_at = now.isoformat()
            p.current_escalation = 0

            # Handle recurring
            if p.recurring:
                next_trigger = calculate_next_trigger(p, now)
                if next_trigger:
                    p.trigger_time = next_trigger.isoformat()
                    p.status = "pending"
                    p.last_ping = None
                    save_pathways(pathways)
                    return {
                        "success": True,
                        "confirmed": pathway_id,
                        "next_trigger": next_trigger.strftime("%Y-%m-%d %H:%M"),
                    }

            # Non-recurring: mark completed
            p.status = "completed"
            save_pathways(pathways)
            return {"success": True, "confirmed": pathway_id, "completed": True}

    return {"error": f"Pathway not found: {pathway_id}"}


def check_pathways() -> list[dict]:
    """Check for pathways that need action. Returns pings to send."""
    pathways = load_pathways()
    now = now_local()
    pings = []
    modified = False

    for p in pathways:
        if p.status in ("completed", "expired", "paused"):
            continue

        # Check if outside active hours
        if not is_in_active_hours(p):
            continue

        trigger = datetime.fromisoformat(p.trigger_time)

        # Pending → check if trigger time reached
        if p.status == "pending":
            if now >= trigger:
                p.status = "active"
                p.current_escalation = 0
                p.last_ping = now.isoformat()
                modified = True

                pings.append({
                    "pathway_id": p.id,
                    "pathway_name": p.name,
                    "user": p.user,
                    "message": get_escalation_message(p),
                    "escalation": 0,
                })

        # Active → check if escalation needed
        elif p.status == "active":
            last_ping = datetime.fromisoformat(p.last_ping) if p.last_ping else trigger
            minutes_since = (now - last_ping).total_seconds() / 60

            if minutes_since >= p.escalate_minutes:
                p.current_escalation += 1

                if p.current_escalation >= p.max_escalations:
                    # Expired - stop asking
                    p.status = "expired"
                    modified = True
                    pings.append({
                        "pathway_id": p.id,
                        "pathway_name": p.name,
                        "user": p.user,
                        "message": f"Giving up on '{p.name}' after {p.max_escalations} attempts.",
                        "escalation": -1,  # Indicates final/expired
                    })
                else:
                    p.last_ping = now.isoformat()
                    modified = True
                    pings.append({
                        "pathway_id": p.id,
                        "pathway_name": p.name,
                        "user": p.user,
                        "message": get_escalation_message(p),
                        "escalation": p.current_escalation,
                    })

    if modified:
        save_pathways(pathways)

    return pings


def status_report() -> dict:
    """Get status of all active pathways."""
    pathways = load_pathways()
    now = now_local()

    active = []
    pending = []

    for p in pathways:
        if p.status == "active":
            active.append({
                "name": p.name,
                "escalation": f"{p.current_escalation}/{p.max_escalations}",
                "last_ping": p.last_ping,
                "prompt": p.prompt[:50],
            })
        elif p.status == "pending":
            trigger = datetime.fromisoformat(p.trigger_time)
            until = trigger - now
            active.append({
                "name": p.name,
                "triggers_in": str(until).split(".")[0],
                "prompt": p.prompt[:50],
            })

    return {
        "active_count": len(active),
        "pathways": active,
        "timestamp": now.isoformat(),
    }


def check_confirmation(pathway_name: str, message: str) -> Optional[dict]:
    """Check if a message confirms a pathway. Called by bot on user messages."""
    pathways = load_pathways()
    message_lower = message.lower().strip()

    for p in pathways:
        if p.status != "active":
            continue

        # Check if this message is a confirmation
        for word in p.confirm_words:
            if word in message_lower:
                # This is a confirmation!
                return confirm_pathway(p.name)

    return None


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "create":
        if len(sys.argv) < 4:
            print("Usage: accountability.py create <name> <prompt> --trigger <time> [options]")
            sys.exit(1)

        name = sys.argv[2]
        prompt = sys.argv[3]

        # Parse options
        args = sys.argv[4:]
        opts = {}
        i = 0
        while i < len(args):
            if args[i] == "--trigger" and i + 1 < len(args):
                opts["trigger"] = args[i + 1]
                i += 2
            elif args[i] == "--escalate" and i + 1 < len(args):
                opts["escalate_minutes"] = int(args[i + 1])
                i += 2
            elif args[i] == "--max-escalations" and i + 1 < len(args):
                opts["max_escalations"] = int(args[i + 1])
                i += 2
            elif args[i] == "--confirm-words" and i + 1 < len(args):
                opts["confirm_words"] = args[i + 1]
                i += 2
            elif args[i] == "--escalate-tone" and i + 1 < len(args):
                opts["escalate_tone"] = args[i + 1]
                i += 2
            elif args[i] == "--active-hours" and i + 1 < len(args):
                opts["active_hours"] = args[i + 1]
                i += 2
            elif args[i] == "--user" and i + 1 < len(args):
                opts["user"] = args[i + 1]
                i += 2
            elif args[i] == "--recurring" and i + 1 < len(args):
                opts["recurring"] = args[i + 1]
                i += 2
            else:
                i += 1

        if "trigger" not in opts:
            print("Error: --trigger is required")
            sys.exit(1)

        result = create_pathway(name, prompt, **opts)
        print(json.dumps(result, indent=2))

    elif cmd == "list":
        result = list_pathways()
        print(json.dumps(result, indent=2))

    elif cmd == "show":
        if len(sys.argv) < 3:
            print("Usage: accountability.py show <pathway_id>")
            sys.exit(1)
        result = show_pathway(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif cmd == "remove":
        if len(sys.argv) < 3:
            print("Usage: accountability.py remove <pathway_id>")
            sys.exit(1)
        result = remove_pathway(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif cmd == "pause":
        if len(sys.argv) < 3:
            print("Usage: accountability.py pause <pathway_id> [hours]")
            sys.exit(1)
        hours = int(sys.argv[3]) if len(sys.argv) > 3 else None
        result = pause_pathway(sys.argv[2], hours)
        print(json.dumps(result, indent=2))

    elif cmd == "resume":
        if len(sys.argv) < 3:
            print("Usage: accountability.py resume <pathway_id>")
            sys.exit(1)
        result = resume_pathway(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif cmd == "confirm":
        if len(sys.argv) < 3:
            print("Usage: accountability.py confirm <pathway_id> [response]")
            sys.exit(1)
        response = sys.argv[3] if len(sys.argv) > 3 else ""
        result = confirm_pathway(sys.argv[2], response)
        print(json.dumps(result, indent=2))

    elif cmd == "check":
        result = check_pathways()
        print(json.dumps(result))

    elif cmd == "status":
        result = status_report()
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        print("Commands: create, list, show, remove, pause, resume, confirm, check, status")
        sys.exit(1)


if __name__ == "__main__":
    main()
