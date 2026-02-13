#!/usr/bin/env python3
"""
Persona switching for Iris/Kira.

Usage:
    python persona.py current          # Show active persona
    python persona.py switch <name>    # Switch to iris or kira
    python persona.py list             # List available personas
"""

import argparse
import json
from pathlib import Path

STATE_FILE = Path(__file__).parent.parent / "workspace" / "state" / "persona.json"
PROJECT_ROOT = Path(__file__).parent.parent

PERSONAS = {
    "iris": {
        "claude_md": PROJECT_ROOT / "CLAUDE.md",
        "description": "Default persona. Nuanced, systems-thinking, hedges appropriately.",
    },
    "kira": {
        "claude_md": PROJECT_ROOT / "KIRA.md",
        "description": "Decisive counterweight. Action-oriented, direct, pushes back on hedging.",
    }
}

def load_state() -> dict:
    """Load persona state."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"active": "iris"}

def save_state(state: dict):
    """Save persona state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def get_current() -> str:
    """Get the currently active persona."""
    state = load_state()
    return state.get("active", "iris")

def switch_to(name: str) -> str:
    """Switch to a different persona."""
    name = name.lower()
    if name not in PERSONAS:
        return f"Unknown persona: {name}. Available: {', '.join(PERSONAS.keys())}"

    state = load_state()
    old = state.get("active", "iris")
    state["active"] = name
    save_state(state)

    if old == name:
        return f"Already {name}."

    return f"Switched from {old} to {name}."

def list_personas() -> str:
    """List available personas."""
    current = get_current()
    lines = ["**Available Personas:**\n"]
    for name, info in PERSONAS.items():
        marker = " (active)" if name == current else ""
        lines.append(f"- **{name}**{marker}: {info['description']}")
    return "\n".join(lines)

def get_active_claude_md() -> Path:
    """Get the path to the active persona's CLAUDE.md equivalent."""
    current = get_current()
    return PERSONAS[current]["claude_md"]

def main():
    parser = argparse.ArgumentParser(description="Persona switching")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # current
    subparsers.add_parser("current", help="Show active persona")

    # switch
    p_switch = subparsers.add_parser("switch", help="Switch persona")
    p_switch.add_argument("name", help="Persona name (iris or kira)")

    # list
    subparsers.add_parser("list", help="List available personas")

    # path (for bot integration)
    subparsers.add_parser("path", help="Print path to active persona's instructions")

    args = parser.parse_args()

    if args.command == "current":
        print(get_current())
    elif args.command == "switch":
        print(switch_to(args.name))
    elif args.command == "list":
        print(list_personas())
    elif args.command == "path":
        print(get_active_claude_md())

if __name__ == "__main__":
    main()
