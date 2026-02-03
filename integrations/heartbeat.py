#!/usr/bin/env python3
"""Heartbeat system for Iris - periodic consciousness with agency.

The heartbeat runs at regular intervals and checks HEARTBEAT.md for what needs attention.
If nothing needs attention, it outputs HEARTBEAT_OK and nothing is sent.
If something needs attention, it surfaces it via DM to Samuel.

Features:
- HEARTBEAT_OK contract: model decides if anything needs attention
- Duplicate suppression: same alert won't repeat within 24h
- Wake coalescing: multiple rapid triggers collapse into one check
- Background task relay: async work completions surface via heartbeat

Usage:
    python heartbeat.py check                        # Run a heartbeat check
    python heartbeat.py status                       # Show heartbeat status
    python heartbeat.py add "<item>"                 # Add item to Active Items
    python heartbeat.py suppress "<item>" [days]    # Suppress item for N days
    python heartbeat.py clear-suppress              # Clear all suppressions
    python heartbeat.py wake [reason]               # Trigger immediate check (with coalescing)
    python heartbeat.py complete <id> "<result>"    # Record background task completion
    python heartbeat.py mark-relayed <id> [id...]   # Mark completions as relayed
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from config import (
    WORKSPACE, STATE_DIR, INTEGRATIONS, VENV_PYTHON,
    TIMEZONE, ACTIVE_START, ACTIVE_END, SAMUEL_ID,
    now_local, is_active_hours
)

HEARTBEAT_FILE = WORKSPACE / "HEARTBEAT.md"
STATE_FILE = STATE_DIR / "heartbeat.json"
LOG_FILE = STATE_DIR / "heartbeat.log"

HEARTBEAT_OK = "HEARTBEAT_OK"


def log(message: str):
    """Log a message with timestamp (in configured timezone)."""
    timestamp = now_local().strftime("%Y-%m-%d %H:%M:%S %Z")
    line = f"[{timestamp}] {message}"
    print(line, file=sys.stderr)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_state() -> dict:
    """Load heartbeat state."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "last_check": None,
        "last_alert": None,
        "suppressed": {},  # item -> suppress_until_date
        "recent_alerts": [],  # for duplicate detection
    }


def save_state(state: dict):
    """Save heartbeat state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def load_heartbeat_md() -> str:
    """Load the heartbeat checklist."""
    if HEARTBEAT_FILE.exists():
        return HEARTBEAT_FILE.read_text()
    return ""


def save_heartbeat_md(content: str):
    """Save the heartbeat checklist."""
    HEARTBEAT_FILE.write_text(content)


def run_integration(script: str, *args, timeout: int = 30) -> tuple[bool, str]:
    """Run an integration script and return (success, output)."""
    script_path = INTEGRATIONS / script
    if not script_path.exists():
        return False, f"Script not found: {script}"

    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(script_path), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE)
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def gather_context() -> dict:
    """Gather context from various integrations."""
    context = {
        "timestamp": now_local().isoformat(),
        "is_active_hours": is_active_hours(),
    }

    # Reminders
    success, output = run_integration("reminders.py", "list", SAMUEL_ID)
    if success and output:
        context["reminders"] = output

    # Calendar - next 6 hours
    success, output = run_integration("google_calendar.py", "list", "1")
    if success and output:
        context["calendar"] = output

    # Todoist - due today
    success, output = run_integration("todoist.py", "list")
    if success and output:
        context["todoist"] = output

    # Unread emails (just count, not content for privacy)
    success, output = run_integration("gmail.py", "unread")
    if success and output:
        context["email_unread"] = output

    # Recent activity
    success, output = run_integration("activity.py", "recent", "6")
    if success and output:
        context["recent_activity"] = output[:1000]  # Truncate

    # Tracked tasks (commitments Samuel made)
    success, output = run_integration("tasks.py", "check", "--json")
    if success and output:
        context["tracked_tasks"] = output

    # Background task completions waiting to be relayed
    completions_file = STATE_DIR / "background_completions.json"
    if completions_file.exists():
        try:
            completions = json.loads(completions_file.read_text())
            pending = [c for c in completions.get("completions", []) if not c.get("relayed")]
            if pending:
                context["background_completions"] = pending
        except:
            pass

    # Check queues
    dm_queue = STATE_DIR / "dm_queue.json"
    if dm_queue.exists():
        try:
            queue = json.loads(dm_queue.read_text())
            context["dm_queue_size"] = len(queue.get("queue", []))
        except:
            pass

    channel_queue = STATE_DIR / "channel_message_queue.json"
    if channel_queue.exists():
        try:
            queue = json.loads(channel_queue.read_text())
            context["channel_queue_size"] = len(queue.get("queue", []))
        except:
            pass

    return context


def run_claude(prompt: str, timeout: int = 180) -> str:
    """Run a prompt through Claude CLI using stdin to avoid arg length limits."""
    try:
        # Ensure claude is in PATH - it's at /home/iris/.local/bin/claude
        env = os.environ.copy()
        env["PATH"] = "/home/iris/.local/bin:" + env.get("PATH", "")

        result = subprocess.run(
            ["claude", "-p", "-", "--output-format", "text"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE),
            env=env
        )
        return result.stdout.strip() if result.returncode == 0 else f"Error: {result.stderr}"
    except subprocess.TimeoutExpired:
        return f"Error: Timeout after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


def extract_response(text: str) -> tuple[bool, str]:
    """Extract the actual response, checking for HEARTBEAT_OK.

    Returns (is_ok, message).
    """
    # Strip markdown code blocks if present
    text = re.sub(r'^```\w*\n?', '', text)
    text = re.sub(r'\n?```$', '', text)
    text = text.strip()

    # Check for HEARTBEAT_OK (case insensitive, might have extra text)
    if HEARTBEAT_OK.lower() in text.lower():
        return True, ""

    return False, text


def is_duplicate_alert(message: str, state: dict) -> bool:
    """Check if this alert was recently sent (within 24h)."""
    # Simple hash of first 100 chars
    msg_hash = hash(message[:100])
    recent = state.get("recent_alerts", [])

    cutoff = (now_local() - timedelta(hours=24)).isoformat()

    for alert in recent:
        if alert.get("hash") == msg_hash and alert.get("time", "") > cutoff:
            return True

    return False


def record_alert(message: str, state: dict):
    """Record that we sent this alert."""
    msg_hash = hash(message[:100])
    recent = state.get("recent_alerts", [])

    # Add new alert
    recent.append({
        "hash": msg_hash,
        "time": now_local().isoformat(),
        "preview": message[:50]
    })

    # Keep only last 24h
    cutoff = (now_local() - timedelta(hours=24)).isoformat()
    state["recent_alerts"] = [a for a in recent if a.get("time", "") > cutoff]


def send_dm(message: str) -> bool:
    """Send a DM to Samuel via the queue."""
    success, output = run_integration("dm.py", "send", "samuel", message)
    return success


def check_heartbeat():
    """Run a heartbeat check."""
    state = load_state()
    heartbeat_md = load_heartbeat_md()

    if not heartbeat_md.strip():
        log("HEARTBEAT.md is empty, skipping check")
        return

    log("Starting heartbeat check...")

    # Gather context
    context = gather_context()

    # Build prompt
    prompt = f"""You are Iris running a heartbeat check. Review the checklist and context, then decide what (if anything) needs Samuel's attention.

## Your Heartbeat Checklist
{heartbeat_md}

## Current Context
- Time: {context['timestamp']}
- Active hours: {context['is_active_hours']}

### Reminders
{context.get('reminders', 'None loaded')}

### Calendar (next 24h)
{context.get('calendar', 'None loaded')}

### Todoist Tasks
{context.get('todoist', 'None loaded')}

### Email
{context.get('email_unread', 'Could not check')}

### Recent Activity
{context.get('recent_activity', 'None')}

### Queue Status
- DM queue: {context.get('dm_queue_size', 0)} pending
- Channel queue: {context.get('channel_queue_size', 0)} pending

### Tracked Commitments
{context.get('tracked_tasks', 'None')}

### Background Task Completions
{json.dumps(context.get('background_completions', []), indent=2) if context.get('background_completions') else 'None pending'}

## Instructions

Review the checklist items against the context. If nothing needs attention, respond with just:
{HEARTBEAT_OK}

If something needs attention, write a brief message (2-4 sentences max) for Samuel. Be specific and actionable. Don't mention things that can wait.

Remember: This runs every 2 hours. Only surface things that are:
1. Time-sensitive (needs action in next few hours)
2. Pattern-breaking (unusual, worth noting)
3. Follow-up worthy (things Samuel said he'd do)

Do NOT surface routine information like "you have 3 tasks due today" unless they're overdue or urgent."""

    # Run through Claude
    response = run_claude(prompt)

    if response.startswith("Error"):
        log(f"Claude error: {response}")
        return

    is_ok, message = extract_response(response)

    # Update state
    state["last_check"] = now_local().isoformat()

    if is_ok:
        log("Heartbeat OK - nothing to surface")
        save_state(state)
        return

    # Check for duplicates
    if is_duplicate_alert(message, state):
        log(f"Duplicate alert suppressed: {message[:50]}...")
        save_state(state)
        return

    # Send the alert
    log(f"Surfacing: {message[:100]}...")

    if send_dm(message):
        state["last_alert"] = now_local().isoformat()
        record_alert(message, state)
        log("Alert sent successfully")
    else:
        log("Failed to send alert")

    save_state(state)


def show_status():
    """Show heartbeat status."""
    state = load_state()

    print("=== Heartbeat Status ===")
    print(f"Timezone: {TIMEZONE}")
    print(f"Current time: {now_local().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Last check: {state.get('last_check', 'Never')}")
    print(f"Last alert: {state.get('last_alert', 'Never')}")
    print(f"Active hours: {ACTIVE_START}:00 - {ACTIVE_END}:00 {TIMEZONE}")
    print(f"Currently active: {is_active_hours()}")

    suppressed = state.get("suppressed", {})
    if suppressed:
        print(f"\nSuppressed items ({len(suppressed)}):")
        for item, until in suppressed.items():
            print(f"  - {item}: until {until}")

    recent = state.get("recent_alerts", [])
    if recent:
        print(f"\nRecent alerts (24h): {len(recent)}")
        for alert in recent[-5:]:
            print(f"  - {alert.get('time', '?')}: {alert.get('preview', '?')}")


def add_active_item(item: str):
    """Add an item to the Active Items section of HEARTBEAT.md."""
    content = load_heartbeat_md()

    # Find the Active Items section
    marker = "## Active Items"
    if marker not in content:
        print(f"Error: Could not find '{marker}' section")
        return

    # Find insertion point (after the section header and any description)
    parts = content.split(marker)
    before = parts[0]
    after = parts[1]

    # Find the end of the section description (first blank line or next ##)
    lines = after.split("\n")
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("##") or (line.strip() == "" and i > 2):
            insert_idx = i
            break
        if line.startswith("<!--"):
            # Skip comment blocks
            for j in range(i, len(lines)):
                if "-->" in lines[j]:
                    insert_idx = j + 1
                    break
            break

    # Insert the new item
    date = now_local().strftime("%Y-%m-%d")
    new_item = f"- [ ] {item} (added {date})"

    lines.insert(insert_idx, new_item)

    new_content = before + marker + "\n".join(lines)
    save_heartbeat_md(new_content)
    print(f"Added to Active Items: {item}")


def suppress_item(item: str, days: int = 1):
    """Suppress an item for N days."""
    state = load_state()
    until = (now_local() + timedelta(days=days)).strftime("%Y-%m-%d")
    state.setdefault("suppressed", {})[item] = until
    save_state(state)
    print(f"Suppressed '{item}' until {until}")


def clear_suppressions():
    """Clear all suppressions."""
    state = load_state()
    state["suppressed"] = {}
    save_state(state)
    print("Cleared all suppressions")


def wake_heartbeat(reason: str = "manual"):
    """Trigger an immediate heartbeat check with coalescing.

    If a wake was already requested in the last 30 seconds, just log and skip.
    This prevents multiple rapid triggers from causing redundant checks.
    """
    state = load_state()
    last_wake = state.get("last_wake")

    if last_wake:
        last_wake_time = datetime.fromisoformat(last_wake)
        # Use naive comparison since last_wake might be stored without tz
        now = now_local().replace(tzinfo=None)
        if last_wake_time.tzinfo:
            last_wake_time = last_wake_time.replace(tzinfo=None)
        if now - last_wake_time < timedelta(seconds=30):
            log(f"Wake coalesced (reason: {reason})")
            return {"status": "coalesced", "reason": reason}

    state["last_wake"] = now_local().isoformat()
    save_state(state)

    log(f"Wake triggered: {reason}")
    check_heartbeat()
    return {"status": "executed", "reason": reason}


def record_completion(task_id: str, result: str, task_type: str = "background"):
    """Record a background task completion for the next heartbeat to relay."""
    completions_file = STATE_DIR / "background_completions.json"

    if completions_file.exists():
        try:
            data = json.loads(completions_file.read_text())
        except:
            data = {"completions": []}
    else:
        data = {"completions": []}

    data["completions"].append({
        "id": task_id,
        "type": task_type,
        "result": result[:500],  # Truncate long results
        "completed_at": now_local().isoformat(),
        "relayed": False,
    })

    # Keep only last 20 completions
    data["completions"] = data["completions"][-20:]

    completions_file.write_text(json.dumps(data, indent=2))
    print(f"Recorded completion: {task_id}")


def mark_relayed(task_ids: list):
    """Mark completions as relayed so they don't repeat."""
    completions_file = STATE_DIR / "background_completions.json"

    if not completions_file.exists():
        return

    try:
        data = json.loads(completions_file.read_text())
        for completion in data.get("completions", []):
            if completion["id"] in task_ids:
                completion["relayed"] = True
        completions_file.write_text(json.dumps(data, indent=2))
    except:
        pass


def main():
    parser = argparse.ArgumentParser(description="Iris heartbeat system")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # check
    subparsers.add_parser("check", help="Run a heartbeat check")

    # status
    subparsers.add_parser("status", help="Show heartbeat status")

    # add
    add_parser = subparsers.add_parser("add", help="Add item to Active Items")
    add_parser.add_argument("item", help="Item to add")

    # suppress
    suppress_parser = subparsers.add_parser("suppress", help="Suppress an item")
    suppress_parser.add_argument("item", help="Item to suppress")
    suppress_parser.add_argument("days", type=int, nargs="?", default=1, help="Days to suppress")

    # clear-suppress
    subparsers.add_parser("clear-suppress", help="Clear all suppressions")

    # wake
    wake_parser = subparsers.add_parser("wake", help="Trigger immediate heartbeat (with coalescing)")
    wake_parser.add_argument("reason", nargs="?", default="manual", help="Reason for wake")

    # complete (record a background task completion)
    complete_parser = subparsers.add_parser("complete", help="Record background task completion")
    complete_parser.add_argument("task_id", help="Task identifier")
    complete_parser.add_argument("result", help="Task result/output")
    complete_parser.add_argument("--type", default="background", help="Task type")

    # mark-relayed
    relayed_parser = subparsers.add_parser("mark-relayed", help="Mark completions as relayed")
    relayed_parser.add_argument("task_ids", nargs="+", help="Task IDs to mark")

    args = parser.parse_args()

    if args.command == "check":
        check_heartbeat()
    elif args.command == "status":
        show_status()
    elif args.command == "add":
        add_active_item(args.item)
    elif args.command == "suppress":
        suppress_item(args.item, args.days)
    elif args.command == "clear-suppress":
        clear_suppressions()
    elif args.command == "wake":
        result = wake_heartbeat(args.reason)
        print(json.dumps(result, indent=2))
    elif args.command == "complete":
        record_completion(args.task_id, args.result, args.type)
    elif args.command == "mark-relayed":
        mark_relayed(args.task_ids)
        print(f"Marked {len(args.task_ids)} completions as relayed")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
