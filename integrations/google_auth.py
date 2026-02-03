#!/usr/bin/env python3
"""Unified Google authentication for all services.

Authenticates once for: Calendar, Drive, Gmail.
Uses device/console flow (works headless — no browser popup needed).

Usage:
    python google_auth.py              # Run OAuth flow
    python google_auth.py status       # Check auth status
    python google_auth.py refresh      # Force token refresh
    python google_auth.py revoke       # Revoke credentials

Requires:
    - credentials.json in workspace/ (from Google Cloud Console)
    - OAuth consent screen with Calendar, Drive, Gmail APIs enabled
"""

import json
import sys
from pathlib import Path
from typing import Optional

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
except ImportError:
    print("Missing dependencies. Run:")
    print("  pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

from config import WORKSPACE, STATE_DIR

CREDENTIALS_FILE = WORKSPACE / "credentials.json"
TOKEN_FILE = STATE_DIR / "google_token.json"

# All scopes needed across integrations
SCOPES = [
    "https://www.googleapis.com/auth/calendar",       # Calendar read/write
    "https://www.googleapis.com/auth/drive",           # Drive read/write
    "https://www.googleapis.com/auth/gmail.readonly",  # Gmail read-only
]

SERVICES = {
    "calendar": ("calendar", "v3"),
    "drive": ("drive", "v3"),
    "gmail": ("gmail", "v1"),
}


def authenticate() -> dict:
    """Run OAuth flow for all Google services at once."""
    if not CREDENTIALS_FILE.exists():
        return {
            "error": f"credentials.json not found at {CREDENTIALS_FILE}",
            "instructions": [
                "1. Go to https://console.cloud.google.com",
                "2. Create/select a project",
                "3. Enable these APIs: Google Calendar, Google Drive, Gmail",
                "4. Go to Credentials → Create OAuth 2.0 Client ID (Desktop app)",
                "5. Download the JSON and save as: " + str(CREDENTIALS_FILE),
            ],
        }

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)

        print("\n🔐 Google Authentication (Calendar + Drive + Gmail)\n")
        print("This will open a browser to authenticate.")
        print("All three services authenticate with a single sign-in.\n")

        # Use local server flow - starts a temporary server to receive the OAuth callback
        # This works reliably and handles the redirect_uri automatically
        creds = flow.run_local_server(
            port=0,  # Use any available port
            authorization_prompt_message="Visit this URL to authenticate:\n{url}",
            success_message="Authentication successful! You can close this tab.",
            open_browser=True,
        )

        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(creds.to_json())

        # Verify each service works
        results = verify_services(creds)

        return {
            "success": True,
            "message": "Authenticated all Google services",
            "token_path": str(TOKEN_FILE),
            "services": results,
        }

    except Exception as e:
        return {"error": f"Authentication failed: {e}"}


def get_credentials() -> Optional[Credentials]:
    """Load and refresh credentials if needed."""
    if not TOKEN_FILE.exists():
        return None

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
        except Exception:
            return None

    if creds and creds.valid:
        return creds
    return None


def verify_services(creds: Credentials) -> dict:
    """Verify each Google service is accessible."""
    results = {}

    # Calendar
    try:
        svc = build("calendar", "v3", credentials=creds)
        cal = svc.calendarList().list(maxResults=1).execute()
        results["calendar"] = {"status": "ok", "calendars": len(cal.get("items", []))}
    except Exception as e:
        results["calendar"] = {"status": "error", "detail": str(e)}

    # Drive
    try:
        svc = build("drive", "v3", credentials=creds)
        about = svc.about().get(fields="user").execute()
        results["drive"] = {"status": "ok", "user": about["user"]["emailAddress"]}
    except Exception as e:
        results["drive"] = {"status": "error", "detail": str(e)}

    # Gmail
    try:
        svc = build("gmail", "v1", credentials=creds)
        profile = svc.users().getProfile(userId="me").execute()
        results["gmail"] = {"status": "ok", "email": profile["emailAddress"]}
    except Exception as e:
        results["gmail"] = {"status": "error", "detail": str(e)}

    return results


def status() -> dict:
    """Check current authentication status."""
    creds = get_credentials()

    if not creds:
        return {
            "authenticated": False,
            "message": "Not authenticated. Run: python google_auth.py",
        }

    result = {
        "authenticated": True,
        "token_path": str(TOKEN_FILE),
        "scopes": creds.scopes or SCOPES,
        "expired": creds.expired,
        "has_refresh_token": bool(creds.refresh_token),
    }

    # Check each service
    result["services"] = verify_services(creds)

    return result


def refresh() -> dict:
    """Force refresh the token."""
    if not TOKEN_FILE.exists():
        return {"error": "No token file. Run: python google_auth.py"}

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds.refresh_token:
        return {"error": "No refresh token. Re-authenticate: python google_auth.py"}

    try:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
        return {"success": True, "message": "Token refreshed"}
    except Exception as e:
        return {"error": f"Refresh failed: {e}"}


def revoke() -> dict:
    """Revoke credentials and delete token."""
    if not TOKEN_FILE.exists():
        return {"message": "No token to revoke"}

    creds = get_credentials()
    if creds:
        try:
            import requests
            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": creds.token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except Exception:
            pass  # Best effort revocation

    TOKEN_FILE.unlink(missing_ok=True)
    return {"success": True, "message": "Token revoked and deleted"}


def main():
    import json as j

    cmd = sys.argv[1] if len(sys.argv) > 1 else "auth"

    if cmd == "auth":
        result = authenticate()
    elif cmd == "status":
        result = status()
    elif cmd == "refresh":
        result = refresh()
    elif cmd == "revoke":
        result = revoke()
    else:
        result = {"error": f"Unknown command: {cmd}", "commands": ["auth", "status", "refresh", "revoke"]}

    print(j.dumps(result, indent=2))


if __name__ == "__main__":
    main()
