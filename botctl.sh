#!/bin/bash
# Iris bot controller - manages running, restarting, and watching for changes

BOT_DIR="/home/iris/executive-assistant"
BOT_SCRIPT="$BOT_DIR/bot.py"
PID_FILE="$BOT_DIR/workspace/state/bot.pid"
LOG_FILE="$BOT_DIR/workspace/state/bot.log"
WATCH_FILES="$BOT_DIR/*.py $BOT_DIR/integrations/*.py $BOT_DIR/CLAUDE.md"

# Source environment
[ -f "$BOT_DIR/.env" ] && source "$BOT_DIR/.env"
export PATH="/home/iris/.local/node_modules/.bin:$PATH"

start_bot() {
    if is_running; then
        echo "Bot is already running (PID: $(cat $PID_FILE))"
        return 1
    fi

    echo "Starting Iris..."
    cd "$BOT_DIR"
    nohup python3 "$BOT_SCRIPT" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Bot started with PID $!"
}

stop_bot() {
    if ! is_running; then
        echo "Bot is not running"
        return 1
    fi

    local pid=$(cat "$PID_FILE")
    echo "Stopping bot (PID: $pid)..."
    kill "$pid" 2>/dev/null

    # Wait for graceful shutdown
    for i in {1..10}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            break
        fi
        sleep 1
    done

    # Force kill if still running
    if kill -0 "$pid" 2>/dev/null; then
        echo "Force killing..."
        kill -9 "$pid" 2>/dev/null
    fi

    rm -f "$PID_FILE"
    echo "Bot stopped"
}

restart_bot() {
    echo "Restarting bot..."
    stop_bot 2>/dev/null
    sleep 2
    start_bot
}

is_running() {
    [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null
}

status() {
    if is_running; then
        echo "Bot is running (PID: $(cat $PID_FILE))"
        return 0
    else
        echo "Bot is not running"
        return 1
    fi
}

logs() {
    local lines=${1:-50}
    tail -n "$lines" "$LOG_FILE"
}

follow() {
    tail -f "$LOG_FILE"
}

# Auto-restart loop - keeps bot running and restarts on crash/request
run_forever() {
    echo "Starting Iris in auto-restart mode..."

    while true; do
        cd "$BOT_DIR"
        echo "[$(date)] Starting bot..."
        python3 "$BOT_SCRIPT" 2>&1 | tee -a "$LOG_FILE"

        exit_code=$?
        echo "[$(date)] Bot exited with code $exit_code"

        # Check if restart was requested (vs crash)
        if [ -f "$BOT_DIR/workspace/state/restart_requested" ]; then
            echo "[$(date)] Restart requested, restarting in 2 seconds..."
            sleep 2
        else
            echo "[$(date)] Bot crashed, restarting in 5 seconds..."
            sleep 5
        fi
    done
}

# Watch for file changes and trigger hot reload signal
watch_mode() {
    if ! command -v inotifywait &> /dev/null; then
        echo "inotifywait not found. Install inotify-tools for watch mode."
        echo "Running in auto-restart mode instead..."
        run_forever
        return
    fi

    echo "Starting Iris with file watching..."

    # Start bot in background
    cd "$BOT_DIR"
    python3 "$BOT_SCRIPT" 2>&1 | tee -a "$LOG_FILE" &
    BOT_PID=$!
    echo $BOT_PID > "$PID_FILE"

    echo "Bot started (PID: $BOT_PID). Watching for file changes..."

    # Watch for changes
    while true; do
        inotifywait -q -e modify $WATCH_FILES 2>/dev/null

        if ! kill -0 $BOT_PID 2>/dev/null; then
            echo "[$(date)] Bot died, restarting..."
            python3 "$BOT_SCRIPT" 2>&1 | tee -a "$LOG_FILE" &
            BOT_PID=$!
            echo $BOT_PID > "$PID_FILE"
        else
            echo "[$(date)] File change detected. Bot will pick up changes on next !reload"
        fi
    done
}

case "${1:-}" in
    start)
        start_bot
        ;;
    stop)
        stop_bot
        ;;
    restart)
        restart_bot
        ;;
    status)
        status
        ;;
    logs)
        logs "${2:-50}"
        ;;
    follow)
        follow
        ;;
    run)
        run_forever
        ;;
    watch)
        watch_mode
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs [n]|follow|run|watch}"
        echo ""
        echo "Commands:"
        echo "  start   - Start the bot in background"
        echo "  stop    - Stop the bot"
        echo "  restart - Restart the bot"
        echo "  status  - Check if bot is running"
        echo "  logs    - Show last N lines of log (default 50)"
        echo "  follow  - Follow log output"
        echo "  run     - Run in foreground with auto-restart on crash"
        echo "  watch   - Run with file watching (requires inotify-tools)"
        exit 1
        ;;
esac
