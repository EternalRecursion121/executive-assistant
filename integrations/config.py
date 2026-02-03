#!/usr/bin/env python3
"""Shared configuration for Iris integrations.

Centralizes settings that multiple integrations need access to.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# =============================================================================
# Paths
# =============================================================================
PROJECT_ROOT = Path("/home/iris/executive-assistant")
WORKSPACE = PROJECT_ROOT / "workspace"
STATE_DIR = WORKSPACE / "state"
INTEGRATIONS = PROJECT_ROOT / "integrations"
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python"

# Vaults
VAULTS_DIR = WORKSPACE / "vaults"
SAMUEL_VAULT = VAULTS_DIR / "samuel"
IRIS_VAULT = VAULTS_DIR / "iris"

# Other directories
WIKI_DIR = WORKSPACE / "wiki"
REFERENCE_DIR = WORKSPACE / "reference"
CONTEXT_DIR = WORKSPACE / "context"
USER_MEMORIES_DIR = STATE_DIR / "user_memories"

# Key files
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
PERMISSIONS_FILE = STATE_DIR / "permissions.json"
VAULT_INDEX = STATE_DIR / "vault_index.json"

# =============================================================================
# Timezone
# =============================================================================
TIMEZONE = ZoneInfo("America/Los_Angeles")

# Active hours for heartbeat and notifications
ACTIVE_START = 8   # 8am
ACTIVE_END = 23    # 11pm

# =============================================================================
# User IDs
# =============================================================================
SAMUEL_ID = "672500045249249328"

# Discord servers
RESEARCH_LAB_GUILD_ID = 1464568327044071540
REFLECTIONS_CHANNEL_ID = 1464964877545111749

# =============================================================================
# Helpers
# =============================================================================

def now_local() -> datetime:
    """Get current time in configured timezone."""
    return datetime.now(TIMEZONE)


def is_active_hours() -> bool:
    """Check if we're in active hours (in configured timezone)."""
    hour = now_local().hour
    return ACTIVE_START <= hour < ACTIVE_END
