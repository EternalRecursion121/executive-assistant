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

WORKSPACE = Path("/home/executive-assistant/workspace")
STATE_DIR = WORKSPACE / "state"
INTEGRATIONS = Path("/home/executive-assistant/integrations")
LOG_FILE = STATE_DIR / "night_tasks.log"

def log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def run_claude(prompt: str, timeout: int = 120) -> str:
    """Run a prompt through Claude CLI."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE),
            env={**os.environ, "PATH": "/home/iris/.local/node_modules/.bin:" + os.environ.get("PATH", "")}
        )
        return result.stdout.strip() if result.returncode == 0 else f"Error: {result.stderr}"
    except subprocess.TimeoutExpired:
        return "Error: Timeout"
    except Exception as e:
        return f"Error: {e}"

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
    claude_md = Path("/home/executive-assistant/CLAUDE.md")
    if not claude_md.exists():
        log("CLAUDE.md not found")
        return

    content = claude_md.read_text()

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
