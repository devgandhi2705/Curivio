#!/bin/bash
set -e

echo "[startup] Curivio starting..."

# Remove nginx default config that may conflict
rm -f /etc/nginx/sites-enabled/default

# Start Python backend in background
echo "[startup] Starting uvicorn backend on 127.0.0.1:8000..."
uvicorn backend.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 1 \
    --log-level info \
    --no-access-log &
UVICORN_PID=$!

# Wait for the backend to be ready (up to 30 seconds)
echo "[startup] Waiting for backend to be ready..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo "[startup] Backend ready after ${i}s"
        break
    fi
    sleep 1
done

# Start nginx in foreground (becomes PID 1 effectively via exec)
echo "[startup] Starting nginx on port 7860..."
exec nginx -g "daemon off;"
