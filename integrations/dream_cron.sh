#!/bin/bash
# Nightly dream scheduler launcher
# Run at 11pm to start a night of random dreaming

cd /home/iris/executive-assistant
export PATH="/home/iris/.local/bin:$PATH"
export HOME="/home/iris"

# Source environment variables if they exist
[ -f /home/iris/executive-assistant/.env ] && source /home/iris/executive-assistant/.env

# Log start
echo "[$(date)] Starting nightly dream session" >> /home/iris/executive-assistant/workspace/state/dream_cron.log

# Run in background so cron doesn't wait
nohup python3 /home/iris/executive-assistant/integrations/dream_scheduler.py start >> /home/iris/executive-assistant/workspace/state/dream_scheduler.log 2>&1 &

echo "[$(date)] Dream scheduler spawned with PID $!" >> /home/iris/executive-assistant/workspace/state/dream_cron.log
