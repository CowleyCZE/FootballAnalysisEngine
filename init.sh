#!/usr/bin/env bash
# FootballAnalysisEngine – Skript pro kompletní inicializaci projektu
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

say() { printf '\n== %s ==\n' "$*"; }
note() { printf '  [OK] %s\n' "$*"; }
warn() { printf '  [!] %s\n' "$*"; }
die() { printf 'CHYBA: %s\n' "$*" >&2; exit 1; }

say "1. Kontrola prostředí a adresářové struktury"
command -v python3 >/dev/null 2>&1 || die "Python3 není nainstalován."
note "Python3 nalezen: $(python3 --version)"

mkdir -p logs database data services/searxng/local-config
note "Adresáře logs/, database/, data/ a configuration připraveny."

# Úklid případných chybných 0B souborů v kořenu repozitáře (např. appai__init__.py)
rm -f app*__init__.py 2>/dev/null || true

say "2. Virtuální prostředí Pythonu (.venv)"
if [[ ! -d ".venv" ]]; then
  printf "Vytvářím .venv...\n"
  python3 -m venv .venv
  note "Virtuální prostředí .venv vytvořeno."
else
  note "Virtuální prostředí .venv již existuje."
fi

PYTHON="$ROOT_DIR/.venv/bin/python"
"$PYTHON" -m pip install --upgrade pip --quiet
printf "Instaluji / aktualizuji závislosti z requirements.txt...\n"
"$PYTHON" -m pip install -r requirements.txt --quiet
note "Závislosti v requirements.txt nainstalovány."

say "3. Konfigurace .env"
PLACEHOLDER_TOKEN='change-this-secure-token-in-production'
new_token() { "$PYTHON" -c 'import secrets; print(secrets.token_urlsafe(32))'; }
if [[ ! -f ".env" ]]; then
  API_TOKEN="$(new_token)"
  cat <<EOF > .env
# Konfigurace FootballAnalysisEngine
WORKER_API_TOKEN=${API_TOKEN}
API_SECRET_TOKEN=${API_TOKEN}
FAE_API_PORT=8000
SEARXNG_PORT=8080
OLLAMA_PORT=11434
FAE_AUTO_HISTORY=1
FAE_HISTORY_CACHE_HOURS=24
# Pro 8 GB RAM je vhodnější než 7B; lze změnit na silnější lokální model.
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_TIMEOUT=60
OLLAMA_MAX_RETRIES=1
FAE_AI_MAX_CLAIMS=24
FAE_AI_MAX_EVIDENCE_PER_CLAIM=3
FAE_AI_MAX_EXCERPT_CHARS=500
EOF
  chmod 600 .env
  note "Soubor .env vytvořen s náhodně vygenerovaným API tokenem (stejný token zadejte na Note 9)."
else
  note "Soubor .env již existuje."
  if grep -q "^\(WORKER_API_TOKEN\|API_SECRET_TOKEN\)=${PLACEHOLDER_TOKEN}\$" .env; then
    API_TOKEN="$(new_token)"
    sed -i "s|^WORKER_API_TOKEN=${PLACEHOLDER_TOKEN}\$|WORKER_API_TOKEN=${API_TOKEN}|" .env
    sed -i "s|^API_SECRET_TOKEN=${PLACEHOLDER_TOKEN}\$|API_SECRET_TOKEN=${API_TOKEN}|" .env
    warn "V .env byl výchozí token; nahrazen náhodným. Aktualizujte jej i na Note 9."
  fi
  grep -q '^FAE_AUTO_HISTORY=' .env || printf '\nFAE_AUTO_HISTORY=1\nFAE_HISTORY_CACHE_HOURS=24\n' >> .env
  grep -q '^OLLAMA_TIMEOUT=' .env || printf 'OLLAMA_TIMEOUT=60\nOLLAMA_MAX_RETRIES=1\nFAE_AI_MAX_CLAIMS=24\nFAE_AI_MAX_EVIDENCE_PER_CLAIM=3\nFAE_AI_MAX_EXCERPT_CHARS=500\n' >> .env
  note "Ověřena konfigurace automatického historického importu."
fi

say "4. Inicializace databáze"
"$PYTHON" scripts/init_database.py
note "Databáze database/football.db inicializována."

say "5. Ověření funkčnosti (Test suite)"
if "$PYTHON" -m pytest tests/api/test_server.py --quiet >/dev/null 2>&1; then
  note "Základní testy API prošly úspěšně."
else
  warn "Základní testy API neprošly. Zkontrolujte výstup: .venv/bin/pytest"
fi

say "Inicializace dokončena!"
printf "Pro spuštění API a síťového setupu použijte: ./scripts/network_setup.sh\n\n"
