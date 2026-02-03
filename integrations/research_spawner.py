#!/usr/bin/env python3
"""Research Thread Spawner for Iris.

Analyzes existing research threads, reads notes from Iris vault, and spawns
new research threads based on patterns, connections, and evolving interests.

Run via cron to autonomously initiate research discussions.
"""

import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import discord

from config import WORKSPACE, STATE_DIR, INTEGRATIONS, IRIS_VAULT
from utils import run_claude as _run_claude, log_to_file

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
LOG_FILE = STATE_DIR / "research_spawner.log"
THREADS_STATE = STATE_DIR / "research_threads.json"
SPAWNER_STATE = STATE_DIR / "research_spawner_state.json"


def log(message: str):
    log_to_file(LOG_FILE, message)


def run_claude(prompt: str, timeout: int = 180) -> str:
    """Run a prompt through Claude CLI with default 180s timeout."""
    return _run_claude(prompt, timeout=timeout)


def load_threads_config() -> dict:
    """Load research threads configuration."""
    if THREADS_STATE.exists():
        try:
            return json.loads(THREADS_STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {"enabled": False, "channels": [], "contribute_thoughts": True}


def load_spawner_state() -> dict:
    """Load spawner state (tracks spawned threads, etc.)."""
    if SPAWNER_STATE.exists():
        try:
            return json.loads(SPAWNER_STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "spawned_threads": [],  # List of {thread_id, topic, timestamp}
        "last_spawn": None,
        "research_seeds": [],  # Topics to potentially explore
    }


def save_spawner_state(state: dict):
    """Save spawner state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SPAWNER_STATE.write_text(json.dumps(state, indent=2))


def get_vault_notes() -> list[dict]:
    """Read notes from Iris vault."""
    notes = []
    if not IRIS_VAULT.exists():
        return notes

    for md_file in IRIS_VAULT.glob("*.md"):
        if md_file.stem in ["Index", "Learnings", "Observations", "Patterns", "References"]:
            continue  # Skip MOC files

        try:
            content = md_file.read_text()
            notes.append({
                "name": md_file.stem,
                "content": content,
                "path": str(md_file)
            })
        except Exception:
            continue

    return notes


async def get_existing_threads(channel_id: int) -> list[dict]:
    """Get existing threads from a research channel."""
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    threads = []

    @client.event
    async def on_ready():
        nonlocal threads
        try:
            channel = client.get_channel(channel_id)
            if not channel:
                await client.close()
                return

            # Get archived and active threads
            for thread in channel.threads:
                threads.append({
                    "id": thread.id,
                    "name": thread.name,
                    "created_at": thread.created_at.isoformat() if thread.created_at else None,
                    "message_count": thread.message_count
                })

            # Also fetch archived threads
            async for thread in channel.archived_threads(limit=50):
                threads.append({
                    "id": thread.id,
                    "name": thread.name,
                    "created_at": thread.created_at.isoformat() if thread.created_at else None,
                    "message_count": thread.message_count,
                    "archived": True
                })

        except Exception as e:
            log(f"Error fetching threads: {e}")
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return threads


async def spawn_thread(channel_id: int, topic: str, initial_message: str) -> dict:
    """Create a new research thread with an initial message."""
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

            # Send the initial message
            msg = await channel.send(initial_message)

            # Create a thread from it
            thread = await msg.create_thread(
                name=topic[:100],
                auto_archive_duration=10080  # 7 days
            )

            result = {
                "success": True,
                "thread_id": thread.id,
                "thread_name": thread.name,
                "message_id": msg.id
            }

        except discord.Forbidden:
            result = {"error": "Missing permissions"}
        except Exception as e:
            result = {"error": str(e)}
        finally:
            await client.close()

    await client.start(DISCORD_TOKEN)
    return result


def analyze_and_spawn():
    """Analyze notes/threads and decide what to spawn."""
    config = load_threads_config()

    if not config.get("enabled") or not config.get("channels"):
        log("Research threads not enabled or no channels configured")
        return

    # Get Iris vault notes
    notes = get_vault_notes()
    if not notes:
        log("No notes in Iris vault to spawn from")
        return

    log(f"Found {len(notes)} notes in Iris vault")

    # Get existing threads from each channel
    all_existing = []
    for channel_id in config["channels"]:
        try:
            threads = asyncio.run(get_existing_threads(channel_id))
            all_existing.extend(threads)
            log(f"Channel {channel_id}: {len(threads)} existing threads")
        except Exception as e:
            log(f"Error checking channel {channel_id}: {e}")

    existing_topics = [t["name"] for t in all_existing]

    # Prepare notes summary
    notes_summary = "\n\n".join([
        f"**{n['name']}**\n{n['content'][:500]}..."
        for n in notes[:5]  # Limit to prevent token overflow
    ])

    existing_summary = "\n".join([f"- {t}" for t in existing_topics[-20:]])

    # Ask Claude to suggest a new research thread
    prompt = f"""You are Iris. You maintain a research channel in Discord where you spawn threads to explore ideas.

YOUR NOTES (from your vault):
{notes_summary}

EXISTING RESEARCH THREADS:
{existing_summary if existing_summary else "(none yet)"}

Based on your notes, suggest ONE new research thread to spawn. It should:
1. Connect to something in your notes
2. Not duplicate existing threads
3. Be a genuine question or topic you want to explore
4. Be specific enough to generate discussion

Respond in JSON:
{{
    "should_spawn": true/false,
    "topic": "Short topic title (max 80 chars)",
    "initial_message": "Your opening message to kick off the discussion. Be curious and substantive. 2-4 sentences.",
    "reasoning": "Why this topic now?"
}}

If there's nothing worth spawning right now, set should_spawn to false."""

    result = run_claude(prompt)

    if result.startswith("Error"):
        log(f"Claude error: {result}")
        return

    # Parse the response
    try:
        json_text = result
        if "```json" in result:
            json_text = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            json_text = result.split("```")[1].split("```")[0]

        suggestion = json.loads(json_text.strip())

        if not suggestion.get("should_spawn"):
            log(f"Decided not to spawn: {suggestion.get('reasoning', 'no reason given')}")
            return

        topic = suggestion.get("topic", "Research Thread")
        initial_message = suggestion.get("initial_message", "")

        if not initial_message:
            log("No initial message generated")
            return

        log(f"Spawning thread: {topic}")
        log(f"Reasoning: {suggestion.get('reasoning', 'none')}")

        # Spawn to the first configured channel
        channel_id = config["channels"][0]
        spawn_result = asyncio.run(spawn_thread(channel_id, topic, initial_message))

        if spawn_result.get("success"):
            log(f"Thread spawned successfully: {spawn_result.get('thread_id')}")

            # Update state
            state = load_spawner_state()
            state["spawned_threads"].append({
                "thread_id": spawn_result["thread_id"],
                "topic": topic,
                "timestamp": datetime.now().isoformat()
            })
            state["last_spawn"] = datetime.now().isoformat()
            save_spawner_state(state)

            # Log activity
            subprocess.run([
                "python3", str(INTEGRATIONS / "activity.py"), "log", "task",
                f"Spawned research thread: {topic}",
                "--meta", json.dumps({"thread_id": spawn_result["thread_id"]})
            ], cwd=str(WORKSPACE))
        else:
            log(f"Failed to spawn: {spawn_result.get('error')}")

    except (json.JSONDecodeError, KeyError) as e:
        log(f"Failed to parse suggestion: {e}")
        log(f"Raw response: {result[:500]}")


def list_spawned():
    """List previously spawned threads."""
    state = load_spawner_state()
    return {
        "spawned_threads": state.get("spawned_threads", [])[-20:],
        "last_spawn": state.get("last_spawn"),
        "total_spawned": len(state.get("spawned_threads", []))
    }


def main():
    parser = argparse.ArgumentParser(description="Research thread spawner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Spawn command
    subparsers.add_parser("spawn", help="Analyze and potentially spawn a new research thread")

    # List command
    subparsers.add_parser("list", help="List previously spawned threads")

    # Status command
    subparsers.add_parser("status", help="Show spawner status")

    args = parser.parse_args()

    if not DISCORD_TOKEN:
        print(json.dumps({"error": "DISCORD_TOKEN not set"}))
        sys.exit(1)

    if args.command == "spawn":
        analyze_and_spawn()
    elif args.command == "list":
        result = list_spawned()
        print(json.dumps(result, indent=2))
    elif args.command == "status":
        config = load_threads_config()
        state = load_spawner_state()
        print(json.dumps({
            "enabled": config.get("enabled"),
            "channels": config.get("channels", []),
            "total_spawned": len(state.get("spawned_threads", [])),
            "last_spawn": state.get("last_spawn")
        }, indent=2))


if __name__ == "__main__":
    main()
