#!/usr/bin/env python3
"""Google Calendar integration.

Usage:
    python google_calendar.py auth          # First-time OAuth setup
    python google_calendar.py list [days]   # List upcoming events (default: 7 days)
    python google_calendar.py add "<title>" "<start>" "<end>" ["<description>"]

Requires:
    - credentials.json from Google Cloud Console in workspace/
    - First run `auth` command to authenticate

Time formats:
    - "2024-01-15 14:00"
    - "tomorrow 2pm"
    - "next monday 9am"
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dateutil import parser as date_parser

# Google API imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    print("Google API libraries not installed. Run:")
    print("pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",           # Calendar read/write
    "https://www.googleapis.com/auth/drive",              # Drive read/write
    "https://www.googleapis.com/auth/gmail.readonly",     # Gmail read-only
]
WORKSPACE = Path("/home/executive-assistant/workspace")
CREDENTIALS_FILE = WORKSPACE / "credentials.json"
TOKEN_FILE = WORKSPACE / "state" / "google_token.json"
PERMISSIONS_FILE = WORKSPACE / "state" / "permissions.json"


def check_permission(capability: str) -> bool:
    """Check if capability is allowed.

    Note: Calendar is typically called by Iris on behalf of a user,
    so we check at the bot level. This is defense-in-depth.
    For CLI usage, we allow it (no user context).
    """
    # When called from CLI directly, allow
    return True


def check_permission_for_user(user_id: str, capability: str) -> bool:
    """Check if a specific user has permission."""
    if not PERMISSIONS_FILE.exists():
        return True

    try:
        perms = json.loads(PERMISSIONS_FILE.read_text())
    except json.JSONDecodeError:
        return True

    user = perms.get("users", {}).get(str(user_id))
    if not user:
        default_role = perms.get("default", "none")
        if default_role == "none":
            return False
        role = perms.get("roles", {}).get(default_role, {})
    else:
        role = perms.get("roles", {}).get(user.get("role", "none"), {})

    # Get permissions from role, with optional user-level overrides
    allow = set(role.get("allow", []))
    deny = set(role.get("deny", []))
    if user:
        allow.update(user.get("allow", []))
        deny.update(user.get("deny", []))

    if "*" in allow and capability not in deny:
        return True
    return capability in allow and capability not in deny


def get_credentials() -> Optional[Credentials]:
    """Get valid credentials, refreshing if necessary."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
        except Exception:
            creds = None

    return creds


def authenticate() -> dict:
    """Run OAuth flow to authenticate with Google."""
    if not CREDENTIALS_FILE.exists():
        return {
            "error": f"credentials.json not found at {CREDENTIALS_FILE}",
            "instructions": [
                "1. Go to https://console.cloud.google.com",
                "2. Create a project and enable Google Calendar API",
                "3. Create OAuth 2.0 credentials (Desktop app)",
                "4. Download credentials.json to " + str(WORKSPACE),
            ],
        }

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())

        return {"success": True, "message": "Successfully authenticated with Google Calendar"}
    except Exception as e:
        return {"error": str(e)}


def get_service():
    """Get authenticated Google Calendar service."""
    creds = get_credentials()
    if not creds or not creds.valid:
        return None
    return build("calendar", "v3", credentials=creds)


def parse_datetime(time_str: str) -> Optional[datetime]:
    """Parse time string into datetime."""
    now = datetime.now()
    time_str = time_str.lower().strip()

    # Handle "tomorrow"
    if "tomorrow" in time_str:
        time_part = time_str.replace("tomorrow", "").replace("at", "").strip()
        base = now + timedelta(days=1)
        if time_part:
            try:
                parsed = date_parser.parse(time_part)
                return base.replace(
                    hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
                )
            except Exception:
                pass
        return base.replace(hour=9, minute=0, second=0, microsecond=0)

    # Handle "next weekday"
    weekdays = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    for day_name, day_num in weekdays.items():
        if f"next {day_name}" in time_str:
            days_ahead = day_num - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            base = now + timedelta(days=days_ahead)
            time_part = time_str.replace(f"next {day_name}", "").replace("at", "").strip()
            if time_part:
                try:
                    parsed = date_parser.parse(time_part)
                    return base.replace(
                        hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
                    )
                except Exception:
                    pass
            return base.replace(hour=9, minute=0, second=0, microsecond=0)

    # Standard parsing
    try:
        return date_parser.parse(time_str, fuzzy=True)
    except Exception:
        return None


def list_events(days: int = 7) -> dict:
    """List upcoming calendar events."""
    service = get_service()
    if not service:
        return {"error": "Not authenticated. Run: python google_calendar.py auth"}

    try:
        now = datetime.utcnow().isoformat() + "Z"
        end = (datetime.utcnow() + timedelta(days=days)).isoformat() + "Z"

        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                timeMax=end,
                maxResults=50,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])

        if not events:
            return {"events": [], "message": f"No events in the next {days} days"}

        formatted = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            end = event["end"].get("dateTime", event["end"].get("date"))

            formatted.append({
                "id": event["id"],
                "title": event.get("summary", "(No title)"),
                "start": start,
                "end": end,
                "location": event.get("location"),
                "description": event.get("description"),
            })

        return {"events": formatted}

    except Exception as e:
        return {"error": str(e)}


def add_event(
    title: str,
    start_str: str,
    end_str: str,
    description: Optional[str] = None,
) -> dict:
    """Add a new calendar event."""
    service = get_service()
    if not service:
        return {"error": "Not authenticated. Run: python google_calendar.py auth"}

    start = parse_datetime(start_str)
    end = parse_datetime(end_str)

    if not start:
        return {"error": f"Could not parse start time: {start_str}"}
    if not end:
        return {"error": f"Could not parse end time: {end_str}"}

    event = {
        "summary": title,
        "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
    }

    if description:
        event["description"] = description

    try:
        result = service.events().insert(calendarId="primary", body=event).execute()
        return {
            "success": True,
            "id": result["id"],
            "title": title,
            "start": start.strftime("%Y-%m-%d %H:%M"),
            "end": end.strftime("%Y-%m-%d %H:%M"),
            "link": result.get("htmlLink"),
        }
    except Exception as e:
        return {"error": str(e)}


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: google_calendar.py <command> [args]")
        print("Commands: auth, list, add")
        sys.exit(1)

    command = sys.argv[1]

    if command == "auth":
        result = authenticate()
        print(json.dumps(result, indent=2))

    elif command == "list":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        result = list_events(days)
        print(json.dumps(result, indent=2))

    elif command == "add":
        if len(sys.argv) < 5:
            print("Usage: google_calendar.py add <title> <start> <end> [description]")
            sys.exit(1)
        description = sys.argv[5] if len(sys.argv) > 5 else None
        result = add_event(sys.argv[2], sys.argv[3], sys.argv[4], description)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
