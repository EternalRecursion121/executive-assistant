#!/usr/bin/env python3
"""Channel message queue integration for Iris.

Queue messages to be posted to Discord channels by the bot.
Used by cron jobs and integrations that need to post without direct Discord access.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from config import STATE_DIR

QUEUE_FILE = STATE_DIR / "channel_message_queue.json"


def load_queue() -> list:
    """Load the message queue."""
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_queue(queue: list) -> None:
    """Save the message queue."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))


def queue_message(channel_id: str, content: str, create_thread: bool = False, thread_name: str = None) -> dict:
    """Queue a message to be sent to a channel.

    Args:
        channel_id: Discord channel ID
        content: Message content to send
        create_thread: If True, create a thread from the message
        thread_name: Name for the thread (if create_thread is True)

    Returns:
        Queued message info
    """
    queue = load_queue()

    msg = {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
        "channel_id": channel_id,
        "content": content,
        "create_thread": create_thread,
        "thread_name": thread_name,
        "queued_at": datetime.now().isoformat(),
        "sent": False,
    }

    queue.append(msg)
    save_queue(queue)

    return {"success": True, "message": msg}


def check_queue() -> list:
    """Check for pending messages and return them (for bot to send).

    Returns unsent messages and marks them as sent.
    """
    queue = load_queue()
    pending = [msg for msg in queue if not msg.get("sent")]

    # Mark as sent
    for msg in pending:
        msg["sent"] = True
        msg["sent_at"] = datetime.now().isoformat()

    save_queue(queue)

    return pending


def list_queue() -> list:
    """List all queued messages."""
    return load_queue()


def clear_sent() -> dict:
    """Clear sent messages from queue."""
    queue = load_queue()
    remaining = [msg for msg in queue if not msg.get("sent")]
    save_queue(remaining)
    return {"cleared": len(queue) - len(remaining), "remaining": len(remaining)}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: channel_message.py <command> [args]"}))
        sys.exit(1)

    command = sys.argv[1]

    if command == "send":
        if len(sys.argv) < 4:
            print(json.dumps({"error": "Usage: channel_message.py send <channel_id> <message> [--thread <name>]"}))
            sys.exit(1)

        channel_id = sys.argv[2]
        content = sys.argv[3]

        # Check for thread option
        create_thread = False
        thread_name = None
        if len(sys.argv) > 4 and sys.argv[4] == "--thread":
            create_thread = True
            thread_name = sys.argv[5] if len(sys.argv) > 5 else None

        result = queue_message(channel_id, content, create_thread, thread_name)
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
