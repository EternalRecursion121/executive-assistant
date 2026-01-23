#!/usr/bin/env python3
"""Direct message integration for Iris.

Send private messages to users without cluttering public channels.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

STATE_DIR = Path("/home/executive-assistant/workspace/state")
DM_QUEUE_FILE = STATE_DIR / "dm_queue.json"

# Known users (for convenience)
USERS = {
    "samuel": "672500045249249328",
    "xi": "208220776619311105",
}


def load_queue() -> list:
    """Load the DM queue."""
    if DM_QUEUE_FILE.exists():
        return json.loads(DM_QUEUE_FILE.read_text())
    return []


def save_queue(queue: list) -> None:
    """Save the DM queue."""
    DM_QUEUE_FILE.write_text(json.dumps(queue, indent=2))


def queue_dm(user: str, message: str) -> dict:
    """Queue a DM to be sent by the bot.

    Args:
        user: Username (samuel, xi) or Discord user ID
        message: Message content to send

    Returns:
        Queued message info
    """
    # Resolve username to ID
    user_id = USERS.get(user.lower(), user)

    queue = load_queue()

    dm = {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
        "user_id": user_id,
        "message": message,
        "queued_at": datetime.now().isoformat(),
        "sent": False,
    }

    queue.append(dm)
    save_queue(queue)

    return {"success": True, "dm": dm}


def check_queue() -> list:
    """Check for pending DMs and return them (for bot to send).

    Returns unsent DMs and marks them as sent.
    """
    queue = load_queue()
    pending = [dm for dm in queue if not dm.get("sent")]

    # Mark as sent
    for dm in pending:
        dm["sent"] = True
        dm["sent_at"] = datetime.now().isoformat()

    save_queue(queue)

    return pending


def list_queue() -> list:
    """List all queued DMs."""
    return load_queue()


def clear_sent() -> dict:
    """Clear sent DMs from queue."""
    queue = load_queue()
    remaining = [dm for dm in queue if not dm.get("sent")]
    save_queue(remaining)
    return {"cleared": len(queue) - len(remaining), "remaining": len(remaining)}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: dm.py <command> [args]"}))
        sys.exit(1)

    command = sys.argv[1]

    if command == "send":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: dm.py send <user> <message>"}))
            sys.exit(1)
        result = queue_dm(sys.argv[2], sys.argv[3])
        print(json.dumps(result))

    elif command == "check":
        pending = check_queue()
        print(json.dumps(pending))

    elif command == "list":
        queue = list_queue()
        print(json.dumps(queue))

    elif command == "clear":
        result = clear_sent()
        print(json.dumps(result))

    else:
        print(json.dumps({"error": f"Unknown command: {command}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
