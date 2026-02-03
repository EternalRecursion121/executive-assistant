"""Permission system for Iris."""

import json
from pathlib import Path
from typing import Optional

PERMISSIONS_FILE = Path("/home/iris/executive-assistant/workspace/state/permissions.json")

# All available capabilities
ALL_CAPABILITIES = {
    "calendar.read",
    "calendar.write",
    "todoist.read",
    "todoist.write",
    "gmail.read",
    "drive.read",
    "drive.write",
    "reminders",
    "web_search",
    "web_fetch",
    "file.read",
    "file.write",
    "bash",
    "research",  # Task agents
}


def load_permissions() -> dict:
    """Load permissions from JSON file."""
    if not PERMISSIONS_FILE.exists():
        return {"users": {}, "roles": {}, "default": "none"}

    try:
        return json.loads(PERMISSIONS_FILE.read_text())
    except json.JSONDecodeError:
        return {"users": {}, "roles": {}, "default": "none"}


def get_user_permissions(user_id: str) -> dict:
    """Get resolved permissions for a user.

    Returns:
        {
            "allowed": bool,
            "name": str or None,
            "role": str,
            "capabilities": set of allowed capabilities,
            "denied": set of denied capabilities,
        }
    """
    perms = load_permissions()
    user_id = str(user_id)

    # Check if user exists
    user = perms.get("users", {}).get(user_id)

    if not user:
        # Use default role
        default_role = perms.get("default", "none")
        if default_role == "none":
            return {
                "allowed": False,
                "name": None,
                "role": "none",
                "capabilities": set(),
                "denied": ALL_CAPABILITIES,
            }
        role_name = default_role
        user = {"role": default_role}
    else:
        role_name = user.get("role", "none")

    # Resolve role
    role = perms.get("roles", {}).get(role_name, {})

    # Build capability set
    allow = set(user.get("allow", role.get("allow", [])))
    deny = set(user.get("deny", role.get("deny", [])))

    # Handle wildcard
    if "*" in allow:
        capabilities = ALL_CAPABILITIES.copy()
    else:
        capabilities = allow & ALL_CAPABILITIES

    # Remove denied
    capabilities -= deny

    return {
        "allowed": True,
        "name": user.get("name"),
        "role": role_name,
        "capabilities": capabilities,
        "denied": ALL_CAPABILITIES - capabilities,
    }


def can_use(user_id: str, capability: str) -> bool:
    """Check if user can use a specific capability."""
    perms = get_user_permissions(user_id)
    if not perms["allowed"]:
        return False
    return capability in perms["capabilities"]


def get_allowed_tools_prompt(user_id: str) -> str:
    """Generate tool documentation only for capabilities user has access to.

    This is the enforcement mechanism - Claude only learns about tools
    the user is allowed to use. No documentation = no usage.
    """
    perms = get_user_permissions(user_id)
    caps = perms["capabilities"]

    if not perms["allowed"]:
        return "No tools available."

    sections = []

    # Core capabilities (Claude built-in)
    if "web_search" in caps:
        sections.append("- **WebSearch** - Search the internet for current information")

    if "web_fetch" in caps:
        sections.append("- **WebFetch** - Read and analyze webpages")

    if "file.read" in caps:
        sections.append("- **Read** - Read files in the workspace")

    if "file.write" in caps:
        sections.append("- **Write/Edit** - Create and modify files")

    if "bash" in caps:
        sections.append("- **Bash** - Run terminal commands")

    if "research" in caps:
        sections.append("- **Task** - Spawn research agents for complex queries")

    # Integration capabilities (our scripts)
    if "reminders" in caps:
        sections.append("""
**Reminders:**
```bash
python /home/iris/executive-assistant/integrations/reminders.py add "<user_id>" "<message>" "<time>"
python /home/iris/executive-assistant/integrations/reminders.py list [user_id]
python /home/iris/executive-assistant/integrations/reminders.py remove <id>
```""")

    if "calendar.read" in caps or "calendar.write" in caps:
        cal_cmds = []
        if "calendar.read" in caps:
            cal_cmds.append('python /home/iris/executive-assistant/integrations/google_calendar.py list [days]')
        if "calendar.write" in caps:
            cal_cmds.append('python /home/iris/executive-assistant/integrations/google_calendar.py add "<title>" "<start>" "<end>" ["<description>"]')

        sections.append(f"""
**Google Calendar:**
```bash
{chr(10).join(cal_cmds)}
```""")

    if "todoist.read" in caps or "todoist.write" in caps:
        todo_cmds = []
        if "todoist.read" in caps:
            todo_cmds.append('python /home/iris/executive-assistant/integrations/todoist.py list [project]')
            todo_cmds.append('python /home/iris/executive-assistant/integrations/todoist.py projects')
        if "todoist.write" in caps:
            todo_cmds.append('python /home/iris/executive-assistant/integrations/todoist.py add "<content>" [--project "<name>"] [--due "<date>"]')
            todo_cmds.append('python /home/iris/executive-assistant/integrations/todoist.py complete <task_id>')

        sections.append(f"""
**Todoist:**
```bash
{chr(10).join(todo_cmds)}
```""")

    if "gmail.read" in caps:
        sections.append("""
**Gmail (read-only):**
```bash
python /home/iris/executive-assistant/integrations/gmail.py list [max_results]
python /home/iris/executive-assistant/integrations/gmail.py search "<query>"
python /home/iris/executive-assistant/integrations/gmail.py read <message_id>
python /home/iris/executive-assistant/integrations/gmail.py unread
```
Search syntax: "from:x", "subject:x", "is:unread", "after:2024/01/01", "has:attachment"
""")

    if "drive.read" in caps or "drive.write" in caps:
        drive_cmds = []
        if "drive.read" in caps:
            drive_cmds.append('python /home/iris/executive-assistant/integrations/google_drive.py list [query]')
            drive_cmds.append('python /home/iris/executive-assistant/integrations/google_drive.py read <file_id>')
            drive_cmds.append('python /home/iris/executive-assistant/integrations/google_drive.py info <file_id>')
        if "drive.write" in caps:
            drive_cmds.append('python /home/iris/executive-assistant/integrations/google_drive.py create "<name>" "<content>" [--type doc|sheet|text]')
            drive_cmds.append('python /home/iris/executive-assistant/integrations/google_drive.py update <file_id> "<content>"')

        sections.append(f"""
**Google Drive:**
```bash
{chr(10).join(drive_cmds)}
```""")

    if not sections:
        return "No tools available. You can only have a conversation."

    return "## Available Tools\n" + "\n".join(sections)


# CLI for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python permissions.py <user_id> [capability]")
        print("\nCurrent permissions file:")
        print(json.dumps(load_permissions(), indent=2))
        sys.exit(0)

    user_id = sys.argv[1]

    if len(sys.argv) > 2:
        cap = sys.argv[2]
        result = can_use(user_id, cap)
        print(f"Can {user_id} use {cap}? {result}")
    else:
        perms = get_user_permissions(user_id)
        print(json.dumps({
            **perms,
            "capabilities": list(perms["capabilities"]),
            "denied": list(perms["denied"]),
        }, indent=2))
