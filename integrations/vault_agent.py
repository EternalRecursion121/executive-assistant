#!/usr/bin/env python3
"""Vault traversal subagent.

A lightweight Haiku-powered agent that can be called to search through
the vaults and summarize relevant information for a given query.

This is designed to be called by the main Claude instance when it needs
context from notes without having to make multiple retrieval calls itself.

Usage:
    python3 vault_agent.py query "<question>" [--vault samuel|iris]
    python3 vault_agent.py summarize "<topic>"
    python3 vault_agent.py connections "<topic>"

Examples:
    python3 vault_agent.py query "What has Samuel written about AI alignment?"
    python3 vault_agent.py summarize "identity"
    python3 vault_agent.py connections "tools for thought"
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Import sibling modules
sys.path.insert(0, str(Path(__file__).parent))
from config import WORKSPACE
from vault_retriever import search, get_context, get_related, get_note_summary
from knowledge import read_note

CLAUDE_PATH = "/home/iris/.local/bin/claude"


async def query_with_context(query: str, vault: str = None, max_notes: int = 5) -> dict:
    """Search vaults and use Haiku to synthesize a relevant answer.

    1. Searches for relevant notes
    2. Reads the top results
    3. Uses Haiku to synthesize an answer based on the vault contents
    """
    # Step 1: Search for relevant notes
    search_results = search(query, vault=vault, limit=max_notes)

    if not search_results.get("results"):
        return {
            "query": query,
            "answer": "No relevant notes found in the vaults.",
            "sources": []
        }

    # Step 2: Read the top notes
    note_contents = []
    sources = []
    for result in search_results["results"][:max_notes]:
        note = read_note(result["name"], result.get("vault"))
        if "error" not in note:
            # Truncate very long notes
            content = note["content"]
            if len(content) > 2000:
                content = content[:2000] + "\n\n[... truncated ...]"

            note_contents.append(f"### {note['name']} (from {note['vault']} vault)\n{content}")
            sources.append({
                "name": note["name"],
                "vault": note["vault"],
                "link_count": note.get("link_count", 0)
            })

    if not note_contents:
        return {
            "query": query,
            "answer": "Found notes but couldn't read their contents.",
            "sources": []
        }

    # Step 3: Use Haiku to synthesize
    notes_text = "\n\n---\n\n".join(note_contents)

    synthesis_prompt = f"""Based on these notes from a personal knowledge vault, answer the following question.

QUESTION: {query}

NOTES FROM VAULT:
{notes_text}

Instructions:
- Synthesize information from the notes to answer the question
- If the notes don't contain relevant information, say so
- Quote or reference specific notes when relevant
- Be concise but thorough
- If there are connections or patterns across notes, highlight them

Answer:"""

    cmd = [
        CLAUDE_PATH,
        "--print",
        "--output-format", "text",
        "--dangerously-skip-permissions",
        "--model", "haiku",
        "-p", synthesis_prompt,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORKSPACE),
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=60,
        )

        answer = stdout.decode().strip()

        return {
            "query": query,
            "answer": answer,
            "sources": sources,
            "notes_searched": search_results["count"]
        }

    except asyncio.TimeoutError:
        return {"error": "Synthesis timed out", "query": query}
    except Exception as e:
        return {"error": str(e), "query": query}


async def summarize_topic(topic: str) -> dict:
    """Get a comprehensive summary of what the vaults contain about a topic.

    Uses the context retriever to get all related notes, then synthesizes.
    """
    # Get comprehensive context
    context = get_context(topic)

    if not context.get("direct_matches") and not context.get("related_notes"):
        return {
            "topic": topic,
            "summary": f"No notes found about '{topic}' in either vault.",
            "sources": []
        }

    # Build context string
    context_parts = []
    sources = []

    for note in context.get("direct_matches", [])[:7]:
        context_parts.append(f"### {note['name']} ({note['vault']})\n{note['excerpt']}")
        sources.append({"name": note["name"], "vault": note["vault"], "type": "direct"})

    for note in context.get("related_notes", [])[:5]:
        # Fetch excerpt for related notes
        full_note = read_note(note["name"], note.get("vault"))
        if "error" not in full_note:
            excerpt = full_note["content"][:500]
            context_parts.append(f"### {note['name']} (related via {note['related_via']})\n{excerpt}")
            sources.append({"name": note["name"], "vault": note["vault"], "type": "related"})

    context_text = "\n\n---\n\n".join(context_parts)

    summary_prompt = f"""Summarize what these personal knowledge notes say about: {topic}

NOTES:
{context_text}

Provide a coherent summary that:
1. Captures the main ideas and themes
2. Notes any tensions or contradictions
3. Highlights connections between different notes
4. Is useful as context for future conversations

Summary:"""

    cmd = [
        CLAUDE_PATH,
        "--print",
        "--output-format", "text",
        "--dangerously-skip-permissions",
        "--model", "haiku",
        "-p", summary_prompt,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORKSPACE),
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=90,
        )

        summary = stdout.decode().strip()

        return {
            "topic": topic,
            "summary": summary,
            "sources": sources,
            "total_notes": context.get("total_notes_found", 0),
            "from_samuel": len(context.get("from_samuel_vault", [])),
            "from_iris": len(context.get("from_iris_vault", []))
        }

    except asyncio.TimeoutError:
        return {"error": "Summary generation timed out", "topic": topic}
    except Exception as e:
        return {"error": str(e), "topic": topic}


async def find_connections(topic: str) -> dict:
    """Find connections and patterns related to a topic across the vaults.

    Focuses on identifying non-obvious links between ideas.
    """
    # Search broadly
    search_results = search(topic, limit=10)

    if not search_results.get("results"):
        return {"topic": topic, "connections": [], "message": "No related notes found."}

    # Get notes and their links
    notes_with_links = []
    all_linked_notes = set()

    for result in search_results["results"][:8]:
        note = read_note(result["name"], result.get("vault"))
        if "error" not in note:
            notes_with_links.append({
                "name": note["name"],
                "vault": note["vault"],
                "links": note.get("links", []),
                "excerpt": note["content"][:800]
            })
            all_linked_notes.update(note.get("links", []))

    # Build context for connection finding
    notes_text = "\n\n".join([
        f"### {n['name']}\nLinks to: {', '.join(n['links'][:10]) or 'none'}\nContent: {n['excerpt']}"
        for n in notes_with_links
    ])

    connections_prompt = f"""Analyze these notes related to "{topic}" and identify:
1. Non-obvious connections between ideas
2. Recurring themes or patterns
3. Potential contradictions or tensions
4. Ideas that might be worth exploring further

NOTES:
{notes_text}

Return your analysis as a structured response:"""

    cmd = [
        CLAUDE_PATH,
        "--print",
        "--output-format", "text",
        "--dangerously-skip-permissions",
        "--model", "haiku",
        "-p", connections_prompt,
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORKSPACE),
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=60,
        )

        analysis = stdout.decode().strip()

        return {
            "topic": topic,
            "analysis": analysis,
            "notes_analyzed": len(notes_with_links),
            "unique_links_found": len(all_linked_notes),
            "source_notes": [n["name"] for n in notes_with_links]
        }

    except asyncio.TimeoutError:
        return {"error": "Connection analysis timed out", "topic": topic}
    except Exception as e:
        return {"error": str(e), "topic": topic}


def main():
    parser = argparse.ArgumentParser(description="Vault traversal subagent")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # query
    query_p = subparsers.add_parser("query", help="Answer a question using vault contents")
    query_p.add_argument("question", help="Question to answer")
    query_p.add_argument("--vault", choices=["samuel", "iris"], help="Limit to specific vault")
    query_p.add_argument("--max-notes", type=int, default=5, help="Max notes to read")

    # summarize
    summarize_p = subparsers.add_parser("summarize", help="Summarize vault contents on a topic")
    summarize_p.add_argument("topic", help="Topic to summarize")

    # connections
    connections_p = subparsers.add_parser("connections", help="Find connections around a topic")
    connections_p.add_argument("topic", help="Topic to explore")

    args = parser.parse_args()

    if args.command == "query":
        result = asyncio.run(query_with_context(
            args.question,
            vault=args.vault,
            max_notes=args.max_notes
        ))
    elif args.command == "summarize":
        result = asyncio.run(summarize_topic(args.topic))
    elif args.command == "connections":
        result = asyncio.run(find_connections(args.topic))
    else:
        parser.print_help()
        return

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
