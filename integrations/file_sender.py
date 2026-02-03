#!/usr/bin/env python3
"""File attachment queue for Discord messages.

Allows Claude to queue file attachments to be sent via Discord.
The bot checks this queue and sends files with messages.

Usage:
    python file_sender.py queue <channel_id> <file_path> [--message "<text>"]
    python file_sender.py queue-dm <user_id> <file_path> [--message "<text>"]
    python file_sender.py list
    python file_sender.py check  # For bot to consume queue
    python file_sender.py clear
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from config import STATE_DIR

STATE_FILE = STATE_DIR / "file_queue.json"


def load_queue() -> list:
    """Load the file queue."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            return []
    return []


def save_queue(queue: list):
    """Save the file queue."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(queue, indent=2))


def queue_file(channel_id: str, file_path: str, message: str = None, is_dm: bool = False):
    """Queue a file to be sent."""
    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    queue = load_queue()
    queue.append({
        "channel_id": channel_id,
        "file_path": str(path.absolute()),
        "message": message,
        "is_dm": is_dm,
        "queued_at": datetime.now().isoformat(),
    })
    save_queue(queue)

    target = f"user {channel_id}" if is_dm else f"channel {channel_id}"
    print(f"Queued {path.name} for {target}")


def list_queue():
    """List pending file attachments."""
    queue = load_queue()
    if not queue:
        print("No files queued.")
        return

    for i, item in enumerate(queue, 1):
        target = f"DM to {item['channel_id']}" if item.get("is_dm") else f"Channel {item['channel_id']}"
        msg = f" with message: {item['message'][:50]}..." if item.get("message") else ""
        print(f"{i}. {Path(item['file_path']).name} -> {target}{msg}")


def check_queue():
    """Output and clear pending files (for bot consumption)."""
    queue = load_queue()
    if queue:
        # Output queue as JSON for bot to parse
        print(json.dumps(queue))
        # Clear the queue
        save_queue([])


def clear_queue():
    """Clear all pending files."""
    save_queue([])
    print("File queue cleared.")


def main():
    parser = argparse.ArgumentParser(description="Queue files for Discord attachment")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Queue to channel
    queue_parser = subparsers.add_parser("queue", help="Queue file for channel")
    queue_parser.add_argument("channel_id", help="Discord channel ID")
    queue_parser.add_argument("file_path", help="Path to file to send")
    queue_parser.add_argument("--message", "-m", help="Optional message with file")

    # Queue to DM
    dm_parser = subparsers.add_parser("queue-dm", help="Queue file for DM")
    dm_parser.add_argument("user_id", help="Discord user ID")
    dm_parser.add_argument("file_path", help="Path to file to send")
    dm_parser.add_argument("--message", "-m", help="Optional message with file")

    # List queue
    subparsers.add_parser("list", help="List queued files")

    # Check (for bot)
    subparsers.add_parser("check", help="Output and clear queue (for bot)")

    # Clear queue
    subparsers.add_parser("clear", help="Clear file queue")

    args = parser.parse_args()

    if args.command == "queue":
        queue_file(args.channel_id, args.file_path, args.message)
    elif args.command == "queue-dm":
        queue_file(args.user_id, args.file_path, args.message, is_dm=True)
    elif args.command == "list":
        list_queue()
    elif args.command == "check":
        check_queue()
    elif args.command == "clear":
        clear_queue()


if __name__ == "__main__":
    main()
