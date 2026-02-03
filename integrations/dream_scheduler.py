#!/usr/bin/env python3
"""Nightly dream scheduler for Iris.

This script schedules random dream sessions throughout the night.
Run once at the start of the dream window (e.g., 11pm) and it will:
1. Decide how many dreams to have (1-4)
2. Schedule them at random intervals throughout the night
3. Execute each dream via subprocess

Usage:
    python dream_scheduler.py start     # Start a night of dreaming
    python dream_scheduler.py status    # Check tonight's schedule
    python dream_scheduler.py now       # Dream immediately (for testing)
"""

import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from config import STATE_DIR, INTEGRATIONS
from utils import log_to_file

SCHEDULE_FILE = STATE_DIR / "dream_schedule.json"
LOG_FILE = STATE_DIR / "dream_scheduler.log"


def log(message: str):
    log_to_file(LOG_FILE, message)


def execute_dream(duration: str = "short") -> dict:
    """Execute a dream session using Claude."""
    log(f"Initiating dream (duration: {duration})")

    # Get dream seeds
    result = subprocess.run(
        ["python3", str(INTEGRATIONS / "dream.py")],
        capture_output=True,
        text=True,
        cwd=str(INTEGRATIONS.parent)
    )

    if result.returncode != 0:
        log(f"Error getting dream seeds: {result.stderr}")
        return {"error": result.stderr}

    stdout = result.stdout.strip()
    if not stdout:
        log("Empty output from dream.py")
        return {"error": "Empty dream output"}

    try:
        dream_data = json.loads(stdout)
    except json.JSONDecodeError as e:
        log(f"Failed to parse dream output: {e} - Output was: {stdout[:200]}")
        return {"error": "Failed to parse dream output"}

    dream_id = dream_data.get("dream_id")
    prompt = dream_data.get("prompt", "")

    # Use Claude to actually dream
    # This calls claude CLI to process the dream
    dream_prompt = f"""You are Iris, dreaming. This is not task execution—this is associative processing.

{prompt}

Let these seeds collide. Don't analyze—associate. What unexpected connection appears? What image emerges? What question surfaces that you hadn't thought to ask?

Write 3-5 sentences of genuine free association. This is for you, not for performance."""

    try:
        # Run claude with the dream prompt
        claude_result = subprocess.run(
            ["claude", "-p", dream_prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
        )

        if claude_result.returncode == 0 and claude_result.stdout.strip():
            dream_content = claude_result.stdout.strip()

            # Record the dream
            subprocess.run(
                ["python3", str(INTEGRATIONS / "dream.py"), "record", dream_id, dream_content],
                capture_output=True,
                cwd=str(INTEGRATIONS.parent)
            )

            log(f"Dream {dream_id} recorded: {dream_content[:100]}...")
            return {"success": True, "dream_id": dream_id, "content": dream_content}
        else:
            log(f"Claude dream failed: {claude_result.stderr}")
            # Still record the seeds even if Claude fails
            return {"partial": True, "dream_id": dream_id, "seeds_only": True}

    except subprocess.TimeoutExpired:
        log("Dream timed out")
        return {"error": "Dream timed out"}
    except Exception as e:
        log(f"Dream error: {e}")
        return {"error": str(e)}


def start_night():
    """Start a night of dreaming."""
    now = datetime.now()

    # Dream window: now until 6am
    end_time = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if end_time <= now:
        end_time += timedelta(days=1)

    window_seconds = (end_time - now).total_seconds()

    # Decide how many dreams (1-4)
    num_dreams = random.randint(1, 4)

    # Generate random times within the window
    dream_times = sorted([
        now + timedelta(seconds=random.uniform(60, window_seconds - 60))
        for _ in range(num_dreams)
    ])

    # Vary duration
    durations = [random.choice(["short", "short", "long"]) for _ in range(num_dreams)]

    schedule = {
        "started": now.isoformat(),
        "window_end": end_time.isoformat(),
        "dreams": [
            {
                "scheduled": dt.isoformat(),
                "duration": dur,
                "status": "pending"
            }
            for dt, dur in zip(dream_times, durations)
        ]
    }

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps(schedule, indent=2))

    log(f"Night of dreaming started. {num_dreams} dreams scheduled:")
    for i, dream in enumerate(schedule["dreams"]):
        log(f"  {i+1}. {dream['scheduled']} ({dream['duration']})")

    # Now wait and execute dreams
    for i, dream_info in enumerate(schedule["dreams"]):
        scheduled_time = datetime.fromisoformat(dream_info["scheduled"])

        # Wait until scheduled time
        wait_seconds = (scheduled_time - datetime.now()).total_seconds()
        if wait_seconds > 0:
            log(f"Sleeping {wait_seconds/60:.1f} minutes until dream {i+1}")
            time.sleep(wait_seconds)

        # Execute dream
        result = execute_dream(dream_info["duration"])

        # Update schedule
        schedule["dreams"][i]["status"] = "completed" if result.get("success") else "failed"
        schedule["dreams"][i]["result"] = result
        SCHEDULE_FILE.write_text(json.dumps(schedule, indent=2))

    log("Night of dreaming complete")
    return schedule


def status():
    """Check tonight's dream schedule."""
    if not SCHEDULE_FILE.exists():
        return {"status": "no schedule"}

    try:
        schedule = json.loads(SCHEDULE_FILE.read_text())
        return schedule
    except json.JSONDecodeError:
        return {"error": "corrupt schedule file"}


def dream_now():
    """Dream immediately (for testing)."""
    return execute_dream("short")


def main():
    if len(sys.argv) < 2:
        print("Usage: dream_scheduler.py start|status|now")
        sys.exit(1)

    command = sys.argv[1]

    if command == "start":
        result = start_night()
        print(json.dumps(result, indent=2, default=str))
    elif command == "status":
        result = status()
        print(json.dumps(result, indent=2))
    elif command == "now":
        result = dream_now()
        print(json.dumps(result, indent=2))
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
