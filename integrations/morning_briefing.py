#!/usr/bin/env python3
"""Morning briefing system for Iris.

Gathers news, calendar events, action items, and tracked tasks,
then sends a structured DM to Samuel with suggestions and asks about plans.

Usage:
    python morning_briefing.py brief              # Send morning briefing DM
    python morning_briefing.py preview            # Preview without sending
    python morning_briefing.py log_plan "<plan>"  # Log Samuel's stated plan
    python morning_briefing.py check_in           # Afternoon check-in
    python morning_briefing.py status             # Show today's plan and status
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Load environment (inline .env parsing to avoid dotenv dependency)
def _load_env(path):
    """Load .env file into os.environ."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            os.environ.setdefault(key, value)

_load_env(Path(__file__).parent.parent / ".env")

from config import (
    WORKSPACE, STATE_DIR, INTEGRATIONS, VENV_PYTHON,
    TIMEZONE, SAMUEL_ID, now_local
)

STATE_FILE = STATE_DIR / "morning_briefing.json"
CLAUDE_PATH = "/home/iris/.local/bin/claude"

# Samuel's interests for news filtering
INTERESTS = [
    "AI safety",
    "AI alignment",
    "interpretability",
    "tools for thought",
    "prediction markets",
    "technology policy",
    "philosophy of mind",
    "autonomous systems",
    "British politics",
    "global politics",
    "UK news",
    "international affairs",
]


def load_state() -> dict:
    """Load briefing state."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {
        "today_plan": None,
        "plan_logged_at": None,
        "last_briefing": None,
        "last_check_in": None,
        "briefing_history": [],
    }


def save_state(state: dict):
    """Save briefing state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def run_integration(script: str, *args, timeout: int = 30) -> tuple[bool, str]:
    """Run an integration script and return (success, output)."""
    script_path = INTEGRATIONS / script
    if not script_path.exists():
        return False, f"Script not found: {script}"

    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(script_path), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKSPACE)
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def gather_calendar() -> str:
    """Get today's calendar events."""
    success, output = run_integration("google_calendar.py", "list", "1")
    if success and output:
        try:
            data = json.loads(output)
            events = data.get("events", [])
            if not events:
                return "No events scheduled"

            lines = []
            for event in events:
                title = event.get("title", "Untitled")
                start = event.get("start", "")

                # Format time nicely
                if "T" in start:
                    # Has time component
                    from datetime import datetime as dt
                    try:
                        # Parse ISO format with timezone
                        time_str = start.split("T")[1][:5]  # Get HH:MM
                        lines.append(f"• **{title}** at {time_str}")
                    except:
                        lines.append(f"• **{title}**")
                else:
                    # All-day event
                    lines.append(f"• **{title}** (all day)")

                if event.get("description"):
                    desc = event["description"][:100]
                    lines.append(f"  ↳ {desc}")

            return "\n".join(lines)
        except json.JSONDecodeError:
            return output  # Return raw if not JSON
    return "Could not load calendar"


def gather_email_action_items() -> list:
    """Get action items from recent emails using screener."""
    # Get screened email list
    success, output = run_integration("email_screener.py", "screen_list", "15")
    if not success:
        return []

    try:
        data = json.loads(output)
        action_items = []

        for email in data.get("emails", []):
            # Look for emails that seem to need action
            # (Fabric/Pair admissions type things)
            subject = email.get("subject", "").lower()
            snippet = email.get("snippet_preview", "").lower()

            action_keywords = [
                "deadline", "due", "expires", "respond by", "action required",
                "application", "admission", "confirm", "rsvp", "register",
                "apply", "submit", "reminder", "don't forget", "last chance"
            ]

            if any(kw in subject or kw in snippet for kw in action_keywords):
                action_items.append({
                    "source": "email",
                    "from": email.get("from"),
                    "subject": email.get("subject"),
                    "snippet": email.get("snippet_preview"),
                    "id": email.get("id")
                })

        return action_items[:5]  # Limit to 5
    except:
        return []


def gather_tasks() -> dict:
    """Get tracked tasks and todoist items."""
    result = {"tracked": [], "todoist": []}

    # Tracked commitments
    success, output = run_integration("tasks.py", "check", "--json")
    if success and output:
        try:
            data = json.loads(output)
            result["tracked"] = data
        except:
            pass

    # Todoist
    success, output = run_integration("todoist.py", "list")
    if success and output:
        result["todoist"] = output

    return result


def gather_reminders() -> list:
    """Get active reminders."""
    success, output = run_integration("reminders.py", "list", SAMUEL_ID)
    if success and output:
        try:
            reminders = json.loads(output)
            return reminders if isinstance(reminders, list) else []
        except:
            return []
    return []


async def fetch_news() -> list:
    """Use Claude to fetch relevant news.

    Note: This uses Haiku which doesn't have web search built-in.
    Returns an empty list if news fetching isn't available.
    The main model (when running briefing) can use WebSearch instead.
    """
    # For now, return empty - news will be gathered by main model when reviewing
    # This is more reliable than having Haiku try to search
    return []

    # Original implementation kept for reference:
    # Build search query from interests
    query = " OR ".join(f'"{i}"' for i in INTERESTS[:4])
    date_str = now_local().strftime("%Y-%m-%d")

    prompt = f"""Search for the most important news from the last 24 hours related to: {', '.join(INTERESTS)}.

Focus on:
- AI safety/alignment developments
- New AI models or capabilities
- Prediction market notable movements
- Philosophy/tech policy intersections

Today is {date_str}.

Return a JSON array of 3-5 news items, each with:
- "headline": Brief headline
- "source": Publication name
- "relevance": Why this matters
- "url": Link if available

JSON only:"""

    cmd = [
        CLAUDE_PATH,
        "--print",
        "--output-format", "text",
        "--model", "haiku",
        "-p", prompt,
    ]

    try:
        env = os.environ.copy()
        env["PATH"] = "/home/iris/.local/bin:" + env.get("PATH", "")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(WORKSPACE),
            env=env,
        )

        stdout, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=60,
        )

        result_text = stdout.decode().strip()

        # Parse JSON
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        return json.loads(result_text.strip())
    except Exception as e:
        return [{"error": str(e)}]


async def generate_briefing(preview: bool = False) -> str:
    """Generate the morning briefing message."""
    state = load_state()
    today = now_local().strftime("%A, %B %d")

    # Gather all data
    calendar = gather_calendar()
    email_actions = gather_email_action_items()
    tasks = gather_tasks()
    reminders = gather_reminders()

    # Fetch news (async)
    news = await fetch_news()

    # Build message
    msg_parts = [f"**Good morning, Samuel** ☀️\n*{today}*\n"]

    # Calendar
    msg_parts.append("## 📅 Today's Schedule")
    if calendar and calendar != "Could not load calendar":
        msg_parts.append(calendar)
    else:
        msg_parts.append("No calendar events today.")
    msg_parts.append("")

    # News
    if news and not (len(news) == 1 and "error" in news[0]):
        msg_parts.append("## 📰 News Worth Knowing")
        for item in news[:4]:
            if "headline" in item:
                msg_parts.append(f"• **{item['headline']}** ({item.get('source', 'unknown')})")
                if item.get('relevance'):
                    msg_parts.append(f"  ↳ {item['relevance']}")
        msg_parts.append("")

    # Action Items (from email)
    if email_actions:
        msg_parts.append("## 🎯 Action Items (from email)")
        for item in email_actions:
            msg_parts.append(f"• **{item['subject']}** (from {item['from']})")
            if item.get('snippet'):
                msg_parts.append(f"  ↳ {item['snippet'][:100]}...")
        msg_parts.append("")

    # Tasks
    tracked = tasks.get("tracked", {})
    if tracked.get("overdue") or tracked.get("due_today"):
        msg_parts.append("## ⚠️ Tasks Needing Attention")
        for task in tracked.get("overdue", []):
            msg_parts.append(f"• 🔴 OVERDUE: {task.get('content', task)}")
        for task in tracked.get("due_today", []):
            msg_parts.append(f"• 🟡 Due today: {task.get('content', task)}")
        msg_parts.append("")

    if tasks.get("todoist"):
        msg_parts.append("## ✅ Todoist")
        todoist_data = tasks["todoist"]
        try:
            data = json.loads(todoist_data)
            todoist_tasks = data.get("tasks", [])[:5]  # Limit to 5
            for t in todoist_tasks:
                content = t.get("content", "")
                due = t.get("due")
                if due:
                    msg_parts.append(f"• {content} (due: {due})")
                else:
                    msg_parts.append(f"• {content}")
        except json.JSONDecodeError:
            # If not JSON, just show first few lines
            lines = todoist_data.strip().split("\n")[:5]
            for line in lines:
                msg_parts.append(line)
        msg_parts.append("")

    # Reminders
    if reminders:
        msg_parts.append("## 🔔 Reminders")
        for r in reminders[:3]:  # Limit to 3
            msg_parts.append(f"• {r.get('message', 'Reminder')}")
        msg_parts.append("")

    # Ask about plans
    msg_parts.append("---")
    msg_parts.append("**What's your focus today?** Reply with your plans and I'll check in this afternoon.")

    message = "\n".join(msg_parts)

    if not preview:
        # Record that we sent a briefing
        state["last_briefing"] = now_local().isoformat()
        state["briefing_history"].append({
            "date": now_local().strftime("%Y-%m-%d"),
            "sent_at": now_local().isoformat(),
        })
        # Keep only last 30 days
        state["briefing_history"] = state["briefing_history"][-30:]
        save_state(state)

    return message


def log_plan(plan: str) -> dict:
    """Log Samuel's stated plan for the day."""
    state = load_state()

    today = now_local().strftime("%Y-%m-%d")

    state["today_plan"] = {
        "date": today,
        "plan": plan,
        "logged_at": now_local().isoformat(),
    }
    state["plan_logged_at"] = now_local().isoformat()

    save_state(state)

    return {
        "success": True,
        "plan": plan,
        "logged_at": state["plan_logged_at"]
    }


async def generate_check_in() -> str:
    """Generate afternoon check-in message."""
    state = load_state()
    today = now_local().strftime("%Y-%m-%d")

    plan = state.get("today_plan", {})

    if not plan or plan.get("date") != today:
        return "Hey! How's your day going? Any wins or blockers to share?"

    # We have a plan to check against
    stated_plan = plan.get("plan", "")

    msg_parts = [
        "**Afternoon check-in** 🌤️\n",
        f"This morning you said: *\"{stated_plan[:200]}{'...' if len(stated_plan) > 200 else ''}\"*\n",
        "How's that going? Any adjustments needed for the rest of the day?",
    ]

    return "\n".join(msg_parts)


def send_dm(message: str) -> bool:
    """Send a DM to Samuel."""
    success, output = run_integration("dm.py", "send", "samuel", message)
    return success


def show_status():
    """Show today's briefing status."""
    state = load_state()
    today = now_local().strftime("%Y-%m-%d")

    print(f"=== Morning Briefing Status ===")
    print(f"Date: {today}")
    print(f"Last briefing: {state.get('last_briefing', 'Never')}")
    print(f"Last check-in: {state.get('last_check_in', 'Never')}")

    plan = state.get("today_plan", {})
    if plan and plan.get("date") == today:
        print(f"\nToday's plan (logged at {plan.get('logged_at', '?')}):")
        print(f"  {plan.get('plan', 'No plan recorded')}")
    else:
        print("\nNo plan logged for today yet.")


async def main_async(args):
    """Async main for commands that need it."""
    if args.command == "brief":
        message = await generate_briefing(preview=False)
        if send_dm(message):
            print("Briefing sent successfully!")
        else:
            print("Failed to send briefing")
            print("\n--- Preview ---")
            print(message)

    elif args.command == "preview":
        message = await generate_briefing(preview=True)
        print(message)

    elif args.command == "check_in":
        state = load_state()
        message = await generate_check_in()
        if send_dm(message):
            state["last_check_in"] = now_local().isoformat()
            save_state(state)
            print("Check-in sent successfully!")
        else:
            print("Failed to send check-in")
            print("\n--- Preview ---")
            print(message)


def main():
    parser = argparse.ArgumentParser(description="Morning briefing system")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # brief
    subparsers.add_parser("brief", help="Send morning briefing DM")

    # preview
    subparsers.add_parser("preview", help="Preview briefing without sending")

    # log_plan
    plan_parser = subparsers.add_parser("log_plan", help="Log today's plan")
    plan_parser.add_argument("plan", help="The plan text")

    # check_in
    subparsers.add_parser("check_in", help="Send afternoon check-in")

    # status
    subparsers.add_parser("status", help="Show briefing status")

    args = parser.parse_args()

    if args.command in ("brief", "preview", "check_in"):
        asyncio.run(main_async(args))

    elif args.command == "log_plan":
        result = log_plan(args.plan)
        print(json.dumps(result, indent=2))

    elif args.command == "status":
        show_status()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
