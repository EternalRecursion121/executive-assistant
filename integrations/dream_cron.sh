#!/bin/bash
# Nightly dream scheduler launcher
# Run at 11pm to start a night of random dreaming

cd /home/executive-assistant
export PATH="/home/iris/.local/node_modules/.bin:$PATH"
export HOME="/home/iris"

# Source environment variables if they exist
[ -f /home/executive-assistant/.env ] && source /home/executive-assistant/.env

# Log start
echo "[$(date)] Starting nightly dream session" >> /home/executive-assistant/workspace/state/dream_cron.log

# Run in background so cron doesn't wait
nohup python3 /home/executive-assistant/integrations/dream_scheduler.py start >> /home/executive-assistant/workspace/state/dream_scheduler.log 2>&1 &

echo "[$(date)] Dream scheduler spawned with PID $!" >> /home/executive-assistant/workspace/state/dream_cron.log
