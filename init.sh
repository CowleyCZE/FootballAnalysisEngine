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
if [[ ! -f ".env" ]]; then
  cat <<'EOF' > .env
# Konfigurace FootballAnalysisEngine
WORKER_API_TOKEN=change-this-secure-token-in-production
API_SECRET_TOKEN=change-this-secure-token-in-production
FAE_API_PORT=8000
SEARXNG_PORT=8080
OLLAMA_PORT=11434
EOF
  note "Soubor .env vytvořen z výchozí šablony. Upravte token dle potřeby."
else
  note "Soubor .env již existuje."
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
