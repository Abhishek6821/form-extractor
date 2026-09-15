#!/usr/bin/env bash
# Run API + editor locally (no Docker). Ctrl-C stops both.
set -e
cd "$(dirname "$0")"
if [ ! -x backend/.venv/bin/uvicorn ]; then
  python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt
fi
[ -d frontend/node_modules ] || (cd frontend && npm install)
backend/.venv/bin/uvicorn app.main:app --app-dir backend --port 8000 --reload &
API=$!
trap 'kill $API' EXIT
cd frontend && npm run dev
