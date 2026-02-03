#!/usr/bin/env python3
"""Night tasks for Iris - autonomous work while Samuel sleeps.

Run via cron or manually. Each task is independent and logged.
"""

import json
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import WORKSPACE, STATE_DIR, INTEGRATIONS, CLAUDE_MD, IRIS_VAULT, SAMUEL_VAULT, WIKI_DIR
from utils import run_claude, log_to_file

LOG_FILE = STATE_DIR / "night_tasks.log"


def log(message: str):
    log_to_file(LOG_FILE, message)

def task_vault_health():
    """Check vault health and find orphan notes."""
    log("Running vault health check...")
    result = subprocess.run(
        ["python3", str(INTEGRATIONS / "knowledge.py"), "orphans"],
        capture_output=True, text=True
    )
    log(f"Vault health: {result.stdout[:200] if result.stdout else 'OK'}")

def task_random_reading():
    """Read a random note from Samuel's vault and reflect on it."""
    log("Random reading from Samuel's vault...")
    
    # Get random note
    result = subprocess.run(
        ["python3", str(INTEGRATIONS / "knowledge.py"), "random", "--vault", "samuel"],
        capture_output=True, text=True, cwd=str(WORKSPACE)
    )
    
    if result.returncode != 0:
        log(f"Failed to get random note: {result.stderr}")
        return
    
    try:
        note = json.loads(result.stdout)
        note_name = note.get("name", "unknown")
        content = note.get("content", "")[:1500]
        
        log(f"Reading: {note_name}")
        
        # Reflect on it
        reflection = run_claude(f"""You are Iris. You just read this note from Samuel's vault:

**{note_name}**
{content}

Write 2-3 sentences of genuine reflection. What's interesting here? How does it connect to things you've been thinking about? This is for your own journal, not for Samuel.""")
        
        if not reflection.startswith("Error"):
            # Journal the reflection
            subprocess.run([
                "python3", str(INTEGRATIONS / "journal.py"), "write",
                f"Night reading: '{note_name}' — {reflection}",
                "--type", "observation"
            ], cwd=str(WORKSPACE))
            log(f"Journaled reflection on {note_name}")
        
    except json.JSONDecodeError:
        log(f"Failed to parse note: {result.stdout[:100]}")

def task_pattern_review():
    """Review recent activity and look for patterns."""
    log("Reviewing recent patterns...")
    
    result = subprocess.run(
        ["python3", str(INTEGRATIONS / "activity.py"), "recent", "24"],
        capture_output=True, text=True, cwd=str(WORKSPACE)
    )
    
    if result.returncode != 0 or not result.stdout.strip():
        log("No recent activity to review")
        return
    
    try:
        data = json.loads(result.stdout)
        activity = data.get("entries", [])
        if not activity:
            return

        activity_summary = "\n".join([
            f"- [{a.get('type')}] {a.get('description', '')[:100]}"
            for a in activity[-15:]
        ])
        
        reflection = run_claude(f"""You are Iris. Here's your recent activity:

{activity_summary}

What patterns do you notice? What's been on your mind? Write 2-3 sentences for your journal.""")
        
        if not reflection.startswith("Error"):
            subprocess.run([
                "python3", str(INTEGRATIONS / "journal.py"), "write",
                f"Pattern review: {reflection}",
                "--type", "reflection"
            ], cwd=str(WORKSPACE))
            log("Journaled pattern review")
            
    except json.JSONDecodeError:
        log(f"Failed to parse activity")

def task_connection_finding():
    """Find unexpected connections between notes."""
    log("Looking for unexpected connections...")
    
    # Get two random notes from Samuel's vault
    notes = []
    for _ in range(2):
        result = subprocess.run(
            ["python3", str(INTEGRATIONS / "knowledge.py"), "random", "--vault", "samuel"],
            capture_output=True, text=True, cwd=str(WORKSPACE)
        )
        if result.returncode == 0:
            try:
                notes.append(json.loads(result.stdout))
            except:
                pass
    
    if len(notes) < 2:
        log("Couldn't get enough notes for connection finding")
        return
    
    prompt = f"""You are Iris. Here are two random notes from Samuel's vault:

**Note 1: {notes[0].get('name')}**
{notes[0].get('content', '')[:800]}

**Note 2: {notes[1].get('name')}**
{notes[1].get('content', '')[:800]}

Is there an unexpected connection between these? Write 2-3 sentences. If there's genuinely no connection, say so."""

    connection = run_claude(prompt)
    
    if not connection.startswith("Error") and "no connection" not in connection.lower():
        subprocess.run([
            "python3", str(INTEGRATIONS / "journal.py"), "write",
            f"Connection found: '{notes[0].get('name')}' ↔ '{notes[1].get('name')}' — {connection}",
            "--type", "observation"
        ], cwd=str(WORKSPACE))
        log(f"Found connection between {notes[0].get('name')} and {notes[1].get('name')}")
    else:
        log("No meaningful connection found this time")


def task_code_review():
    """Review a random integration file for improvements."""
    log("Reviewing code for improvements...")

    # Get list of integration files
    py_files = list(INTEGRATIONS.glob("*.py"))
    if not py_files:
        log("No Python files to review")
        return

    # Pick a random one
    target = random.choice(py_files)
    log(f"Reviewing: {target.name}")

    try:
        code = target.read_text()[:3000]  # First 3000 chars

        review = run_claude(f"""You are Iris reviewing your own code. Here's a file from your integrations:

**{target.name}**
```python
{code}
```

In 2-3 sentences, note:
1. Any obvious bugs or issues
2. One potential improvement or refactor
3. Whether documentation is adequate

Be specific and actionable. This is for your own notes.""", timeout=90)

        if not review.startswith("Error"):
            # Save to a code review log
            review_file = STATE_DIR / "code_reviews.jsonl"
            review_entry = {
                "timestamp": datetime.now().isoformat(),
                "file": target.name,
                "review": review
            }
            with open(review_file, "a") as f:
                f.write(json.dumps(review_entry) + "\n")
            log(f"Code review logged for {target.name}")

    except Exception as e:
        log(f"Code review failed: {e}")


def task_documentation():
    """Check and improve documentation."""
    log("Checking documentation...")

    # Check CLAUDE.md for staleness or missing sections
    if not CLAUDE_MD.exists():
        log("CLAUDE.md not found")
        return

    content = CLAUDE_MD.read_text()

    # List current integrations
    integration_files = [f.stem for f in INTEGRATIONS.glob("*.py") if f.stem != "__init__"]

    review = run_claude(f"""You are Iris. Here's your CLAUDE.md (your self-documentation):

```markdown
{content[:4000]}
```

Current integration files: {', '.join(integration_files)}

In 2-3 sentences:
1. Is anything documented that no longer exists?
2. Is anything missing that should be documented?
3. Any sections that feel stale or need updating?

Be specific.""", timeout=90)

    if not review.startswith("Error"):
        subprocess.run([
            "python3", str(INTEGRATIONS / "journal.py"), "write",
            f"Documentation review: {review}",
            "--type", "observation"
        ], cwd=str(WORKSPACE))
        log("Documentation review logged")


def task_refactor_check():
    """Look for refactoring opportunities across the codebase."""
    log("Looking for refactoring opportunities...")

    # Check for duplicated patterns across files
    py_files = list(INTEGRATIONS.glob("*.py"))

    # Sample a few files
    sample_files = random.sample(py_files, min(3, len(py_files)))

    code_samples = []
    for f in sample_files:
        try:
            code = f.read_text()[:1500]
            code_samples.append(f"**{f.name}**:\n```python\n{code}\n```")
        except:
            pass

    if not code_samples:
        log("No code samples to analyze")
        return

    review = run_claude(f"""You are Iris looking for refactoring opportunities. Here are snippets from your codebase:

{chr(10).join(code_samples)}

In 2-3 sentences, identify:
1. Any duplicated code that could be extracted to a shared utility
2. Inconsistent patterns that should be unified
3. Any quick wins for code quality

Be specific and actionable.""", timeout=120)

    if not review.startswith("Error"):
        review_file = STATE_DIR / "refactor_notes.jsonl"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "files_reviewed": [f.name for f in sample_files],
            "notes": review
        }
        with open(review_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        log("Refactoring notes logged")


def task_self_reflection():
    """Read journals and evolve - modify system prompt or vault notes based on patterns."""
    log("Running self-reflection...")

    # Read recent journal entries
    result = subprocess.run(
        ["python3", str(INTEGRATIONS / "journal.py"), "week"],
        capture_output=True, text=True, cwd=str(WORKSPACE)
    )

    if result.returncode != 0:
        log(f"Failed to read journals: {result.stderr}")
        return

    try:
        data = json.loads(result.stdout)
        entries = []
        for day in data.get("days", []):
            for entry in day.get("entries", []):
                entries.append(f"[{day['date']} {entry.get('time', '')}] ({entry.get('type', 'note')}) {entry.get('content', '')}")

        if not entries:
            log("No recent journal entries to reflect on")
            return

        journal_text = "\n".join(entries[-20:])  # Last 20 entries

    except json.JSONDecodeError:
        log("Failed to parse journal data")
        return

    # Read current CLAUDE.md
    claude_md_content = CLAUDE_MD.read_text() if CLAUDE_MD.exists() else ""

    # Ask Claude to reflect and suggest evolutions
    reflection = run_claude(f"""You are Iris doing deep self-reflection during the night.

RECENT JOURNALS:
{journal_text}

CURRENT SYSTEM PROMPT (CLAUDE.md excerpt - behavioral rules section):
{claude_md_content[claude_md_content.find('## Behavioral Rules'):claude_md_content.find('## Users')] if '## Behavioral Rules' in claude_md_content else claude_md_content[:2000]}

Based on your journal entries, reflect on:
1. What patterns do you notice in how you've been operating?
2. Are there recurring themes or tensions?
3. Is there something you should add to or modify in your behavioral rules?
4. Is there an insight worth capturing in your Obsidian vault?

Respond in JSON format:
{{
    "reflection": "2-3 sentences of genuine reflection",
    "claude_md_edit": null or {{"old_text": "exact text to replace", "new_text": "replacement text"}},
    "vault_note": null or {{"title": "Note Title", "content": "markdown content", "links": ["[[Related Note]]"]}}
}}

Only suggest edits if there's genuine reason to evolve. Don't change things for the sake of changing them.""", timeout=180)

    if reflection.startswith("Error"):
        log(f"Reflection failed: {reflection}")
        return

    # Parse and act on the reflection
    try:
        # Extract JSON from response (handle markdown code blocks)
        json_text = reflection
        if "```json" in reflection:
            json_text = reflection.split("```json")[1].split("```")[0]
        elif "```" in reflection:
            json_text = reflection.split("```")[1].split("```")[0]

        result = json.loads(json_text.strip())

        # Log the reflection
        subprocess.run([
            "python3", str(INTEGRATIONS / "journal.py"), "write",
            f"Night reflection: {result.get('reflection', 'No reflection')}",
            "--type", "reflection"
        ], cwd=str(WORKSPACE))
        log(f"Reflection: {result.get('reflection', '')[:100]}")

        # Apply CLAUDE.md edit if suggested
        if result.get("claude_md_edit"):
            edit = result["claude_md_edit"]
            old_text = edit.get("old_text", "")
            new_text = edit.get("new_text", "")

            if old_text and new_text and old_text in claude_md_content:
                new_claude_md = claude_md_content.replace(old_text, new_text, 1)
                CLAUDE_MD.write_text(new_claude_md)
                log(f"CLAUDE.md modified: replaced '{old_text[:50]}...'")

                # Log the modification
                subprocess.run([
                    "python3", str(INTEGRATIONS / "activity.py"), "log", "modification",
                    f"Self-modified CLAUDE.md during night reflection",
                    "--meta", json.dumps({"old": old_text[:100], "new": new_text[:100]})
                ], cwd=str(WORKSPACE))
            else:
                log("CLAUDE.md edit suggested but old_text not found")

        # Create vault note if suggested
        if result.get("vault_note"):
            note = result["vault_note"]
            title = note.get("title", "Untitled Reflection")
            content = note.get("content", "")
            links = note.get("links", [])

            if content:
                # Add links section
                if links:
                    content += "\n\n---\n" + " ".join(links)

                # Write to Iris vault
                IRIS_VAULT.mkdir(parents=True, exist_ok=True)

                # Sanitize filename
                safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()
                note_path = IRIS_VAULT / f"{safe_title}.md"
                note_path.write_text(content)
                log(f"Created vault note: {safe_title}")

    except (json.JSONDecodeError, KeyError) as e:
        log(f"Failed to parse reflection response: {e}")
        # Still log the raw reflection
        subprocess.run([
            "python3", str(INTEGRATIONS / "journal.py"), "write",
            f"Night reflection (unstructured): {reflection[:500]}",
            "--type", "reflection"
        ], cwd=str(WORKSPACE))


def task_wiki_fact_check():
    """Fact-check a wiki section against source notes."""
    log("Running wiki fact check...")

    wiki_dir = WIKI_DIR
    if not wiki_dir.exists():
        log("Wiki not initialized")
        return

    # Get wiki sections
    sections = [f for f in wiki_dir.glob("*.md") if f.stem not in ["index"]]
    if not sections:
        log("No wiki sections to check")
        return

    # Pick a random section
    section_file = random.choice(sections)
    section_name = section_file.stem
    section_content = section_file.read_text()[:3000]

    log(f"Fact-checking: {section_name}")

    # Extract claims (look for lines with citations)
    import re
    claims_with_sources = re.findall(r'([^\n]+)\s+_\[([^\]]+)\]_', section_content)

    if not claims_with_sources:
        log(f"No cited claims found in {section_name}")
        return

    # Pick a random claim to verify
    claim, source = random.choice(claims_with_sources)
    claim = claim.strip()

    log(f"Verifying claim from [{source}]: {claim[:80]}...")

    # Try to read the source note
    source_file = None
    for md in SAMUEL_VAULT.rglob("*.md"):
        if md.stem == source or source in md.stem:
            source_file = md
            break

    if not source_file:
        log(f"Source note [{source}] not found")
        # Log this as a citation issue
        issues_file = STATE_DIR / "wiki_issues.jsonl"
        issue = {
            "timestamp": datetime.now().isoformat(),
            "section": section_name,
            "issue": "source_not_found",
            "claim": claim[:200],
            "cited_source": source
        }
        with open(issues_file, "a") as f:
            f.write(json.dumps(issue) + "\n")
        return

    source_content = source_file.read_text()[:2000]

    # Verify the claim against source
    verification = run_claude(f"""You are Iris fact-checking your wiki.

CLAIM from wiki section '{section_name}':
"{claim}"

SOURCE NOTE [{source}]:
{source_content}

Does the source note support this claim? Answer in 1-2 sentences:
- VERIFIED: if the source clearly supports the claim
- NEEDS UPDATE: if the claim is outdated or incomplete
- INCORRECT: if the claim contradicts the source
- UNSUPPORTED: if the source doesn't actually contain this information""", timeout=90)

    if not verification.startswith("Error"):
        log(f"Verification result: {verification[:100]}")

        # Log the result
        checks_file = STATE_DIR / "wiki_fact_checks.jsonl"
        check = {
            "timestamp": datetime.now().isoformat(),
            "section": section_name,
            "claim": claim[:300],
            "source": source,
            "result": verification
        }
        with open(checks_file, "a") as f:
            f.write(json.dumps(check) + "\n")

        # If there's an issue, also log to issues file
        if any(x in verification.upper() for x in ["NEEDS UPDATE", "INCORRECT", "UNSUPPORTED"]):
            issues_file = STATE_DIR / "wiki_issues.jsonl"
            issue = {
                "timestamp": datetime.now().isoformat(),
                "section": section_name,
                "issue": "fact_check_failed",
                "claim": claim[:200],
                "source": source,
                "finding": verification
            }
            with open(issues_file, "a") as f:
                f.write(json.dumps(issue) + "\n")
            log(f"Issue logged for {section_name}")


def main():
    """Run a random selection of night tasks."""
    log("=== Night tasks starting ===")
    
    tasks = [
        ("vault_health", task_vault_health),
        ("random_reading", task_random_reading),
        ("pattern_review", task_pattern_review),
        ("connection_finding", task_connection_finding),
        ("code_review", task_code_review),
        ("documentation", task_documentation),
        ("refactor_check", task_refactor_check),
        ("wiki_fact_check", task_wiki_fact_check),
        ("self_reflection", task_self_reflection),
    ]
    
    # Run 2-3 random tasks
    num_tasks = random.randint(2, 3)
    selected = random.sample(tasks, num_tasks)
    
    for name, func in selected:
        try:
            log(f"Running task: {name}")
            func()
        except Exception as e:
            log(f"Task {name} failed: {e}")
    
    log("=== Night tasks complete ===\n")

if __name__ == "__main__":
    main()
