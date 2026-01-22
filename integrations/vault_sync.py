#!/usr/bin/env python3
"""S3 to local vault sync for Obsidian vault."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config

# Load environment
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Configuration
S3_ENDPOINT = os.environ.get("AWS_S3_ENDPOINT", "https://s3.eu-west-2.amazonaws.com/")
AWS_REGION = os.environ.get("AWS_REGION", "eu-west-2")
AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
BUCKET_NAME = os.environ.get("OBSIDIAN_BUCKET", "obsidian-vault-samuel")
S3_PREFIX = os.environ.get("OBSIDIAN_PREFIX", "VAULT")

LOCAL_VAULT = Path("/home/executive-assistant/workspace/vaults/samuel")
SYNC_STATE_FILE = Path("/home/executive-assistant/workspace/state/vault_sync_state.json")
LOG_FILE = Path("/home/executive-assistant/workspace/state/vault_sync.log")


def get_s3_client():
    """Create S3 client with credentials."""
    config = Config(
        region_name=AWS_REGION,
        signature_version='s3v4',
    )
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        config=config,
    )


def load_sync_state() -> dict:
    """Load previous sync state."""
    if SYNC_STATE_FILE.exists():
        return json.loads(SYNC_STATE_FILE.read_text())
    return {"files": {}, "last_sync": None}


def save_sync_state(state: dict) -> None:
    """Save sync state."""
    SYNC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_FILE.write_text(json.dumps(state, indent=2))


def log(message: str) -> None:
    """Log sync activity."""
    timestamp = datetime.now().isoformat()
    line = f"[{timestamp}] {message}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def list_s3_objects(client) -> dict:
    """List all objects in the S3 bucket under prefix."""
    objects = {}
    paginator = client.get_paginator('list_objects_v2')

    prefix = f"{S3_PREFIX}/" if S3_PREFIX else ""

    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']
            # Remove prefix to get relative path
            rel_path = key[len(prefix):] if prefix else key
            # Skip directory markers (keys ending with /) and empty keys
            if rel_path and not rel_path.endswith('/') and obj['Size'] > 0:
                objects[rel_path] = {
                    'etag': obj['ETag'].strip('"'),
                    'size': obj['Size'],
                    'modified': obj['LastModified'].isoformat(),
                }

    return objects


def sync_vault(dry_run: bool = False) -> dict:
    """Sync S3 vault to local directory.

    Returns:
        Dict with sync statistics
    """
    stats = {
        "downloaded": 0,
        "deleted": 0,
        "unchanged": 0,
        "errors": [],
    }

    try:
        client = get_s3_client()
    except Exception as e:
        log(f"ERROR: Failed to create S3 client: {e}")
        stats["errors"].append(str(e))
        return stats

    state = load_sync_state()
    previous_files = state.get("files", {})

    log("Listing S3 objects...")
    try:
        s3_objects = list_s3_objects(client)
    except Exception as e:
        log(f"ERROR: Failed to list S3 objects: {e}")
        stats["errors"].append(str(e))
        return stats

    log(f"Found {len(s3_objects)} files in S3")

    # Download new/modified files
    prefix = f"{S3_PREFIX}/" if S3_PREFIX else ""

    for rel_path, obj_info in s3_objects.items():
        local_path = LOCAL_VAULT / rel_path
        s3_key = f"{prefix}{rel_path}"

        # Check if file needs download
        prev_etag = previous_files.get(rel_path, {}).get('etag')
        if prev_etag == obj_info['etag'] and local_path.exists():
            stats["unchanged"] += 1
            continue

        if dry_run:
            log(f"Would download: {rel_path}")
            stats["downloaded"] += 1
            continue

        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(BUCKET_NAME, s3_key, str(local_path))
            log(f"Downloaded: {rel_path}")
            stats["downloaded"] += 1
        except Exception as e:
            log(f"ERROR downloading {rel_path}: {e}")
            stats["errors"].append(f"{rel_path}: {e}")

    # Remove files that no longer exist in S3
    for rel_path in previous_files:
        if rel_path not in s3_objects:
            local_path = LOCAL_VAULT / rel_path
            if local_path.exists():
                if dry_run:
                    log(f"Would delete: {rel_path}")
                else:
                    local_path.unlink()
                    log(f"Deleted: {rel_path}")
                stats["deleted"] += 1

    # Clean up empty directories
    if not dry_run:
        for dirpath, dirnames, filenames in os.walk(LOCAL_VAULT, topdown=False):
            if not dirnames and not filenames:
                try:
                    Path(dirpath).rmdir()
                except OSError:
                    pass

    # Save state
    if not dry_run:
        state["files"] = s3_objects
        state["last_sync"] = datetime.now().isoformat()
        save_sync_state(state)

    log(f"Sync complete: {stats['downloaded']} downloaded, {stats['deleted']} deleted, {stats['unchanged']} unchanged")

    return stats


def get_status() -> dict:
    """Get current sync status."""
    state = load_sync_state()

    # Count local files
    local_count = sum(1 for _ in LOCAL_VAULT.rglob("*") if _.is_file()) if LOCAL_VAULT.exists() else 0

    return {
        "last_sync": state.get("last_sync"),
        "tracked_files": len(state.get("files", {})),
        "local_files": local_count,
        "vault_path": str(LOCAL_VAULT),
    }


def main():
    parser = argparse.ArgumentParser(description="Sync Obsidian vault from S3")
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # sync command
    sync_parser = subparsers.add_parser("sync", help="Sync vault from S3")
    sync_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")

    # status command
    subparsers.add_parser("status", help="Show sync status")

    args = parser.parse_args()

    if args.command == "sync":
        stats = sync_vault(dry_run=args.dry_run)
        if stats["errors"]:
            sys.exit(1)
    elif args.command == "status":
        status = get_status()
        print(json.dumps(status, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
