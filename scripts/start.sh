#!/usr/bin/env bash
set -euo pipefail

# talos-gateway start script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SERVICE_NAME="talos-gateway"
PID_FILE="/tmp/${SERVICE_NAME}.pid"
LOG_FILE="/tmp/${SERVICE_NAME}.log"
PORT="${TALOS_GATEWAY_PORT:-8000}"
HOST="${TALOS_BIND_HOST:-127.0.0.1}"

source_env_file() {
    local file="$1"
    if [ -f "$file" ]; then
        set -a
        . "$file"
        set +a
    fi
}

source_env_file "$ROOT_DIR/.env"
source_env_file "$ROOT_DIR/.env.local"
source_env_file "$REPO_DIR/.env"
source_env_file "$REPO_DIR/.env.local"

cd "$REPO_DIR"

# Check if already running
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "$SERVICE_NAME is already running (PID: $(cat "$PID_FILE"))"
    exit 0
fi

# Start service
echo "Starting $SERVICE_NAME on port $PORT..."
MODE="${MODE:-${TALOS_ENV:-development}}"
MODE_LOWER="$(printf '%s' "$MODE" | tr '[:upper:]' '[:lower:]')"
case "$MODE_LOWER" in
    dev|development|test)
        DEV_MODE="${DEV_MODE:-true}"
        ;;
    *)
        DEV_MODE="${DEV_MODE:-false}"
        ;;
esac

TALOS_ENV="${TALOS_ENV:-development}" \
TALOS_RUN_ID="${TALOS_RUN_ID:-default}" \
MODE="$MODE" \
DEV_MODE="$DEV_MODE" \
uvicorn main:app --port "$PORT" --host "$HOST" > "$LOG_FILE" 2>&1 &


PID=$!
echo "$PID" > "$PID_FILE"

# Wait for startup
sleep 2

# Verify running
if kill -0 "$PID" 2>/dev/null; then
    echo "✓ $SERVICE_NAME started (PID: $PID, Port: $PORT)"
else
    echo "✗ $SERVICE_NAME failed to start. Check $LOG_FILE"
    exit 1
fi
