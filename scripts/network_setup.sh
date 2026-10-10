#!/usr/bin/env bash
# Interactive, local-only setup for moving FootballAnalysisEngine to another Wi-Fi.
# It never changes firewall rules and never writes an application token.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

say() { printf '\n== %s ==\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
command_exists() { command -v "$1" >/dev/null 2>&1; }
ask_yes_no() {
  local prompt=$1 answer
  read -r -p "$prompt [y/N] " answer
  [[ "$answer" =~ ^[Yy]([Ee][Ss])?$ ]]
}

is_ipv4() {
  [[ $1 =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  local IFS=. octet
  read -r -a octet <<< "$1"
  for octet in "${octet[@]}"; do (( 10#$octet <= 255 )) || return 1; done
}

say "Repository and Python"
[[ -f requirements.txt ]] || die "Run this script from a FootballAnalysisEngine checkout."
note "Repository: $ROOT_DIR"
note "Branch: $(git branch --show-current 2>/dev/null || printf 'not a Git checkout')"
command_exists python3 || die "python3 is required."

say "Active LAN connection"
# A route lookup picks the actual default LAN interface, avoiding Docker, veth
# and Tailscale interfaces even when they are up.
ROUTE="$(ip -4 route get 1.1.1.1 2>/dev/null | head -n1 || true)"
LAN_IF="$(awk '{for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}' <<< "$ROUTE")"
GATEWAY="$(awk '{for (i=1;i<=NF;i++) if ($i=="via") {print $(i+1); exit}}' <<< "$ROUTE")"
[[ -n "$LAN_IF" ]] || die "No active IPv4 default route was found. Connect the notebook to Wi-Fi or Ethernet first."
case "$LAN_IF" in docker*|br-*|veth*|tailscale*) die "Default route selected '$LAN_IF', which is not a normal LAN interface. Check the network connection first.";; esac
LAN_CIDR="$(ip -o -4 addr show dev "$LAN_IF" scope global | awk 'NR==1 {print $4}')"
[[ -n "$LAN_CIDR" ]] || die "Interface $LAN_IF has no global IPv4 address."
LAN_IP="${LAN_CIDR%/*}"; PREFIX="${LAN_CIDR#*/}"
TYPE="Ethernet"; [[ -d "/sys/class/net/$LAN_IF/wireless" ]] && TYPE="Wi-Fi"
note "Connection: $TYPE on $LAN_IF"
note "Notebook IPv4/subnet: $LAN_CIDR"
note "Gateway: ${GATEWAY:-not reported by route}"
note "Docker/Tailscale are intentionally not selected as the LAN path."

say "Samsung Note 9 (optional client)"
note "On the Note 9, open Wi-Fi details for the same network and read its IPv4 address."
note "The repository contains a notebook-hosted FastAPI search proxy; it does not prove that the Note 9 hosts a service."
PHONE_IP=""
read -r -p "Note 9 IPv4 (press Enter to skip): " PHONE_IP
if [[ -n "$PHONE_IP" ]]; then
  is_ipv4 "$PHONE_IP" || die "'$PHONE_IP' is not a valid IPv4 address."
  if command_exists ping; then
    if ping -c 1 -W 2 "$PHONE_IP" >/dev/null 2>&1; then note "Phone responds to ping."; else note "Phone did not respond to ping (Android may block ICMP; this alone is not a failure)."; fi
  fi
fi

say "Local services discovered in this repository"
API_PORT="${FAE_API_PORT:-8000}"       # app SearchWorker's documented local proxy default
SEARX_PORT="${SEARXNG_PORT:-8080}"     # services/searxng/docker-compose.yml default
OLLAMA_PORT="${OLLAMA_PORT:-11434}"    # app/workers/ai_worker.py default
note "FastAPI: http://$LAN_IP:$API_PORT (uvicorn port can be overridden with FAE_API_PORT)"
note "SearXNG: http://127.0.0.1:$SEARX_PORT (SEARXNG_PORT)"
note "Ollama:  http://127.0.0.1:$OLLAMA_PORT (OLLAMA_URL may override this in the app)"
note "No port is opened on the phone by this script."

say "Python environment"
if [[ ! -x .venv/bin/python ]]; then
  if ask_yes_no "Create .venv and install requirements now?"; then
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
  else
    die "A project virtual environment is required to start the API and worker."
  fi
fi
PYTHON="$ROOT_DIR/.venv/bin/python"
"$PYTHON" -c 'import fastapi, uvicorn; print("Python dependencies are available")' || die "Install dependencies with: $PYTHON -m pip install -r requirements.txt"

say "Database"
"$PYTHON" scripts/init_database.py
note "Database initialized: database/football.db"

say "SearXNG"
if command_exists docker && docker compose version >/dev/null 2>&1; then
  if ask_yes_no "Start or refresh the repository's local SearXNG stack?"; then
    mkdir -p services/searxng/local-config
    if [[ ! -f services/searxng/local-config/settings.yml ]]; then
      cp services/searxng/core-config/settings.yml services/searxng/local-config/settings.yml
      SECRET="$($PYTHON -c 'import secrets; print(secrets.token_hex(32))')"
      "$PYTHON" - "$SECRET" <<'PY'
from pathlib import Path
import sys
p = Path("services/searxng/local-config/settings.yml")
p.write_text(p.read_text().replace("CHANGE_ME_SEARXNG_SECRET_KEY_ENV_VAR", sys.argv[1]))
PY
      unset SECRET
      note "Created ignored local SearXNG configuration with a generated secret."
    fi
    ( cd services/searxng && SEARXNG_CONFIG_DIR=./local-config docker compose up -d )
    sleep 2
    curl --fail --silent --show-error "http://127.0.0.1:$SEARX_PORT/" >/dev/null && note "SearXNG is reachable." || note "SearXNG was started but is not ready yet; inspect: cd services/searxng && docker compose logs --tail=100 core"
  fi
else
  note "Docker Compose is unavailable; SearXNG was not started. Install/configure Docker only if you want live search."
fi

say "Ollama (optional AI dependency)"
if curl --fail --silent --max-time 2 "http://127.0.0.1:$OLLAMA_PORT/api/tags" >/dev/null; then
  note "Ollama is already reachable."
elif command_exists ollama; then
  note "Ollama is installed but not responding. Start it separately if AI_ANALYSIS is needed: ollama serve"
  note "Do not download a model automatically; the repository defaults to qwen2.5:7b and this laptop has limited RAM."
else
  note "Ollama is not installed. The engine's tested fallback reports insufficient_data for unavailable AI."
fi

say "Start Football Analysis Engine"
mkdir -p logs
API_BIND=127.0.0.1
if [[ -n "$PHONE_IP" ]] && ask_yes_no "Expose the authenticated API to the LAN for the Note 9?"; then
  [[ -n "${WORKER_API_TOKEN:-${API_SECRET_TOKEN:-}}" ]] || die "Set WORKER_API_TOKEN or API_SECRET_TOKEN in this terminal before exposing protected API endpoints."
  API_BIND=0.0.0.0
fi
if curl --fail --silent --max-time 2 "http://127.0.0.1:$API_PORT/health" >/dev/null; then
  note "FastAPI is already responding on port $API_PORT; it was not started twice."
else
  nohup "$PYTHON" -m uvicorn app.main:app --host "$API_BIND" --port "$API_PORT" >logs/api.log 2>&1 &
  API_PID=$!
  sleep 2
  curl --fail --silent --show-error "http://127.0.0.1:$API_PORT/health" >/dev/null || { tail -n 80 logs/api.log >&2 || true; die "FastAPI did not start."; }
  note "FastAPI started (PID $API_PID, log: logs/api.log)."
fi
if ask_yes_no "Start the local all-capabilities worker now?"; then
  if pgrep -f '[s]cripts/run_worker.py' >/dev/null; then
    note "A worker launcher is already running; it was not started twice."
  else
    nohup "$PYTHON" scripts/run_worker.py >logs/worker.log 2>&1 &
    note "Worker started (PID $!, log: logs/worker.log)."
  fi
fi

say "Connectivity checks and exact commands"
note "Notebook health: curl -fsS http://127.0.0.1:$API_PORT/health"
if [[ "$API_BIND" == 0.0.0.0 ]]; then
  note "From Note 9 (same Wi-Fi): http://$LAN_IP:$API_PORT/health"
  note "Protected endpoint port check: nc -vz $LAN_IP $API_PORT  (run where nc is available)"
else
  note "API remains loopback-only. Re-run and choose LAN exposure only after exporting a token."
fi
note "Worker log: tail -f logs/worker.log"
note "API log: tail -f logs/api.log"
note "Stop local launchers: pkill -f 'uvicorn app.main:app'; pkill -f 'scripts/run_worker.py'"
note "Firewall rules were not inspected or changed. If a firewall blocks the chosen LAN port, review it and explicitly approve a rule yourself."
