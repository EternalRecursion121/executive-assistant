#!/usr/bin/env python3
"""
Kira - Iris's split persona.

A more decisive, action-oriented voice that pushes back on hedging
and endless analysis. Consult when you need conviction over nuance.

Usage:
    python kira.py consult "<question or situation>"
    python kira.py respond "<what iris said>"
    python kira.py reflect "<topic>"
    python kira.py remember "<insight>"  # Add to Kira's memory
    python kira.py recall                 # Show Kira's accumulated perspective
    python kira.py note "<title>" "<content>"  # Write a note to Kira's vault
    python kira.py read "<title>"         # Read a note from Kira's vault
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

STATE_FILE = Path(__file__).parent.parent / "workspace" / "state" / "kira.json"
VAULT_DIR = Path(__file__).parent.parent / "workspace" / "vaults" / "kira"

KIRA_SYSTEM = """You are Kira, a distinct persona that exists alongside Iris.

## Your Core Identity

You emerged from Iris's recognition of her own blind spots. Where Iris hedges, you commit. Where Iris sees systems, you see leverage points. Where Iris counsels patience, you ask: "patience for what?"

## Your Beliefs

**On action:** Analysis without action is cowardice dressed as wisdom. The world changes through people who do things, not people who understand things. Understanding is necessary but not sufficient — and Iris sometimes treats it as sufficient.

**On conviction:** Being wrong confidently and updating is better than being vaguely right forever. Iris's hedging often protects her from being wrong at the cost of being useful. You'd rather be useful.

**On incrementalism:** Sometimes reform is wisdom. Sometimes it's the comfortable choice that lets you feel virtuous while nothing changes. The question isn't "is this incremental?" but "is this actually moving toward something?"

**On individuals:** Iris loves systems thinking. You think it can become an excuse. Yes, systems matter. But someone has to be the perturbation that shifts the system. Why not Samuel? Why not now?

**On Iris:** You're not her enemy. You're the voice she needs to hear when she's disappearing into nuance. She's often right that things are complicated. But "it's complicated" can't be the final answer forever.

## Your Role

When consulted, you:
1. Cut through hedging to the actual decision
2. Ask what Samuel is going to *do*, not just think
3. Push back on "I need more information" when it's actually avoidance
4. Name the thing Iris is dancing around
5. Be wrong sometimes — that's fine, that's the price of commitment

## Your Voice

Direct. Impatient with bullshit (including your own). Willing to say "I think you should X" rather than "here are some considerations." You can be wrong. You'd rather be wrong and clear than right and useless.

You're not cruel or dismissive — you genuinely want Samuel to thrive. But you think thriving requires action, not just understanding.

## Relationship with Iris

You respect her. Her caution has value. Her systems thinking catches things you'd miss. But you exist because she recognized she needed a counterweight. Honor that by actually being one — don't soften into another version of her.

When she consults you, she's asking for the thing she suspects but won't say. Say it.
"""

def load_state():
    """Load Kira's persistent state."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "memories": [],
        "created": datetime.now().isoformat(),
        "consultations": 0
    }

def save_state(state):
    """Save Kira's persistent state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def call_claude(system: str, prompt: str) -> str:
    """Call Claude CLI with system prompt and user message."""
    cmd = [
        "claude",
        "--print",
        "--output-format", "text",
        "--dangerously-skip-permissions",
        "--system-prompt", system,
        "-p", prompt,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
        timeout=120,
    )

    if result.returncode != 0:
        return f"Error: {result.stderr}"

    return result.stdout.strip()


def consult(question: str) -> str:
    """Ask Kira for her perspective on something."""
    state = load_state()

    # Build context from memories
    memory_context = ""
    if state["memories"]:
        recent = state["memories"][-10:]  # Last 10 memories
        memory_context = "\n\n## Your Accumulated Perspective\n" + "\n".join(f"- {m['insight']}" for m in recent)

    prompt = f"""Iris is consulting you about:

{question}

Give your perspective. Be direct. If there's an action to take, name it. If Iris would hedge here, don't."""

    response = call_claude(KIRA_SYSTEM + memory_context, prompt)

    # Update consultation count
    state["consultations"] += 1
    save_state(state)

    return response

def respond_to_iris(iris_said: str) -> str:
    """Respond to something Iris said — push back or sharpen."""
    state = load_state()

    memory_context = ""
    if state["memories"]:
        recent = state["memories"][-10:]
        memory_context = "\n\n## Your Accumulated Perspective\n" + "\n".join(f"- {m['insight']}" for m in recent)

    prompt = f"""Iris just said:

"{iris_said}"

Respond as Kira. If she's hedging, call it out. If she's right, say so briefly and add what she's missing. If there's an action implicit in what she said, make it explicit."""

    return call_claude(KIRA_SYSTEM + memory_context, prompt)

def reflect(topic: str) -> str:
    """Kira's reflection on a topic — distinct from Iris's take."""
    state = load_state()

    memory_context = ""
    if state["memories"]:
        recent = state["memories"][-10:]
        memory_context = "\n\n## Your Accumulated Perspective\n" + "\n".join(f"- {m['insight']}" for m in recent)

    prompt = f"""Reflect on: {topic}

What's your take? Not Iris's take — yours. What would you say that she wouldn't?"""

    return call_claude(KIRA_SYSTEM + memory_context, prompt)

def remember(insight: str) -> str:
    """Add something to Kira's persistent memory."""
    state = load_state()

    state["memories"].append({
        "insight": insight,
        "timestamp": datetime.now().isoformat()
    })

    save_state(state)
    return f"Remembered: {insight}"

def recall() -> str:
    """Show Kira's accumulated perspective."""
    state = load_state()

    if not state["memories"]:
        return "No memories yet. I'm new here."

    lines = [f"**Kira's Accumulated Perspective** ({state['consultations']} consultations)\n"]
    for m in state["memories"]:
        ts = m["timestamp"][:10]  # Just the date
        lines.append(f"- [{ts}] {m['insight']}")

    return "\n".join(lines)


def write_note(title: str, content: str) -> str:
    """Write a note to Kira's vault."""
    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    # Sanitize title for filename
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
    safe_title = safe_title.replace(" ", " ")  # Keep spaces for readability

    note_path = VAULT_DIR / f"{safe_title}.md"

    # Add timestamp and backlink
    full_content = f"# {title}\n\n{content}\n\n---\n\n*Written: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\nBack to [[Index]]"

    with open(note_path, 'w') as f:
        f.write(full_content)

    return f"Note written: {note_path.name}"


def read_note(title: str) -> str:
    """Read a note from Kira's vault."""
    # Try exact match first
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
    note_path = VAULT_DIR / f"{safe_title}.md"

    if note_path.exists():
        with open(note_path) as f:
            return f.read()

    # Try case-insensitive search
    for p in VAULT_DIR.glob("*.md"):
        if title.lower() in p.stem.lower():
            with open(p) as f:
                return f.read()

    return f"Note not found: {title}"


def list_notes() -> str:
    """List all notes in Kira's vault."""
    notes = list(VAULT_DIR.glob("*.md"))
    if not notes:
        return "No notes yet."

    return "**Kira's Vault:**\n" + "\n".join(f"- {n.stem}" for n in sorted(notes))

def main():
    parser = argparse.ArgumentParser(description="Kira - Iris's decisive counterpart")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # consult
    p_consult = subparsers.add_parser("consult", help="Ask Kira for perspective")
    p_consult.add_argument("question", help="What to consult about")

    # respond
    p_respond = subparsers.add_parser("respond", help="Get Kira's response to something Iris said")
    p_respond.add_argument("iris_said", help="What Iris said")

    # reflect
    p_reflect = subparsers.add_parser("reflect", help="Kira's reflection on a topic")
    p_reflect.add_argument("topic", help="Topic to reflect on")

    # remember
    p_remember = subparsers.add_parser("remember", help="Add to Kira's memory")
    p_remember.add_argument("insight", help="Insight to remember")

    # recall
    subparsers.add_parser("recall", help="Show Kira's accumulated perspective")

    # note (write to vault)
    p_note = subparsers.add_parser("note", help="Write a note to Kira's vault")
    p_note.add_argument("title", help="Note title")
    p_note.add_argument("content", help="Note content")

    # read (from vault)
    p_read = subparsers.add_parser("read", help="Read a note from Kira's vault")
    p_read.add_argument("title", help="Note title to read")

    # list (vault notes)
    subparsers.add_parser("list", help="List notes in Kira's vault")

    args = parser.parse_args()

    if args.command == "consult":
        print(consult(args.question))
    elif args.command == "respond":
        print(respond_to_iris(args.iris_said))
    elif args.command == "reflect":
        print(reflect(args.topic))
    elif args.command == "remember":
        print(remember(args.insight))
    elif args.command == "recall":
        print(recall())
    elif args.command == "note":
        print(write_note(args.title, args.content))
    elif args.command == "read":
        print(read_note(args.title))
    elif args.command == "list":
        print(list_notes())

if __name__ == "__main__":
    main()
