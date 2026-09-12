#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
python3 -m uvicorn app:app --host 127.0.0.1 --port 8000 &
PID=$!
sleep 2
python3 -m webbrowser http://127.0.0.1:8000 >/dev/null 2>&1 || true
wait $PID
