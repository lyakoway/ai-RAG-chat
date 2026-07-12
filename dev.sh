#!/usr/bin/env bash
# Поднимает backend (:8000) и frontend (:5173) вместе. Ctrl+C останавливает оба.
set -euo pipefail
cd "$(dirname "$0")"

# --- Backend ---
if [ ! -d backend/.venv ]; then
  echo "▶ Создаю venv и ставлю зависимости backend…"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q --upgrade pip
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi

echo "▶ Запускаю backend на http://localhost:8000"
( cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000 ) &
BACK_PID=$!

# --- Frontend ---
if [ ! -d frontend/node_modules ]; then
  echo "▶ Ставлю зависимости frontend…"
  ( cd frontend && npm install )
fi

echo "▶ Запускаю frontend на http://localhost:5173"
( cd frontend && npm run dev ) &
FRONT_PID=$!

trap 'echo; echo "⏹ Останавливаю…"; kill $BACK_PID $FRONT_PID 2>/dev/null || true' INT TERM
wait
