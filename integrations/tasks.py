#!/usr/bin/env python3
"""Task and commitment tracking for Iris.

Tracks things Samuel says he'll do, commitments mentioned in conversation,
and allows heartbeat to check for follow-through.

Usage:
    python tasks.py add "<task>" [--due "<date>"] [--source "<context>"]
    python tasks.py list [--status pending|done|overdue]
    python tasks.py complete <id>
    python tasks.py remove <id>
    python tasks.py check             # Check for overdue/due-soon tasks
    python tasks.py extract "<text>"  # Extract commitments from text (AI-assisted)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import uuid

from config import WORKSPACE, STATE_DIR, VENV_PYTHON

STATE_FILE = STATE_DIR / "tracked_tasks.json"


def load_tasks() -> dict:
    """Load tasks from state file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"tasks": [], "version": 1}


def save_tasks(data: dict):
    """Save tasks to state file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2, default=str))


def generate_id() -> str:
    """Generate a short unique ID."""
    return uuid.uuid4().hex[:8]


def parse_date(date_str: str) -> Optional[str]:
    """Parse a date string into ISO format."""
    if not date_str:
        return None

    date_str = date_str.lower().strip()

    # Relative dates
    today = datetime.now().date()

    if date_str == "today":
        return today.isoformat()
    elif date_str == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    elif date_str in ("next week", "nextweek"):
        return (today + timedelta(weeks=1)).isoformat()
    elif date_str.startswith("in "):
        # "in 3 days", "in 1 week"
        match = re.match(r"in (\d+) (day|days|week|weeks)", date_str)
        if match:
            num = int(match.group(1))
            unit = match.group(2)
            if "week" in unit:
                return (today + timedelta(weeks=num)).isoformat()
            else:
                return (today + timedelta(days=num)).isoformat()

    # Try to parse as date
    for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%m/%d", "%B %d", "%b %d"]:
        try:
            parsed = datetime.strptime(date_str, fmt)
            if parsed.year == 1900:  # No year provided
                parsed = parsed.replace(year=today.year)
                # If the date is in the past, assume next year
                if parsed.date() < today:
                    parsed = parsed.replace(year=today.year + 1)
            return parsed.date().isoformat()
        except ValueError:
            continue

    return None


def add_task(content: str, due: Optional[str] = None, source: Optional[str] = None) -> dict:
    """Add a new task."""
    data = load_tasks()

    task = {
        "id": generate_id(),
        "content": content,
        "status": "pending",
        "created": datetime.now().isoformat(),
        "due": parse_date(due) if due else None,
        "source": source,
        "completed_at": None,
    }

    data["tasks"].append(task)
    save_tasks(data)

    return task


def list_tasks(status: Optional[str] = None) -> list:
    """List tasks, optionally filtered by status."""
    data = load_tasks()
    tasks = data.get("tasks", [])

    today = datetime.now().date().isoformat()

    # Add computed status for overdue
    for task in tasks:
        if task["status"] == "pending" and task.get("due") and task["due"] < today:
            task["computed_status"] = "overdue"
        else:
            task["computed_status"] = task["status"]

    if status == "overdue":
        return [t for t in tasks if t.get("computed_status") == "overdue"]
    elif status == "pending":
        return [t for t in tasks if t["status"] == "pending"]
    elif status == "done":
        return [t for t in tasks if t["status"] == "done"]
    else:
        # Return all pending and overdue by default
        return [t for t in tasks if t["status"] == "pending"]


def complete_task(task_id: str) -> Optional[dict]:
    """Mark a task as complete."""
    data = load_tasks()

    for task in data.get("tasks", []):
        if task["id"] == task_id:
            task["status"] = "done"
            task["completed_at"] = datetime.now().isoformat()
            save_tasks(data)
            return task

    return None


def remove_task(task_id: str) -> bool:
    """Remove a task entirely."""
    data = load_tasks()
    original_count = len(data.get("tasks", []))
    data["tasks"] = [t for t in data.get("tasks", []) if t["id"] != task_id]

    if len(data["tasks"]) < original_count:
        save_tasks(data)
        return True
    return False


def check_tasks() -> dict:
    """Check for tasks that need attention."""
    tasks = list_tasks()
    today = datetime.now().date().isoformat()
    tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()

    result = {
        "overdue": [],
        "due_today": [],
        "due_tomorrow": [],
        "pending_count": len(tasks),
    }

    for task in tasks:
        due = task.get("due")
        if not due:
            continue

        if due < today:
            result["overdue"].append(task)
        elif due == today:
            result["due_today"].append(task)
        elif due == tomorrow:
            result["due_tomorrow"].append(task)

    return result


def run_claude(prompt: str, timeout: int = 60) -> str:
    """Run a prompt through Claude CLI."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE),
            env={**os.environ, "PATH": "/home/iris/.local/bin:" + os.environ.get("PATH", "")}
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except:
        return ""


def extract_commitments(text: str) -> list:
    """Use Claude to extract commitments from text."""
    prompt = f"""Extract any commitments, intentions, or tasks from this text. Look for phrases like:
- "I will...", "I'll...", "I need to...", "I should..."
- "remind me to...", "don't let me forget..."
- "today/tomorrow I'll..."

Text:
{text}

Return a JSON array of objects with "content" (the task) and "due" (if mentioned, e.g. "today", "tomorrow", date).
If no commitments found, return [].
Example: [{{"content": "reply to Mark's email", "due": "today"}}]

JSON only, no explanation:"""

    response = run_claude(prompt)

    # Try to parse JSON from response
    try:
        # Handle markdown code blocks
        if "```" in response:
            match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", response, re.DOTALL)
            if match:
                response = match.group(1)

        return json.loads(response)
    except json.JSONDecodeError:
        return []


def format_task(task: dict) -> str:
    """Format a task for display."""
    status_icon = "✓" if task["status"] == "done" else "○"
    due_str = f" (due: {task.get('due')})" if task.get("due") else ""

    if task.get("computed_status") == "overdue":
        due_str = f" ⚠️ OVERDUE (was due: {task['due']})"

    return f"[{task['id']}] {status_icon} {task['content']}{due_str}"


def main():
    parser = argparse.ArgumentParser(description="Task and commitment tracking")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # add
    add_parser = subparsers.add_parser("add", help="Add a task")
    add_parser.add_argument("content", help="Task content")
    add_parser.add_argument("--due", help="Due date")
    add_parser.add_argument("--source", help="Source/context")

    # list
    list_parser = subparsers.add_parser("list", help="List tasks")
    list_parser.add_argument("--status", choices=["pending", "done", "overdue"], help="Filter by status")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # complete
    complete_parser = subparsers.add_parser("complete", help="Complete a task")
    complete_parser.add_argument("id", help="Task ID")

    # remove
    remove_parser = subparsers.add_parser("remove", help="Remove a task")
    remove_parser.add_argument("id", help="Task ID")

    # check
    check_parser = subparsers.add_parser("check", help="Check for due/overdue tasks")
    check_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # extract
    extract_parser = subparsers.add_parser("extract", help="Extract commitments from text")
    extract_parser.add_argument("text", help="Text to extract from")
    extract_parser.add_argument("--add", action="store_true", help="Add extracted tasks")

    args = parser.parse_args()

    if args.command == "add":
        task = add_task(args.content, args.due, args.source)
        print(f"Added: {format_task(task)}")

    elif args.command == "list":
        tasks = list_tasks(args.status)
        if args.json:
            print(json.dumps(tasks, indent=2))
        elif tasks:
            for task in tasks:
                print(format_task(task))
        else:
            print("No tasks found")

    elif args.command == "complete":
        task = complete_task(args.id)
        if task:
            print(f"Completed: {format_task(task)}")
        else:
            print(f"Task not found: {args.id}")

    elif args.command == "remove":
        if remove_task(args.id):
            print(f"Removed task: {args.id}")
        else:
            print(f"Task not found: {args.id}")

    elif args.command == "check":
        result = check_tasks()
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result["overdue"]:
                print("⚠️ OVERDUE:")
                for task in result["overdue"]:
                    print(f"  {format_task(task)}")
            if result["due_today"]:
                print("📅 DUE TODAY:")
                for task in result["due_today"]:
                    print(f"  {format_task(task)}")
            if result["due_tomorrow"]:
                print("📅 DUE TOMORROW:")
                for task in result["due_tomorrow"]:
                    print(f"  {format_task(task)}")
            if not any([result["overdue"], result["due_today"], result["due_tomorrow"]]):
                print(f"No urgent tasks ({result['pending_count']} pending)")

    elif args.command == "extract":
        commitments = extract_commitments(args.text)
        if commitments:
            for c in commitments:
                if args.add:
                    task = add_task(c["content"], c.get("due"))
                    print(f"Added: {format_task(task)}")
                else:
                    print(f"Found: {c['content']} (due: {c.get('due', 'unspecified')})")
        else:
            print("No commitments found")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
