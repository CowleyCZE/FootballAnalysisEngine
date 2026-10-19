#!/usr/bin/env bash
# Zastaví procesy FootballAnalysisEngine, Ollama a lokální SearXNG.
set -u
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

stop_pattern() {
  local pattern="$1"
  pkill -TERM -f "$pattern" 2>/dev/null || true
}

stop_pattern "uvicorn app.main:app"
stop_pattern "scripts/run_worker.py"
stop_pattern "run_worker.py --worker-id"
stop_pattern "$ROOT_DIR/scripts/run_local.sh"
stop_pattern "ollama serve"

if command -v docker >/dev/null 2>&1 && [[ -f "$ROOT_DIR/services/searxng/docker-compose.yml" && -f "$ROOT_DIR/services/searxng/.env" ]]; then
  (cd "$ROOT_DIR/services/searxng" && docker compose down --remove-orphans >/dev/null 2>&1) || true
fi

sleep 1
printf 'FootballAnalysisEngine, Ollama a SearXNG byly zastaveny (pokud běžely).\n'
