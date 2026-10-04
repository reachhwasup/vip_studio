#!/bin/sh
# Stop the Short Drama Downloader started with ./start.sh.

cd "$(dirname "$0")" || exit 1

PID_FILE=".app.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "Not running (no $PID_FILE). If you started it by hand, press Ctrl+C in that terminal."
    exit 0
fi

read -r PID PORT < "$PID_FILE"

if [ -z "$PID" ] || ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Not running (it had already stopped)."
    exit 0
fi

# Only stop the process if it really is this app, in case the pid was reused.
case "$(ps -o command= -p "$PID" 2>/dev/null)" in
    *app.py*) ;;
    *)
        rm -f "$PID_FILE"
        echo "Pid $PID is not the downloader any more; nothing stopped."
        exit 0
        ;;
esac

kill "$PID" 2>/dev/null

i=0
while [ "$i" -lt 20 ] && kill -0 "$PID" 2>/dev/null; do
    sleep 0.25
    i=$((i + 1))
done

if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null
    sleep 0.5
fi

rm -f "$PID_FILE"
echo "Stopped (pid $PID, port $PORT)."
