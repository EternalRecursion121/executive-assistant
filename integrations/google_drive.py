#!/usr/bin/env python3
"""Google Drive integration.

Usage:
    python google_drive.py list [query]           # List/search files
    python google_drive.py read <file_id>         # Read file contents
    python google_drive.py info <file_id>         # Get file metadata
    python google_drive.py create "<name>" "<content>" [--type doc|sheet|text]
    python google_drive.py update <file_id> "<content>"

Requires:
    - Run google_calendar.py auth first (shares credentials)
"""

import json
import sys
from pathlib import Path
from typing import Optional

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload, MediaInMemoryUpload
except ImportError:
    print("Google API libraries not installed. Run:")
    print("pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

import io

WORKSPACE = Path("/home/executive-assistant/workspace")
TOKEN_FILE = WORKSPACE / "state" / "google_token.json"

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
    """Get authenticated Drive service."""
    creds = get_credentials()
    if not creds:
        return None
    return build("drive", "v3", credentials=creds)


def list_files(query: Optional[str] = None, max_results: int = 20) -> dict:
    """List or search files in Drive."""
    service = get_service()
    if not service:
        return {"error": "Not authenticated. Run: python google_calendar.py auth"}

    try:
        # Build query
        q = None
        if query:
            # Search in name and full text
            q = f"name contains '{query}' or fullText contains '{query}'"

        results = (
            service.files()
            .list(
                q=q,
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, size, webViewLink)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )

        files = results.get("files", [])

        if not files:
            return {"files": [], "message": "No files found"}

        formatted = []
        for f in files:
            formatted.append({
                "id": f["id"],
                "name": f["name"],
                "type": f["mimeType"].split(".")[-1] if "." in f["mimeType"] else f["mimeType"],
                "modified": f.get("modifiedTime"),
                "size": f.get("size"),
                "link": f.get("webViewLink"),
            })

        return {"files": formatted, "count": len(formatted)}

    except Exception as e:
        return {"error": str(e)}


def read_file(file_id: str) -> dict:
    """Read file contents."""
    service = get_service()
    if not service:
        return {"error": "Not authenticated. Run: python google_calendar.py auth"}

    try:
        # Get file metadata first
        file_meta = service.files().get(fileId=file_id, fields="name, mimeType").execute()
        mime_type = file_meta.get("mimeType", "")
        name = file_meta.get("name", "")

        # Handle Google Docs/Sheets/Slides - export as text
        if mime_type == "application/vnd.google-apps.document":
            response = service.files().export(fileId=file_id, mimeType="text/plain").execute()
            content = response.decode("utf-8") if isinstance(response, bytes) else response

        elif mime_type == "application/vnd.google-apps.spreadsheet":
            response = service.files().export(fileId=file_id, mimeType="text/csv").execute()
            content = response.decode("utf-8") if isinstance(response, bytes) else response

        elif mime_type == "application/vnd.google-apps.presentation":
            response = service.files().export(fileId=file_id, mimeType="text/plain").execute()
            content = response.decode("utf-8") if isinstance(response, bytes) else response

        elif mime_type.startswith("text/") or mime_type == "application/json":
            # Regular text files - download directly
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            content = fh.getvalue().decode("utf-8")

        else:
            return {
                "error": f"Cannot read file type: {mime_type}",
                "name": name,
                "suggestion": "Use the webViewLink to view in browser",
            }

        return {
            "name": name,
            "type": mime_type,
            "content": content[:50000],  # Limit size
            "truncated": len(content) > 50000,
        }

    except Exception as e:
        return {"error": str(e)}


def get_file_info(file_id: str) -> dict:
    """Get detailed file metadata."""
    service = get_service()
    if not service:
        return {"error": "Not authenticated. Run: python google_calendar.py auth"}

    try:
        file_meta = (
            service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, modifiedTime, createdTime, size, webViewLink, owners, shared",
            )
            .execute()
        )

        return {
            "id": file_meta["id"],
            "name": file_meta["name"],
            "type": file_meta["mimeType"],
            "created": file_meta.get("createdTime"),
            "modified": file_meta.get("modifiedTime"),
            "size": file_meta.get("size"),
            "link": file_meta.get("webViewLink"),
            "shared": file_meta.get("shared", False),
            "owners": [o.get("emailAddress") for o in file_meta.get("owners", [])],
        }

    except Exception as e:
        return {"error": str(e)}


def create_file(name: str, content: str, file_type: str = "doc") -> dict:
    """Create a new file in Drive.

    Args:
        name: File name
        content: Text content
        file_type: 'doc' (Google Doc), 'sheet' (Google Sheet), or 'text' (plain text)
    """
    service = get_service()
    if not service:
        return {"error": "Not authenticated. Run: python google_calendar.py auth"}

    try:
        if file_type == "doc":
            # Create Google Doc
            file_metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.document",
            }
            # Upload as plain text, Google converts to Doc
            media = MediaInMemoryUpload(
                content.encode("utf-8"),
                mimetype="text/plain",
                resumable=True,
            )
        elif file_type == "sheet":
            # Create Google Sheet (content should be CSV)
            file_metadata = {
                "name": name,
                "mimeType": "application/vnd.google-apps.spreadsheet",
            }
            media = MediaInMemoryUpload(
                content.encode("utf-8"),
                mimetype="text/csv",
                resumable=True,
            )
        else:
            # Plain text file
            file_metadata = {"name": name}
            media = MediaInMemoryUpload(
                content.encode("utf-8"),
                mimetype="text/plain",
                resumable=True,
            )

        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id, name, webViewLink")
            .execute()
        )

        return {
            "success": True,
            "id": file["id"],
            "name": file["name"],
            "link": file.get("webViewLink"),
        }

    except Exception as e:
        return {"error": str(e)}


def update_file(file_id: str, content: str) -> dict:
    """Update an existing file's content."""
    service = get_service()
    if not service:
        return {"error": "Not authenticated. Run: python google_calendar.py auth"}

    try:
        # Get current file type
        file_meta = service.files().get(fileId=file_id, fields="mimeType, name").execute()
        mime_type = file_meta.get("mimeType", "")
        name = file_meta.get("name", "")

        # Determine upload mime type
        if mime_type == "application/vnd.google-apps.document":
            upload_mime = "text/plain"
        elif mime_type == "application/vnd.google-apps.spreadsheet":
            upload_mime = "text/csv"
        else:
            upload_mime = "text/plain"

        media = MediaInMemoryUpload(
            content.encode("utf-8"),
            mimetype=upload_mime,
            resumable=True,
        )

        file = (
            service.files()
            .update(fileId=file_id, media_body=media, fields="id, name, webViewLink")
            .execute()
        )

        return {
            "success": True,
            "id": file["id"],
            "name": file["name"],
            "link": file.get("webViewLink"),
        }

    except Exception as e:
        return {"error": str(e)}


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: google_drive.py <command> [args]")
        print("Commands: list, read, info, create, update")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        query = sys.argv[2] if len(sys.argv) > 2 else None
        result = list_files(query)
        print(json.dumps(result, indent=2))

    elif command == "read":
        if len(sys.argv) < 3:
            print("Usage: google_drive.py read <file_id>")
            sys.exit(1)
        result = read_file(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif command == "info":
        if len(sys.argv) < 3:
            print("Usage: google_drive.py info <file_id>")
            sys.exit(1)
        result = get_file_info(sys.argv[2])
        print(json.dumps(result, indent=2))

    elif command == "create":
        if len(sys.argv) < 4:
            print("Usage: google_drive.py create <name> <content> [--type doc|sheet|text]")
            sys.exit(1)
        name = sys.argv[2]
        content = sys.argv[3]
        file_type = "doc"
        if "--type" in sys.argv:
            idx = sys.argv.index("--type")
            if idx + 1 < len(sys.argv):
                file_type = sys.argv[idx + 1]
        result = create_file(name, content, file_type)
        print(json.dumps(result, indent=2))

    elif command == "update":
        if len(sys.argv) < 4:
            print("Usage: google_drive.py update <file_id> <content>")
            sys.exit(1)
        result = update_file(sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
