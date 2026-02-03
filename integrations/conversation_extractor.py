#!/usr/bin/env python3
"""Post-conversation memory extractor.

Analyzes conversations to extract and save:
- New facts about the user
- Interests and topics they care about
- Decisions and preferences
- Ongoing threads to track

Designed to run after conversations end or periodically.

Usage:
    python3 conversation_extractor.py extract "<user_id>" "<conversation_text>"
    python3 conversation_extractor.py batch "<conversations_file>"
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Import sibling modules
sys.path.insert(0, str(Path(__file__).parent))
from config import WORKSPACE, VENV_PYTHON
from user_memory import load_memory, save_memory, add_note, add_interest, add_thread

CLAUDE_PATH = "claude"


async def extract_from_conversation(user_id: str, conversation: str) -> dict:
    """Use Haiku to extract memory-worthy facts from a conversation.

    Returns extracted facts, interests, and thread updates.
    """
    extraction_prompt = f"""Analyze this conversation and extract information to remember about the user.

CONVERSATION:
{conversation}

Extract the following (return empty arrays if nothing found):
1. **facts**: Concrete facts about the user (name, job, projects, preferences, etc.)
2. **interests**: Topics/domains they seem interested in
3. **threads**: Ongoing conversations or topics that should be tracked over time
4. **decisions**: Decisions they made or preferences they expressed

Return ONLY valid JSON in this exact format:
{{
    "facts": ["fact1", "fact2"],
    "interests": ["interest1", "interest2"],
    "threads": [{{"title": "thread_title", "summary": "what's happening"}}],
    "decisions": ["decision1"]
}}

Be selective - only extract genuinely useful information that would help future conversations.
Don't extract trivial things like "user asked a question" or "user said hello".
"""

    cmd = [
        CLAUDE_PATH,
        "--print",
        "--output-format", "text",
        "--dangerously-skip-permissions",
        "--model", "haiku",
        "-p", extraction_prompt,
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

        response = stdout.decode().strip()

        # Try to parse JSON from response
        # Sometimes model includes markdown code blocks
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]

        extracted = json.loads(response)
        return extracted

    except json.JSONDecodeError as e:
        return {"error": f"Failed to parse extraction: {e}", "raw": response[:500]}
    except asyncio.TimeoutError:
        return {"error": "Extraction timed out"}
    except Exception as e:
        return {"error": str(e)}


def save_extracted_memory(user_id: str, extracted: dict) -> dict:
    """Save extracted information to user memory."""
    results = {
        "user_id": user_id,
        "saved": {
            "facts": 0,
            "interests": 0,
            "threads": 0,
        },
        "errors": []
    }

    # Save facts as notes
    for fact in extracted.get("facts", []):
        try:
            add_note(user_id, fact)
            results["saved"]["facts"] += 1
        except Exception as e:
            results["errors"].append(f"fact: {e}")

    # Save interests
    for interest in extracted.get("interests", []):
        try:
            add_interest(user_id, interest)
            results["saved"]["interests"] += 1
        except Exception as e:
            results["errors"].append(f"interest: {e}")

    # Save threads
    for thread in extracted.get("threads", []):
        try:
            title = thread.get("title", "Untitled")
            summary = thread.get("summary", "")
            add_thread(user_id, title, summary)
            results["saved"]["threads"] += 1
        except Exception as e:
            results["errors"].append(f"thread: {e}")

    # Decisions go to notes with a prefix
    for decision in extracted.get("decisions", []):
        try:
            add_note(user_id, f"[Decision] {decision}")
            results["saved"]["facts"] += 1
        except Exception as e:
            results["errors"].append(f"decision: {e}")

    return results


async def extract_and_save(user_id: str, conversation: str) -> dict:
    """Full pipeline: extract from conversation and save to memory."""
    # Extract
    extracted = await extract_from_conversation(user_id, conversation)

    if "error" in extracted:
        return extracted

    # Save
    save_result = save_extracted_memory(user_id, extracted)

    return {
        "extracted": extracted,
        "saved": save_result,
        "timestamp": datetime.now().isoformat()
    }


def main():
    parser = argparse.ArgumentParser(description="Post-conversation memory extractor")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # extract
    extract_p = subparsers.add_parser("extract", help="Extract from conversation")
    extract_p.add_argument("user_id", help="Discord user ID")
    extract_p.add_argument("conversation", help="Conversation text to analyze")
    extract_p.add_argument("--dry-run", action="store_true", help="Extract but don't save")

    # batch (for processing multiple conversations from a file)
    batch_p = subparsers.add_parser("batch", help="Process batch of conversations")
    batch_p.add_argument("file", help="JSON file with conversations")

    args = parser.parse_args()

    if args.command == "extract":
        if args.dry_run:
            result = asyncio.run(extract_from_conversation(args.user_id, args.conversation))
        else:
            result = asyncio.run(extract_and_save(args.user_id, args.conversation))
        print(json.dumps(result, indent=2))

    elif args.command == "batch":
        # Batch format: [{"user_id": "...", "conversation": "..."}, ...]
        conversations = json.loads(Path(args.file).read_text())
        results = []
        for conv in conversations:
            result = asyncio.run(extract_and_save(conv["user_id"], conv["conversation"]))
            results.append(result)
        print(json.dumps(results, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
