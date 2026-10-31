#!/usr/bin/env bash
# PawPath 개발 서버 실행: 백엔드(8000)와 프론트엔드(5173)를 함께 띄운다. Ctrl+C로 함께 종료한다.
set -euo pipefail
for tool in uv node npm; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "Required tool '$tool' was not found. Install uv and Node.js 20+ first." >&2
    exit 1
  }
done
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

(cd "$ROOT/backend" && uv sync --quiet)
[ -d "$ROOT/frontend/node_modules" ] || (cd "$ROOT/frontend" && npm install --no-audit --no-fund)

(cd "$ROOT/backend" && exec uv run uvicorn app.main:app --port 8000) &
API_PID=$!
(cd "$ROOT/frontend" && exec npm run dev) &
WEB_PID=$!
trap 'kill "$API_PID" "$WEB_PID" 2>/dev/null || true' EXIT INT TERM

echo "PawPath: http://localhost:5173  /  API 문서: http://localhost:8000/docs"
wait
