#!/usr/bin/env python3
"""Gmail integration (read-only).

Usage:
    python gmail.py list [max_results]            # List recent emails
    python gmail.py search "<query>"              # Search emails
    python gmail.py read <message_id>             # Read full email
    python gmail.py unread                        # List unread emails

Requires:
    - Run google_calendar.py auth first (shares credentials)

Search examples:
    "from:someone@example.com"
    "subject:meeting"
    "is:unread"
    "after:2024/01/01"
    "has:attachment"
"""

import json
import sys
import base64
from pathlib import Path
from typing import Optional
from email.utils import parsedate_to_datetime

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError:
    print("Google API libraries not installed. Run:")
    print("pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

from config import STATE_DIR

TOKEN_FILE = STATE_DIR / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def get_credentials() -> Optional[Credentials]:
    """Get valid credentials (shared with calendar)."""
    if not TOKEN_FILE.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.valid:
        return creds
    return None


def get_service():
    """Get authenticated Gmail service."""
    creds = get_credentials()
    if not creds:
        return None
    return build("gmail", "v1", credentials=creds)


def _parse_headers(headers: list) -> dict:
    """Extract common headers into a dict."""
    result = {}
    for h in headers:
        name = h["name"].lower()
        if name in ("from", "to", "subject", "date", "cc"):
            result[name] = h["value"]
    return result


def _get_body(payload: dict) -> str:
    """Extract plain text body from message payload."""
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain" and part["body"].get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            # Recurse into nested parts
            if "parts" in part:
                body = _get_body(part)
                if body:
                    return body

    return ""


def list_emails(max_results: int = 10, query: Optional[str] = None) -> dict:
    """List recent emails."""
    service = get_service()
    if not service:
        return {"error": "Not authenticated. Run: python google_calendar.py auth"}

    try:
        results = (
            service.users()
            .messages()
            .list(userId="me", maxResults=max_results, q=query)
            .execute()
        )

        messages = results.get("messages", [])

        if not messages:
            return {"emails": [], "message": "No emails found"}

        emails = []
        for msg in messages:
            # Get message details
            detail = (
                service.users()
                .messages()
                .get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["From", "To", "Subject", "Date"])
                .execute()
            )

            headers = _parse_headers(detail.get("payload", {}).get("headers", []))
            labels = detail.get("labelIds", [])

            emails.append({
                "id": msg["id"],
                "thread_id": msg.get("threadId"),
                "from": headers.get("from"),
                "to": headers.get("to"),
                "subject": headers.get("subject"),
                "date": headers.get("date"),
                "unread": "UNREAD" in labels,
                "snippet": detail.get("snippet"),
            })

        return {"emails": emails, "count": len(emails)}

    except Exception as e:
        return {"error": str(e)}


def search_emails(query: str, max_results: int = 10) -> dict:
    """Search emails with Gmail query syntax."""
    return list_emails(max_results=max_results, query=query)


def read_email(message_id: str) -> dict:
    """Read full email content."""
    service = get_service()
    if not service:
        return {"error": "Not authenticated. Run: python google_calendar.py auth"}

    try:
        message = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

        payload = message.get("payload", {})
        headers = _parse_headers(payload.get("headers", []))
        body = _get_body(payload)

        # Get attachments info
        attachments = []
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("filename"):
                    attachments.append({
                        "filename": part["filename"],
                        "mimeType": part["mimeType"],
                        "size": part["body"].get("size"),
                    })

        return {
            "id": message_id,
            "thread_id": message.get("threadId"),
            "from": headers.get("from"),
            "to": headers.get("to"),
            "cc": headers.get("cc"),
            "subject": headers.get("subject"),
            "date": headers.get("date"),
            "body": body[:50000],  # Limit size
            "truncated": len(body) > 50000,
            "attachments": attachments,
            "labels": message.get("labelIds", []),
        }

    except Exception as e:
        return {"error": str(e)}


def list_unread(max_results: int = 10) -> dict:
    """List unread emails."""
    return list_emails(max_results=max_results, query="is:unread")


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: gmail.py <command> [args]")
        print("Commands: list, search, read, unread")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        result = list_emails(max_results)
        print(json.dumps(result, indent=2))

    elif command == "search":
        if len(sys.argv) < 3:
            print("Usage: gmail.py search <query>")
            sys.exit(1)
        result = search_emails(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif command == "read":
        if len(sys.argv) < 3:
            print("Usage: gmail.py read <message_id>")
            sys.exit(1)
        result = read_email(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif command == "unread":
        max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        result = list_unread(max_results)
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
