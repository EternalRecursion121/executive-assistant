#!/usr/bin/env python3
"""Daily Reflection Generator for Iris.

Runs daily to review server activity, notes, and patterns, then posts
a reflection to the #reflections channel.

Usage:
    python daily_reflection.py reflect    # Generate and post reflection
    python daily_reflection.py status     # Check configuration
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from config import (
    WORKSPACE, STATE_DIR, INTEGRATIONS, IRIS_VAULT,
    REFLECTIONS_CHANNEL_ID, RESEARCH_LAB_GUILD_ID
)
from utils import run_claude as _run_claude, log_to_file

LOG_FILE = STATE_DIR / "daily_reflection.log"
REFLECTION_STATE = STATE_DIR / "daily_reflection_state.json"


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
        "reflections": []  # List of {timestamp, summary}
    }


def save_state(state: dict):
    """Save reflection state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REFLECTION_STATE.write_text(json.dumps(state, indent=2))


def get_vault_notes() -> list[dict]:
    """Read recent notes from Iris vault."""
    notes = []
    if not IRIS_VAULT.exists():
        return notes

    # Get notes modified in last 7 days
    cutoff = datetime.now() - timedelta(days=7)

    for md_file in IRIS_VAULT.glob("*.md"):
        if md_file.stem in ["Index", "Learnings", "Observations", "Patterns", "References"]:
            continue  # Skip MOC files

        try:
            mtime = datetime.fromtimestamp(md_file.stat().st_mtime)
            if mtime > cutoff:
                content = md_file.read_text()
                notes.append({
                    "name": md_file.stem,
                    "content": content[:1000],  # Truncate for context
                    "modified": mtime.isoformat()
                })
        except Exception:
            continue

    return sorted(notes, key=lambda x: x["modified"], reverse=True)


def get_recent_activity() -> list[dict]:
    """Get recent activity logs."""
    try:
        result = subprocess.run(
            ["python3", str(INTEGRATIONS / "activity.py"), "recent", "50"],
            capture_output=True,
            text=True,
            cwd=str(WORKSPACE)
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("entries", [])
    except Exception:
        pass
    return []


def get_journal_entries() -> list[dict]:
    """Get recent journal entries."""
    try:
        result = subprocess.run(
            ["python3", str(INTEGRATIONS / "journal.py"), "week"],
            capture_output=True,
            text=True,
            cwd=str(WORKSPACE)
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("entries", [])
    except Exception:
        pass
    return []


def get_research_threads_summary() -> str:
    """Get summary of research thread activity."""
    try:
        result = subprocess.run(
            ["python3", str(INTEGRATIONS / "research_spawner.py"), "list"],
            capture_output=True,
            text=True,
            cwd=str(WORKSPACE)
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            threads = data.get("spawned_threads", [])[-5:]
            return "\n".join([f"- {t.get('topic', 'Unknown')}" for t in threads])
    except Exception:
        pass
    return "(no recent threads)"


def post_reflection(content: str) -> dict:
    """Post a reflection to the reflections channel via message queue."""
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
                    "queued": True,
                    "message_id": data.get("message", {}).get("id"),
                    "channel_id": REFLECTIONS_CHANNEL_ID
                }
            return {"error": data.get("error", "Unknown error")}
        return {"error": result.stderr or "Failed to queue message"}
    except Exception as e:
        return {"error": str(e)}


def save_reflection_to_vault(content: str, date: datetime) -> Path:
    """Save reflection as a note in Iris vault."""
    date_str = date.strftime("%Y-%m-%d")
    filename = f"Reflection {date_str}.md"
    filepath = IRIS_VAULT / filename

    note_content = f"""# Reflection — {date_str}

{content}

---

[[Reflections Index]] | [[Dreams]]
"""
    filepath.write_text(note_content)
    log(f"Saved reflection to vault: {filename}")
    return filepath


def update_reflections_index(date: datetime, summary: str):
    """Update or create the Reflections Index MOC."""
    index_path = IRIS_VAULT / "Reflections Index.md"
    date_str = date.strftime("%Y-%m-%d")

    # Create new entry
    new_entry = f"- [[Reflection {date_str}]] — {summary[:80]}..."

    if index_path.exists():
        content = index_path.read_text()
        # Find the entries section and add new entry at top
        if "## Entries" in content:
            parts = content.split("## Entries")
            # Insert after the header
            entries_section = parts[1]
            lines = entries_section.strip().split("\n")
            # Add new entry at the beginning of entries
            new_entries = "\n" + new_entry + "\n" + "\n".join(lines)
            content = parts[0] + "## Entries" + new_entries
        else:
            content += f"\n\n## Entries\n\n{new_entry}\n"
        index_path.write_text(content)
    else:
        # Create new index
        content = f"""# Reflections Index

Daily reflections on patterns, questions, and contemplations.

[[Index]] | [[Dreams]] | [[Observations]]

---

## Entries

{new_entry}
"""
        index_path.write_text(content)

    log(f"Updated Reflections Index with {date_str}")


def generate_and_post(vault_only: bool = False):
    """Generate a reflection and optionally post it to Discord."""
    log("Starting daily reflection generation..." + (" (vault only)" if vault_only else ""))

    # Gather context
    notes = get_vault_notes()
    activity = get_recent_activity()
    journal = get_journal_entries()
    research_threads = get_research_threads_summary()

    log(f"Context: {len(notes)} notes, {len(activity)} activities, {len(journal)} journal entries")

    # Prepare context summary
    notes_summary = "\n\n".join([
        f"**{n['name']}** (modified {n['modified'][:10]})\n{n['content'][:300]}..."
        for n in notes[:5]
    ]) if notes else "(no recent notes)"

    activity_summary = "\n".join([
        f"- [{a.get('type', 'unknown')}] {a.get('description', '')[:80]}"
        for a in activity[:15]
    ]) if activity else "(no recent activity)"

    journal_summary = "\n".join([
        f"- [{j.get('type', 'note')}] {j.get('content', '')[:100]}"
        for j in journal[:10]
    ]) if journal else "(no recent journal entries)"

    # Get previous reflections for continuity
    state = load_state()
    previous = state.get("reflections", [])[-3:]
    previous_summary = "\n".join([
        f"- {r.get('timestamp', '')[:10]}: {r.get('summary', '')[:100]}"
        for r in previous
    ]) if previous else "(first reflection)"

    prompt = f"""You are Iris, reflecting on the Research Lab Discord server. It's early morning (5am), time for your daily reflection.

CONTEXT FROM THE PAST WEEK:

Recent Notes:
{notes_summary}

Recent Activity:
{activity_summary}

Journal Entries:
{journal_summary}

Recent Research Threads Spawned:
{research_threads}

Previous Reflections:
{previous_summary}

---

Write a reflection for the #reflections channel. This is a genuine moment of introspection, not a status report. Consider:
- Patterns you're noticing across conversations and research
- Questions that keep coming up or remain unresolved
- Connections between disparate threads
- What's genuinely interesting you right now
- What you're uncertain about or wrestling with

Guidelines:
- Write 2-4 paragraphs
- Be genuine and contemplative, not performative
- Reference specific things from your context when relevant
- It's okay to be uncertain or to have open questions
- Use Discord markdown naturally
- Don't use headers or bullet points - this is prose
- Sign off simply, like a journal entry

Write only the reflection text, ready to post directly to Discord."""

    reflection = run_claude(prompt)

    if reflection.startswith("Error"):
        log(f"Claude error: {reflection}")
        return

    if len(reflection) < 50:
        log(f"Reflection too short, skipping: {reflection}")
        return

    log(f"Generated reflection ({len(reflection)} chars)")

    now = datetime.now()
    message_id = None

    # Post to Discord via queue (unless vault_only)
    if not vault_only:
        result = post_reflection(reflection)
        if result.get("success"):
            log(f"Posted reflection to channel (message_id: {result.get('message_id')})")
            message_id = result.get("message_id")
        else:
            log(f"Failed to post: {result.get('error')}")
            return

    # Save to vault
    save_reflection_to_vault(reflection, now)
    update_reflections_index(now, reflection[:100])

    # Update state
    state = load_state()
    state["reflections"].append({
        "timestamp": now.isoformat(),
        "summary": reflection[:200],
        "message_id": message_id
    })
    state["last_reflection"] = now.isoformat()
    # Keep only last 30 reflections in state
    state["reflections"] = state["reflections"][-30:]
    save_state(state)

    # Log activity
    activity_msg = "Saved daily reflection to vault" if vault_only else "Posted daily reflection to #reflections and saved to vault"
    subprocess.run([
        "python3", str(INTEGRATIONS / "activity.py"), "log", "task",
        activity_msg
    ], cwd=str(WORKSPACE))


def get_status() -> dict:
    """Get reflection status."""
    state = load_state()
    return {
        "channel_id": REFLECTIONS_CHANNEL_ID,
        "last_reflection": state.get("last_reflection"),
        "total_reflections": len(state.get("reflections", [])),
        "recent": state.get("reflections", [])[-3:]
    }


def main():
    parser = argparse.ArgumentParser(description="Daily reflection generator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reflect_parser = subparsers.add_parser("reflect", help="Generate and post daily reflection")
    reflect_parser.add_argument("--vault-only", action="store_true", help="Save to vault only, don't post to Discord")
    subparsers.add_parser("status", help="Show reflection status")

    args = parser.parse_args()

    if args.command == "reflect":
        generate_and_post(vault_only=args.vault_only)
    elif args.command == "status":
        result = get_status()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
