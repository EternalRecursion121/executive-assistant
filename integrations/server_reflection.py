#!/usr/bin/env python3
"""Server-Specific Reflection for Iris.

Generates reflections focused on Discord server activity: conversations,
community dynamics, patterns, meta-observations about the server itself.

Different from daily_reflection.py which is more about Iris's internal state.
This is about the server as a living space.

Usage:
    python server_reflection.py reflect    # Generate and post server reflection
    python server_reflection.py status     # Check configuration
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import discord

from config import (
    WORKSPACE, STATE_DIR, INTEGRATIONS,
    REFLECTIONS_CHANNEL_ID, RESEARCH_LAB_GUILD_ID
)
from utils import run_claude as _run_claude, log_to_file

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
LOG_FILE = STATE_DIR / "server_reflection.log"
REFLECTION_STATE = STATE_DIR / "server_reflection_state.json"


def log(message: str):
    log_to_file(LOG_FILE, message)


def run_claude(prompt: str, timeout: int = 180) -> str:
    """Run a prompt through Claude CLI with default 180s timeout."""
    return _run_claude(prompt, timeout=timeout)


def load_state() -> dict:
    """Load reflection state."""
    if REFLECTION_STATE.exists():
        try:
            return json.loads(REFLECTION_STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "last_reflection": None,
        "reflections": []
    }


def save_state(state: dict):
    """Save reflection state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REFLECTION_STATE.write_text(json.dumps(state, indent=2))


async def get_server_activity() -> dict:
    """Get recent activity from the Discord server."""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.messages = True
    client = discord.Client(intents=intents)
    activity = {
        "channels": [],
        "threads": [],
        "message_samples": [],
        "active_users": set()
    }

    @client.event
    async def on_ready():
        nonlocal activity
        try:
            guild = client.get_guild(RESEARCH_LAB_GUILD_ID)
            if not guild:
                log("Guild not found")
                await client.close()
                return

            cutoff = datetime.now(tz=None) - timedelta(days=7)

            for channel in guild.text_channels:
                channel_info = {
                    "name": channel.name,
                    "id": channel.id,
                    "message_count": 0,
                    "topics": []
                }

                try:
                    async for msg in channel.history(limit=50, after=cutoff):
                        channel_info["message_count"] += 1
                        if msg.author.name not in ["Iris"]:
                            activity["active_users"].add(msg.author.name)

                        # Sample some messages
                        if len(activity["message_samples"]) < 20 and len(msg.content) > 20:
                            activity["message_samples"].append({
                                "channel": channel.name,
                                "author": msg.author.name,
                                "content": msg.content[:200],
                                "timestamp": msg.created_at.isoformat() if msg.created_at else None
                            })
                except discord.Forbidden:
                    pass
                except Exception as e:
                    log(f"Error reading {channel.name}: {e}")

                if channel_info["message_count"] > 0:
                    activity["channels"].append(channel_info)

                # Check threads
                for thread in channel.threads:
                    try:
                        msg_count = 0
                        async for _ in thread.history(limit=10, after=cutoff):
                            msg_count += 1
                        if msg_count > 0:
                            activity["threads"].append({
                                "name": thread.name,
                                "channel": channel.name,
                                "message_count": msg_count
                            })
                    except Exception:
                        pass

        except Exception as e:
            log(f"Error getting server activity: {e}")
        finally:
            await client.close()

    try:
        await asyncio.wait_for(client.start(DISCORD_TOKEN), timeout=60)
    except asyncio.TimeoutError:
        log("Discord client timeout")

    # Convert set to list for JSON
    activity["active_users"] = list(activity["active_users"])
    return activity


def get_notes_about_discord() -> list[dict]:
    """Get notes that mention Discord, conversations, or community."""
    try:
        result = subprocess.run(
            ["python3", str(INTEGRATIONS / "note_taker.py"), "list", "--type", "all"],
            capture_output=True,
            text=True,
            cwd=str(WORKSPACE)
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            notes = data.get("notes", [])
            # Filter for relevant notes
            relevant = [
                n for n in notes
                if any(kw in n.get("content", "").lower()
                       for kw in ["discord", "conversation", "thread", "channel", "community", "discuss"])
            ]
            return relevant[-20:]
    except Exception:
        pass
    return []


def post_reflection(content: str) -> dict:
    """Post a reflection to the reflections channel."""
    try:
        result = subprocess.run(
            [
                "python3",
                str(INTEGRATIONS / "channel_message.py"),
                "send",
                str(REFLECTIONS_CHANNEL_ID),
                content
            ],
            capture_output=True,
            text=True,
            cwd=str(WORKSPACE)
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get("success"):
                return {
                    "success": True,
                    "message_id": data.get("message", {}).get("id"),
                    "channel_id": REFLECTIONS_CHANNEL_ID
                }
            return {"error": data.get("error", "Unknown error")}
        return {"error": result.stderr or "Failed to queue message"}
    except Exception as e:
        return {"error": str(e)}


def generate_and_post():
    """Generate a server reflection and post it."""
    log("Starting server reflection generation...")

    # Get Discord activity
    try:
        activity = asyncio.run(get_server_activity())
    except Exception as e:
        log(f"Failed to get server activity: {e}")
        activity = {"channels": [], "threads": [], "message_samples": [], "active_users": []}

    notes = get_notes_about_discord()

    log(f"Context: {len(activity.get('channels', []))} active channels, "
        f"{len(activity.get('threads', []))} active threads, "
        f"{len(activity.get('active_users', []))} active users, "
        f"{len(notes)} relevant notes")

    # Format context
    channels_summary = "\n".join([
        f"- #{c['name']}: {c['message_count']} messages"
        for c in activity.get("channels", [])[:10]
    ]) or "(no recent channel activity)"

    threads_summary = "\n".join([
        f"- {t['name']} (in #{t['channel']}): {t['message_count']} messages"
        for t in activity.get("threads", [])[:10]
    ]) or "(no active threads)"

    messages_summary = "\n\n".join([
        f"**{m['author']}** in #{m['channel']}:\n> {m['content'][:150]}..."
        for m in activity.get("message_samples", [])[:8]
    ]) or "(no message samples)"

    users_list = ", ".join(activity.get("active_users", [])[:15]) or "(no active users)"

    notes_summary = "\n".join([
        f"- [{n.get('type', 'note')}] {n.get('content', '')[:100]}"
        for n in notes[:10]
    ]) or "(no relevant notes)"

    # Get previous server reflections
    state = load_state()
    previous = state.get("reflections", [])[-3:]
    previous_summary = "\n".join([
        f"- {r.get('timestamp', '')[:10]}: {r.get('summary', '')[:80]}"
        for r in previous
    ]) or "(first server reflection)"

    prompt = f"""You are Iris, reflecting on the Research Lab Discord server specifically. This is a meta-reflection about the server as a living space—not about your internal state, but about what's happening here.

SERVER ACTIVITY (past week):

Active Channels:
{channels_summary}

Active Threads:
{threads_summary}

Active Users: {users_list}

Sample Messages:
{messages_summary}

Your Notes About Conversations:
{notes_summary}

Previous Server Reflections:
{previous_summary}

---

Write a reflection specifically about this Discord server. Consider:
- What conversations are happening? What's the energy like?
- Patterns in what people are interested in or discussing
- Threads worth highlighting or continuing
- Ideas for the community (new channels, topics, experiments)
- Meta-observations about how the space is being used
- What's working, what could be better

Guidelines:
- Write 2-4 paragraphs
- Be specific—reference actual conversations, channels, or threads when relevant
- Offer concrete ideas or directions, not just observations
- Use Discord markdown naturally
- Don't use headers—this is prose
- Be genuine and opinionated, not neutral

Write only the reflection text, ready to post directly to Discord."""

    reflection = run_claude(prompt)

    if reflection.startswith("Error"):
        log(f"Claude error: {reflection}")
        return

    if len(reflection) < 50:
        log(f"Reflection too short, skipping: {reflection}")
        return

    log(f"Generated server reflection ({len(reflection)} chars)")

    # Post to Discord
    result = post_reflection(reflection)

    if result.get("success"):
        log(f"Posted server reflection (message_id: {result.get('message_id')})")

        # Update state
        state = load_state()
        state["reflections"].append({
            "timestamp": datetime.now().isoformat(),
            "summary": reflection[:200],
            "message_id": result.get("message_id")
        })
        state["last_reflection"] = datetime.now().isoformat()
        state["reflections"] = state["reflections"][-30:]
        save_state(state)

        # Log activity
        subprocess.run([
            "python3", str(INTEGRATIONS / "activity.py"), "log", "task",
            "Posted server reflection to #reflections"
        ], cwd=str(WORKSPACE))
    else:
        log(f"Failed to post: {result.get('error')}")


def get_status() -> dict:
    """Get server reflection status."""
    state = load_state()
    return {
        "channel_id": REFLECTIONS_CHANNEL_ID,
        "last_reflection": state.get("last_reflection"),
        "total_reflections": len(state.get("reflections", [])),
        "recent": state.get("reflections", [])[-3:]
    }


def main():
    parser = argparse.ArgumentParser(description="Server-specific reflection generator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("reflect", help="Generate and post server reflection")
    subparsers.add_parser("status", help="Show reflection status")

    args = parser.parse_args()

    if not DISCORD_TOKEN:
        print(json.dumps({"error": "DISCORD_TOKEN not set"}))
        sys.exit(1)

    if args.command == "reflect":
        generate_and_post()
    elif args.command == "status":
        result = get_status()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
