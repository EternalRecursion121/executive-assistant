#!/bin/bash
# Safe bot restart with syntax validation
# Usage: ./restart.sh
# Checks all Python files for syntax errors before restarting.
# If validation fails, prints errors and does NOT restart.

set -e

BOT_DIR="/home/iris/executive-assistant"
VENV="$BOT_DIR/venv/bin/python"

echo "Validating Python syntax..."

ERRORS=""
for f in "$BOT_DIR/bot.py" "$BOT_DIR/claude_client.py" "$BOT_DIR/context_builder.py" "$BOT_DIR/assistant_prompt.py" "$BOT_DIR/permissions.py"; do
    if [ -f "$f" ]; then
        OUTPUT=$($VENV -c "import ast; ast.parse(open('$f').read())" 2>&1) || {
            ERRORS="$ERRORS\nSyntax error in $f:\n$OUTPUT"
        }
    fi
done

# Also try importing the main modules to catch import errors
OUTPUT=$($VENV -c "
import sys
sys.path.insert(0, '$BOT_DIR')
import claude_client
import context_builder
import permissions
import assistant_prompt
" 2>&1) || {
    ERRORS="$ERRORS\nImport error:\n$OUTPUT"
}

if [ -n "$ERRORS" ]; then
    echo -e "VALIDATION FAILED. Not restarting.\n$ERRORS"
    exit 1
fi

echo "Validation passed. Restarting bot..."
sudo /usr/bin/systemctl restart iris-bot
sleep 3

if sudo /usr/bin/systemctl is-active --quiet iris-bot; then
    echo "Bot restarted successfully."
else
    echo "ERROR: Bot failed to start after restart."
    sudo /usr/bin/systemctl status iris-bot --no-pager | tail -10
    exit 1
fi
