#!/bin/sh
# Start the Short Drama Downloader in the background.
# Usage: ./start.sh [port]      (default port 5055; macOS AirPlay already uses 5000)

cd "$(dirname "$0")" || exit 1

PORT="${1:-5055}"
PID_FILE=".app.pid"
LOG_FILE="app.log"
URL="http://127.0.0.1:$PORT"

if [ -f "$PID_FILE" ]; then
    read -r OLD_PID OLD_PORT < "$PID_FILE"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Already running (pid $OLD_PID): http://127.0.0.1:$OLD_PORT"
        exit 0
    fi
    rm -f "$PID_FILE"
fi

if lsof -nP -iTCP@127.0.0.1:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Port $PORT is already in use by another program. Try: ./start.sh <other port>"
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found. Install Python 3 first."
    exit 1
fi

# The page is opened below once the server answers, so the app need not open it itself.
OPEN_BROWSER=0 nohup python3 app.py "$PORT" >> "$LOG_FILE" 2>&1 &
PID=$!
echo "$PID $PORT" > "$PID_FILE"

i=0
while [ "$i" -lt 30 ]; do
    if ! kill -0 "$PID" 2>/dev/null; then
        rm -f "$PID_FILE"
        echo "The app stopped right after starting. Last lines of $LOG_FILE:"
        tail -n 15 "$LOG_FILE"
        exit 1
    fi
    if curl -s -o /dev/null -m 2 "$URL/"; then
        echo "Started (pid $PID): $URL"
        echo "Log: $(pwd)/$LOG_FILE    Stop with: ./stop.sh"
        [ "${OPEN_BROWSER:-1}" != "0" ] && command -v open >/dev/null 2>&1 && open "$URL"
        exit 0
    fi
    sleep 0.5
    i=$((i + 1))
done

echo "Started (pid $PID) but it is not answering yet at $URL. Check $LOG_FILE."
exit 1
