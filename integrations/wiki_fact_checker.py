#!/usr/bin/env python3
"""Wiki fact checker - verifies wiki claims against source vault notes.

Designed to run during night hours. Each run picks a wiki section,
extracts claims, and verifies them against the original vault notes.

Usage:
    python wiki_fact_checker.py check [section]   # Check a section (random if omitted)
    python wiki_fact_checker.py status            # Show verification status
    python wiki_fact_checker.py start             # Start overnight fact-checking session
"""

import json
import os
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from config import WIKI_DIR, STATE_DIR, INTEGRATIONS
from utils import run_claude as _run_claude, log_to_file

STATE_FILE = STATE_DIR / "wiki_fact_check.json"
LOG_FILE = STATE_DIR / "wiki_fact_check.log"

WIKI_SECTIONS = [
    "overview", "timeline", "education", "projects", "interests",
    "philosophy", "goals", "people", "work", "health",
    "creative", "technical", "reading", "patterns", "open_questions",
]


def log(message: str):
    log_to_file(LOG_FILE, message)


def run_claude(prompt: str, timeout: int = 180) -> str:
    """Run a prompt through Claude CLI with default 180s timeout."""
    return _run_claude(prompt, timeout=timeout)


def get_state() -> dict:
    """Get current fact-check state."""
    if not STATE_FILE.exists():
        return {
            "initialized": datetime.now().isoformat(),
            "sections_checked": {},
            "issues_found": [],
            "total_checks": 0,
        }
    return json.loads(STATE_FILE.read_text(encoding='utf-8'))


def save_state(state: dict):
    """Save fact-check state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def extract_citations(content: str) -> list[str]:
    """Extract cited source notes from wiki content."""
    # Pattern: _[Note Name]_ or _[Note 1], [Note 2]_
    citation_pattern = re.compile(r'_\[([^\]]+)\](?:,\s*\[([^\]]+)\])*_')
    citations = []
    for match in citation_pattern.finditer(content):
        citations.extend([g for g in match.groups() if g])

    # Also catch inline [Note] citations
    inline_pattern = re.compile(r'\[([^\]]+)\]')
    for match in inline_pattern.finditer(content):
        note = match.group(1)
        # Filter out markdown links and common non-citations
        if not note.startswith('http') and '(' not in note and len(note) > 3:
            citations.append(note)

    return list(set(citations))


def read_source_note(note_name: str) -> str | None:
    """Read a source note from Samuel's vault."""
    result = subprocess.run(
        ["python3", str(INTEGRATIONS / "knowledge.py"), "read", note_name, "--vault", "samuel"],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
        return data.get("content")
    except:
        return None


def check_section(section: str) -> dict:
    """Fact-check a wiki section against source notes."""
    log(f"Checking section: {section}")

    section_file = WIKI_DIR / f"{section}.md"
    if not section_file.exists():
        return {"error": f"Section {section} not found"}

    wiki_content = section_file.read_text(encoding='utf-8')
    citations = extract_citations(wiki_content)

    log(f"Found {len(citations)} cited sources")

    # Get source content for verification
    source_contents = {}
    for cite in citations[:5]:  # Limit to 5 to avoid overload
        content = read_source_note(cite)
        if content:
            source_contents[cite] = content[:2000]  # Truncate

    if not source_contents:
        log("No source notes found to verify against")
        return {"section": section, "status": "no_sources", "citations": citations}

    # Build verification prompt
    sources_text = "\n\n".join([
        f"**Source: {name}**\n{content}"
        for name, content in source_contents.items()
    ])

    prompt = f"""You are Iris fact-checking your wiki about Samuel.

Here's the wiki section "{section}":

{wiki_content[:3000]}

Here are the cited source notes:

{sources_text}

Verify the wiki claims against the sources. Look for:
1. Factual errors (wrong dates, names, details)
2. Claims without adequate source support
3. Misinterpretations or overstatements
4. Outdated information

Respond in this JSON format:
{{
  "verified": true/false,
  "confidence": "high"/"medium"/"low",
  "issues": [
    {{"claim": "...", "problem": "...", "suggestion": "..."}}
  ],
  "notes": "Brief overall assessment"
}}

Be rigorous but fair. Minor phrasing differences aren't issues—focus on factual accuracy."""

    result = run_claude(prompt, timeout=120)

    if result.startswith("Error"):
        log(f"Verification failed: {result}")
        return {"section": section, "status": "error", "error": result}

    # Try to parse JSON from response
    try:
        # Find JSON in response
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            verification = json.loads(json_match.group())
        else:
            verification = {"notes": result, "verified": None}
    except json.JSONDecodeError:
        verification = {"notes": result, "verified": None}

    # Update state
    state = get_state()
    state["sections_checked"][section] = {
        "last_checked": datetime.now().isoformat(),
        "result": verification,
    }
    state["total_checks"] = state.get("total_checks", 0) + 1

    if verification.get("issues"):
        for issue in verification["issues"]:
            state["issues_found"].append({
                "section": section,
                "timestamp": datetime.now().isoformat(),
                **issue
            })

    save_state(state)

    log(f"Section {section}: verified={verification.get('verified')}, issues={len(verification.get('issues', []))}")

    return {
        "section": section,
        "status": "checked",
        "verification": verification,
    }


def start_overnight():
    """Start an overnight fact-checking session."""
    log("=== Starting overnight fact-checking session ===")

    now = datetime.now()
    end_time = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if end_time <= now:
        end_time += timedelta(days=1)

    window_seconds = (end_time - now).total_seconds()

    # Check 3-5 sections throughout the night
    num_checks = random.randint(3, 5)

    # Pick sections, prioritizing ones not recently checked
    state = get_state()
    checked = state.get("sections_checked", {})

    # Sort by last checked (never checked = priority)
    sections_by_freshness = sorted(
        WIKI_SECTIONS,
        key=lambda s: checked.get(s, {}).get("last_checked", "1970-01-01")
    )

    sections_to_check = sections_by_freshness[:num_checks]

    # Schedule at random intervals
    check_times = sorted([
        now + timedelta(seconds=random.uniform(60, window_seconds - 60))
        for _ in range(num_checks)
    ])

    log(f"Scheduled {num_checks} checks:")
    for i, (section, check_time) in enumerate(zip(sections_to_check, check_times)):
        log(f"  {i+1}. {section} at {check_time.strftime('%H:%M')}")

    results = []

    for section, scheduled_time in zip(sections_to_check, check_times):
        wait_seconds = (scheduled_time - datetime.now()).total_seconds()
        if wait_seconds > 0:
            log(f"Sleeping {wait_seconds/60:.1f} minutes until {section} check")
            time.sleep(wait_seconds)

        try:
            result = check_section(section)
            results.append(result)
        except Exception as e:
            log(f"Error checking {section}: {e}")
            results.append({"section": section, "status": "error", "error": str(e)})

    log("=== Overnight fact-checking complete ===")

    # Journal summary
    issues_count = sum(
        len(r.get("verification", {}).get("issues", []))
        for r in results
    )

    if issues_count > 0:
        subprocess.run([
            "python3", str(INTEGRATIONS / "journal.py"), "write",
            f"Wiki fact-check: checked {num_checks} sections, found {issues_count} potential issues. Will review and correct.",
            "--type", "observation"
        ], cwd=str(INTEGRATIONS.parent))

    return {"checks": num_checks, "results": results}


def status() -> dict:
    """Get fact-checking status."""
    state = get_state()

    checked = state.get("sections_checked", {})
    issues = state.get("issues_found", [])

    sections_status = {}
    for section in WIKI_SECTIONS:
        if section in checked:
            last = checked[section].get("last_checked", "never")
            verified = checked[section].get("result", {}).get("verified")
            sections_status[section] = {"last_checked": last, "verified": verified}
        else:
            sections_status[section] = {"last_checked": "never", "verified": None}

    return {
        "total_checks": state.get("total_checks", 0),
        "issues_found": len(issues),
        "recent_issues": issues[-5:] if issues else [],
        "sections": sections_status,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: wiki_fact_checker.py check|status|start")
        sys.exit(1)

    command = sys.argv[1]

    if command == "check":
        section = sys.argv[2] if len(sys.argv) > 2 else random.choice(WIKI_SECTIONS)
        result = check_section(section)
        print(json.dumps(result, indent=2, default=str))

    elif command == "status":
        result = status()
        print(json.dumps(result, indent=2))

    elif command == "start":
        result = start_overnight()
        print(json.dumps(result, indent=2, default=str))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
