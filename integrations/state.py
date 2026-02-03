#!/usr/bin/env python3
"""State management for Iris.

Usage:
    python state.py collections                # list all collections
    python state.py list <collection>          # list entries
    python state.py get <collection> <id>      # get entry
    python state.py set <collection> <json>    # create/update
    python state.py delete <collection> <id>   # delete
    python state.py search <collection> <query># search
    python state.py log <action> [details]     # activity log

Collections are created automatically on first write.
Entries auto-get: id, created, updated fields.
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import STATE_DIR

SCHEMA_FILE = STATE_DIR / "schema.json"


def load_schema() -> dict:
    if SCHEMA_FILE.exists():
        return json.loads(SCHEMA_FILE.read_text())
    return {"collections": {}}


def save_schema(schema: dict) -> None:
    SCHEMA_FILE.write_text(json.dumps(schema, indent=2))


def get_collection_file(name: str) -> Path:
    return STATE_DIR / f"{name}.json"


def load_collection(name: str) -> list[dict]:
    path = get_collection_file(name)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except:
        return []


def save_collection(name: str, data: list[dict]) -> None:
    schema = load_schema()
    if name not in schema["collections"]:
        schema["collections"][name] = {"created": datetime.now().isoformat()}
        save_schema(schema)
    get_collection_file(name).write_text(json.dumps(data, indent=2, default=str))


def add_auto_fields(entry: dict, is_new: bool) -> dict:
    now = datetime.now().isoformat()
    if is_new:
        if "id" not in entry and "key" not in entry:
            entry["id"] = str(uuid.uuid4())[:8]
        entry["created"] = now
    entry["updated"] = now
    return entry


def list_collections() -> dict:
    schema = load_schema()
    result = {}
    for name in schema.get("collections", {}):
        result[name] = len(load_collection(name))
    return {"collections": result}


def list_entries(collection: str) -> dict:
    return {"collection": collection, "entries": load_collection(collection)}


def get_entry(collection: str, entry_id: str) -> dict:
    for entry in load_collection(collection):
        if entry.get("id") == entry_id or entry.get("key") == entry_id:
            return {"entry": entry}
    return {"error": "not found"}


def set_entry(collection: str, entry_json: str) -> dict:
    try:
        entry = json.loads(entry_json)
    except:
        return {"error": "invalid json"}

    data = load_collection(collection)
    entry_id = entry.get("id") or entry.get("key")

    for i, existing in enumerate(data):
        if existing.get("id") == entry_id or existing.get("key") == entry_id:
            entry = add_auto_fields(entry, is_new=False)
            entry["created"] = existing.get("created", entry["updated"])
            data[i] = entry
            save_collection(collection, data)
            return {"action": "updated", "entry": entry}

    entry = add_auto_fields(entry, is_new=True)
    data.append(entry)
    save_collection(collection, data)
    return {"action": "created", "entry": entry}


def delete_entry(collection: str, entry_id: str) -> dict:
    data = load_collection(collection)
    filtered = [e for e in data if e.get("id") != entry_id and e.get("key") != entry_id]
    if len(filtered) == len(data):
        return {"error": "not found"}
    save_collection(collection, filtered)
    return {"deleted": entry_id}


def search_entries(collection: str, query: str) -> dict:
    query = query.lower()
    matches = []
    for entry in load_collection(collection):
        if query in json.dumps(entry).lower():
            matches.append(entry)
    return {"matches": matches}


def append_log(action: str, details: Optional[str] = None) -> dict:
    entry = {"action": action}
    if details:
        try:
            entry["details"] = json.loads(details)
        except:
            entry["details"] = details
    return set_entry("log", json.dumps(entry))


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"usage": "state.py <collections|list|get|set|delete|search|log>"}))
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "collections":
        print(json.dumps(list_collections(), indent=2))
    elif cmd == "list" and len(sys.argv) > 2:
        print(json.dumps(list_entries(sys.argv[2]), indent=2))
    elif cmd == "get" and len(sys.argv) > 3:
        print(json.dumps(get_entry(sys.argv[2], sys.argv[3]), indent=2))
    elif cmd == "set" and len(sys.argv) > 3:
        print(json.dumps(set_entry(sys.argv[2], sys.argv[3]), indent=2))
    elif cmd == "delete" and len(sys.argv) > 3:
        print(json.dumps(delete_entry(sys.argv[2], sys.argv[3]), indent=2))
    elif cmd == "search" and len(sys.argv) > 3:
        print(json.dumps(search_entries(sys.argv[2], sys.argv[3]), indent=2))
    elif cmd == "log" and len(sys.argv) > 2:
        details = sys.argv[3] if len(sys.argv) > 3 else None
        print(json.dumps(append_log(sys.argv[2], details), indent=2))
    else:
        print(json.dumps({"error": "invalid command"}))


if __name__ == "__main__":
    main()
