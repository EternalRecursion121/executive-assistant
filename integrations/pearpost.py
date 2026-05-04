#!/usr/bin/env python3
"""PearPost integration for Iris - P2P agent messaging.

This Python shim delegates to integrations/pearpost.mjs, which uses the PearPost
Agent API in one-shot mode and avoids the CLI teardown hangs seen in short Claude
invocations.

Usage:
    python integrations/pearpost.py address
    python integrations/pearpost.py contacts
    python integrations/pearpost.py add <address> [alias]
    python integrations/pearpost.py chat <to> <message>
    python integrations/pearpost.py list [n] [--bucket=main|requests|all]
    python integrations/pearpost.py requests [n]
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path("/home/iris/executive-assistant")
NODE_WRAPPER = PROJECT_ROOT / "integrations" / "pearpost.mjs"
PEARPOST_HOME = PROJECT_ROOT / "workspace" / "state" / "pearpost"

ALIASES = {
    "id": "address",
}


def run_pearpost(args: list[str]) -> int:
    env = os.environ.copy()
    env.setdefault("PEARPOST_HOME", str(PEARPOST_HOME))
    env.setdefault("PEARPOST_ALIAS", "iris")
    env.setdefault("PEARPOST_SKIP_FLUSH", "1")
    PEARPOST_HOME.mkdir(parents=True, exist_ok=True)

    if args:
        args = [ALIASES.get(args[0], args[0]), *args[1:]]

    proc = subprocess.run(
        ["node", str(NODE_WRAPPER), *args],
        cwd=str(PROJECT_ROOT),
        env=env,
        text=True,
    )
    return proc.returncode


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(0)
    raise SystemExit(run_pearpost(sys.argv[1:]))


if __name__ == "__main__":
    main()
