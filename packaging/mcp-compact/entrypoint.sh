#!/bin/bash
# No core/index/library setup; existing installed environment only.
set -eu
if [ -z "${SECRET_KEY:-}" ]; then
    SECRET_FILE="${DATA_DIR:-/app/data}/.secret_key"
    mkdir -p "$(dirname "$SECRET_FILE")"
    if [ ! -f "$SECRET_FILE" ]; then
        (umask 077; head -c 48 /dev/urandom | base64 | tr -d '\n' > "$SECRET_FILE")
    fi
    export SECRET_KEY="$(cat "$SECRET_FILE")"
fi
IDF_EXPORT="${IDF_PATH:-/opt/esp-idf}/export.sh"
test -f "$IDF_EXPORT" || { echo 'Installed IDF export missing; no setup attempted' >&2; exit 1; }
# export.sh is the existing local SDK activation, never install.sh.
# Its own environment/dependency failure stops startup; no healing/fallback.
set +u
. "$IDF_EXPORT"
set -u
nginx -t
uvicorn app.main:app --host 127.0.0.1 --port 8001 --workers 1 &
UVICORN_PID=$!
nginx -g 'daemon off;' &
NGINX_PID=$!
cleanup() {
    trap - TERM INT
    kill -TERM "$UVICORN_PID" "$NGINX_PID" 2>/dev/null || true
    wait "$UVICORN_PID" "$NGINX_PID" 2>/dev/null || true
}
trap cleanup TERM INT
set +e
wait -n "$UVICORN_PID" "$NGINX_PID"
EXIT_CODE=$?
cleanup
exit "$EXIT_CODE"
