#!/usr/bin/env python3
"""Self-documenter for Iris - keeps CLAUDE.md in sync with actual codebase.

Scans integrations, state files, and cron jobs to detect drift from documentation.
Can run in check-only mode or auto-update mode.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from config import PROJECT_ROOT, CLAUDE_MD, INTEGRATIONS, STATE_DIR, VENV_PYTHON

def log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def get_integration_info() -> dict:
    """Get info about all integration scripts."""
    integrations = {}

    for py_file in sorted(INTEGRATIONS.glob("*.py")):
        if py_file.name == "__init__.py":
            continue

        name = py_file.stem
        info = {"file": py_file.name, "commands": [], "description": ""}

        # Try to get --help output
        try:
            result = subprocess.run(
                [str(VENV_PYTHON), str(py_file), "--help"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                help_text = result.stdout
                # Extract first line as description
                lines = help_text.strip().split("\n")
                if lines:
                    info["description"] = lines[0][:100]

                # Extract subcommands if present
                if "Commands:" in help_text or "positional arguments:" in help_text:
                    # Look for command patterns
                    commands = re.findall(r'^\s+(\w+)\s+', help_text, re.MULTILINE)
                    info["commands"] = [c for c in commands if c not in ["help", "options"]]
        except (subprocess.TimeoutExpired, Exception) as e:
            # Read file directly for docstring
            try:
                content = py_file.read_text()
                match = re.search(r'"""([^"]+)"""', content)
                if match:
                    info["description"] = match.group(1).split("\n")[0][:100]
            except:
                pass

        integrations[name] = info

    return integrations

def get_state_files() -> list:
    """Get list of state files."""
    state_files = []
    if STATE_DIR.exists():
        for f in sorted(STATE_DIR.glob("*.json")):
            state_files.append(f.name)
        for f in sorted(STATE_DIR.glob("*.jsonl")):
            state_files.append(f.name)
    return state_files

def get_crontab() -> str:
    """Get current crontab."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else ""
    except:
        return ""

def parse_claude_md() -> dict:
    """Parse CLAUDE.md to extract documented items."""
    if not CLAUDE_MD.exists():
        return {}

    content = CLAUDE_MD.read_text()

    parsed = {
        "integrations_mentioned": set(),
        "state_files_mentioned": set(),
        "users_documented": set(),
    }

    # Find mentioned integration scripts
    for match in re.finditer(r'(\w+)\.py', content):
        parsed["integrations_mentioned"].add(match.group(1))

    # Find mentioned state files
    for match in re.finditer(r'`([^`]+\.json[l]?)`', content):
        parsed["state_files_mentioned"].add(match.group(1))

    # Find documented users
    for match in re.finditer(r'\|\s*(\w+)\s*\|\s*(\d+)\s*\|', content):
        parsed["users_documented"].add(match.group(1).lower())

    return parsed

def check_drift() -> dict:
    """Check for drift between CLAUDE.md and actual state."""
    integrations = get_integration_info()
    state_files = get_state_files()
    crontab = get_crontab()
    documented = parse_claude_md()

    drift = {
        "missing_integrations": [],
        "extra_integrations": [],
        "missing_state_files": [],
        "cron_changes": False,
        "details": []
    }

    # Check integrations
    actual_integrations = set(integrations.keys())
    documented_integrations = documented.get("integrations_mentioned", set())

    missing = actual_integrations - documented_integrations

    # Filter out common false positives
    missing = {m for m in missing if m not in ["__init__"]}

    # Only flag "extra" if the .py file was explicitly documented in integrations context
    # (bot, claude_client, context_builder are runtime files, not integrations)
    extra = set()  # Don't flag documented-but-missing, too many false positives

    if missing:
        drift["missing_integrations"] = list(missing)
        drift["details"].append(f"Undocumented integrations: {', '.join(missing)}")

    if extra:
        drift["extra_integrations"] = list(extra)
        drift["details"].append(f"Documented but missing: {', '.join(extra)}")

    # Check state files (just the important ones)
    important_state = ["permissions.json", "dm_queue.json", "channel_message_queue.json",
                       "activity.json", "reminders.json", "research_threads.json"]
    documented_state = documented.get("state_files_mentioned", set())

    for sf in important_state:
        if sf in state_files and sf not in documented_state:
            drift["missing_state_files"].append(sf)

    if drift["missing_state_files"]:
        drift["details"].append(f"Undocumented state files: {', '.join(drift['missing_state_files'])}")

    return drift

def run_claude_update(drift: dict, claude_md_content: str) -> str:
    """Use Claude to generate updated CLAUDE.md sections."""

    integrations = get_integration_info()

    # Build context about what needs updating
    context_parts = []

    if drift["missing_integrations"]:
        for name in drift["missing_integrations"]:
            info = integrations.get(name, {})
            context_parts.append(f"- {name}.py: {info.get('description', 'No description')}")
            if info.get("commands"):
                context_parts.append(f"  Commands: {', '.join(info['commands'])}")

    if not context_parts:
        return None

    prompt = f"""You are Iris updating your own CLAUDE.md documentation.

DRIFT DETECTED:
{chr(10).join(drift['details'])}

NEW INTEGRATIONS TO DOCUMENT:
{chr(10).join(context_parts)}

CURRENT CLAUDE.MD (relevant sections):
{claude_md_content[claude_md_content.find('## Subagents'):claude_md_content.find('## Cron Schedule')] if '## Subagents' in claude_md_content else ''}

Generate the specific text edits needed. Return JSON:
{{
    "edits": [
        {{"section": "section name", "action": "add_row|add_section|update", "content": "exact markdown to add/update"}}
    ],
    "summary": "one sentence describing changes"
}}

Only suggest changes for genuinely missing items. Be conservative."""

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "PATH": "/home/iris/.local/bin:" + os.environ.get("PATH", "")}
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception as e:
        log(f"Claude call failed: {e}")
        return None

def apply_updates(updates_json: str, dry_run: bool = False) -> bool:
    """Apply updates to CLAUDE.md."""
    try:
        # Extract JSON from response
        json_text = updates_json
        if "```json" in updates_json:
            json_text = updates_json.split("```json")[1].split("```")[0]
        elif "```" in updates_json:
            json_text = updates_json.split("```")[1].split("```")[0]

        updates = json.loads(json_text.strip())

        if not updates.get("edits"):
            log("No edits to apply")
            return False

        log(f"Update summary: {updates.get('summary', 'No summary')}")

        if dry_run:
            log("DRY RUN - would apply:")
            for edit in updates["edits"]:
                log(f"  {edit['action']} in {edit['section']}: {edit['content'][:50]}...")
            return True

        # Read current content
        content = CLAUDE_MD.read_text()

        # Apply each edit
        for edit in updates["edits"]:
            action = edit.get("action")
            section = edit.get("section", "")
            new_content = edit.get("content", "")

            if action == "add_row" and section:
                # Find the table in the section and add a row
                section_pattern = rf'(## {re.escape(section)}.*?\n\|[^\n]+\|\n\|[-| ]+\|)'
                match = re.search(section_pattern, content, re.DOTALL)
                if match:
                    # Find end of table (next section or double newline)
                    table_end = content.find("\n\n", match.end())
                    if table_end == -1:
                        table_end = len(content)
                    # Insert before table end
                    content = content[:table_end] + "\n" + new_content + content[table_end:]
                    log(f"Added row to {section}")

            elif action == "add_section":
                # Add a new section before "## Reference" or at end
                insert_point = content.find("## Reference")
                if insert_point == -1:
                    insert_point = len(content)
                content = content[:insert_point] + new_content + "\n\n" + content[insert_point:]
                log(f"Added section: {section}")

        # Write back
        CLAUDE_MD.write_text(content)
        log("CLAUDE.md updated")

        # Log the activity
        subprocess.run([
            str(VENV_PYTHON), str(INTEGRATIONS / "activity.py"), "log", "modification",
            f"Self-documenter updated CLAUDE.md: {updates.get('summary', 'documentation sync')}",
            "--meta", json.dumps({"edits": len(updates["edits"])})
        ], cwd=str(PROJECT_ROOT / "workspace"))

        return True

    except (json.JSONDecodeError, KeyError) as e:
        log(f"Failed to parse updates: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Self-documenter for CLAUDE.md")
    parser.add_argument("command", choices=["check", "update", "full-update"],
                       help="check=report drift, update=auto-fix drift, full-update=comprehensive review")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without applying")
    args = parser.parse_args()

    log(f"Running self-documenter: {args.command}")

    # Check for drift
    drift = check_drift()

    if args.command == "check":
        if drift["details"]:
            log("Drift detected:")
            for detail in drift["details"]:
                log(f"  - {detail}")
            sys.exit(1)
        else:
            log("No drift detected")
            sys.exit(0)

    elif args.command in ["update", "full-update"]:
        if not drift["details"] and args.command == "update":
            log("No drift to fix")
            sys.exit(0)

        content = CLAUDE_MD.read_text() if CLAUDE_MD.exists() else ""

        updates = run_claude_update(drift, content)
        if updates:
            success = apply_updates(updates, dry_run=args.dry_run)
            sys.exit(0 if success else 1)
        else:
            log("No updates generated")
            sys.exit(0)

if __name__ == "__main__":
    main()
