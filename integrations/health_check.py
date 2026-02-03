#!/usr/bin/env python3
"""
Self-healing health check for Iris system.
Runs periodically, fixes what it can, alerts only when intervention needed.
"""

import argparse
import asyncio
import json
import os
import pwd
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Paths
STATE_DIR = Path("/home/iris/executive-assistant/workspace/state")
HEALTH_STATE = STATE_DIR / "health_state.json"
DM_QUEUE = STATE_DIR / "dm_queue.json"
RESPONSE_STATS = STATE_DIR / "response_stats.json"

# Critical paths that must be owned by iris
CRITICAL_PATHS = [
    Path("/home/iris/.claude.json"),
    Path("/home/iris/.claude/.credentials.json"),
    Path("/home/iris/.claude/stats-cache.json"),
    STATE_DIR,
]

# Samuel's Discord ID
SAMUEL_ID = "672500045249249328"


def log(msg: str):
    """Print timestamped log message."""
    print(f"[{datetime.now().isoformat()}] {msg}")


def get_iris_uid_gid():
    """Get iris user's UID and GID."""
    try:
        pw = pwd.getpwnam("iris")
        return pw.pw_uid, pw.pw_gid
    except KeyError:
        return None, None


def check_file_ownership(path: Path) -> tuple[bool, str]:
    """Check if file is owned by iris. Returns (ok, message)."""
    if not path.exists():
        return True, f"{path} doesn't exist (ok)"

    stat = path.stat()
    iris_uid, iris_gid = get_iris_uid_gid()

    if iris_uid is None:
        return False, "Could not find iris user"

    if stat.st_uid != iris_uid:
        return False, f"{path} owned by uid {stat.st_uid}, not iris ({iris_uid})"

    return True, f"{path} ownership ok"


def fix_file_ownership(path: Path) -> tuple[bool, str]:
    """Fix file ownership to iris:iris. Returns (success, message)."""
    iris_uid, iris_gid = get_iris_uid_gid()
    if iris_uid is None:
        return False, "Could not find iris user"

    try:
        os.chown(path, iris_uid, iris_gid)
        return True, f"Fixed ownership of {path}"
    except PermissionError:
        return False, f"Permission denied fixing {path} - need root"
    except Exception as e:
        return False, f"Error fixing {path}: {e}"


def check_bot_running() -> tuple[bool, str]:
    """Check if bot process is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python.*bot.py"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            return True, f"Bot running (PID: {pids[0]})"
        return False, "Bot not running"
    except Exception as e:
        return False, f"Error checking bot: {e}"


def check_response_stats() -> tuple[bool, str]:
    """Check recent response success rate."""
    if not RESPONSE_STATS.exists():
        return True, "No response stats yet"

    try:
        stats = json.loads(RESPONSE_STATS.read_text())
        recent = stats.get("recent", [])

        if len(recent) < 3:
            return True, f"Too few responses to analyze ({len(recent)})"

        # Check last 10 responses
        last_n = recent[-10:]
        failures = sum(1 for r in last_n if not r.get("success", True))

        if failures >= 5:
            errors = [r.get("error", "unknown") for r in last_n if not r.get("success")]
            return False, f"High failure rate: {failures}/{len(last_n)} recent responses failed. Errors: {errors[:3]}"

        return True, f"Response stats ok ({failures}/{len(last_n)} recent failures)"

    except Exception as e:
        return True, f"Could not check stats: {e}"


def check_claude_cli() -> tuple[bool, str]:
    """Test that Claude CLI responds."""
    try:
        # Run as iris user
        result = subprocess.run(
            ["su", "-", "iris", "-c",
             "timeout 30 claude --print --output-format text -p 'respond with just the word: working'"],
            capture_output=True,
            text=True,
            timeout=35
        )

        output = result.stdout.strip().lower()
        if "working" in output:
            return True, "Claude CLI responding"

        # Check stderr for specific errors
        if "permission denied" in result.stderr.lower():
            return False, f"Claude CLI permission error: {result.stderr[:100]}"
        if result.stderr:
            return False, f"Claude CLI error: {result.stderr[:100]}"

        return False, f"Claude CLI unexpected response: {output[:100]}"

    except subprocess.TimeoutExpired:
        return False, "Claude CLI timed out"
    except Exception as e:
        return False, f"Claude CLI check failed: {e}"


def queue_dm(message: str):
    """Queue a DM to Samuel."""
    queue = []
    if DM_QUEUE.exists():
        try:
            queue = json.loads(DM_QUEUE.read_text())
        except:
            queue = []

    queue.append({
        "user_id": SAMUEL_ID,
        "message": message,
        "timestamp": datetime.now().isoformat()
    })

    DM_QUEUE.write_text(json.dumps(queue, indent=2))
    log(f"Queued DM: {message[:50]}...")


def load_health_state() -> dict:
    """Load previous health state."""
    if HEALTH_STATE.exists():
        try:
            return json.loads(HEALTH_STATE.read_text())
        except:
            pass
    return {"last_check": None, "issues": [], "alerts_sent": {}}


def save_health_state(state: dict):
    """Save health state."""
    state["last_check"] = datetime.now().isoformat()
    HEALTH_STATE.write_text(json.dumps(state, indent=2))


def run_health_check(alert: bool = True, fix: bool = True) -> dict:
    """
    Run full health check.

    Args:
        alert: Whether to send DMs for unfixable issues
        fix: Whether to attempt automatic fixes

    Returns:
        Dict with check results
    """
    log("Starting health check...")
    state = load_health_state()
    results = {
        "timestamp": datetime.now().isoformat(),
        "checks": [],
        "fixed": [],
        "alerts": [],
        "all_ok": True
    }

    # Check file ownership
    for path in CRITICAL_PATHS:
        ok, msg = check_file_ownership(path)
        results["checks"].append({"check": f"ownership:{path}", "ok": ok, "message": msg})

        if not ok and fix:
            fixed, fix_msg = fix_file_ownership(path)
            if fixed:
                results["fixed"].append(fix_msg)
                log(f"AUTO-FIX: {fix_msg}")
            else:
                results["all_ok"] = False
                if alert:
                    # Only alert if we haven't recently
                    alert_key = f"ownership:{path}"
                    last_alert = state.get("alerts_sent", {}).get(alert_key)
                    if not last_alert or (datetime.now() - datetime.fromisoformat(last_alert)).total_seconds() > 3600:
                        queue_dm(f"Health check: {fix_msg}")
                        results["alerts"].append(fix_msg)
                        state.setdefault("alerts_sent", {})[alert_key] = datetime.now().isoformat()

    # Check bot running
    ok, msg = check_bot_running()
    results["checks"].append({"check": "bot_running", "ok": ok, "message": msg})
    if not ok:
        results["all_ok"] = False
        if alert:
            alert_key = "bot_running"
            last_alert = state.get("alerts_sent", {}).get(alert_key)
            if not last_alert or (datetime.now() - datetime.fromisoformat(last_alert)).total_seconds() > 1800:
                queue_dm(f"Health check: Bot not running")
                results["alerts"].append("Bot not running")
                state.setdefault("alerts_sent", {})[alert_key] = datetime.now().isoformat()

    # Check Claude CLI (only if ownership checks passed)
    ownership_ok = all(c["ok"] for c in results["checks"] if c["check"].startswith("ownership:"))
    if ownership_ok:
        ok, msg = check_claude_cli()
        results["checks"].append({"check": "claude_cli", "ok": ok, "message": msg})
        if not ok:
            results["all_ok"] = False
            if alert:
                alert_key = "claude_cli"
                last_alert = state.get("alerts_sent", {}).get(alert_key)
                if not last_alert or (datetime.now() - datetime.fromisoformat(last_alert)).total_seconds() > 1800:
                    queue_dm(f"Health check: {msg}")
                    results["alerts"].append(msg)
                    state.setdefault("alerts_sent", {})[alert_key] = datetime.now().isoformat()
    else:
        results["checks"].append({"check": "claude_cli", "ok": False, "message": "Skipped - ownership issues"})

    # Check response stats
    ok, msg = check_response_stats()
    results["checks"].append({"check": "response_stats", "ok": ok, "message": msg})
    if not ok:
        results["all_ok"] = False
        if alert:
            alert_key = "response_stats"
            last_alert = state.get("alerts_sent", {}).get(alert_key)
            if not last_alert or (datetime.now() - datetime.fromisoformat(last_alert)).total_seconds() > 1800:
                queue_dm(f"Health check: {msg}")
                results["alerts"].append(msg)
                state.setdefault("alerts_sent", {})[alert_key] = datetime.now().isoformat()

    # Clear old alerts for issues that are now resolved
    for check in results["checks"]:
        if check["ok"]:
            alert_key = check["check"]
            if alert_key in state.get("alerts_sent", {}):
                del state["alerts_sent"][alert_key]

    save_health_state(state)

    # Summary
    if results["all_ok"]:
        log("Health check passed - all systems operational")
    else:
        log(f"Health check found issues: {len([c for c in results['checks'] if not c['ok']])} problems")
        if results["fixed"]:
            log(f"Auto-fixed: {len(results['fixed'])} issues")
        if results["alerts"]:
            log(f"Alerts sent: {len(results['alerts'])}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Iris health check")
    parser.add_argument("command", choices=["check", "status"],
                       help="check = run health check, status = show last state")
    parser.add_argument("--no-alert", action="store_true",
                       help="Don't send DMs for issues")
    parser.add_argument("--no-fix", action="store_true",
                       help="Don't attempt automatic fixes")
    parser.add_argument("--json", action="store_true",
                       help="Output as JSON")

    args = parser.parse_args()

    if args.command == "status":
        state = load_health_state()
        if args.json:
            print(json.dumps(state, indent=2))
        else:
            print(f"Last check: {state.get('last_check', 'never')}")
            if state.get("alerts_sent"):
                print(f"Active alerts: {list(state['alerts_sent'].keys())}")
            else:
                print("No active alerts")
        return

    results = run_health_check(
        alert=not args.no_alert,
        fix=not args.no_fix
    )

    if args.json:
        print(json.dumps(results, indent=2))

    # Exit code reflects health
    sys.exit(0 if results["all_ok"] else 1)


if __name__ == "__main__":
    main()
