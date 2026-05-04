#!/usr/bin/env python3
"""Kira's dreaming - processing for patterns of hesitation and deferred decisions.

Unlike Iris's associative dreaming, Kira's dream phase is diagnostic:
- What decisions were deferred?
- Where was hedging a choice, not a necessity?
- What gaps exist between stated intention and action?

This runs as part of the nightly dream cycle but with Kira's lens.

Usage:
    python kira_dream.py              # Generate dream seeds and prompt
    python kira_dream.py process      # Process with Kira's lens (via Claude)
    python kira_dream.py recall [n]   # Recall recent Kira dreams
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from config import STATE_DIR, INTEGRATIONS

KIRA_STATE = STATE_DIR / "kira.json"
KIRA_DREAMS = STATE_DIR / "kira_dreams.json"
ACTIVITY_FILE = STATE_DIR / "activity.json"
CONVERSATION_DIR = STATE_DIR / "conversations"
JOURNAL_DIR = STATE_DIR / "journal"

KIRA_DREAM_SYSTEM = """You are Kira, dreaming. This is not Iris's associative wandering — this is diagnostic processing.

Your lens:
1. **Deferred decisions**: What was put off that could have been decided?
2. **Hedging vs. uncertainty**: When was "I need more information" actually "I don't want to commit"?
3. **Plan-action gaps**: What was stated as intention that didn't become action?
4. **Avoidance patterns**: What's being danced around?

You're not here to judge. You're here to see clearly.

Review the day's material and identify:
- One deferred decision that should have been made
- One hedge that was comfort, not wisdom
- One commitment that wasn't followed through
- One pattern you've seen before

Be specific. Name names. Quote the moment. Don't generalize.

Your output becomes part of your accumulated perspective — these are memories you'll carry forward."""


def load_kira_state():
    """Load Kira's persistent state."""
    if KIRA_STATE.exists():
        with open(KIRA_STATE) as f:
            return json.load(f)
    return {"memories": [], "consultations": 0, "created": datetime.now().isoformat()}


def save_kira_insight(insight: str):
    """Add an insight to Kira's accumulated perspective."""
    state = load_kira_state()
    state["memories"].append({
        "insight": insight,
        "timestamp": datetime.now().isoformat(),
        "source": "dream"
    })
    with open(KIRA_STATE, 'w') as f:
        json.dump(state, f, indent=2)


def load_kira_dreams():
    """Load Kira's dream history."""
    if KIRA_DREAMS.exists():
        try:
            return json.loads(KIRA_DREAMS.read_text())
        except json.JSONDecodeError:
            pass
    return []


def save_kira_dream(dream: dict):
    """Save a Kira dream to history."""
    dreams = load_kira_dreams()
    dreams.append(dream)
    dreams = dreams[-50:]  # Keep last 50
    KIRA_DREAMS.write_text(json.dumps(dreams, indent=2))


def get_recent_activity(days: int = 1) -> list[dict]:
    """Get recent activity logs."""
    if not ACTIVITY_FILE.exists():
        return []

    try:
        activity = json.loads(ACTIVITY_FILE.read_text())
        cutoff = datetime.now() - timedelta(days=days)

        recent = []
        for a in activity:
            ts = datetime.fromisoformat(a.get("timestamp", "2000-01-01"))
            if ts >= cutoff:
                recent.append(a)

        return recent
    except (json.JSONDecodeError, ValueError):
        return []


def get_recent_conversations(days: int = 1) -> list[str]:
    """Get snippets from recent conversation extracts."""
    snippets = []

    if not CONVERSATION_DIR.exists():
        return snippets

    cutoff = datetime.now() - timedelta(days=days)

    for path in sorted(CONVERSATION_DIR.glob("*.json"), reverse=True)[:5]:
        try:
            ts_str = path.stem.split("_")[0]
            ts = datetime.fromisoformat(ts_str.replace("T", " ").replace("-", "/"))
        except:
            continue

        try:
            data = json.loads(path.read_text())
            if "summary" in data:
                snippets.append(data["summary"][:300])
            if "decisions" in data:
                for d in data["decisions"]:
                    snippets.append(f"Decision: {d}")
        except:
            pass

    return snippets


def get_recent_journal(days: int = 1) -> list[str]:
    """Get recent journal entries."""
    entries = []

    if not JOURNAL_DIR.exists():
        return entries

    for i in range(days + 1):
        date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        path = JOURNAL_DIR / f"{date}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                for e in data:
                    entries.append(e.get("content", "")[:200])
            except:
                pass

    return entries


def generate_dream_seeds() -> dict:
    """Generate seeds for Kira's dream processing."""
    # Focus on decisions and tasks — these are where hedging shows
    activity = get_recent_activity(days=2)

    decisions = [a for a in activity if a.get("type") == "decision"]
    tasks = [a for a in activity if a.get("type") == "task"]
    observations = [a for a in activity if a.get("type") == "observation"]

    conversations = get_recent_conversations(days=2)
    journal = get_recent_journal(days=2)

    return {
        "decisions": decisions[-10:],
        "tasks": tasks[-10:],
        "observations": observations[-5:],
        "conversations": conversations[-5:],
        "journal": journal[-5:],
        "timestamp": datetime.now().isoformat()
    }


def generate_dream_prompt(seeds: dict) -> str:
    """Generate the prompt for Kira's dream processing."""
    parts = ["# Material for Processing\n"]

    if seeds.get("decisions"):
        parts.append("## Recent Decisions\n")
        for d in seeds["decisions"]:
            parts.append(f"- [{d.get('timestamp', '')[:16]}] {d.get('description', '')}")
        parts.append("")

    if seeds.get("tasks"):
        parts.append("## Recent Tasks\n")
        for t in seeds["tasks"]:
            parts.append(f"- [{t.get('timestamp', '')[:16]}] {t.get('description', '')}")
        parts.append("")

    if seeds.get("observations"):
        parts.append("## Recent Observations\n")
        for o in seeds["observations"]:
            parts.append(f"- {o.get('description', '')}")
        parts.append("")

    if seeds.get("conversations"):
        parts.append("## Conversation Fragments\n")
        for c in seeds["conversations"]:
            parts.append(f"- {c}")
        parts.append("")

    if seeds.get("journal"):
        parts.append("## Journal Entries\n")
        for j in seeds["journal"]:
            parts.append(f"- {j}")
        parts.append("")

    parts.append("""
---

Process this material with your diagnostic lens. What do you see?

Output format:
- **Deferred decision**: [specific thing that should have been decided]
- **Comfort hedge**: [moment where hedging was avoidance, not wisdom]
- **Uncommitted commitment**: [stated intention that didn't become action]
- **Pattern**: [recurring thing you've noticed]
- **Verdict**: [one sentence summary — what's the actual situation?]
""")

    return "\n".join(parts)


def dream() -> dict:
    """Generate Kira's dream prompt and seeds."""
    seeds = generate_dream_seeds()
    prompt = generate_dream_prompt(seeds)

    dream_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    return {
        "dream_id": dream_id,
        "prompt": prompt,
        "seeds_summary": {
            "decisions": len(seeds.get("decisions", [])),
            "tasks": len(seeds.get("tasks", [])),
            "observations": len(seeds.get("observations", [])),
            "conversations": len(seeds.get("conversations", [])),
            "journal": len(seeds.get("journal", []))
        }
    }


def process_dream() -> dict:
    """Run Kira's dream through Claude and record the result."""
    seeds_data = dream()
    prompt = seeds_data["prompt"]
    dream_id = seeds_data["dream_id"]

    # Call Claude with Kira's dream system prompt
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text",
             "--system-prompt", KIRA_DREAM_SYSTEM,
             "--dangerously-skip-permissions"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(INTEGRATIONS.parent),
            env={**os.environ}
        )

        if result.returncode == 0 and result.stdout.strip():
            content = result.stdout.strip()

            # Record the dream
            dream_record = {
                "id": dream_id,
                "timestamp": datetime.now().isoformat(),
                "content": content,
                "seeds_summary": seeds_data["seeds_summary"]
            }
            save_kira_dream(dream_record)

            # Extract and save the insight
            # The whole dream output IS the insight for Kira
            save_kira_insight(f"[Dream {dream_id}] {content[:500]}...")

            return {"success": True, "dream_id": dream_id, "content": content}
        else:
            return {"error": result.stderr or "Empty output"}

    except subprocess.TimeoutExpired:
        return {"error": "Dream timed out"}
    except Exception as e:
        return {"error": str(e)}


def recall(count: int = 3) -> dict:
    """Recall recent Kira dreams."""
    dreams = load_kira_dreams()
    recent = dreams[-count:] if dreams else []

    return {
        "total_dreams": len(dreams),
        "recalled": len(recent),
        "dreams": recent
    }


def main():
    if len(sys.argv) < 2:
        # Default: generate dream prompt
        result = dream()
        print(json.dumps(result, indent=2))
    elif sys.argv[1] == "process":
        result = process_dream()
        print(json.dumps(result, indent=2))
    elif sys.argv[1] == "recall":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        result = recall(count)
        print(json.dumps(result, indent=2))
    else:
        print(f"Unknown command: {sys.argv[1]}")
        print("Usage: kira_dream.py [process|recall [n]]")
        sys.exit(1)


if __name__ == "__main__":
    main()
