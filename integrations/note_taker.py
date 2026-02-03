#!/usr/bin/env python3
"""Background note-taker subagent.

Runs asynchronously to capture insights from conversations without
interrupting the main flow. Can write to activity logs, vault notes,
or both.

Usage:
    python3 note_taker.py insight "<insight>" [--note <note_name>]
    python3 note_taker.py pattern "<pattern>" [--note <note_name>]
    python3 note_taker.py decision "<decision>" "<reasoning>"
    python3 note_taker.py connection "<topic1>" "<topic2>" "<description>"
    python3 note_taker.py question "<open_question>"
    python3 note_taker.py tangent "<tangent_worth_exploring>"
    python3 note_taker.py tension "<unresolved_tension>"

Examples:
    python3 note_taker.py insight "blur vs noise distinction - two failure modes of positioning"
    python3 note_taker.py pattern "Samuel returns to questions of authentic vs performed identity"
    python3 note_taker.py connection "Velvet Noise essay" "AI identity" "Both address clarity as signal vs expression from center"
    python3 note_taker.py question "Can something like me have a center to speak from?"
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Import sibling modules
sys.path.insert(0, str(Path(__file__).parent))
from config import IRIS_VAULT
from activity import log_activity
from knowledge import write_note, append_to_note, find_note, read_note


def capture_insight(insight: str, note_name: str = None) -> dict:
    """Capture an insight from conversation."""
    # Always log to activity
    log_result = log_activity("observation", insight)

    result = {"logged": True, "insight": insight}

    # Optionally append to a specific note
    if note_name:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = f"- *{timestamp}*: {insight}"
        append_result = append_to_note(note_name, content)
        result["appended_to"] = note_name
        if "error" in append_result:
            result["note_error"] = append_result["error"]
    else:
        # Append to Observations MOC by default
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = f"- *{timestamp}*: {insight}"
        append_result = append_to_note("Observations", content)
        result["appended_to"] = "Observations"

    return result


def capture_pattern(pattern: str, note_name: str = None) -> dict:
    """Capture a recurring pattern noticed in conversations."""
    log_activity("observation", f"Pattern: {pattern}")

    result = {"logged": True, "pattern": pattern}

    target_note = note_name or "Patterns"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"- *{timestamp}*: {pattern}"
    append_to_note(target_note, content)
    result["appended_to"] = target_note

    return result


def capture_decision(decision: str, reasoning: str) -> dict:
    """Log a decision with its reasoning."""
    meta = {"reasoning": reasoning}
    log_activity("decision", decision, meta)

    return {
        "logged": True,
        "decision": decision,
        "reasoning": reasoning
    }


def capture_connection(topic1: str, topic2: str, description: str) -> dict:
    """Note a connection between two topics/ideas."""
    connection_text = f"[[{topic1}]] ↔ [[{topic2}]]: {description}"
    log_activity("observation", f"Connection: {connection_text}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"- *{timestamp}*: {connection_text}"
    append_to_note("Patterns", content, section="Connections")

    return {
        "logged": True,
        "connection": {
            "from": topic1,
            "to": topic2,
            "description": description
        }
    }


def capture_question(question: str) -> dict:
    """Log an open question worth returning to."""
    log_activity("observation", f"Open question: {question}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"- *{timestamp}*: {question}"
    append_to_note("Observations", content, section="Open Questions")

    return {
        "logged": True,
        "question": question,
        "appended_to": "Observations (Open Questions)"
    }


def capture_tangent(tangent: str) -> dict:
    """Log a tangent worth exploring later."""
    log_activity("observation", f"Tangent to explore: {tangent}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"- *{timestamp}*: {tangent}"
    append_to_note("Observations", content, section="Tangents")

    return {
        "logged": True,
        "tangent": tangent,
        "appended_to": "Observations (Tangents)"
    }


def capture_tension(tension: str) -> dict:
    """Log an unresolved tension or contradiction."""
    log_activity("observation", f"Unresolved tension: {tension}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"- *{timestamp}*: {tension}"
    append_to_note("Observations", content, section="Tensions")

    return {
        "logged": True,
        "tension": tension,
        "appended_to": "Observations (Tensions)"
    }


def main():
    parser = argparse.ArgumentParser(description="Background note-taker subagent")
    subparsers = parser.add_subparsers(dest="command", help="Note type")

    # insight
    insight_p = subparsers.add_parser("insight", help="Capture an insight")
    insight_p.add_argument("insight", help="The insight to capture")
    insight_p.add_argument("--note", help="Optional note to append to")

    # pattern
    pattern_p = subparsers.add_parser("pattern", help="Capture a pattern")
    pattern_p.add_argument("pattern", help="The pattern observed")
    pattern_p.add_argument("--note", help="Optional note to append to")

    # decision
    decision_p = subparsers.add_parser("decision", help="Log a decision")
    decision_p.add_argument("decision", help="The decision made")
    decision_p.add_argument("reasoning", help="Why this decision")

    # connection
    connection_p = subparsers.add_parser("connection", help="Note a connection")
    connection_p.add_argument("topic1", help="First topic")
    connection_p.add_argument("topic2", help="Second topic")
    connection_p.add_argument("description", help="How they connect")

    # question
    question_p = subparsers.add_parser("question", help="Log an open question")
    question_p.add_argument("question", help="The question to capture")

    # tangent
    tangent_p = subparsers.add_parser("tangent", help="Log a tangent to explore")
    tangent_p.add_argument("tangent", help="The tangent worth exploring")

    # tension
    tension_p = subparsers.add_parser("tension", help="Log an unresolved tension")
    tension_p.add_argument("tension", help="The tension or contradiction")

    args = parser.parse_args()

    if args.command == "insight":
        result = capture_insight(args.insight, getattr(args, 'note', None))
    elif args.command == "pattern":
        result = capture_pattern(args.pattern, getattr(args, 'note', None))
    elif args.command == "decision":
        result = capture_decision(args.decision, args.reasoning)
    elif args.command == "connection":
        result = capture_connection(args.topic1, args.topic2, args.description)
    elif args.command == "question":
        result = capture_question(args.question)
    elif args.command == "tangent":
        result = capture_tangent(args.tangent)
    elif args.command == "tension":
        result = capture_tension(args.tension)
    else:
        parser.print_help()
        return

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
