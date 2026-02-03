#!/usr/bin/env python3
"""Vault indexer - builds a searchable index of all notes with metadata extraction."""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import SAMUEL_VAULT, IRIS_VAULT, VAULT_INDEX

INDEX_PATH = VAULT_INDEX

# Patterns
WIKILINK_PATTERN = re.compile(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]')
TAG_PATTERN = re.compile(r'#([a-zA-Z][a-zA-Z0-9_/-]+)')
FRONTMATTER_PATTERN = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)
HEADING_PATTERN = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
DATE_PATTERN = re.compile(r'(\d{4}-\d{2}-\d{2})')


def extract_frontmatter(content: str) -> dict:
    """Extract YAML-like frontmatter."""
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}

    fm = {}
    for line in match.group(1).split('\n'):
        if ':' in line:
            key, _, value = line.partition(':')
            fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def extract_headings(content: str) -> list[dict]:
    """Extract all headings with their levels."""
    return [{"level": len(m.group(1)), "text": m.group(2).strip()}
            for m in HEADING_PATTERN.finditer(content)]


def categorize_note(path: Path, content: str, frontmatter: dict) -> list[str]:
    """Auto-categorize a note based on path, content, and metadata."""
    categories = []
    path_str = str(path).lower()
    content_lower = content.lower()
    name = path.stem.lower()

    # Path-based
    if '41 daily' in path_str or 'periodic' in path_str:
        categories.append('journal')
    if 'template' in path_str:
        categories.append('template')
    if 'meta' in path_str:
        categories.append('meta')
    if 'excalidraw' in path_str:
        categories.append('drawing')

    # Date-named notes are journal entries
    if DATE_PATTERN.match(name):
        categories.append('journal')

    # Content-based categorization
    if any(w in content_lower for w in ['meeting', 'agenda', 'attendees', 'action items']):
        categories.append('meeting')
    if any(w in content_lower for w in ['project', 'milestone', 'deadline', 'deliverable']):
        categories.append('project')
    if any(w in content_lower for w in ['learn', 'course', 'study', 'homework', 'assignment', 'school', 'exam']):
        categories.append('education')
    if any(w in content_lower for w in ['goal', 'objective', 'resolution', 'habit']):
        categories.append('goals')
    if any(w in content_lower for w in ['idea', 'brainstorm', 'concept', 'thought experiment']):
        categories.append('ideas')
    if any(w in content_lower for w in ['book', 'reading', 'author', 'chapter']):
        categories.append('reading')
    if any(w in content_lower for w in ['code', 'programming', 'function', 'api', 'software', 'dev']):
        categories.append('technical')
    if any(w in content_lower for w in ['reflect', 'feeling', 'grateful', 'mood', 'emotion']):
        categories.append('reflection')
    if any(w in content_lower for w in ['person', 'friend', 'family', 'contact']):
        categories.append('people')
    if any(w in content_lower for w in ['work', 'job', 'career', 'company', 'business']):
        categories.append('work')
    if any(w in content_lower for w in ['health', 'exercise', 'fitness', 'diet', 'sleep']):
        categories.append('health')
    if any(w in content_lower for w in ['philosophy', 'meaning', 'existential', 'values', 'ethics']):
        categories.append('philosophy')
    if any(w in content_lower for w in ['creative', 'writing', 'story', 'poem', 'art', 'music']):
        categories.append('creative')

    # Frontmatter tags
    if 'tags' in frontmatter:
        tags = frontmatter['tags']
        if isinstance(tags, str):
            categories.extend([t.strip() for t in tags.split(',')])

    return list(set(categories)) if categories else ['uncategorized']


def index_note(path: Path, vault_name: str) -> dict:
    """Index a single note."""
    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        return {"error": str(e), "path": str(path)}

    frontmatter = extract_frontmatter(content)
    headings = extract_headings(content)
    links = WIKILINK_PATTERN.findall(content)
    tags = TAG_PATTERN.findall(content)
    categories = categorize_note(path, content, frontmatter)

    # Extract first meaningful paragraph as summary
    lines = content.split('\n')
    summary_lines = []
    in_frontmatter = False
    for line in lines:
        if line.strip() == '---':
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if line.strip() and not line.startswith('#') and not line.startswith('```'):
            summary_lines.append(line.strip())
            if len(' '.join(summary_lines)) > 200:
                break
    summary = ' '.join(summary_lines)[:300]

    # Detect date from name or frontmatter
    date = None
    date_match = DATE_PATTERN.search(path.stem)
    if date_match:
        date = date_match.group(1)
    elif 'date' in frontmatter:
        date_match = DATE_PATTERN.search(frontmatter['date'])
        if date_match:
            date = date_match.group(1)
    elif 'created' in frontmatter:
        date_match = DATE_PATTERN.search(frontmatter['created'])
        if date_match:
            date = date_match.group(1)

    vault_path = SAMUEL_VAULT if vault_name == 'samuel' else IRIS_VAULT
    rel_path = path.relative_to(vault_path)

    return {
        "name": path.stem,
        "path": str(rel_path),
        "vault": vault_name,
        "date": date,
        "categories": categories,
        "tags": tags,
        "links": links,
        "link_count": len(links),
        "headings": headings,
        "frontmatter": frontmatter,
        "summary": summary,
        "word_count": len(content.split()),
        "char_count": len(content),
    }


def build_index(vault: str = None, force: bool = False) -> dict:
    """Build or rebuild the full vault index."""
    index = {"notes": [], "built_at": datetime.now().isoformat(), "stats": {}}

    vaults = []
    if vault == 'samuel' or vault is None:
        vaults.append(('samuel', SAMUEL_VAULT))
    if vault == 'iris' or vault is None:
        vaults.append(('iris', IRIS_VAULT))

    for vault_name, vault_path in vaults:
        if not vault_path.exists():
            continue
        for path in vault_path.rglob("*.md"):
            entry = index_note(path, vault_name)
            if "error" not in entry:
                index["notes"].append(entry)

    # Build stats
    all_categories = {}
    all_tags = {}
    date_range = {"earliest": None, "latest": None}

    for note in index["notes"]:
        for cat in note["categories"]:
            all_categories[cat] = all_categories.get(cat, 0) + 1
        for tag in note["tags"]:
            all_tags[tag] = all_tags.get(tag, 0) + 1
        if note["date"]:
            if not date_range["earliest"] or note["date"] < date_range["earliest"]:
                date_range["earliest"] = note["date"]
            if not date_range["latest"] or note["date"] > date_range["latest"]:
                date_range["latest"] = note["date"]

    index["stats"] = {
        "total_notes": len(index["notes"]),
        "categories": all_categories,
        "tags": all_tags,
        "date_range": date_range,
        "total_words": sum(n["word_count"] for n in index["notes"]),
    }

    # Save index
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2, default=str), encoding='utf-8')

    return {"status": "built", "total_notes": len(index["notes"]), "path": str(INDEX_PATH)}


def search_index(query: str, category: str = None, date_from: str = None, date_to: str = None, vault: str = None, limit: int = 30) -> list[dict]:
    """Search the index with filters."""
    if not INDEX_PATH.exists():
        build_index()

    index = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
    query_lower = query.lower() if query else ""
    results = []

    for note in index["notes"]:
        # Apply filters
        if vault and note["vault"] != vault:
            continue
        if category and category not in note["categories"]:
            continue
        if date_from and note["date"] and note["date"] < date_from:
            continue
        if date_to and note["date"] and note["date"] > date_to:
            continue

        # Score relevance
        score = 0
        if query_lower:
            name_lower = note["name"].lower()
            if query_lower in name_lower:
                score += 10
                if name_lower == query_lower:
                    score += 20
            if query_lower in note["summary"].lower():
                score += 5
            if any(query_lower in t.lower() for t in note["tags"]):
                score += 3
            if any(query_lower in h["text"].lower() for h in note["headings"]):
                score += 4

            if score == 0:
                continue
        else:
            score = note["word_count"]  # Default sort by length if no query

        results.append({**note, "_score": score})

    results.sort(key=lambda x: x["_score"], reverse=True)
    return results[:limit]


def get_batch(offset: int = 0, limit: int = 20, category: str = None, vault: str = None) -> dict:
    """Get a batch of notes for processing."""
    if not INDEX_PATH.exists():
        build_index()

    index = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
    notes = index["notes"]

    # Filter
    if category:
        notes = [n for n in notes if category in n["categories"]]
    if vault:
        notes = [n for n in notes if n["vault"] == vault]

    # Sort by date (most recent first), then name
    notes.sort(key=lambda x: (x["date"] or "0000-00-00", x["name"]), reverse=True)

    batch = notes[offset:offset + limit]

    return {
        "batch": batch,
        "offset": offset,
        "limit": limit,
        "total": len(notes),
        "has_more": offset + limit < len(notes),
    }


def get_stats() -> dict:
    """Get index statistics."""
    if not INDEX_PATH.exists():
        return {"error": "Index not built. Run: python vault_indexer.py build"}

    index = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
    return index["stats"]


def get_categories() -> dict:
    """List all categories with counts."""
    if not INDEX_PATH.exists():
        build_index()
    index = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
    return index["stats"]["categories"]


def main():
    parser = argparse.ArgumentParser(description="Vault indexer - batch search and categorization")
    subparsers = parser.add_subparsers(dest="command")

    # build
    build_p = subparsers.add_parser("build", help="Build/rebuild the index")
    build_p.add_argument("--vault", choices=['samuel', 'iris'])

    # search
    search_p = subparsers.add_parser("search", help="Search with filters")
    search_p.add_argument("query", nargs='?', default="")
    search_p.add_argument("--category", help="Filter by category")
    search_p.add_argument("--from", dest="date_from", help="Date from (YYYY-MM-DD)")
    search_p.add_argument("--to", dest="date_to", help="Date to (YYYY-MM-DD)")
    search_p.add_argument("--vault", choices=['samuel', 'iris'])
    search_p.add_argument("--limit", type=int, default=30)

    # batch
    batch_p = subparsers.add_parser("batch", help="Get a batch of notes")
    batch_p.add_argument("--offset", type=int, default=0)
    batch_p.add_argument("--limit", type=int, default=20)
    batch_p.add_argument("--category", help="Filter by category")
    batch_p.add_argument("--vault", choices=['samuel', 'iris'])

    # stats
    subparsers.add_parser("stats", help="Show index statistics")

    # categories
    subparsers.add_parser("categories", help="List categories")

    args = parser.parse_args()

    if args.command == "build":
        result = build_index(getattr(args, 'vault', None))
    elif args.command == "search":
        result = search_index(
            args.query,
            category=getattr(args, 'category', None),
            date_from=getattr(args, 'date_from', None),
            date_to=getattr(args, 'date_to', None),
            vault=getattr(args, 'vault', None),
            limit=args.limit,
        )
    elif args.command == "batch":
        result = get_batch(
            offset=args.offset,
            limit=args.limit,
            category=getattr(args, 'category', None),
            vault=getattr(args, 'vault', None),
        )
    elif args.command == "stats":
        result = get_stats()
    elif args.command == "categories":
        result = get_categories()
    else:
        parser.print_help()
        return

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
