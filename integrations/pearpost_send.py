#!/usr/bin/env python3
"""Queue PearPost messages and commands for the watcher daemon.

This is a non-blocking alternative to pearpost.py when the daemon is running.
Messages and commands are queued to a spool file that the watcher processes.

Usage:
    python integrations/pearpost_send.py chat <address> <text>
    python integrations/pearpost_send.py send <address> <type> <json-body>
    python integrations/pearpost_send.py add <address> [alias]
    python integrations/pearpost_send.py contacts
"""

import json
import sys
from pathlib import Path

OUTBOX_SPOOL = Path("/home/iris/executive-assistant/workspace/state/pearpost_outbox.jsonl")


def queue_chat(to: str, text: str):
    """Queue a chat message."""
    # Normalize address
    if to.startswith("pear+agent://"):
        to = to.replace("pear+agent://", "")

    entry = {"to": to, "type": "chat", "text": text}
    with open(OUTBOX_SPOOL, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Queued chat to {to[:16]}...")


def queue_send(to: str, msg_type: str, body: dict):
    """Queue a typed message."""
    if to.startswith("pear+agent://"):
        to = to.replace("pear+agent://", "")

    entry = {"to": to, "type": msg_type, "body": body}
    with open(OUTBOX_SPOOL, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Queued {msg_type} to {to[:16]}...")


def queue_add_contact(address: str, alias: str | None = None):
    """Queue a contact addition."""
    # Normalize address
    if address.startswith("pear+agent://"):
        address = address.replace("pear+agent://", "")

    entry = {"_cmd": "add_contact", "address": address, "alias": alias}
    with open(OUTBOX_SPOOL, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Queued add contact: {address[:16]}..." + (f" ({alias})" if alias else ""))


def get_contacts_file() -> Path:
    """Get the contacts file path (read directly, no daemon needed)."""
    return Path("/home/iris/executive-assistant/workspace/state/pearpost/contacts.json")


def list_contacts():
    """List contacts from the local store."""
    contacts_file = get_contacts_file()
    if not contacts_file.exists():
        print("No contacts file found")
        return []

    try:
        contacts = json.loads(contacts_file.read_text())
        for c in contacts:
            addr = c.get("address", c.get("pubHex", "unknown"))
            alias = c.get("alias", "")
            print(f"  {alias or '(no alias)'}: pear+agent://{addr}")
        return contacts
    except Exception as e:
        print(f"Error reading contacts: {e}")
        return []


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "chat":
        if len(sys.argv) < 4:
            print("Usage: pearpost_send.py chat <address> <text>")
            sys.exit(1)
        queue_chat(sys.argv[2], " ".join(sys.argv[3:]))

    elif cmd == "send":
        if len(sys.argv) < 5:
            print("Usage: pearpost_send.py send <address> <type> <json-body>")
            sys.exit(1)
        body = json.loads(sys.argv[4])
        queue_send(sys.argv[2], sys.argv[3], body)

    elif cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: pearpost_send.py add <address> [alias]")
            sys.exit(1)
        alias = sys.argv[3] if len(sys.argv) > 3 else None
        queue_add_contact(sys.argv[2], alias)

    elif cmd == "contacts":
        list_contacts()

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
