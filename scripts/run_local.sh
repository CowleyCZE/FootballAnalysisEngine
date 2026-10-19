#!/usr/bin/env bash
# Spustí lokální API a autonomní SQLite worker bez placených cloudových služeb.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
PYTHON="${PYTHON:-$ROOT_DIR/.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
# init.sh ukládá konfiguraci mimo zdrojový kód; exportujeme ji pro API i worker.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
HOST="${FAE_API_HOST:-127.0.0.1}"
PORT="${FAE_API_PORT:-8000}"
mkdir -p logs database
"$PYTHON" scripts/init_database.py
"$PYTHON" -m uvicorn app.main:app --host "$HOST" --port "$PORT" >logs/api.log 2>&1 &
API_PID=$!
"$PYTHON" scripts/run_worker.py --worker-id "${FAE_WORKER_ID:-notebook-$(hostname)}" >logs/worker.log 2>&1 &
WORKER_PID=$!
cleanup() { kill "$WORKER_PID" "$API_PID" 2>/dev/null || true; wait "$WORKER_PID" "$API_PID" 2>/dev/null || true; }
trap cleanup INT TERM EXIT
printf 'FootballAnalysisEngine běží: http://%s:%s/health\n' "$HOST" "$PORT"
printf 'Logy: logs/api.log a logs/worker.log (Ctrl+C ukončí oba procesy)\n'
wait -n "$API_PID" "$WORKER_PID"
