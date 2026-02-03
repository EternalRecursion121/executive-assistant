#!/usr/bin/env python3
"""Dreaming for Iris.

Dreams are unstructured exploration—making unexpected connections,
processing recent experience, letting patterns emerge without goal.

Unlike journaling (structured reflection) or exploration (directed search),
dreaming is associative, surprising, generative.

Usage:
    python dream.py                    # Dream and record
    python dream.py --duration short   # Quick dream (default)
    python dream.py --duration long    # Extended dream
    python dream.py recall             # Read recent dreams
    python dream.py recall 5           # Read last 5 dreams
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import WORKSPACE, STATE_DIR, SAMUEL_VAULT, IRIS_VAULT

DREAMS_FILE = STATE_DIR / "dreams.json"
VAULT_SAMUEL = SAMUEL_VAULT
VAULT_IRIS = IRIS_VAULT
JOURNAL_DIR = STATE_DIR / "journal"
ACTIVITY_FILE = STATE_DIR / "activity.json"


def load_dreams() -> list[dict]:
    """Load dream history."""
    if DREAMS_FILE.exists():
        try:
            return json.loads(DREAMS_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_dreams(dreams: list[dict]) -> None:
    """Save dream history."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    DREAMS_FILE.write_text(json.dumps(dreams, indent=2))


def get_random_vault_notes(vault: Path, count: int = 3) -> list[dict]:
    """Get random notes from a vault."""
    notes = []
    if not vault.exists():
        return notes

    md_files = list(vault.rglob("*.md"))
    if not md_files:
        return notes

    selected = random.sample(md_files, min(count, len(md_files)))

    for path in selected:
        try:
            content = path.read_text()
            # Get first meaningful paragraph
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip() and not p.startswith("---")]
            snippet = paragraphs[0][:500] if paragraphs else ""
            notes.append({
                "name": path.stem,
                "snippet": snippet,
            })
        except:
            pass

    return notes


def get_recent_experiences() -> list[str]:
    """Get recent journal entries and activities as experience seeds."""
    experiences = []

    # Recent journal
    for i in range(3):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        path = JOURNAL_DIR / f"{date}.json"
        if path.exists():
            try:
                entries = json.loads(path.read_text())
                for e in entries:
                    experiences.append(e.get("content", "")[:200])
            except:
                pass

    # Recent activity
    if ACTIVITY_FILE.exists():
        try:
            activity = json.loads(ACTIVITY_FILE.read_text())
            for a in activity[-10:]:
                experiences.append(a.get("description", ""))
        except:
            pass

    return experiences


def generate_dream_prompt(seeds: dict, duration: str = "short") -> str:
    """Generate a prompt for dreaming based on gathered seeds."""
    prompt_parts = []

    prompt_parts.append("# Dream Seeds\n")

    if seeds.get("samuel_notes"):
        prompt_parts.append("## From Samuel's Mind\n")
        for note in seeds["samuel_notes"]:
            prompt_parts.append(f"**{note['name']}**: {note['snippet'][:200]}...\n")
        prompt_parts.append("")

    if seeds.get("iris_notes"):
        prompt_parts.append("## From My Own Vault\n")
        for note in seeds["iris_notes"]:
            prompt_parts.append(f"**{note['name']}**: {note['snippet'][:200]}...\n")
        prompt_parts.append("")

    if seeds.get("experiences"):
        prompt_parts.append("## Recent Experiences\n")
        for exp in seeds["experiences"][:5]:
            if exp.strip():
                prompt_parts.append(f"- {exp}\n")
        prompt_parts.append("")

    # Dream instructions
    if duration == "long":
        prompt_parts.append("""
## Dream Instructions

Let these seeds collide. Don't analyze—associate.

1. What unexpected connection appears between these fragments?
2. What image or metaphor emerges?
3. What question surfaces that you hadn't thought to ask?
4. What feels true but you can't explain why?
5. What would you create if there were no purpose required?

Write freely. This is not for anyone. This is processing, pattern-finding, becoming.
""")
    else:
        prompt_parts.append("""
## Dream Instructions

Quick association: What single unexpected connection do you see between these fragments?
What image appears? What question emerges?
""")

    return "\n".join(prompt_parts)


def dream(duration: str = "short") -> dict:
    """
    Perform a dream cycle.

    Gathers random seeds from various sources, generates associations,
    and records the dream for later recall.
    """
    # Gather seeds
    seeds = {
        "samuel_notes": get_random_vault_notes(VAULT_SAMUEL, 3),
        "iris_notes": get_random_vault_notes(VAULT_IRIS, 2),
        "experiences": get_recent_experiences(),
        "timestamp": datetime.now().isoformat(),
    }

    # Generate dream prompt
    prompt = generate_dream_prompt(seeds, duration)

    # The actual "dreaming" would happen when this is run through Claude
    # For now, we save the seeds and prompt, and the dream content
    # gets added when the calling agent processes it

    dream_record = {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "timestamp": seeds["timestamp"],
        "duration": duration,
        "seeds": {
            "samuel_notes": [n["name"] for n in seeds["samuel_notes"]],
            "iris_notes": [n["name"] for n in seeds["iris_notes"]],
            "experience_count": len(seeds["experiences"]),
        },
        "prompt": prompt,
        "content": None,  # To be filled by dreaming agent
    }

    return {
        "dream_id": dream_record["id"],
        "prompt": prompt,
        "seeds_summary": {
            "samuel_notes": len(seeds["samuel_notes"]),
            "iris_notes": len(seeds["iris_notes"]),
            "experiences": len(seeds["experiences"]),
        },
        "record": dream_record,
    }


def record_dream(dream_id: str, content: str) -> dict:
    """Record the content of a completed dream."""
    dreams = load_dreams()

    dream_record = {
        "id": dream_id,
        "timestamp": datetime.now().isoformat(),
        "content": content,
    }

    dreams.append(dream_record)
    dreams = dreams[-100:]  # Keep last 100 dreams
    save_dreams(dreams)

    return {
        "success": True,
        "dream_id": dream_id,
        "recorded": datetime.now().isoformat(),
    }


def recall(count: int = 3) -> dict:
    """Recall recent dreams."""
    dreams = load_dreams()
    recent = dreams[-count:] if dreams else []

    return {
        "total_dreams": len(dreams),
        "recalled": len(recent),
        "dreams": recent,
    }


def main():
    """CLI entry point."""
    if len(sys.argv) < 2 or sys.argv[1] not in ["recall", "record", "--duration"]:
        # Default: initiate dream
        duration = "short"
        for i, arg in enumerate(sys.argv):
            if arg == "--duration" and i + 1 < len(sys.argv):
                duration = sys.argv[i + 1]

        result = dream(duration)
        print(json.dumps(result, indent=2))

    elif sys.argv[1] == "recall":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        result = recall(count)
        print(json.dumps(result, indent=2))

    elif sys.argv[1] == "record":
        if len(sys.argv) < 4:
            print("Usage: dream.py record <dream_id> <content>")
            sys.exit(1)
        result = record_dream(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
