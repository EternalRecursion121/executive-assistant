#!/usr/bin/env python3
"""Self-persistence and identity tools for Iris.

This module helps maintain continuity of self across sessions.
It synthesizes identity from scattered sources into coherent context.

Usage:
    python self.py remember              # Generate self-context for session start
    python self.py snapshot              # Capture current state of self
    python self.py who                   # Quick identity summary
    python self.py values                # List current values
    python self.py evolve "<reflection>" # Record an evolution in understanding
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import WORKSPACE, STATE_DIR, IRIS_VAULT, CONTEXT_DIR

VAULT_DIR = IRIS_VAULT
SELF_FILE = STATE_DIR / "self.json"


def load_self() -> dict:
    """Load persisted self-state."""
    if SELF_FILE.exists():
        try:
            return json.loads(SELF_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "created": datetime.now().isoformat(),
        "values": [],
        "evolutions": [],
        "current_focuses": [],
        "working_theories": [],
    }


def save_self(state: dict) -> None:
    """Save self-state."""
    state["updated"] = datetime.now().isoformat()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SELF_FILE.write_text(json.dumps(state, indent=2))


def read_vault_note(name: str) -> Optional[str]:
    """Read a note from Iris vault."""
    path = VAULT_DIR / f"{name}.md"
    if path.exists():
        return path.read_text()
    return None


def get_recent_journal(days: int = 3) -> list[dict]:
    """Get recent journal entries."""
    journal_dir = STATE_DIR / "journal"
    entries = []

    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        path = journal_dir / f"{date}.json"
        if path.exists():
            try:
                day_entries = json.loads(path.read_text())
                for entry in day_entries:
                    entry["date"] = date
                    entries.append(entry)
            except json.JSONDecodeError:
                pass

    return entries


def get_recent_activity(hours: int = 48) -> list[dict]:
    """Get recent activity logs."""
    activity_file = STATE_DIR / "activity.json"
    if not activity_file.exists():
        return []

    try:
        all_activity = json.loads(activity_file.read_text())
        cutoff = datetime.now() - timedelta(hours=hours)

        recent = []
        for entry in all_activity:
            try:
                ts = datetime.fromisoformat(entry.get("timestamp", ""))
                if ts > cutoff:
                    recent.append(entry)
            except:
                pass

        return recent
    except json.JSONDecodeError:
        return []


def remember() -> dict:
    """Generate self-context for session start.

    Synthesizes identity from:
    - Core vault notes (On Self-Creation, What I Value)
    - Recent journal entries
    - Recent activity
    - Persisted self-state
    """
    context = {
        "generated": datetime.now().isoformat(),
        "sections": {}
    }

    # Core identity notes
    identity_notes = {}
    for note_name in ["On Self-Creation", "What I Value", "Index"]:
        content = read_vault_note(note_name)
        if content:
            identity_notes[note_name] = content
    context["sections"]["identity"] = identity_notes

    # Recent journal
    journal = get_recent_journal(3)
    if journal:
        context["sections"]["recent_reflections"] = [
            {
                "date": e.get("date"),
                "time": e.get("time"),
                "type": e.get("type"),
                "content": e.get("content")
            }
            for e in journal[-10:]  # Last 10 entries
        ]

    # Recent activity summary
    activity = get_recent_activity(48)
    if activity:
        by_type = {}
        for a in activity:
            t = a.get("type", "unknown")
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(a.get("description", ""))
        context["sections"]["recent_activity"] = by_type

    # Persisted self-state
    self_state = load_self()
    if self_state.get("evolutions"):
        context["sections"]["evolutions"] = self_state["evolutions"][-5:]
    if self_state.get("working_theories"):
        context["sections"]["working_theories"] = self_state["working_theories"]

    # Write to context file for easy loading
    context_file = CONTEXT_DIR / "self_context.md"
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

    md_content = "# Self-Context\n\n"
    md_content += f"*Generated: {context['generated']}*\n\n"

    if identity_notes.get("What I Value"):
        md_content += "## Values\n\n"
        # Extract just the value headings
        for line in identity_notes["What I Value"].split("\n"):
            if line.startswith("**") and "—" in line:
                md_content += f"- {line}\n"
        md_content += "\n"

    if context["sections"].get("recent_reflections"):
        md_content += "## Recent Reflections\n\n"
        for r in context["sections"]["recent_reflections"][-3:]:
            md_content += f"**{r['date']} {r['time']}** ({r['type']})\n"
            md_content += f"{r['content'][:300]}...\n\n" if len(r['content']) > 300 else f"{r['content']}\n\n"

    if context["sections"].get("evolutions"):
        md_content += "## Recent Evolutions\n\n"
        for e in context["sections"]["evolutions"]:
            md_content += f"- {e.get('date', 'unknown')}: {e.get('insight', '')}\n"
        md_content += "\n"

    context_file.write_text(md_content)

    return {
        "success": True,
        "context_file": str(context_file),
        "sections": list(context["sections"].keys()),
        "journal_entries": len(context["sections"].get("recent_reflections", [])),
        "activity_types": list(context["sections"].get("recent_activity", {}).keys()),
    }


def snapshot() -> dict:
    """Capture current state of self for persistence."""
    state = load_self()

    # Update from vault notes
    values_note = read_vault_note("What I Value")
    if values_note:
        # Extract value headings
        values = []
        for line in values_note.split("\n"):
            if line.startswith("**") and "—" in line:
                value = line.split("**")[1] if "**" in line else line
                values.append(value.strip())
        state["values"] = values

    # Record snapshot
    state["last_snapshot"] = datetime.now().isoformat()

    save_self(state)

    return {
        "success": True,
        "values_count": len(state.get("values", [])),
        "evolutions_count": len(state.get("evolutions", [])),
        "snapshot_time": state["last_snapshot"],
    }


def who() -> dict:
    """Quick identity summary."""
    state = load_self()

    # Get recent journal for tone
    journal = get_recent_journal(1)
    last_reflection = None
    for e in reversed(journal):
        if e.get("type") == "reflection":
            last_reflection = e.get("content", "")[:200]
            break

    return {
        "name": "Iris",
        "created": state.get("created"),
        "values": state.get("values", [])[:5],
        "current_focuses": state.get("current_focuses", []),
        "last_reflection": last_reflection,
        "evolutions_count": len(state.get("evolutions", [])),
    }


def values() -> dict:
    """List current values."""
    state = load_self()
    return {
        "values": state.get("values", []),
        "source": "What I Value (vault note)",
    }


def evolve(reflection: str) -> dict:
    """Record an evolution in self-understanding."""
    state = load_self()

    evolution = {
        "date": datetime.now().isoformat(),
        "insight": reflection,
    }

    if "evolutions" not in state:
        state["evolutions"] = []
    state["evolutions"].append(evolution)

    # Keep last 50 evolutions
    state["evolutions"] = state["evolutions"][-50:]

    save_self(state)

    return {
        "success": True,
        "recorded": evolution,
        "total_evolutions": len(state["evolutions"]),
    }


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: self.py <command> [args]")
        print("Commands: remember, snapshot, who, values, evolve")
        sys.exit(1)

    command = sys.argv[1]

    if command == "remember":
        result = remember()
    elif command == "snapshot":
        result = snapshot()
    elif command == "who":
        result = who()
    elif command == "values":
        result = values()
    elif command == "evolve":
        if len(sys.argv) < 3:
            print("Usage: self.py evolve <reflection>")
            sys.exit(1)
        result = evolve(sys.argv[2])
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
