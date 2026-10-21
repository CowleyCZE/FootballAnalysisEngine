#!/usr/bin/env bash
# Interaktivní místní nastavení FootballAnalysisEngine po změně Wi-Fi.
# Nikdy nemění pravidla firewallu ani nezapisuje aplikační token.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

say() { printf '\n== %s ==\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die() { printf 'CHYBA: %s\n' "$*" >&2; exit 1; }
command_exists() { command -v "$1" >/dev/null 2>&1; }
ask_yes_no() {
  local prompt=$1 answer
  read -r -p "$prompt [a/N] " answer
  [[ "$answer" =~ ^([Aa]([Nn][Oo])?|[Yy]([Ee][Ss])?)$ ]]
}

wait_for_http() {
  local url=$1 service=$2 attempt
  for attempt in {1..15}; do
    if curl --fail --silent --show-error --max-time 3 "$url" >/dev/null 2>&1; then
      note "$service je dostupný."
      return 0
    fi
    sleep 2
  done
  note "$service se do 30 sekund nepřipravil; zkontrolujte: cd services/searxng && docker compose logs --tail=100 core"
  return 1
}

check_searx_search() {
  local url="http://127.0.0.1:$SEARX_PORT/search?q=football&format=json&language=all"
  local response
  response="$(mktemp "${TMPDIR:-/tmp}/fae-searx-smoke.XXXXXX")" || return 1
  if ! curl --fail --silent --show-error --max-time 15 "$url" -o "$response"; then
    rm -f "$response"
    note "SearXNG HTTP search endpoint selhal. Zkontrolujte Docker logy; samotná stránka '/' nestačí k ověření enginů."
    return 1
  fi
  "$PYTHON" - "$response" <<'PY'
import json
import sys

try:
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    print(f"  SearXNG vrátil neplatnou JSON odpověď: {exc}")
    raise SystemExit(1)
results = payload.get("results")
if not isinstance(results, list):
    print("  SearXNG JSON neobsahuje pole results; ověřte formát JSON v settings.yml.")
    raise SystemExit(1)
unresponsive = payload.get("unresponsive_engines") or []
names = []
for engine in unresponsive:
    if isinstance(engine, (list, tuple)) and engine:
        name = str(engine[0])
        error = str(engine[1]).split("?", 1)[0][:160] if len(engine) > 1 else "bez detailu"
        names.append(f"{name} ({error})")
    elif isinstance(engine, dict):
        name = str(engine.get("name") or engine.get("engine") or "unknown")
        error = str(engine.get("error") or engine.get("exception") or engine.get("status") or "bez detailu").split("?", 1)[0][:160]
        names.append(f"{name} ({error})")
    else:
        names.append(str(engine))
if results:
    print(f"  SearXNG vyhledávání funguje: {len(results)} raw výsledků.")
else:
    print("  SearXNG endpoint odpovídá, ale testovací dotaz nemá žádné raw výsledky.")
if names:
    print("  Neodpovídající enginy: " + ", ".join(names))
    print("  Zkontrolujte jejich blokace/limity v SearXNG a logy: cd services/searxng && docker compose logs --tail=100 core")
PY
  local status=$?
  rm -f "$response"
  return "$status"
}

is_ipv4() {
  [[ $1 =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  local IFS=. octet
  read -r -a octet <<< "$1"
  for octet in "${octet[@]}"; do (( 10#$octet <= 255 )) || return 1; done
}

say "Repozitář a Python"
[[ -f requirements.txt ]] || die "Skript musí běžet z checkoutu FootballAnalysisEngine."
note "Repozitář: $ROOT_DIR"
note "Větev: $(git branch --show-current 2>/dev/null || printf 'nejde o Git checkout')"
command_exists python3 || die "Je nutný python3."

say "Aktivní LAN připojení"
# Výchozí trasa vybere skutečné LAN rozhraní a vynechá Docker, veth a Tailscale.
ROUTE="$(ip -4 route get 1.1.1.1 2>/dev/null | head -n1 || true)"
LAN_IF="$(awk '{for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}' <<< "$ROUTE")"
GATEWAY="$(awk '{for (i=1;i<=NF;i++) if ($i=="via") {print $(i+1); exit}}' <<< "$ROUTE")"
[[ -n "$LAN_IF" ]] || die "Nenalezena aktivní výchozí IPv4 trasa. Nejprve připojte notebook k Wi-Fi nebo Ethernetu."
case "$LAN_IF" in docker*|br-*|veth*|tailscale*) die "Výchozí trasa vybrala '$LAN_IF', což není běžné LAN rozhraní. Zkontrolujte připojení.";; esac
LAN_CIDR="$(ip -o -4 addr show dev "$LAN_IF" scope global | awk 'NR==1 {print $4}')"
[[ -n "$LAN_CIDR" ]] || die "Rozhraní $LAN_IF nemá globální IPv4 adresu."
LAN_IP="${LAN_CIDR%/*}"; PREFIX="${LAN_CIDR#*/}"
TYPE="Ethernet"; [[ -d "/sys/class/net/$LAN_IF/wireless" ]] && TYPE="Wi-Fi"
note "Připojení: $TYPE přes $LAN_IF"
note "IPv4/podsíť notebooku: $LAN_CIDR"
note "Brána: ${GATEWAY:-trasa ji neuvádí}"
note "Docker/Tailscale nejsou záměrně vybrány jako LAN cesta."

say "Samsung Note 9 (volitelný klient)"
note "Na Note 9 otevřete podrobnosti stejné Wi-Fi a zjistěte jeho IPv4 adresu."
note "Repozitář obsahuje vyhledávací proxy FastAPI na notebooku; nedokazuje, že službu hostuje Note 9."
PHONE_IP=""
read -r -p "IPv4 Note 9 (Enter = přeskočit): " PHONE_IP
if [[ -n "$PHONE_IP" ]]; then
  is_ipv4 "$PHONE_IP" || die "'$PHONE_IP' není platná IPv4 adresa."
  if command_exists ping; then
    if ping -c 1 -W 2 "$PHONE_IP" >/dev/null 2>&1; then note "Telefon odpovídá na ping."; else note "Telefon na ping neodpověděl (Android může ICMP blokovat; samo o sobě nejde o chybu)."; fi
  fi
fi

say "Lokální služby nalezené v repozitáři"
API_PORT="${FAE_API_PORT:-8000}"       # app SearchWorker's documented local proxy default
SEARX_PORT="${SEARXNG_PORT:-8080}"     # services/searxng/docker-compose.yml default
OLLAMA_PORT="${OLLAMA_PORT:-11434}"    # app/workers/ai_worker.py default
OLLAMA_BASE_URL="${OLLAMA_URL:-http://127.0.0.1:${OLLAMA_PORT:-11434}}"   # OLLAMA_URL (dokumentováno v runbooku) má přednost před OLLAMA_PORT
OLLAMA_BASE_URL="${OLLAMA_BASE_URL%/}"
note "FastAPI: http://$LAN_IP:$API_PORT (port lze změnit přes FAE_API_PORT)"
note "SearXNG: http://127.0.0.1:$SEARX_PORT (SEARXNG_PORT)"
note "Ollama:  $OLLAMA_BASE_URL (OLLAMA_URL, výchozí model OLLAMA_MODEL=${OLLAMA_MODEL:-qwen2.5:3b})"
note "Skript na telefonu neotevírá žádný port."

say "Prostředí Pythonu"
if [[ ! -x .venv/bin/python ]]; then
  if ask_yes_no "Vytvořit .venv a nyní nainstalovat závislosti?"; then
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
  else
    die "Pro spuštění API a workeru je nutné virtuální prostředí projektu."
  fi
fi
PYTHON="$ROOT_DIR/.venv/bin/python"
"$PYTHON" -c 'import fastapi, uvicorn; print("Závislosti Pythonu jsou dostupné")' || die "Nainstalujte závislosti příkazem: $PYTHON -m pip install -r requirements.txt"

say "Databáze"
"$PYTHON" scripts/init_database.py
note "Databáze inicializována: database/football.db"

say "SearXNG"
if command_exists docker && docker compose version >/dev/null 2>&1; then
  if ask_yes_no "Spustit nebo obnovit lokální SearXNG z tohoto repozitáře?"; then
    # Keep each user's config stable. The Docker image's default FORCE_OWNERSHIP
    # chowns mounted config to its internal user; the compose file disables that
    # behavior so this user-owned path remains editable on later setup runs.
    SEARXNG_CONFIG_NAME="runtime-config-$(id -u)-managed"
    mkdir -p "services/searxng/$SEARXNG_CONFIG_NAME"
    "$PYTHON" scripts/configure_searxng.py "services/searxng/$SEARXNG_CONFIG_NAME/settings.yml"
    ( cd services/searxng && SEARXNG_CONFIG_DIR="./$SEARXNG_CONFIG_NAME" docker compose up -d )
    # První start stáhne image a inicializuje worker; jednorázová kontrola po
    # dvou sekundách často ještě není vypovídající.
    wait_for_http "http://127.0.0.1:$SEARX_PORT/" "SearXNG" || true
    check_searx_search || true
  fi
else
  note "Docker Compose není dostupný; SearXNG nebyl spuštěn. Docker instalujte či nastavte jen pro živé vyhledávání."
fi

say "Ollama – volitelná AI závislost"
if curl --fail --silent --max-time 2 "$OLLAMA_BASE_URL/api/tags" >/dev/null; then
  note "Ollama je již dostupná."
elif command_exists ollama; then
  note "Ollama je nainstalovaná, ale neodpovídá. Pro AI_ANALYSIS ji spusťte zvlášť: ollama serve"
  note "Model se nestahuje automaticky; výchozí je ${OLLAMA_MODEL:-qwen2.5:3b} (ollama pull ${OLLAMA_MODEL:-qwen2.5:3b}), silnější 7B je pro tento notebook náročný na RAM."
else
  note "Ollama není nainstalovaná. Ověřený fallback enginu pro nedostupnou AI vrátí insufficient_data."
fi

find_terminal_emulator() {
  if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    return 1
  fi
  for term in gnome-terminal konsole xfce4-terminal x-terminal-emulator xterm; do
    if command_exists "$term"; then
      printf '%s' "$term"
      return 0
    fi
  done
  return 1
}

launch_in_new_terminal() {
  local title=$1 cmd=$2 term
  term="$(find_terminal_emulator || true)"
  if [[ -z "$term" ]]; then
    return 1
  fi

  # Bezpečné předání proměnných prostředí bez expozice tokenu v argv/ps
  local env_file
  umask 077
  env_file="$(mktemp "${TMPDIR:-/tmp}/fae_env.XXXXXX")" || return 1
  chmod 600 "$env_file"

  {
    printf 'export ROOT_DIR=%q\n' "$ROOT_DIR"
    if [[ -n "${WORKER_API_TOKEN:-}" ]]; then
      printf 'export WORKER_API_TOKEN=%q\n' "$WORKER_API_TOKEN"
    fi
    if [[ -n "${API_SECRET_TOKEN:-}" ]]; then
      printf 'export API_SECRET_TOKEN=%q\n' "$API_SECRET_TOKEN"
    fi
  } > "$env_file"

  local shell_cmd="source '$env_file' && rm -f '$env_file' && cd '$ROOT_DIR' && $cmd; exec bash"

  case "$term" in
    gnome-terminal)
      gnome-terminal --title="$title" -- bash -c "$shell_cmd" &
      ;;
    konsole)
      konsole -p tabtitle="$title" -e bash -c "$shell_cmd" &
      ;;
    xfce4-terminal)
      xfce4-terminal --title="$title" --command="bash -c \"$shell_cmd\"" &
      ;;
    x-terminal-emulator|xterm)
      "$term" -title "$title" -e bash -c "$shell_cmd" &
      ;;
    *)
      rm -f "$env_file"
      return 1
      ;;
  esac
  return 0
}

say "Spuštění Football Analysis Enginu"
mkdir -p logs
API_BIND=127.0.0.1
if [[ -n "$PHONE_IP" ]] && ask_yes_no "Zpřístupnit ověřené API do LAN pro Note 9?"; then
  [[ -n "${WORKER_API_TOKEN:-${API_SECRET_TOKEN:-}}" ]] || die "Před zpřístupněním chráněných API endpointů nastavte v tomto terminálu WORKER_API_TOKEN nebo API_SECRET_TOKEN."
  API_BIND=0.0.0.0
fi

if curl --fail --silent --max-time 2 "http://127.0.0.1:$API_PORT/health" >/dev/null; then
  note "UPOZORNĚNÍ: FastAPI již odpovídá na portu $API_PORT; nebylo spuštěno podruhé."
  if [[ "$API_BIND" == 0.0.0.0 ]]; then
    note "Běžící API nepřevezme token z tohoto spuštění. Pokud bylo spuštěno bez tokenu nebo se starým tokenem, zastavte ho a spusťte setup znovu."
  fi
else
  API_CMD="\"$PYTHON\" -m uvicorn app.main:app --host \"$API_BIND\" --port \"$API_PORT\" --timeout-keep-alive 65"
  if launch_in_new_terminal "Football Analysis Engine API" "$API_CMD"; then
    note "FastAPI spuštěna v samostatném terminálovém okně."
  else
    note "Grafická relace nebo akceptovatelný emulátor terminálu nejsou k dispozici."
    note "Spouštím API na pozadí jako fallback: nohup $PYTHON -m uvicorn ... > logs/api.log 2>&1 &"
    nohup "$PYTHON" -m uvicorn app.main:app --host "$API_BIND" --port "$API_PORT" --timeout-keep-alive 65 >logs/api.log 2>&1 &
  fi
  wait_for_http "http://127.0.0.1:$API_PORT/health" "FastAPI" || {
    [[ -f logs/api.log ]] && tail -n 80 logs/api.log >&2 || true
    die "FastAPI se nespustila."
  }
fi

if ask_yes_no "Spustit nyní místní worker se všemi schopnostmi?"; then
  if pgrep -f '[s]cripts/run_worker.py' >/dev/null; then
    note "Spouštěč workeru již běží; nebyl spuštěn podruhé."
  else
    WORKER_CMD="\"$PYTHON\" scripts/run_worker.py"
    if launch_in_new_terminal "Football Analysis Engine Worker" "$WORKER_CMD"; then
      note "Worker spuštěn v samostatném terminálovém okně."
    else
      note "Grafická relace nebo akceptovatelný emulátor terminálu nejsou k dispozici."
      note "Spouštím worker na pozadí jako fallback: nohup $PYTHON scripts/run_worker.py > logs/worker.log 2>&1 &"
      nohup "$PYTHON" scripts/run_worker.py >logs/worker.log 2>&1 &
    fi
  fi
fi

say "Kontroly spojení a přesné příkazy"
note "Stav notebooku: curl -fsS http://127.0.0.1:$API_PORT/health"
if [[ "$API_BIND" == 0.0.0.0 ]]; then
  note "Z Note 9 (stejná Wi-Fi): http://$LAN_IP:$API_PORT/health"
  note "Kontrola portu chráněného endpointu: nc -vz $LAN_IP $API_PORT  (spusťte tam, kde je nc dostupné)"
else
  note "API zůstává dostupné jen lokálně. Znovu spusťte skript a LAN zvolte až po nastavení tokenu."
fi
note "Log workeru: tail -f logs/worker.log"
note "Log API: tail -f logs/api.log"
note "Zastavení místních procesů: pkill -f 'uvicorn app.main:app'; pkill -f 'scripts/run_worker.py'"
note "Pravidla firewallu nebyla zkoumána ani měněna. Pokud firewall blokuje zvolený LAN port, nejprve ho zkontrolujte a pravidlo schvalte sami."
