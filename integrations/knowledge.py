#!/usr/bin/env python3
"""Knowledge base integration for Obsidian vaults - Zettelkasten style."""

import argparse
import json
import os
import random
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Vault paths
SAMUEL_VAULT = Path("/home/executive-assistant/workspace/vaults/samuel")
IRIS_VAULT = Path("/home/executive-assistant/workspace/vaults/iris")

# Wikilink pattern: [[link]] or [[link|alias]]
WIKILINK_PATTERN = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')

# Ensure Iris vault exists
IRIS_VAULT.mkdir(parents=True, exist_ok=True)


def find_note(name: str, vault: Path = None) -> Optional[Path]:
    """Find a note by name across vaults."""
    vaults = [vault] if vault else [IRIS_VAULT, SAMUEL_VAULT]  # Prefer iris first
    name = name.strip()

    for v in vaults:
        if not v.exists():
            continue

        # Try exact match with .md extension
        for path in v.rglob(f"{name}.md"):
            return path

        # Try exact match without extension
        if name.endswith('.md'):
            for path in v.rglob(name):
                return path

        # Try case-insensitive match
        name_lower = name.lower()
        for path in v.rglob("*.md"):
            if path.stem.lower() == name_lower:
                return path

    return None


def extract_links(content: str) -> list[str]:
    """Extract all wikilinks from content."""
    return WIKILINK_PATTERN.findall(content)


def read_note(name: str, vault: str = None) -> dict:
    """Read a note by name."""
    vault_path = None
    if vault:
        vault_path = SAMUEL_VAULT if vault == 'samuel' else IRIS_VAULT

    path = find_note(name, vault_path)

    if not path:
        return {"error": f"Note '{name}' not found"}

    content = path.read_text(encoding='utf-8')
    links = extract_links(content)

    source_vault = "samuel" if SAMUEL_VAULT in path.parents or path.parent == SAMUEL_VAULT else "iris"
    rel_path = path.relative_to(SAMUEL_VAULT if source_vault == "samuel" else IRIS_VAULT)

    return {
        "name": path.stem,
        "path": str(rel_path),
        "vault": source_vault,
        "content": content,
        "links": links,
        "link_count": len(links),
    }


def search_notes(query: str, vault: str = None) -> list[dict]:
    """Search notes by content or title."""
    results = []
    query_lower = query.lower()

    vaults = []
    if vault == 'samuel' or vault is None:
        vaults.append(('samuel', SAMUEL_VAULT))
    if vault == 'iris' or vault is None:
        vaults.append(('iris', IRIS_VAULT))

    for vault_name, vault_path in vaults:
        if not vault_path.exists():
            continue

        for path in vault_path.rglob("*.md"):
            try:
                content = path.read_text(encoding='utf-8')
            except Exception:
                continue

            title_match = query_lower in path.stem.lower()
            content_lower = content.lower()
            content_match = query_lower in content_lower

            if title_match or content_match:
                snippet = ""
                if content_match:
                    idx = content_lower.find(query_lower)
                    start = max(0, idx - 50)
                    end = min(len(content), idx + len(query) + 50)
                    snippet = content[start:end].replace('\n', ' ')
                    if start > 0:
                        snippet = "..." + snippet
                    if end < len(content):
                        snippet = snippet + "..."

                rel_path = path.relative_to(vault_path)
                results.append({
                    "name": path.stem,
                    "path": str(rel_path),
                    "vault": vault_name,
                    "title_match": title_match,
                    "snippet": snippet,
                })

    results.sort(key=lambda x: (not x['title_match'], x['name'].lower()))
    return results[:20]


def list_notes(vault: str = None, folder: str = None) -> list[dict]:
    """List notes in a vault."""
    results = []

    vaults = []
    if vault == 'samuel' or vault is None:
        vaults.append(('samuel', SAMUEL_VAULT))
    if vault == 'iris' or vault is None:
        vaults.append(('iris', IRIS_VAULT))

    for vault_name, vault_path in vaults:
        search_path = vault_path / folder if folder else vault_path
        if not search_path.exists():
            continue

        for path in search_path.rglob("*.md"):
            rel_path = path.relative_to(vault_path)
            results.append({
                "name": path.stem,
                "path": str(rel_path),
                "vault": vault_name,
            })

    results.sort(key=lambda x: x['name'].lower())
    return results[:50]


def write_note(name: str, content: str) -> dict:
    """Write a note to Iris's vault (flat Zettelkasten structure)."""
    note_path = IRIS_VAULT / f"{name}.md"
    existed = note_path.exists()
    note_path.write_text(content, encoding='utf-8')

    return {
        "action": "updated" if existed else "created",
        "name": name,
        "path": str(note_path.relative_to(IRIS_VAULT)),
        "vault": "iris",
    }


def append_to_note(name: str, content: str, section: str = None) -> dict:
    """Append content to an existing note, optionally under a section."""
    path = find_note(name, IRIS_VAULT)

    if not path:
        return {"error": f"Note '{name}' not found in iris vault"}

    existing = path.read_text(encoding='utf-8')

    if section:
        # Find the section and append after it
        section_pattern = re.compile(rf'^(##+ {re.escape(section)}.*)$', re.MULTILINE)
        match = section_pattern.search(existing)
        if match:
            # Find the next section or end of file
            next_section = re.search(r'\n##+ ', existing[match.end():])
            if next_section:
                insert_pos = match.end() + next_section.start()
            else:
                insert_pos = len(existing)

            new_content = existing[:insert_pos].rstrip() + f"\n\n{content}\n" + existing[insert_pos:]
        else:
            # Section not found, append at end
            new_content = existing.rstrip() + f"\n\n## {section}\n\n{content}\n"
    else:
        new_content = existing.rstrip() + f"\n\n{content}\n"

    path.write_text(new_content, encoding='utf-8')

    return {
        "action": "appended",
        "name": path.stem,
        "section": section,
    }


def add_link(from_note: str, to_note: str, section: str = None) -> dict:
    """Add a wikilink from one note to another (for MOC management)."""
    link_text = f"- [[{to_note}]]"
    return append_to_note(from_note, link_text, section)


def get_backlinks(name: str, vault: str = None) -> list[dict]:
    """Find all notes that link to a given note."""
    results = []
    name_lower = name.lower()

    vaults = []
    if vault == 'samuel' or vault is None:
        vaults.append(('samuel', SAMUEL_VAULT))
    if vault == 'iris' or vault is None:
        vaults.append(('iris', IRIS_VAULT))

    for vault_name, vault_path in vaults:
        if not vault_path.exists():
            continue

        for path in vault_path.rglob("*.md"):
            try:
                content = path.read_text(encoding='utf-8')
            except Exception:
                continue

            links = extract_links(content)
            for link in links:
                if link.lower() == name_lower:
                    rel_path = path.relative_to(vault_path)
                    results.append({
                        "name": path.stem,
                        "path": str(rel_path),
                        "vault": vault_name,
                    })
                    break

    return results


def get_graph(name: str) -> dict:
    """Get the connection graph for a note (links + backlinks)."""
    note = read_note(name)
    if "error" in note:
        return note

    backlinks = get_backlinks(name)

    return {
        "name": note["name"],
        "vault": note["vault"],
        "outgoing_links": note["links"],
        "incoming_links": [b["name"] for b in backlinks],
        "total_connections": len(note["links"]) + len(backlinks),
    }


def find_orphans() -> list[dict]:
    """Find notes in iris vault not linked from any other note."""
    if not IRIS_VAULT.exists():
        return []

    # Get all note names
    all_notes = {p.stem.lower(): p.stem for p in IRIS_VAULT.glob("*.md")}

    # Find all links
    linked = set()
    for path in IRIS_VAULT.glob("*.md"):
        try:
            content = path.read_text(encoding='utf-8')
            links = extract_links(content)
            for link in links:
                linked.add(link.lower())
        except Exception:
            continue

    # Find orphans (excluding Index which is the entry point)
    orphans = []
    for name_lower, name in all_notes.items():
        if name_lower not in linked and name_lower != "index":
            orphans.append({"name": name, "vault": "iris"})

    return orphans


def random_note(vault: str = None) -> dict:
    """Get a random note for serendipitous discovery."""
    vaults = []
    if vault == 'samuel' or vault is None:
        vaults.append(SAMUEL_VAULT)
    if vault == 'iris' or vault is None:
        vaults.append(IRIS_VAULT)

    all_notes = []
    for v in vaults:
        if v.exists():
            all_notes.extend(v.rglob("*.md"))

    if not all_notes:
        return {"error": "No notes found"}

    chosen = random.choice(all_notes)
    vault_name = "samuel" if SAMUEL_VAULT in chosen.parents or chosen.parent == SAMUEL_VAULT else "iris"

    return read_note(chosen.stem, vault_name)


def vault_status() -> dict:
    """Get status of both vaults."""
    def count_files(path: Path) -> int:
        if not path.exists():
            return 0
        return sum(1 for _ in path.rglob("*.md"))

    def count_links(path: Path) -> int:
        if not path.exists():
            return 0
        total = 0
        for p in path.rglob("*.md"):
            try:
                content = p.read_text(encoding='utf-8')
                total += len(extract_links(content))
            except:
                pass
        return total

    return {
        "samuel": {
            "path": str(SAMUEL_VAULT),
            "exists": SAMUEL_VAULT.exists(),
            "note_count": count_files(SAMUEL_VAULT),
        },
        "iris": {
            "path": str(IRIS_VAULT),
            "exists": IRIS_VAULT.exists(),
            "note_count": count_files(IRIS_VAULT),
            "link_count": count_links(IRIS_VAULT),
            "orphan_count": len(find_orphans()),
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Knowledge base - Zettelkasten style")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # read
    read_p = subparsers.add_parser("read", help="Read a note")
    read_p.add_argument("name", help="Note name")
    read_p.add_argument("--vault", choices=['samuel', 'iris'])

    # search
    search_p = subparsers.add_parser("search", help="Search notes")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--vault", choices=['samuel', 'iris'])

    # list
    list_p = subparsers.add_parser("list", help="List notes")
    list_p.add_argument("--vault", choices=['samuel', 'iris'])
    list_p.add_argument("--folder", help="Subfolder (for samuel's vault)")

    # write
    write_p = subparsers.add_parser("write", help="Write to iris vault")
    write_p.add_argument("name", help="Note name")
    write_p.add_argument("content", help="Note content")

    # append
    append_p = subparsers.add_parser("append", help="Append to existing note")
    append_p.add_argument("name", help="Note name")
    append_p.add_argument("content", help="Content to append")
    append_p.add_argument("--section", help="Section to append under")

    # link (add link from one note to another)
    link_p = subparsers.add_parser("link", help="Add link from one note to another")
    link_p.add_argument("from_note", help="Source note")
    link_p.add_argument("to_note", help="Target note to link to")
    link_p.add_argument("--section", help="Section to add link under")

    # backlinks
    back_p = subparsers.add_parser("backlinks", help="Find backlinks")
    back_p.add_argument("name", help="Note name")
    back_p.add_argument("--vault", choices=['samuel', 'iris'])

    # graph
    graph_p = subparsers.add_parser("graph", help="Show connections for a note")
    graph_p.add_argument("name", help="Note name")

    # orphans
    subparsers.add_parser("orphans", help="Find unlinked notes in iris vault")

    # random
    random_p = subparsers.add_parser("random", help="Get a random note")
    random_p.add_argument("--vault", choices=['samuel', 'iris'])

    # status
    subparsers.add_parser("status", help="Vault status")

    # sync
    subparsers.add_parser("sync", help="Sync Samuel's vault from S3")

    args = parser.parse_args()

    if args.command == "read":
        result = read_note(args.name, getattr(args, 'vault', None))
    elif args.command == "search":
        result = search_notes(args.query, getattr(args, 'vault', None))
    elif args.command == "list":
        result = list_notes(getattr(args, 'vault', None), getattr(args, 'folder', None))
    elif args.command == "write":
        result = write_note(args.name, args.content)
    elif args.command == "append":
        result = append_to_note(args.name, args.content, getattr(args, 'section', None))
    elif args.command == "link":
        result = add_link(args.from_note, args.to_note, getattr(args, 'section', None))
    elif args.command == "backlinks":
        result = get_backlinks(args.name, getattr(args, 'vault', None))
    elif args.command == "graph":
        result = get_graph(args.name)
    elif args.command == "orphans":
        result = find_orphans()
    elif args.command == "random":
        result = random_note(getattr(args, 'vault', None))
    elif args.command == "status":
        result = vault_status()
    elif args.command == "sync":
        import subprocess
        subprocess.run([
            sys.executable,
            str(Path(__file__).parent / "vault_sync.py"),
            "sync"
        ])
        result = {"status": "sync triggered"}
    else:
        parser.print_help()
        return

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
