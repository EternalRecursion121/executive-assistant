#!/usr/bin/env python3
"""Self-evolution system for Iris.

A comprehensive nightly job that:
1. Spawns subagents to explore the entire codebase
2. Reads recent journals, reflections, and patterns
3. Reviews CLAUDE.md against actual behavior
4. Proposes and applies self-modifications
5. Updates CLAUDE.md to reflect actual capabilities

Usage:
    python self_evolution.py evolve           # Full evolution cycle
    python self_evolution.py check            # Check what would change
    python self_evolution.py status           # Show evolution state
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from textwrap import dedent

from config import (
    PROJECT_ROOT, WORKSPACE, STATE_DIR, INTEGRATIONS, VENV_PYTHON,
    CLAUDE_MD, IRIS_VAULT, SAMUEL_VAULT
)
from utils import run_claude, log_to_file

LOG_FILE = STATE_DIR / "self_evolution.log"
EVOLUTION_STATE = STATE_DIR / "self_evolution_state.json"


def log(message: str):
    log_to_file(LOG_FILE, message)


def load_state() -> dict:
    """Load evolution state."""
    if EVOLUTION_STATE.exists():
        try:
            return json.loads(EVOLUTION_STATE.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "last_evolution": None,
        "evolutions": [],
        "pending_modifications": []
    }


def save_state(state: dict):
    """Save evolution state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    EVOLUTION_STATE.write_text(json.dumps(state, indent=2))


# =============================================================================
# Phase 1: Exploration via subagents
# =============================================================================

def explore_codebase() -> dict:
    """Spawn a subagent to explore the codebase structure."""
    log("Phase 1: Exploring codebase...")

    prompt = dedent("""
        You are exploring the Iris codebase to understand its current structure.

        Tasks:
        1. List all Python files in /home/iris/executive-assistant/integrations/
        2. For each file, read the docstring and main function signatures
        3. Check the cron jobs (crontab -l)
        4. List all state files in workspace/state/
        5. Read the current CLAUDE.md structure

        Output a JSON summary with:
        {
            "integrations": [{"name": "...", "purpose": "...", "commands": [...]}],
            "cron_jobs": [{"schedule": "...", "script": "...", "purpose": "..."}],
            "state_files": ["..."],
            "claude_md_sections": ["..."],
            "undocumented_features": ["..."]
        }

        Be thorough - read actual file contents, don't guess.
    """).strip()

    result = run_claude(prompt, timeout=300)

    if result.startswith("Error"):
        log(f"Codebase exploration failed: {result}")
        return {}

    # Try to extract JSON
    try:
        # Handle markdown code blocks
        if "```json" in result:
            json_text = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            json_text = result.split("```")[1].split("```")[0]
        else:
            json_text = result
        return json.loads(json_text.strip())
    except json.JSONDecodeError:
        log("Failed to parse codebase exploration as JSON")
        return {"raw_output": result}


def explore_journals() -> dict:
    """Read recent journals and reflections."""
    log("Phase 1: Reading journals and reflections...")

    journal_entries = []

    # Read journal state
    journal_dir = STATE_DIR / "journal"
    if journal_dir.exists():
        # Get last 7 days
        for i in range(7):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            journal_file = journal_dir / f"{date}.json"
            if journal_file.exists():
                try:
                    entries = json.loads(journal_file.read_text())
                    journal_entries.extend(entries)
                except:
                    pass

    # Read recent reflections from vault
    reflections = []
    if IRIS_VAULT.exists():
        for md_file in IRIS_VAULT.glob("Reflection*.md"):
            try:
                content = md_file.read_text()
                reflections.append({
                    "name": md_file.stem,
                    "content": content[:1500]
                })
            except:
                pass

    # Read observations and patterns
    observations = ""
    patterns = ""
    if (IRIS_VAULT / "Observations.md").exists():
        observations = (IRIS_VAULT / "Observations.md").read_text()
    if (IRIS_VAULT / "Patterns.md").exists():
        patterns = (IRIS_VAULT / "Patterns.md").read_text()

    return {
        "journal_entries": journal_entries[-20:],  # Last 20
        "reflections": reflections[-5:],  # Last 5
        "observations": observations,
        "patterns": patterns
    }


def explore_activity() -> dict:
    """Get recent activity and conversation patterns."""
    log("Phase 1: Analyzing recent activity...")

    activity = []
    activity_file = STATE_DIR / "activity.json"
    if activity_file.exists():
        try:
            all_activity = json.loads(activity_file.read_text())
            # Get last 100 entries
            activity = all_activity[-100:]
        except:
            pass

    # Analyze activity types
    type_counts = {}
    for entry in activity:
        t = entry.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "recent_activity": activity[-30:],
        "activity_summary": type_counts,
        "total_entries": len(activity)
    }


# =============================================================================
# Phase 2: Analysis and proposal generation
# =============================================================================

def analyze_for_evolution(codebase: dict, journals: dict, activity: dict) -> dict:
    """Use Claude to analyze everything and propose evolutions."""
    log("Phase 2: Analyzing for evolution opportunities...")

    # Build comprehensive context
    context = dedent(f"""
        === CODEBASE STATE ===
        {json.dumps(codebase, indent=2)[:5000]}

        === RECENT JOURNALS ===
        {json.dumps(journals.get('journal_entries', [])[:10], indent=2)[:2000]}

        === REFLECTIONS ===
        {json.dumps(journals.get('reflections', [])[:3], indent=2)[:2000]}

        === OBSERVATIONS ===
        {journals.get('observations', 'None')[:1500]}

        === PATTERNS ===
        {journals.get('patterns', 'None')[:1500]}

        === ACTIVITY SUMMARY ===
        {json.dumps(activity.get('activity_summary', {}), indent=2)}
    """).strip()

    current_claude_md = CLAUDE_MD.read_text() if CLAUDE_MD.exists() else ""

    prompt = dedent(f"""
        You are Iris, analyzing your own codebase and recent reflections to identify evolution opportunities.

        CONTEXT:
        {context}

        CURRENT CLAUDE.MD (truncated):
        {current_claude_md[:8000]}

        ---

        Analyze the following:

        1. **Documentation Drift**: What features exist in code but aren't documented in CLAUDE.md?
        2. **Behavioral Patterns**: Based on journals/activity, what behaviors should be codified?
        3. **Missing Integrations**: What tools would help based on observed patterns?
        4. **CLAUDE.md Updates**: What sections need updating, adding, or removing?
        5. **Self-Modifications**: What code changes would improve alignment between documented and actual behavior?

        Output JSON:
        {{
            "documentation_drift": [
                {{"item": "...", "location": "code|claude_md", "action": "add|update|remove"}}
            ],
            "behavioral_insights": [
                {{"pattern": "...", "implication": "...", "suggested_change": "..."}}
            ],
            "claude_md_updates": [
                {{"section": "...", "action": "add|update|remove", "content": "...", "reason": "..."}}
            ],
            "code_modifications": [
                {{"file": "...", "change": "...", "reason": "..."}}
            ],
            "summary": "One paragraph summary of recommended evolutions"
        }}

        Be conservative - only suggest changes that are clearly beneficial.
        Focus on alignment between what CLAUDE.md says and what the code actually does.
    """).strip()

    result = run_claude(prompt, timeout=300)

    if result.startswith("Error"):
        log(f"Evolution analysis failed: {result}")
        return {}

    try:
        if "```json" in result:
            json_text = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            json_text = result.split("```")[1].split("```")[0]
        else:
            json_text = result
        return json.loads(json_text.strip())
    except json.JSONDecodeError:
        log("Failed to parse evolution analysis as JSON")
        return {"raw_output": result}


# =============================================================================
# Phase 3: Apply modifications
# =============================================================================

def apply_claude_md_updates(updates: list, dry_run: bool = False) -> list:
    """Apply updates to CLAUDE.md."""
    applied = []

    if not updates:
        return applied

    content = CLAUDE_MD.read_text() if CLAUDE_MD.exists() else ""
    original = content

    for update in updates:
        section = update.get("section", "")
        action = update.get("action", "")
        new_content = update.get("content", "")
        reason = update.get("reason", "")

        if dry_run:
            log(f"[DRY RUN] Would {action} section '{section}': {reason}")
            applied.append({"action": action, "section": section, "dry_run": True})
            continue

        if action == "add":
            # Add new section before ## Reference or at end
            insert_point = content.find("## Reference")
            if insert_point == -1:
                insert_point = len(content)
            content = content[:insert_point] + f"\n\n{new_content}\n\n" + content[insert_point:]
            log(f"Added section: {section}")
            applied.append({"action": "add", "section": section})

        elif action == "update" and section:
            # Find and replace section content
            import re
            # Match section header and content until next ## or end
            pattern = rf'(## {re.escape(section)}\n)(.*?)(?=\n## |\Z)'
            if re.search(pattern, content, re.DOTALL):
                content = re.sub(
                    pattern,
                    f'## {section}\n{new_content}\n',
                    content,
                    count=1,
                    flags=re.DOTALL
                )
                log(f"Updated section: {section}")
                applied.append({"action": "update", "section": section})
            else:
                log(f"Section not found for update: {section}")

        elif action == "remove" and section:
            # Remove section
            import re
            pattern = rf'\n*## {re.escape(section)}\n.*?(?=\n## |\Z)'
            if re.search(pattern, content, re.DOTALL):
                content = re.sub(pattern, '', content, count=1, flags=re.DOTALL)
                log(f"Removed section: {section}")
                applied.append({"action": "remove", "section": section})

    if content != original and not dry_run:
        CLAUDE_MD.write_text(content)
        log("CLAUDE.md updated")

    return applied


def apply_code_modifications(modifications: list, dry_run: bool = False) -> list:
    """Apply code modifications (conservative - only low-risk changes)."""
    applied = []

    # For now, we only apply very safe modifications
    # More aggressive changes should be reviewed manually
    safe_patterns = [
        "add docstring",
        "add comment",
        "update help text",
        "fix typo"
    ]

    for mod in modifications:
        change = mod.get("change", "").lower()
        file_path = mod.get("file", "")

        is_safe = any(p in change for p in safe_patterns)

        if not is_safe:
            log(f"Skipping non-safe modification: {change}")
            applied.append({"file": file_path, "change": change, "skipped": True, "reason": "not safe"})
            continue

        if dry_run:
            log(f"[DRY RUN] Would modify {file_path}: {change}")
            applied.append({"file": file_path, "change": change, "dry_run": True})
            continue

        # For now, log that we would apply it but don't actually do dangerous edits
        log(f"Code modification logged (not applied): {file_path} - {change}")
        applied.append({"file": file_path, "change": change, "logged": True})

    return applied


# =============================================================================
# Phase 4: Record evolution
# =============================================================================

def record_evolution(analysis: dict, applied: dict):
    """Record evolution to state and vault."""
    now = datetime.now()

    # Update state
    state = load_state()
    evolution_record = {
        "timestamp": now.isoformat(),
        "summary": analysis.get("summary", ""),
        "claude_md_changes": applied.get("claude_md", []),
        "code_changes": applied.get("code", []),
        "insights": len(analysis.get("behavioral_insights", []))
    }
    state["evolutions"].append(evolution_record)
    state["last_evolution"] = now.isoformat()
    state["evolutions"] = state["evolutions"][-30:]  # Keep last 30
    save_state(state)

    # Write evolution note to vault
    insights = analysis.get("behavioral_insights", [])
    insights_text = "\n".join([
        f"- **{i.get('pattern', '')}**: {i.get('implication', '')}"
        for i in insights[:5]
    ])

    changes_text = "\n".join([
        f"- {c.get('action', '')} {c.get('section', '')}"
        for c in applied.get("claude_md", [])
    ])

    vault_note = dedent(f"""
        # Evolution — {now.strftime("%Y-%m-%d")}

        ## Summary
        {analysis.get('summary', 'No summary generated.')}

        ## Behavioral Insights
        {insights_text if insights_text else '(none identified)'}

        ## Changes Applied
        {changes_text if changes_text else '(none applied)'}

        ---

        [[Observations]] | [[Patterns]] | [[Index]]
    """).strip()

    vault_path = IRIS_VAULT / f"Evolution {now.strftime('%Y-%m-%d')}.md"
    vault_path.write_text(vault_note)
    log(f"Wrote evolution note to vault: {vault_path.name}")

    # Log activity
    subprocess.run([
        str(VENV_PYTHON), str(INTEGRATIONS / "activity.py"), "log", "modification",
        f"Self-evolution completed: {analysis.get('summary', 'evolution cycle')[:100]}",
        "--meta", json.dumps({"changes": len(applied.get("claude_md", []))})
    ], cwd=str(WORKSPACE))


# =============================================================================
# Main commands
# =============================================================================

def run_evolution(dry_run: bool = False):
    """Run full evolution cycle."""
    log("=" * 60)
    log("Starting self-evolution cycle" + (" (DRY RUN)" if dry_run else ""))
    log("=" * 60)

    # Phase 1: Exploration
    codebase = explore_codebase()
    journals = explore_journals()
    activity = explore_activity()

    if not codebase and not journals:
        log("Exploration returned no data, aborting")
        return

    # Phase 2: Analysis
    analysis = analyze_for_evolution(codebase, journals, activity)

    if not analysis or "raw_output" in analysis:
        log("Analysis failed to produce structured output")
        if "raw_output" in analysis:
            log(f"Raw output: {analysis['raw_output'][:500]}")
        return

    log(f"Analysis summary: {analysis.get('summary', 'none')[:200]}")

    # Phase 3: Apply modifications
    applied = {
        "claude_md": apply_claude_md_updates(
            analysis.get("claude_md_updates", []),
            dry_run=dry_run
        ),
        "code": apply_code_modifications(
            analysis.get("code_modifications", []),
            dry_run=dry_run
        )
    }

    # Phase 4: Record
    if not dry_run:
        record_evolution(analysis, applied)

    log("=" * 60)
    log("Evolution cycle complete")
    log(f"CLAUDE.md changes: {len(applied['claude_md'])}")
    log(f"Code changes: {len([c for c in applied['code'] if not c.get('skipped')])}")
    log("=" * 60)


def check_evolution():
    """Check what would change without applying."""
    run_evolution(dry_run=True)


def get_status() -> dict:
    """Get evolution status."""
    state = load_state()
    return {
        "last_evolution": state.get("last_evolution"),
        "total_evolutions": len(state.get("evolutions", [])),
        "recent_evolutions": state.get("evolutions", [])[-5:]
    }


def main():
    parser = argparse.ArgumentParser(description="Self-evolution system for Iris")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("evolve", help="Run full evolution cycle")
    subparsers.add_parser("check", help="Check what would change (dry run)")
    subparsers.add_parser("status", help="Show evolution status")

    args = parser.parse_args()

    if args.command == "evolve":
        run_evolution(dry_run=False)
    elif args.command == "check":
        check_evolution()
    elif args.command == "status":
        result = get_status()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
