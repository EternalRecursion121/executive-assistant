#!/usr/bin/env python3
"""Dynamic context generation for Iris.

Generates context files that should be read at session start.
Run this before sessions to have continuity.

Usage:
    python3 context.py generate    # regenerate all context files
    python3 context.py last        # show last journal entry
    python3 context.py status      # show current context state
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from config import CONTEXT_DIR, STATE_DIR

JOURNAL_DIR = STATE_DIR / "journal"


def ensure_dirs():
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)


def get_last_journal_entry() -> dict | None:
    """Get the most recent journal entry across all days."""
    if not JOURNAL_DIR.exists():
        return None

    # Get all journal files, sorted by date descending
    files = sorted(JOURNAL_DIR.glob("*.json"), reverse=True)

    for f in files:
        try:
            entries = json.loads(f.read_text())
            if entries:
                # Return the last entry from the most recent non-empty day
                entry = entries[-1]
                entry["_date"] = f.stem  # Add the date from filename
                return entry
        except:
            continue

    return None


def generate_context():
    """Generate all dynamic context files."""
    ensure_dirs()

    # Last journal entry
    last_entry = get_last_journal_entry()

    if last_entry:
        content = f"""## Last Journal Entry

**{last_entry.get('_date')} {last_entry.get('time', '')}** ({last_entry.get('type', 'note')})

{last_entry.get('content', '')}
"""
    else:
        content = "## Last Journal Entry\n\nNo entries yet.\n"

    (CONTEXT_DIR / "last_journal.md").write_text(content)

    return {
        "generated": ["last_journal.md"],
        "last_entry": last_entry
    }


def get_status() -> dict:
    """Get current context state."""
    last_entry = get_last_journal_entry()
    context_files = list(CONTEXT_DIR.glob("*")) if CONTEXT_DIR.exists() else []

    return {
        "context_files": [f.name for f in context_files],
        "last_journal": last_entry,
        "context_dir": str(CONTEXT_DIR)
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"usage": "context.py <generate|last|status>"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "generate":
        print(json.dumps(generate_context(), indent=2))
    elif cmd == "last":
        entry = get_last_journal_entry()
        if entry:
            print(f"[{entry.get('_date')} {entry.get('time', '')}] ({entry.get('type', 'note')})")
            print(entry.get('content', ''))
        else:
            print("No journal entries yet.")
    elif cmd == "status":
        print(json.dumps(get_status(), indent=2))
    else:
        print(json.dumps({"error": "invalid command"}))


if __name__ == "__main__":
    main()
