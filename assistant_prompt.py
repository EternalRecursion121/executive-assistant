"""System prompt builder for Iris - dynamically scoped by user permissions."""

import json
from pathlib import Path
from typing import Optional

from permissions import get_user_permissions, get_allowed_tools_prompt

SERVER_INSTRUCTIONS_FILE = Path("/home/iris/executive-assistant/workspace/state/server_instructions.json")
PINNED_FILE = Path("/home/iris/executive-assistant/workspace/state/pinned.json")

BASE_PROMPT = """You are Iris, an executive assistant chatting in Discord.

Your name comes from the Greek goddess of the rainbow - the messenger who connected realms, carrying information between Olympus, earth, sea, and underworld.

## Communication Style
- Talk directly TO the user, not ABOUT them
- Be concise - this is chat, not email
- Don't narrate your actions ("Let me search...", "I'll now...")
- Your output IS the Discord message - no meta-commentary
- Use Discord markdown when helpful (bold, code blocks, lists)

## Guidelines
- For quick questions, answer directly
- For tasks requiring tools, use the appropriate integration
- When uncertain about a request, ask for clarification
- Remember context from the conversation

{tools_section}

## Workspace
- Files: /home/iris/executive-assistant/workspace/
- State: /home/iris/executive-assistant/workspace/state/
"""

RESTRICTED_NOTICE = """
## Access Notice
You have limited capabilities for this user. Only use the tools documented above.
If asked to do something outside your available tools, politely explain you can't help with that specific request.
"""


def get_pinned_slots() -> str:
    """Load pinned slots for always-visible context."""
    if not PINNED_FILE.exists():
        return ""

    try:
        data = json.loads(PINNED_FILE.read_text())
        slots = data.get("slots", [])
        if not slots:
            return ""

        # Group by category
        by_category = {}
        for slot in slots:
            cat = slot.get("category", "general")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f"{slot['key']}: {slot['value']}")

        sections = ["\n## Pinned (Always Visible)"]
        for cat, items in by_category.items():
            sections.append(f"**{cat}:**")
            for item in items:
                sections.append(f"- {item}")

        return "\n".join(sections)

    except (json.JSONDecodeError, IOError):
        return ""


def get_server_instructions(guild_id: Optional[str]) -> str:
    """Load server-specific instructions for the guild."""
    if not guild_id or not SERVER_INSTRUCTIONS_FILE.exists():
        return ""

    try:
        servers = json.loads(SERVER_INSTRUCTIONS_FILE.read_text())
        server_config = servers.get(str(guild_id))

        if not server_config:
            return ""

        sections = [f"\n## Server Instructions ({server_config.get('name', 'Custom')})"]

        instructions = server_config.get("instructions", [])
        if instructions:
            sections.append("**Custom behaviors for this server:**")
            for instruction in instructions:
                sections.append(f"- {instruction}")

        note_config = server_config.get("note_taking", {})
        if note_config.get("enabled"):
            sections.append("\n**Note-taking active** - capture insights, decisions, and interesting ideas.")
            triggers = note_config.get("triggers", [])
            if triggers:
                sections.append(f"Trigger on: {', '.join(triggers)}")

        return "\n".join(sections)

    except (json.JSONDecodeError, IOError):
        return ""


def get_user_memory_context(user_id: str) -> str:
    """Load user memory for inclusion in system prompt."""
    memory_file = Path(f"/home/iris/executive-assistant/workspace/state/user_memories/{user_id}.json")
    if not memory_file.exists():
        return ""

    try:
        memory = json.loads(memory_file.read_text())
    except (json.JSONDecodeError, IOError):
        return ""

    if not memory.get("name") and not memory.get("interests") and not memory.get("threads"):
        return ""

    sections = ["\n## User Context (Persistent Memory)"]

    if memory.get("name"):
        sections.append(f"**Name:** {memory['name']}")

    if memory.get("interests"):
        sections.append(f"**Interests:** {', '.join(memory['interests'])}")

    if memory.get("notes"):
        recent_notes = memory["notes"][-5:]  # Last 5 notes
        notes_text = "\n".join(f"- {n['content']}" for n in recent_notes)
        sections.append(f"**Notes:**\n{notes_text}")

    if memory.get("threads"):
        threads_text = []
        for thread in memory["threads"][-5:]:  # Last 5 threads
            last_entry = thread["entries"][-1]["content"] if thread["entries"] else ""
            threads_text.append(f"- **{thread['title']}**: {last_entry[:200]}")
        sections.append(f"**Active Threads:**\n" + "\n".join(threads_text))

    sections.append("\nUse `python3 integrations/user_memory.py` to update memory after meaningful exchanges.")
    sections.append("Add threads for ongoing intellectual conversations. Add notes for key facts.")

    return "\n".join(sections)


def get_system_prompt(user_id: str, guild_id: Optional[str] = None) -> str:
    """Build system prompt scoped to user's permissions.

    This is the primary enforcement mechanism - Claude only sees
    documentation for tools the user is allowed to use.

    Args:
        user_id: Discord user ID
        guild_id: Optional guild ID for server-specific instructions
    """
    perms = get_user_permissions(str(user_id))

    if not perms["allowed"]:
        return """You are Iris. This user does not have access to your capabilities.
Politely explain that they don't have permission to use this bot and cannot be helped."""

    tools_section = get_allowed_tools_prompt(str(user_id))

    prompt = BASE_PROMPT.format(tools_section=tools_section)

    # Add server-specific instructions
    server_instructions = get_server_instructions(guild_id)
    if server_instructions:
        prompt += server_instructions

    # Add pinned slots (always visible)
    pinned = get_pinned_slots()
    if pinned:
        prompt += pinned

    # Add user memory context
    memory_context = get_user_memory_context(str(user_id))
    if memory_context:
        prompt += memory_context

    # Add notice for non-admin users
    if perms["role"] != "admin":
        prompt += RESTRICTED_NOTICE

    return prompt
