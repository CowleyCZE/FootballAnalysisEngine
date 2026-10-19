#!/usr/bin/env bash
# Spustí celý lokální stack v samostatných terminálech.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

"$ROOT_DIR/scripts/stop_all.sh"

PYTHON="${PYTHON:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  printf 'Virtuální prostředí nebo jeho Python chybí. Spouštím init.sh...\n'
  "$ROOT_DIR/init.sh"
  PYTHON="$ROOT_DIR/.venv/bin/python"
fi
if [[ ! -x "$PYTHON" ]] || ! "$PYTHON" -c 'import uvicorn' >/dev/null 2>&1; then
  printf 'Doplňuji Python závislosti do virtuálního prostředí...\n'
  "$PYTHON" -m pip install -r "$ROOT_DIR/requirements.txt" --quiet
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

"$PYTHON" scripts/init_database.py
mkdir -p logs

open_terminal() {
  local title="$1"
  local command_text="$2"
  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="$title" -- bash -lc "$command_text; printf '\n[$title] skončeno. Stiskněte Enter.\n'; read -r"
  elif command -v konsole >/dev/null 2>&1; then
    konsole --new-tab -p tabtitle="$title" -e bash -lc "$command_text; printf '\n[$title] skončeno. Stiskněte Enter.\n'; read -r" &
  elif command -v xfce4-terminal >/dev/null 2>&1; then
    xfce4-terminal --title="$title" --command="bash -lc '$command_text; read -r'" &
  elif command -v x-terminal-emulator >/dev/null 2>&1; then
    x-terminal-emulator -e bash -lc "$command_text; read -r" &
  else
    printf 'Nenalezen terminálový emulátor pro okno %s. Spusťte ručně:\n%s\n' "$title" "$command_text"
  fi
}

API_PORT="${FAE_API_PORT:-8000}"
if curl --fail --silent --max-time 2 "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
  printf 'FAE API již běží na portu %s; druhé instance nebyla spuštěna.\n' "$API_PORT"
else
  open_terminal "FAE API" "cd '$ROOT_DIR'; set -a; source .env 2>/dev/null || true; set +a; '$PYTHON' -m uvicorn app.main:app --host \"\${FAE_API_HOST:-127.0.0.1}\" --port \"\${FAE_API_PORT:-8000}\" 2>&1 | tee logs/api.log"
fi

if pgrep -af "$ROOT_DIR/scripts/run_worker.py" >/dev/null 2>&1; then
  printf 'FAE Worker již běží; druhá instance nebyla spuštěna.\n'
else
  open_terminal "FAE Worker" "cd '$ROOT_DIR'; set -a; source .env 2>/dev/null || true; set +a; exec '$PYTHON' scripts/run_worker.py --worker-id notebook-\$(hostname) 2>&1 | tee logs/worker.log"
fi

OLLAMA_URL_VALUE="${OLLAMA_URL:-http://127.0.0.1:11434}"
if curl --fail --silent --max-time 2 "${OLLAMA_URL_VALUE%/}/api/tags" >/dev/null 2>&1; then
  printf 'Ollama již běží na %s; druhá instance nebyla spuštěna.\n' "$OLLAMA_URL_VALUE"
elif command -v ollama >/dev/null 2>&1; then
  open_terminal "Ollama" "ollama serve 2>&1 | tee '$ROOT_DIR/logs/ollama.log'"
else
  printf 'Ollama není nainstalována; statistická predikce bude fungovat, AI vrstva použije bezpečný fallback.\n'
fi

if command -v docker >/dev/null 2>&1 && [[ -f "$ROOT_DIR/services/searxng/docker-compose.yml" ]]; then
  SEARX_DIR="$ROOT_DIR/services/searxng"
  SEARX_CONFIG_NAME="runtime-config-$(id -u)-managed"
  mkdir -p "$SEARX_DIR/$SEARX_CONFIG_NAME"
  "$PYTHON" scripts/configure_searxng.py "$SEARX_DIR/$SEARX_CONFIG_NAME/settings.yml" >/dev/null
  touch "$SEARX_DIR/$SEARX_CONFIG_NAME/limiter.toml"
  SEARX_ENV="$SEARX_DIR/.env"
  grep -q '^SEARXNG_PORT=' "$SEARX_ENV" 2>/dev/null || printf 'SEARXNG_PORT=%s\n' "${SEARXNG_PORT:-8080}" >> "$SEARX_ENV"
  grep -q '^SEARXNG_HOST=' "$SEARX_ENV" 2>/dev/null || printf 'SEARXNG_HOST=\n' >> "$SEARX_ENV"
  grep -q '^SEARXNG_CONFIG_DIR=' "$SEARX_ENV" 2>/dev/null || printf 'SEARXNG_CONFIG_DIR=./%s\n' "$SEARX_CONFIG_NAME" >> "$SEARX_ENV"
  SEARX_PORT="${SEARXNG_PORT:-8080}"
  if curl --fail --silent --max-time 2 "http://127.0.0.1:${SEARX_PORT}/" >/dev/null 2>&1; then
    printf 'SearXNG již běží na portu %s; druhá instance nebyla spuštěna.\n' "$SEARX_PORT"
  else
    open_terminal "SearXNG" "cd '$SEARX_DIR'; docker compose --env-file .env up"
  fi
else
  printf 'Docker/SearXNG není dostupný; živé vyhledávání může používat jiný nakonfigurovaný zdroj.\n'
fi

printf '\nStack byl spuštěn v samostatných terminálech. API: http://127.0.0.1:%s/health\n' "${FAE_API_PORT:-8000}"
printf 'Pro zastavení všeho: %s\n' "$ROOT_DIR/scripts/stop_all.sh"
