#!/usr/bin/env python3
"""Vault retrieval subagent.

Intelligent retrieval from both Samuel's and Iris's vaults.
Combines search, contextual lookups, and semantic queries.

Usage:
    python3 vault_retriever.py search "<query>" [--vault samuel|iris]
    python3 vault_retriever.py context "<topic>"        # Get all context around a topic
    python3 vault_retriever.py related "<note_name>"    # Get related notes via links
    python3 vault_retriever.py recent [days]            # Recently modified notes
    python3 vault_retriever.py by-tag "<tag>"           # Notes with specific tag
    python3 vault_retriever.py by-category "<category>" # Notes in category
    python3 vault_retriever.py random                   # Serendipitous discovery
    python3 vault_retriever.py summary "<note_name>"    # Get note with summary

Examples:
    python3 vault_retriever.py search "identity"
    python3 vault_retriever.py context "AI alignment"
    python3 vault_retriever.py related "What I Value"
    python3 vault_retriever.py recent 7
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Import sibling modules
sys.path.insert(0, str(Path(__file__).parent))
from config import SAMUEL_VAULT, IRIS_VAULT
from knowledge import search_notes, read_note, get_backlinks, get_graph, random_note, find_note
from vault_indexer import search_index, get_batch, get_categories, build_index, INDEX_PATH


def ensure_index():
    """Ensure index exists and is reasonably fresh."""
    if not INDEX_PATH.exists():
        build_index()


def search(query: str, vault: str = None, limit: int = 15) -> dict:
    """Search notes across vaults."""
    # Combine basic search with index search for best results
    basic_results = search_notes(query, vault)

    ensure_index()
    index_results = search_index(query, vault=vault, limit=limit)

    # Merge results, preferring basic search for title matches
    seen = set()
    combined = []

    for r in basic_results:
        key = (r['vault'], r['name'])
        if key not in seen:
            seen.add(key)
            combined.append({
                **r,
                "match_type": "title" if r.get('title_match') else "content"
            })

    for r in index_results:
        key = (r['vault'], r['name'])
        if key not in seen:
            seen.add(key)
            combined.append({
                "name": r['name'],
                "path": r['path'],
                "vault": r['vault'],
                "summary": r.get('summary', ''),
                "categories": r.get('categories', []),
                "match_type": "indexed"
            })

    return {
        "query": query,
        "results": combined[:limit],
        "count": len(combined[:limit])
    }


def get_context(topic: str) -> dict:
    """Get comprehensive context around a topic.

    Searches both vaults, follows links, and aggregates related content.
    """
    # Search for the topic
    results = search(topic, limit=10)

    context = {
        "topic": topic,
        "direct_matches": [],
        "related_notes": [],
        "from_samuel_vault": [],
        "from_iris_vault": [],
    }

    seen = set()

    for r in results['results']:
        note_name = r['name']
        if note_name in seen:
            continue
        seen.add(note_name)

        # Get the full note with links
        full_note = read_note(note_name, r.get('vault'))
        if 'error' in full_note:
            continue

        note_summary = {
            "name": full_note['name'],
            "vault": full_note['vault'],
            "link_count": full_note['link_count'],
            "excerpt": full_note['content'][:500] if len(full_note['content']) > 500 else full_note['content'],
            "links": full_note['links'][:10]  # First 10 links
        }

        # Categorize by vault
        if full_note['vault'] == 'samuel':
            context['from_samuel_vault'].append(note_summary)
        else:
            context['from_iris_vault'].append(note_summary)

        context['direct_matches'].append(note_summary)

        # Get backlinks for related content
        backlinks = get_backlinks(note_name)
        for bl in backlinks[:5]:  # First 5 backlinks
            if bl['name'] not in seen:
                seen.add(bl['name'])
                context['related_notes'].append({
                    "name": bl['name'],
                    "vault": bl['vault'],
                    "related_via": note_name
                })

    context['total_notes_found'] = len(context['direct_matches']) + len(context['related_notes'])

    return context


def get_related(note_name: str) -> dict:
    """Get all notes related to a given note via links."""
    graph = get_graph(note_name)

    if 'error' in graph:
        return graph

    related = {
        "note": note_name,
        "vault": graph['vault'],
        "outgoing": [],
        "incoming": [],
        "total_connections": graph['total_connections']
    }

    # Get details on outgoing links
    for link in graph['outgoing_links'][:20]:
        note = read_note(link)
        if 'error' not in note:
            related['outgoing'].append({
                "name": note['name'],
                "vault": note['vault'],
                "excerpt": note['content'][:200]
            })
        else:
            related['outgoing'].append({"name": link, "status": "not found"})

    # Get details on incoming links
    for link_name in graph['incoming_links'][:20]:
        note = read_note(link_name)
        if 'error' not in note:
            related['incoming'].append({
                "name": note['name'],
                "vault": note['vault'],
                "excerpt": note['content'][:200]
            })

    return related


def get_recent(days: int = 7) -> dict:
    """Get recently modified notes."""
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    recent = []

    for vault_name, vault_path in [('samuel', SAMUEL_VAULT), ('iris', IRIS_VAULT)]:
        if not vault_path.exists():
            continue

        for path in vault_path.rglob("*.md"):
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if mtime > cutoff:
                recent.append({
                    "name": path.stem,
                    "vault": vault_name,
                    "modified": mtime.isoformat(),
                    "days_ago": (datetime.now() - mtime).days
                })

    recent.sort(key=lambda x: x['modified'], reverse=True)

    return {
        "days": days,
        "count": len(recent),
        "notes": recent[:30]
    }


def by_tag(tag: str) -> dict:
    """Get notes with a specific tag."""
    ensure_index()

    results = []
    index = json.loads(INDEX_PATH.read_text())

    for note in index['notes']:
        if tag.lower() in [t.lower() for t in note.get('tags', [])]:
            results.append({
                "name": note['name'],
                "vault": note['vault'],
                "summary": note.get('summary', '')[:200],
                "tags": note.get('tags', [])
            })

    return {
        "tag": tag,
        "count": len(results),
        "notes": results
    }


def by_category(category: str) -> dict:
    """Get notes in a specific category."""
    ensure_index()

    batch = get_batch(category=category, limit=50)

    return {
        "category": category,
        "count": batch['total'],
        "notes": [{
            "name": n['name'],
            "vault": n['vault'],
            "summary": n.get('summary', '')[:200],
            "date": n.get('date')
        } for n in batch['batch']]
    }


def get_random_note() -> dict:
    """Get a random note for serendipitous discovery."""
    note = random_note()

    if 'error' in note:
        return note

    return {
        "name": note['name'],
        "vault": note['vault'],
        "link_count": note['link_count'],
        "content": note['content'][:1000] + ("..." if len(note['content']) > 1000 else ""),
        "links": note['links']
    }


def get_note_summary(note_name: str) -> dict:
    """Get a note with structured summary."""
    note = read_note(note_name)

    if 'error' in note:
        return note

    content = note['content']
    lines = content.split('\n')

    # Extract headings for structure
    headings = [l.strip() for l in lines if l.strip().startswith('#')]

    # Get first paragraph as summary
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip() and not p.strip().startswith('#')]
    summary = paragraphs[0] if paragraphs else ""

    # Get graph info
    graph = get_graph(note_name)

    return {
        "name": note['name'],
        "vault": note['vault'],
        "headings": headings[:10],
        "summary": summary[:500],
        "word_count": len(content.split()),
        "links": note['links'],
        "backlinks": graph.get('incoming_links', []) if 'error' not in graph else [],
        "full_content": content
    }


def main():
    parser = argparse.ArgumentParser(description="Vault retrieval subagent")
    subparsers = parser.add_subparsers(dest="command", help="Retrieval command")

    # search
    search_p = subparsers.add_parser("search", help="Search notes")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--vault", choices=['samuel', 'iris'])
    search_p.add_argument("--limit", type=int, default=15)

    # context
    context_p = subparsers.add_parser("context", help="Get context around topic")
    context_p.add_argument("topic", help="Topic to explore")

    # related
    related_p = subparsers.add_parser("related", help="Get related notes")
    related_p.add_argument("note_name", help="Note to find relations for")

    # recent
    recent_p = subparsers.add_parser("recent", help="Recently modified notes")
    recent_p.add_argument("days", type=int, nargs='?', default=7)

    # by-tag
    tag_p = subparsers.add_parser("by-tag", help="Notes with tag")
    tag_p.add_argument("tag", help="Tag to search for")

    # by-category
    cat_p = subparsers.add_parser("by-category", help="Notes in category")
    cat_p.add_argument("category", help="Category name")

    # random
    subparsers.add_parser("random", help="Random note")

    # summary
    summary_p = subparsers.add_parser("summary", help="Note with summary")
    summary_p.add_argument("note_name", help="Note name")

    # categories (list available)
    subparsers.add_parser("categories", help="List available categories")

    args = parser.parse_args()

    if args.command == "search":
        result = search(args.query, getattr(args, 'vault', None), getattr(args, 'limit', 15))
    elif args.command == "context":
        result = get_context(args.topic)
    elif args.command == "related":
        result = get_related(args.note_name)
    elif args.command == "recent":
        result = get_recent(args.days)
    elif args.command == "by-tag":
        result = by_tag(args.tag)
    elif args.command == "by-category":
        result = by_category(args.category)
    elif args.command == "random":
        result = get_random_note()
    elif args.command == "summary":
        result = get_note_summary(args.note_name)
    elif args.command == "categories":
        result = get_categories()
    else:
        parser.print_help()
        return

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
