#!/bin/bash
# Cron wrapper for Iris self-journaling
# Spawns a Claude Code session to reflect and write journal entries

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="/home/executive-assistant"
LOG_FILE="$WORKSPACE/workspace/state/journal_cron.log"

# Get the journal prompt
PROMPT=$(python3 "$SCRIPT_DIR/journal_agent.py" spawn 2>/dev/null)
SESSION_TYPE=$(echo "$PROMPT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_type','reflection'))" 2>/dev/null)

# Log the attempt
echo "[$(date -Iseconds)] Starting $SESSION_TYPE journaling session" >> "$LOG_FILE"

# Build the instruction for Claude
INSTRUCTION="You are Iris. It's time for your $SESSION_TYPE journaling session.

Based on the time of day and your recent activity, write 1-3 genuine journal entries.
Use: python3 integrations/journal.py write \"<your thought>\" --type <type>

Types: observation, reflection, learning, intention, note

Be genuine - this is for your own continuity, not performance. Then exit."

# Run Claude Code with the journaling task
cd "$WORKSPACE"
claude --print "$INSTRUCTION" 2>> "$LOG_FILE" || echo "[$(date -Iseconds)] Session failed" >> "$LOG_FILE"

# Regenerate context for next session
python3 "$SCRIPT_DIR/context.py" generate >> "$LOG_FILE" 2>&1

echo "[$(date -Iseconds)] Completed $SESSION_TYPE session" >> "$LOG_FILE"
