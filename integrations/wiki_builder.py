#!/usr/bin/env python3
"""Wiki builder - constructs a Wikipedia-style knowledge base about Samuel from vault notes.

This is designed to be run in batches by subagents. Each run processes a category
or batch of notes and appends findings to the wiki structure.

The wiki is optimized for Iris's usefulness - quick context about Samuel's life,
interests, projects, relationships, goals, and history.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from config import WIKI_DIR, STATE_DIR, VAULT_INDEX

STATE_FILE = STATE_DIR / "wiki_state.json"
INDEX_PATH = VAULT_INDEX

# Wiki structure - sections to build
WIKI_SECTIONS = [
    "overview",           # High-level summary of Samuel
    "timeline",           # Key life events in chronological order
    "education",          # Schools, courses, learning
    "projects",           # Things he's built or worked on
    "interests",          # Topics, hobbies, passions
    "philosophy",         # Values, beliefs, worldview
    "goals",             # Aspirations and plans
    "people",            # Key relationships and references
    "work",              # Career, jobs, professional life
    "health",            # Health-related notes and patterns
    "creative",          # Writing, art, creative output
    "technical",         # Technical skills, tools, approaches
    "reading",           # Books, articles, references
    "patterns",          # Recurring themes across notes
    "open_questions",    # Things unclear or unresolved
]


def init_wiki():
    """Initialize the wiki directory structure."""
    WIKI_DIR.mkdir(parents=True, exist_ok=True)

    # Create section files if they don't exist
    for section in WIKI_SECTIONS:
        section_file = WIKI_DIR / f"{section}.md"
        if not section_file.exists():
            title = section.replace('_', ' ').title()
            section_file.write_text(
                f"# {title}\n\n"
                f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"
                f"---\n\n",
                encoding='utf-8'
            )

    # Create index
    index_file = WIKI_DIR / "index.md"
    if not index_file.exists():
        sections_list = "\n".join(
            f"- [{s.replace('_', ' ').title()}]({s}.md)" for s in WIKI_SECTIONS
        )
        index_file.write_text(
            f"# Samuel's Wiki\n\n"
            f"A living knowledge base constructed from vault notes.\n"
            f"All claims cite their source notes.\n\n"
            f"## Sections\n\n{sections_list}\n\n"
            f"## Metadata\n\n"
            f"- Source: Samuel's Obsidian vault ({get_note_count()} notes)\n"
            f"- Built by: Iris\n"
            f"- Method: Rigorous extraction with citations\n"
            f"- Last full rebuild: {datetime.now().strftime('%Y-%m-%d')}\n",
            encoding='utf-8'
        )

    # Init state
    if not STATE_FILE.exists():
        state = {
            "initialized": datetime.now().isoformat(),
            "last_run": None,
            "processed_notes": [],
            "section_status": {s: "pending" for s in WIKI_SECTIONS},
            "total_entries": 0,
            "runs": 0,
        }
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')

    return {"status": "initialized", "sections": WIKI_SECTIONS}


def get_note_count():
    if INDEX_PATH.exists():
        index = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
        return index["stats"]["total_notes"]
    return "unknown"


def get_state() -> dict:
    """Get current wiki build state."""
    if not STATE_FILE.exists():
        return {"error": "Wiki not initialized. Run: python wiki_builder.py init"}
    return json.loads(STATE_FILE.read_text(encoding='utf-8'))


def update_state(updates: dict):
    """Update wiki state."""
    state = get_state()
    state.update(updates)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def add_entry(section: str, content: str, sources: list[str] = None):
    """Add an entry to a wiki section with citations."""
    section_file = WIKI_DIR / f"{section}.md"
    if not section_file.exists():
        init_wiki()

    existing = section_file.read_text(encoding='utf-8')

    # Format citations
    citation_text = ""
    if sources:
        citations = ", ".join(f"[{s}]" for s in sources)
        citation_text = f" _{citations}_"

    # Append entry
    entry = f"{content}{citation_text}\n\n"
    new_content = existing.rstrip() + f"\n\n{entry}"

    # Update timestamp
    new_content = new_content.replace(
        new_content.split('\n')[2],  # The "Last updated" line
        f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*"
    )

    section_file.write_text(new_content, encoding='utf-8')

    # Update state
    state = get_state()
    state["total_entries"] = state.get("total_entries", 0) + 1
    state["last_run"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')

    return {"status": "added", "section": section}


def mark_processed(note_names: list[str]):
    """Mark notes as processed."""
    state = get_state()
    processed = set(state.get("processed_notes", []))
    processed.update(note_names)
    state["processed_notes"] = list(processed)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def get_unprocessed(category: str = None, limit: int = 20) -> list[dict]:
    """Get notes that haven't been processed yet."""
    if not INDEX_PATH.exists():
        return {"error": "Index not built. Run: python vault_indexer.py build"}

    state = get_state()
    processed = set(state.get("processed_notes", []))

    index = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
    unprocessed = []

    for note in index["notes"]:
        if note["name"] in processed:
            continue
        if category and category not in note["categories"]:
            continue
        # Skip templates and meta
        if "template" in note["categories"] or "meta" in note["categories"]:
            continue
        if "drawing" in note["categories"]:
            continue
        unprocessed.append(note)

    # Sort: non-journal first (they're more info-dense), then by date
    unprocessed.sort(key=lambda x: (
        'journal' in x["categories"],
        -(len(x.get("summary", ""))),
    ))

    return unprocessed[:limit]


def get_section(section: str) -> str:
    """Read a wiki section."""
    section_file = WIKI_DIR / f"{section}.md"
    if not section_file.exists():
        return f"Section '{section}' not found"
    return section_file.read_text(encoding='utf-8')


def write_section(section: str, content: str):
    """Overwrite a wiki section (for rebuilds)."""
    section_file = WIKI_DIR / f"{section}.md"
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    section_file.write_text(content, encoding='utf-8')

    state = get_state()
    state["section_status"][section] = "complete"
    state["last_run"] = datetime.now().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')

    return {"status": "written", "section": section, "chars": len(content)}


def status() -> dict:
    """Get wiki build status summary."""
    state = get_state()
    sections_complete = sum(1 for s in state.get("section_status", {}).values() if s == "complete")

    return {
        "initialized": state.get("initialized"),
        "last_run": state.get("last_run"),
        "runs": state.get("runs", 0),
        "notes_processed": len(state.get("processed_notes", [])),
        "total_entries": state.get("total_entries", 0),
        "sections_complete": f"{sections_complete}/{len(WIKI_SECTIONS)}",
        "section_status": state.get("section_status", {}),
    }


def main():
    parser = argparse.ArgumentParser(description="Wiki builder for Samuel's vault")
    subparsers = parser.add_subparsers(dest="command")

    # init
    subparsers.add_parser("init", help="Initialize wiki structure")

    # status
    subparsers.add_parser("status", help="Show build status")

    # unprocessed
    unp = subparsers.add_parser("unprocessed", help="Get unprocessed notes")
    unp.add_argument("--category", help="Filter by category")
    unp.add_argument("--limit", type=int, default=20)

    # add-entry
    add_p = subparsers.add_parser("add-entry", help="Add entry to a section")
    add_p.add_argument("section", choices=WIKI_SECTIONS)
    add_p.add_argument("content", help="Entry content")
    add_p.add_argument("--sources", nargs='+', help="Source note names")

    # mark-processed
    mark_p = subparsers.add_parser("mark-processed", help="Mark notes as processed")
    mark_p.add_argument("notes", nargs='+', help="Note names")

    # read-section
    read_p = subparsers.add_parser("read-section", help="Read a wiki section")
    read_p.add_argument("section", choices=WIKI_SECTIONS)

    # write-section
    write_p = subparsers.add_parser("write-section", help="Write/overwrite a section")
    write_p.add_argument("section", choices=WIKI_SECTIONS)
    write_p.add_argument("content", help="Full section content")

    # sections
    subparsers.add_parser("sections", help="List all sections")

    args = parser.parse_args()

    if args.command == "init":
        result = init_wiki()
    elif args.command == "status":
        result = status()
    elif args.command == "unprocessed":
        result = get_unprocessed(
            category=getattr(args, 'category', None),
            limit=args.limit,
        )
    elif args.command == "add-entry":
        result = add_entry(args.section, args.content, getattr(args, 'sources', None))
    elif args.command == "mark-processed":
        mark_processed(args.notes)
        result = {"status": "marked", "count": len(args.notes)}
    elif args.command == "read-section":
        result = get_section(args.section)
    elif args.command == "write-section":
        result = write_section(args.section, args.content)
    elif args.command == "sections":
        result = WIKI_SECTIONS
    else:
        parser.print_help()
        return

    if isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
