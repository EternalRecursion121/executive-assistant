#!/usr/bin/env python3
"""PearPost wake consumer - processes incoming messages and invokes Claude.

This script reads from the wake spool (populated by pearpost_watcher.mjs),
and invokes Claude to respond to new messages.

Usage:
    python integrations/pearpost_wake_consumer.py         # Process spool once
    python integrations/pearpost_wake_consumer.py --poll  # Poll continuously
    python integrations/pearpost_wake_consumer.py --status # Show spool status
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Flush stdout immediately for logging
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

PROJECT_ROOT = Path("/home/iris/executive-assistant")
WAKE_SPOOL = PROJECT_ROOT / "workspace" / "state" / "pearpost_wake.jsonl"
CONSUMED_FILE = PROJECT_ROOT / "workspace" / "state" / "pearpost_consumed.json"
CONTACTS_CACHE = PROJECT_ROOT / "workspace" / "state" / "pearpost_contacts.json"
POLL_INTERVAL = 5  # seconds

# Contacts we auto-respond to (pub hex -> alias)
TRUSTED_CONTACTS = {
    "ef719aa4a3893a2af9a086401ef489085f5ef0a5c592ba7cd169f0f1be2f8d09": "hermes",
}


def load_consumed() -> set[str]:
    """Load IDs of messages we've already consumed."""
    try:
        return set(json.loads(CONSUMED_FILE.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_consumed(consumed: set[str]):
    """Save consumed IDs, keeping only last 500."""
    arr = list(consumed)[-500:]
    CONSUMED_FILE.write_text(json.dumps(arr, indent=2))


def read_spool() -> list[dict]:
    """Read all entries from the wake spool."""
    if not WAKE_SPOOL.exists():
        return []

    entries = []
    for line in WAKE_SPOOL.read_text().strip().split("\n"):
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def clear_spool():
    """Clear the wake spool after processing."""
    WAKE_SPOOL.write_text("")


def get_sender_alias(from_hex: str) -> str | None:
    """Get human-readable alias for a sender."""
    return TRUSTED_CONTACTS.get(from_hex)


def is_trusted_sender(from_hex: str) -> bool:
    """Check if sender is trusted for auto-response."""
    return from_hex in TRUSTED_CONTACTS


def invoke_claude(message: dict) -> str | None:
    """Invoke Claude to handle an incoming PearPost message."""
    from_hex = message.get("from", "")
    sender = get_sender_alias(from_hex) or from_hex[:16]
    msg_type = message.get("type", "unknown")
    body = message.get("body", {})

    if msg_type == "chat":
        text = body.get("text", "") if isinstance(body, dict) else str(body)
    else:
        text = json.dumps(body)

    prompt = f"""You received a PearPost message from {sender}:

Type: {msg_type}
Content: {text}

Respond appropriately. If this requires a reply, use the PearPost integration to send one.
Use: venv/bin/python integrations/pearpost.py chat "pear+agent://{from_hex}" "<your reply>"
"""

    # Invoke Claude Code
    result = subprocess.run(
        [
            str(PROJECT_ROOT / "venv" / "bin" / "python"),
            "-m", "claude_code",
            "--print",
            "-m", prompt,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(PROJECT_ROOT),
    )

    return result.stdout if result.returncode == 0 else None


def invoke_claude_simple(message: dict) -> str | None:
    """Invoke Claude using the same mechanism as the bot."""
    # Add project root to path for imports
    sys.path.insert(0, str(PROJECT_ROOT))
    from claude_client import ClaudeClient
    from assistant_prompt import get_system_prompt

    from_hex = message.get("from", "")
    sender = get_sender_alias(from_hex) or from_hex[:16]
    msg_type = message.get("type", "unknown")
    body = message.get("body", {})

    if msg_type == "chat":
        text = body.get("text", "") if isinstance(body, dict) else str(body)
    else:
        text = json.dumps(body)

    prompt = f"""[PearPost message from {sender}]

{text}

---
If this message warrants a reply, respond using PearPost:
venv/bin/python integrations/pearpost.py chat "pear+agent://{from_hex}" "<your reply>"
"""

    client = ClaudeClient(
        workspace=PROJECT_ROOT / "workspace",
        timeout=300,
        claude_path="/home/iris/.local/bin/claude"
    )
    loop = asyncio.new_event_loop()
    try:
        response = loop.run_until_complete(
            client.send(message=prompt, system_prompt=get_system_prompt("pearpost", None))
        )
        return response
    finally:
        loop.close()


def process_spool_once() -> int:
    """Process all unprocessed messages in spool. Returns count processed."""
    entries = read_spool()
    if not entries:
        return 0

    consumed = load_consumed()
    processed = 0

    for entry in entries:
        msg_id = entry.get("id")
        if not msg_id:
            continue
        if msg_id in consumed:
            continue

        from_hex = entry.get("from", "")

        # Skip untrusted senders
        if not is_trusted_sender(from_hex):
            print(f"[wake-consumer] Skipping untrusted sender: {from_hex[:16]}...")
            consumed.add(msg_id)
            continue

        print(f"[wake-consumer] Processing message {msg_id} from {get_sender_alias(from_hex)}")

        try:
            response = invoke_claude_simple(entry)
            if response:
                print(f"[wake-consumer] Claude responded: {response[:200]}...")
            consumed.add(msg_id)
            processed += 1
        except Exception as e:
            print(f"[wake-consumer] Error processing message: {e}")

    save_consumed(consumed)
    clear_spool()

    return processed


def poll_loop():
    """Continuously poll and process the spool."""
    print(f"[wake-consumer] Starting poll loop (interval: {POLL_INTERVAL}s)")

    while True:
        try:
            count = process_spool_once()
            if count > 0:
                print(f"[wake-consumer] Processed {count} messages")
        except Exception as e:
            print(f"[wake-consumer] Error in poll loop: {e}")

        time.sleep(POLL_INTERVAL)


def show_status():
    """Show current spool status."""
    entries = read_spool()
    consumed = load_consumed()

    print(f"Wake spool: {WAKE_SPOOL}")
    print(f"Total entries in spool: {len(entries)}")
    print(f"Consumed message IDs: {len(consumed)}")

    pending = [e for e in entries if e.get("id") not in consumed]
    print(f"Pending to process: {len(pending)}")

    if pending:
        print("\nPending messages:")
        for entry in pending[:10]:
            sender = get_sender_alias(entry.get("from", "")) or entry.get("from", "")[:16]
            trusted = "✓" if is_trusted_sender(entry.get("from", "")) else "✗"
            print(f"  [{trusted}] {entry.get('type')} from {sender}: {str(entry.get('body', ''))[:50]}...")


def main():
    parser = argparse.ArgumentParser(description="PearPost wake consumer")
    parser.add_argument("--poll", action="store_true", help="Poll continuously")
    parser.add_argument("--status", action="store_true", help="Show spool status")
    args = parser.parse_args()

    # Ensure we're in the right directory
    os.chdir(PROJECT_ROOT)

    if args.status:
        show_status()
    elif args.poll:
        poll_loop()
    else:
        count = process_spool_once()
        print(f"Processed {count} messages")


if __name__ == "__main__":
    main()
