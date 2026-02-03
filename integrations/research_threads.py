#!/usr/bin/env python3
"""
Research Thread Auto-Threading Integration

Monitors designated research channels and:
1. Automatically creates threads for new messages
2. Contributes Iris's thoughts/opinions within threads when relevant

Configuration stored in workspace/state/research_threads.json
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import discord

from config import WORKSPACE, STATE_DIR

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
STATE_FILE = STATE_DIR / "research_threads.json"


def load_state() -> dict:
    """Load research threads state."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "enabled": True,
        "channels": [],  # List of channel IDs to monitor
        "thread_prefix": "",  # Optional prefix for thread names
        "contribute_thoughts": True,  # Whether Iris should add opinions
        "processed_messages": [],  # Track already-processed message IDs
    }


def save_state(state: dict):
    """Save research threads state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


async def list_channels(guild_id: int) -> list:
    """List all text channels in a guild."""
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    channels = []

    @client.event
    async def on_ready():
        nonlocal channels
        try:
            guild = client.get_guild(guild_id)
            if guild:
                for channel in guild.channels:
                    if isinstance(channel, discord.TextChannel):
                        channels.append({
                            "id": channel.id,
                            "name": channel.name,
                            "category": channel.category.name if channel.category else None
                        })
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return channels


async def create_thread_for_message(channel_id: int, message_id: int, thread_name: str) -> dict:
    """Create a thread from a message."""
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    result = {}

    @client.event
    async def on_ready():
        nonlocal result
        try:
            channel = client.get_channel(channel_id)
            if not channel:
                result = {"error": f"Channel {channel_id} not found"}
                await client.close()
                return

            message = await channel.fetch_message(message_id)

            # Create thread from message
            thread = await message.create_thread(
                name=thread_name[:100],  # Discord limit
                auto_archive_duration=10080  # 7 days
            )

            result = {
                "success": True,
                "thread_id": thread.id,
                "thread_name": thread.name,
                "message_id": message_id
            }
        except discord.Forbidden:
            result = {"error": "Missing permissions to create thread"}
        except discord.HTTPException as e:
            result = {"error": f"Discord API error: {e}"}
        except Exception as e:
            result = {"error": str(e)}
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return result


async def post_to_thread(thread_id: int, content: str) -> dict:
    """Post a message to a thread."""
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    result = {}

    @client.event
    async def on_ready():
        nonlocal result
        try:
            thread = client.get_channel(thread_id)
            if not thread:
                # Try fetching it
                thread = await client.fetch_channel(thread_id)

            if not thread:
                result = {"error": f"Thread {thread_id} not found"}
                await client.close()
                return

            msg = await thread.send(content)
            result = {
                "success": True,
                "message_id": msg.id
            }
        except Exception as e:
            result = {"error": str(e)}
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return result


def add_channel(channel_id: int):
    """Add a channel to the monitored list."""
    state = load_state()
    if channel_id not in state["channels"]:
        state["channels"].append(channel_id)
        save_state(state)
        return {"success": True, "message": f"Added channel {channel_id}"}
    return {"success": True, "message": f"Channel {channel_id} already monitored"}


def remove_channel(channel_id: int):
    """Remove a channel from the monitored list."""
    state = load_state()
    if channel_id in state["channels"]:
        state["channels"].remove(channel_id)
        save_state(state)
        return {"success": True, "message": f"Removed channel {channel_id}"}
    return {"error": f"Channel {channel_id} not in list"}


def get_status():
    """Get current configuration status."""
    state = load_state()
    return {
        "enabled": state["enabled"],
        "monitored_channels": state["channels"],
        "contribute_thoughts": state["contribute_thoughts"],
        "processed_count": len(state.get("processed_messages", []))
    }


def set_enabled(enabled: bool):
    """Enable or disable auto-threading."""
    state = load_state()
    state["enabled"] = enabled
    save_state(state)
    return {"success": True, "enabled": enabled}


def main():
    parser = argparse.ArgumentParser(description="Research thread auto-threading")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Status
    subparsers.add_parser("status", help="Show current configuration")

    # Enable/disable
    enable_parser = subparsers.add_parser("enable", help="Enable auto-threading")
    disable_parser = subparsers.add_parser("disable", help="Disable auto-threading")

    # Add channel
    add_parser = subparsers.add_parser("add", help="Add channel to monitor")
    add_parser.add_argument("channel_id", type=int, help="Channel ID")

    # Remove channel
    remove_parser = subparsers.add_parser("remove", help="Remove channel from monitoring")
    remove_parser.add_argument("channel_id", type=int, help="Channel ID")

    # List available channels
    list_parser = subparsers.add_parser("list", help="List available channels")
    list_parser.add_argument("guild_id", type=int, help="Guild ID")

    # Create thread (for testing)
    thread_parser = subparsers.add_parser("thread", help="Create thread from message")
    thread_parser.add_argument("channel_id", type=int, help="Channel ID")
    thread_parser.add_argument("message_id", type=int, help="Message ID")
    thread_parser.add_argument("name", help="Thread name")

    # Post to thread
    post_parser = subparsers.add_parser("post", help="Post to a thread")
    post_parser.add_argument("thread_id", type=int, help="Thread ID")
    post_parser.add_argument("content", help="Message content")

    args = parser.parse_args()

    if args.command == "status":
        result = get_status()
    elif args.command == "enable":
        result = set_enabled(True)
    elif args.command == "disable":
        result = set_enabled(False)
    elif args.command == "add":
        result = add_channel(args.channel_id)
    elif args.command == "remove":
        result = remove_channel(args.channel_id)
    elif args.command == "list":
        if not DISCORD_TOKEN:
            print(json.dumps({"error": "DISCORD_TOKEN not set"}))
            sys.exit(1)
        result = asyncio.run(list_channels(args.guild_id))
    elif args.command == "thread":
        if not DISCORD_TOKEN:
            print(json.dumps({"error": "DISCORD_TOKEN not set"}))
            sys.exit(1)
        result = asyncio.run(create_thread_for_message(args.channel_id, args.message_id, args.name))
    elif args.command == "post":
        if not DISCORD_TOKEN:
            print(json.dumps({"error": "DISCORD_TOKEN not set"}))
            sys.exit(1)
        result = asyncio.run(post_to_thread(args.thread_id, args.content))

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
