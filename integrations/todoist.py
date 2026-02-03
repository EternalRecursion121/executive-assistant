#!/usr/bin/env python3
"""Todoist integration.

Usage:
    python todoist.py list [project]
    python todoist.py add "<content>" [--project "<name>"] [--due "<date>"] [--priority <1-4>]
    python todoist.py complete <task_id>
    python todoist.py projects

Requires:
    - TODOIST_API_TOKEN environment variable
    - Get token from: https://todoist.com/app/settings/integrations/developer
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from todoist_api_python.api import TodoistAPI
except ImportError:
    print("Todoist API library not installed. Run:")
    print("pip install todoist-api-python")
    sys.exit(1)

from config import PERMISSIONS_FILE

API_TOKEN = os.environ.get("TODOIST_API_TOKEN")


def check_permission_for_user(user_id: str, capability: str) -> bool:
    """Check if a specific user has permission."""
    if not PERMISSIONS_FILE.exists():
        return True

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

    # Get permissions from role, with optional user-level overrides
    allow = set(role.get("allow", []))
    deny = set(role.get("deny", []))
    if user:
        allow.update(user.get("allow", []))
        deny.update(user.get("deny", []))

    if "*" in allow and capability not in deny:
        return True
    return capability in allow and capability not in deny


def get_api() -> Optional[TodoistAPI]:
    """Get Todoist API client."""
    if not API_TOKEN:
        return None
    return TodoistAPI(API_TOKEN)


def list_tasks(project_name: Optional[str] = None) -> dict:
    """List tasks, optionally filtered by project."""
    api = get_api()
    if not api:
        return {"error": "TODOIST_API_TOKEN not set"}

    try:
        # Flatten paginated results (each page is a list of tasks)
        tasks = []
        for page in api.get_tasks():
            tasks.extend(page)

        # Filter by project if specified
        if project_name:
            # Flatten paginated project results
            projects = []
            for page in api.get_projects():
                projects.extend(page)
            project_id = None
            for p in projects:
                if p.name.lower() == project_name.lower():
                    project_id = p.id
                    break
            if project_id:
                tasks = [t for t in tasks if t.project_id == project_id]
            else:
                return {"error": f"Project '{project_name}' not found"}

        formatted = []
        for task in tasks:
            formatted.append({
                "id": task.id,
                "content": task.content,
                "description": task.description or None,
                "due": task.due.string if task.due else None,
                "priority": task.priority,
                "project_id": task.project_id,
                "labels": task.labels,
            })

        return {"tasks": formatted, "count": len(formatted)}

    except Exception as e:
        return {"error": str(e)}


def add_task(
    content: str,
    project_name: Optional[str] = None,
    due_string: Optional[str] = None,
    priority: int = 1,
) -> dict:
    """Add a new task."""
    api = get_api()
    if not api:
        return {"error": "TODOIST_API_TOKEN not set"}

    try:
        kwargs = {"content": content, "priority": priority}

        if due_string:
            kwargs["due_string"] = due_string

        if project_name:
            projects = api.get_projects()
            for p in projects:
                if p.name.lower() == project_name.lower():
                    kwargs["project_id"] = p.id
                    break

        task = api.add_task(**kwargs)

        return {
            "success": True,
            "id": task.id,
            "content": task.content,
            "due": task.due.string if task.due else None,
            "url": task.url,
        }

    except Exception as e:
        return {"error": str(e)}


def complete_task(task_id: str) -> dict:
    """Mark a task as complete."""
    api = get_api()
    if not api:
        return {"error": "TODOIST_API_TOKEN not set"}

    try:
        api.close_task(task_id)
        return {"success": True, "completed": task_id}
    except Exception as e:
        return {"error": str(e)}


def list_projects() -> dict:
    """List all projects."""
    api = get_api()
    if not api:
        return {"error": "TODOIST_API_TOKEN not set"}

    try:
        # Flatten paginated results
        projects = []
        for page in api.get_projects():
            projects.extend(page)
        formatted = [
            {"id": p.id, "name": p.name, "color": p.color}
            for p in projects
        ]
        return {"projects": formatted}
    except Exception as e:
        return {"error": str(e)}


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: todoist.py <command> [args]")
        print("Commands: list, add, complete, projects")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        project = sys.argv[2] if len(sys.argv) > 2 else None
        result = list_tasks(project)
        print(json.dumps(result, indent=2))

    elif command == "add":
        if len(sys.argv) < 3:
            print("Usage: todoist.py add <content> [--project <name>] [--due <date>] [--priority <1-4>]")
            sys.exit(1)

        content = sys.argv[2]
        project = None
        due = None
        priority = 1

        # Parse optional args
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--project" and i + 1 < len(sys.argv):
                project = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--due" and i + 1 < len(sys.argv):
                due = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--priority" and i + 1 < len(sys.argv):
                priority = int(sys.argv[i + 1])
                i += 2
            else:
                i += 1

        result = add_task(content, project, due, priority)
        print(json.dumps(result, indent=2))

    elif command == "complete":
        if len(sys.argv) < 3:
            print("Usage: todoist.py complete <task_id>")
            sys.exit(1)
        result = complete_task(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif command == "projects":
        result = list_projects()
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
