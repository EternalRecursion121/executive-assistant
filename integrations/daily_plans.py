#!/usr/bin/env python3
"""Daily plans tracker for Iris - stores and retrieves daily intentions.

Usage:
    python daily_plans.py log "<plans>" [--date YYYY-MM-DD]
    python daily_plans.py get [--date YYYY-MM-DD]
    python daily_plans.py review [--date YYYY-MM-DD]   # Get plan + add reflection
    python daily_plans.py reflect "<reflection>" [--date YYYY-MM-DD]
    python daily_plans.py history [days]              # Show recent days
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from config import STATE_DIR, now_local

STATE_FILE = STATE_DIR / "daily_plans.json"


def load_plans() -> dict:
    """Load all daily plans."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"plans": {}, "version": 1}


def save_plans(data: dict):
    """Save daily plans."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2, default=str))


def get_date(date_str: str = None) -> str:
    """Get date string (YYYY-MM-DD), defaulting to today."""
    if date_str:
        return date_str
    return now_local().strftime("%Y-%m-%d")


def log_plan(plans_text: str, date: str = None) -> dict:
    """Log daily plans for a given date."""
    data = load_plans()
    date = get_date(date)

    if date not in data["plans"]:
        data["plans"][date] = {
            "plans": [],
            "reflections": [],
            "logged_at": None,
            "briefing_sent": False,
            "checkin_sent": False,
        }

    data["plans"][date]["plans"].append({
        "text": plans_text,
        "logged_at": now_local().isoformat(),
    })
    data["plans"][date]["logged_at"] = now_local().isoformat()

    save_plans(data)
    return data["plans"][date]


def get_plan(date: str = None) -> dict:
    """Get plans for a given date."""
    data = load_plans()
    date = get_date(date)
    return data["plans"].get(date, None)


def add_reflection(reflection: str, date: str = None) -> dict:
    """Add a reflection for a given date."""
    data = load_plans()
    date = get_date(date)

    if date not in data["plans"]:
        data["plans"][date] = {
            "plans": [],
            "reflections": [],
            "logged_at": None,
            "briefing_sent": False,
            "checkin_sent": False,
        }

    data["plans"][date]["reflections"].append({
        "text": reflection,
        "logged_at": now_local().isoformat(),
    })

    save_plans(data)
    return data["plans"][date]


def mark_briefing_sent(date: str = None):
    """Mark that morning briefing was sent for this date."""
    data = load_plans()
    date = get_date(date)

    if date not in data["plans"]:
        data["plans"][date] = {
            "plans": [],
            "reflections": [],
            "logged_at": None,
            "briefing_sent": False,
            "checkin_sent": False,
        }

    data["plans"][date]["briefing_sent"] = True
    data["plans"][date]["briefing_sent_at"] = now_local().isoformat()
    save_plans(data)


def mark_checkin_sent(date: str = None):
    """Mark that evening check-in was sent for this date."""
    data = load_plans()
    date = get_date(date)

    if date in data["plans"]:
        data["plans"][date]["checkin_sent"] = True
        data["plans"][date]["checkin_sent_at"] = now_local().isoformat()
        save_plans(data)


def get_history(days: int = 7) -> list:
    """Get plans history for the last N days."""
    data = load_plans()
    history = []

    for i in range(days):
        date = (now_local() - timedelta(days=i)).strftime("%Y-%m-%d")
        if date in data["plans"]:
            history.append({
                "date": date,
                **data["plans"][date]
            })

    return history


def format_plan(plan_data: dict, date: str) -> str:
    """Format a plan for display."""
    if not plan_data:
        return f"No plans logged for {date}"

    lines = [f"=== Plans for {date} ==="]

    if plan_data.get("plans"):
        lines.append("\n📋 Plans:")
        for p in plan_data["plans"]:
            lines.append(f"  • {p['text']}")

    if plan_data.get("reflections"):
        lines.append("\n💭 Reflections:")
        for r in plan_data["reflections"]:
            lines.append(f"  • {r['text']}")

    meta = []
    if plan_data.get("briefing_sent"):
        meta.append(f"Briefing sent: {plan_data.get('briefing_sent_at', 'yes')}")
    if plan_data.get("checkin_sent"):
        meta.append(f"Check-in sent: {plan_data.get('checkin_sent_at', 'yes')}")

    if meta:
        lines.append(f"\n[{', '.join(meta)}]")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Daily plans tracker")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # log
    log_parser = subparsers.add_parser("log", help="Log daily plans")
    log_parser.add_argument("plans", help="Plans text")
    log_parser.add_argument("--date", help="Date (YYYY-MM-DD)")

    # get
    get_parser = subparsers.add_parser("get", help="Get plans for a date")
    get_parser.add_argument("--date", help="Date (YYYY-MM-DD)")
    get_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # reflect
    reflect_parser = subparsers.add_parser("reflect", help="Add reflection")
    reflect_parser.add_argument("reflection", help="Reflection text")
    reflect_parser.add_argument("--date", help="Date (YYYY-MM-DD)")

    # review
    review_parser = subparsers.add_parser("review", help="Review plans for check-in")
    review_parser.add_argument("--date", help="Date (YYYY-MM-DD)")

    # history
    history_parser = subparsers.add_parser("history", help="Show recent history")
    history_parser.add_argument("days", type=int, nargs="?", default=7, help="Number of days")
    history_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # mark-briefing
    mark_brief_parser = subparsers.add_parser("mark-briefing", help="Mark briefing sent")
    mark_brief_parser.add_argument("--date", help="Date (YYYY-MM-DD)")

    # mark-checkin
    mark_check_parser = subparsers.add_parser("mark-checkin", help="Mark check-in sent")
    mark_check_parser.add_argument("--date", help="Date (YYYY-MM-DD)")

    args = parser.parse_args()

    if args.command == "log":
        plan_data = log_plan(args.plans, args.date)
        print(f"Logged plans for {get_date(args.date)}")

    elif args.command == "get":
        date = get_date(args.date)
        plan_data = get_plan(date)
        if args.json:
            print(json.dumps(plan_data, indent=2))
        else:
            print(format_plan(plan_data, date))

    elif args.command == "reflect":
        plan_data = add_reflection(args.reflection, args.date)
        print(f"Added reflection for {get_date(args.date)}")

    elif args.command == "review":
        date = get_date(args.date)
        plan_data = get_plan(date)
        print(format_plan(plan_data, date))

    elif args.command == "history":
        history = get_history(args.days)
        if args.json:
            print(json.dumps(history, indent=2))
        else:
            if not history:
                print("No plans in history")
            else:
                for entry in history:
                    print(format_plan(entry, entry["date"]))
                    print()

    elif args.command == "mark-briefing":
        mark_briefing_sent(args.date)
        print(f"Marked briefing sent for {get_date(args.date)}")

    elif args.command == "mark-checkin":
        mark_checkin_sent(args.date)
        print(f"Marked check-in sent for {get_date(args.date)}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
