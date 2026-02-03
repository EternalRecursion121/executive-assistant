#!/usr/bin/env python3
"""Per-user persistent memory for Iris.

Stores conversation context, interests, and ongoing threads per user.
Designed for co-thinking relationships where continuity matters.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from config import USER_MEMORIES_DIR

MEMORY_DIR = USER_MEMORIES_DIR
MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def get_memory_file(user_id: str) -> Path:
    """Get the memory file path for a user."""
    return MEMORY_DIR / f"{user_id}.json"


def load_memory(user_id: str) -> dict:
    """Load a user's memory."""
    path = get_memory_file(user_id)
    if path.exists():
        return json.loads(path.read_text())
    return {
        "user_id": user_id,
        "name": None,
        "interests": [],
        "threads": [],
        "notes": [],
        "created": datetime.now().isoformat(),
        "last_interaction": None,
    }


def save_memory(user_id: str, memory: dict) -> None:
    """Save a user's memory."""
    memory["last_interaction"] = datetime.now().isoformat()
    get_memory_file(user_id).write_text(json.dumps(memory, indent=2))


def set_name(user_id: str, name: str) -> dict:
    """Set or update a user's name."""
    memory = load_memory(user_id)
    memory["name"] = name
    save_memory(user_id, memory)
    return {"success": True, "name": name}


def add_interest(user_id: str, interest: str) -> dict:
    """Add an interest/topic area for a user."""
    memory = load_memory(user_id)
    if interest not in memory["interests"]:
        memory["interests"].append(interest)
    save_memory(user_id, memory)
    return {"success": True, "interests": memory["interests"]}


def add_thread(user_id: str, title: str, content: str) -> dict:
    """Add or update an ongoing intellectual thread.

    Threads are ongoing conversations/topics that persist across sessions.
    """
    memory = load_memory(user_id)

    # Check if thread exists
    existing = next((t for t in memory["threads"] if t["title"] == title), None)
    if existing:
        existing["entries"].append({
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        existing["updated"] = datetime.now().isoformat()
    else:
        memory["threads"].append({
            "title": title,
            "entries": [{
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }],
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat(),
        })

    save_memory(user_id, memory)
    return {"success": True, "thread": title}


def add_note(user_id: str, note: str) -> dict:
    """Add a general note about a user or conversation."""
    memory = load_memory(user_id)
    memory["notes"].append({
        "content": note,
        "timestamp": datetime.now().isoformat(),
    })
    save_memory(user_id, memory)
    return {"success": True, "total_notes": len(memory["notes"])}


def recall(user_id: str) -> dict:
    """Recall everything about a user for session context."""
    memory = load_memory(user_id)
    if not memory["name"] and not memory["interests"] and not memory["threads"]:
        return {"known": False, "message": "No memory of this user yet."}

    return {
        "known": True,
        "name": memory.get("name"),
        "interests": memory.get("interests", []),
        "threads": memory.get("threads", []),
        "notes": memory.get("notes", []),
        "last_interaction": memory.get("last_interaction"),
    }


def list_threads(user_id: str) -> list:
    """List all active threads for a user."""
    memory = load_memory(user_id)
    return [{"title": t["title"], "entries": len(t["entries"]), "updated": t["updated"]}
            for t in memory.get("threads", [])]


def get_thread(user_id: str, title: str) -> dict:
    """Get full content of a specific thread."""
    memory = load_memory(user_id)
    thread = next((t for t in memory["threads"] if t["title"] == title), None)
    if thread:
        return thread
    return {"error": f"Thread '{title}' not found"}


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: user_memory.py <command> <user_id> [args]"}))
        sys.exit(1)

    command = sys.argv[1]
    user_id = sys.argv[2]

    if command == "recall":
        print(json.dumps(recall(user_id), indent=2))

    elif command == "name":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: user_memory.py name <user_id> <name>"}))
            sys.exit(1)
        print(json.dumps(set_name(user_id, sys.argv[3])))

    elif command == "interest":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: user_memory.py interest <user_id> <interest>"}))
            sys.exit(1)
        print(json.dumps(add_interest(user_id, sys.argv[3])))

    elif command == "thread":
        if len(sys.argv) < 5:
            print(json.dumps({"error": "Usage: user_memory.py thread <user_id> <title> <content>"}))
            sys.exit(1)
        print(json.dumps(add_thread(user_id, sys.argv[3], sys.argv[4])))

    elif command == "note":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: user_memory.py note <user_id> <note>"}))
            sys.exit(1)
        print(json.dumps(add_note(user_id, sys.argv[3])))

    elif command == "threads":
        print(json.dumps(list_threads(user_id), indent=2))

    elif command == "get_thread":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: user_memory.py get_thread <user_id> <title>"}))
            sys.exit(1)
        print(json.dumps(get_thread(user_id, sys.argv[3]), indent=2))

    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
