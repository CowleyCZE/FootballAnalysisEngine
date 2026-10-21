# Football Analysis Engine – kompletní návod pro aktuální verzi

Tento návod je určen pro notebook s Linux Mint/Ubuntu, přibližně 8 GB RAM, a aktuální verzi aplikace. Aplikace pracuje lokálně, používá SQLite, SearXNG pro vyhledávání, Ollamu jako volitelnou AI syntézu a statistický model pro přesné skóre.

Důležité: přesný statistický tip nezávisí na Ollamě. Pokud Ollama není dostupná, AI vysvětlení se označí jako `insufficient_data`, ale statistická predikce a audit se dokončí.

## 0. Vždy nejdříve zastavte staré procesy

Toto je první příkaz po otevření terminálu:

```bash
cd ~/FootballAnalysisEngine && ./scripts/stop_all.sh
```

Skript zastaví API, worker, Ollamu a lokální SearXNG. Je bezpečné ho spustit i tehdy, když nic neběží.

Pokud skript ještě nemá právo ke spuštění:

```bash
cd ~/FootballAnalysisEngine && chmod +x scripts/*.sh scripts/*.py
```

## 1. Instalace systémových balíčků

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl unzip sqlite3 git
```

Docker je potřeba pouze pro SearXNG:

```bash
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Po přidání uživatele do skupiny Docker se odhlaste a znovu přihlaste, nebo použijte nový terminál.

## 2. Instalace projektu

Pokud projekt teprve rozbalujete:

```bash
cd ~
unzip ~/Downloads/FootballAnalysisEngine_ollama_fix.zip -d /tmp/fae-install
rm -rf ~/FootballAnalysisEngine
mv /tmp/fae-install/FootballAnalysisEngine ~/FootballAnalysisEngine
cd ~/FootballAnalysisEngine
```

Pokud už projekt existuje, stačí:

```bash
cd ~/FootballAnalysisEngine
```

Nastavte spustitelnost:

```bash
chmod +x init.sh scripts/*.sh scripts/*.py
```

## 3. Vytvoření virtuálního prostředí a základní instalace

```bash
cd ~/FootballAnalysisEngine
./init.sh
```

Skript vytvoří `.venv`, nainstaluje Python závislosti, vytvoří `.env` a inicializuje databázi.

### 3a. Playwright (volitelný renderování JS stránek)

Crawler použije Playwright jako zálohu, když HTTP vrátí málo textu (JS stránky). Bez prohlížeče fallback jen zapíše varování do logu a pokračuje se samotným HTTP:

```bash
cd ~/FootballAnalysisEngine && source .venv/bin/activate
pip install playwright
playwright install chromium
# pokud chybí systémové knihovny: sudo .venv/bin/playwright install-deps chromium
```

## 4. Kontrola konfigurace `.env`

Otevřete konfiguraci:

```bash
cd ~/FootballAnalysisEngine
nano .env
```

Doporučené hodnoty pro notebook s 8 GB RAM:

```env
FAE_API_HOST=127.0.0.1
FAE_API_PORT=8000
SEARXNG_PORT=8080
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_TIMEOUT=60
OLLAMA_MAX_RETRIES=1
FAE_AUTO_HISTORY=1
FAE_HISTORY_CACHE_HOURS=24
FAE_AI_MAX_CLAIMS=24
FAE_AI_MAX_EVIDENCE_PER_CLAIM=3
FAE_AI_MAX_EXCERPT_CHARS=500
```

Pokud `.env` vznikl ve starší verzi a některé řádky chybí, doplňte je jedním příkazem:

```bash
cd ~/FootballAnalysisEngine
cat >> .env <<'EOF'
OLLAMA_TIMEOUT=60
OLLAMA_MAX_RETRIES=1
FAE_AI_MAX_CLAIMS=24
FAE_AI_MAX_EVIDENCE_PER_CLAIM=3
FAE_AI_MAX_EXCERPT_CHARS=500
EOF
```

Předchozí příkaz nepoužívejte opakovaně, jinak vytvoří duplicitní řádky. Lepší varianta pro existující `.env` je:

```bash
cd ~/FootballAnalysisEngine
for line in \
  'OLLAMA_TIMEOUT=60' \
  'OLLAMA_MAX_RETRIES=1' \
  'FAE_AI_MAX_CLAIMS=24' \
  'FAE_AI_MAX_EVIDENCE_PER_CLAIM=3' \
  'FAE_AI_MAX_EXCERPT_CHARS=500'; do
  key="${line%%=*}"
  grep -q "^${key}=" .env || printf '%s\n' "$line" >> .env
done
```

Zkontrolujte hodnoty bez zobrazování tokenů:

```bash
grep -E '^(FAE_API_HOST|FAE_API_PORT|SEARXNG_PORT|OLLAMA_URL|OLLAMA_MODEL|OLLAMA_TIMEOUT|OLLAMA_MAX_RETRIES|FAE_AUTO_HISTORY|FAE_AI_)=' .env
```

## 5. Volitelná instalace a příprava Ollamy

Ollama je potřebná pouze pro textovou AI syntézu. Statistický výpočet přesného skóre funguje i bez ní.

Instalace:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Stažení modelu:

```bash
ollama pull qwen2.5:3b
```

Ruční kontrola:

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

Není nutné spouštět `ollama serve` ručně, protože následující launcher ho otevře v novém terminálu. Pokud Ollama neodpovídá, aplikace po 60 sekundách použije bezpečný AI fallback a nezablokuje přesný statistický tip.

## 6. SearXNG a živé vyhledávání

SearXNG je doporučený pro automatický research týmů. Pokud Docker funguje, zkontrolujte konfiguraci:

```bash
cd ~/FootballAnalysisEngine
./scripts/network_setup.sh
```

Kontrola endpointu:

```bash
curl 'http://127.0.0.1:8080/search?q=football&format=json'
```

Když SearXNG není dostupný, nejde o chybu statistického jádra. Research může mít méně aktuálních zdrojů a aplikace to uvede ve varováních.

## 7. Jedním příkazem spusťte vše v nových terminálech

Toto je doporučený způsob spuštění aktuální verze:

```bash
cd ~/FootballAnalysisEngine && ./scripts/start_all_terminals.sh
```

Launcher automaticky:

1. zastaví staré API, workery, Ollamu a SearXNG,
2. ověří a inicializuje databázi,
3. otevře nové okno pro FastAPI/Uvicorn,
4. otevře nové okno pro SQLite worker,
5. otevře nové okno pro Ollamu, pokud je nainstalovaná,
6. otevře nové okno pro SearXNG, pokud je dostupný Docker.

Launcher vždy používá `.venv/bin/python`. Pokud virtuální prostředí neexistuje,
spustí `init.sh`; pokud v něm chybí `uvicorn`, automaticky doinstaluje
`requirements.txt`. Tím se zabrání chybě:

```text
/usr/bin/python3: No module named uvicorn
```

Launcher před spuštěním kontroluje, zda už API, worker, Ollama nebo SearXNG
běží. Již běžící službu nespouští podruhé, takže se neopakuje chyba:

```text
listen tcp 127.0.0.1:11434: bind: address already in use
```

Při prvním spuštění SearXNG launcher automaticky vytvoří
`services/searxng/.env`, vygeneruje soukromý secret a nastaví runtime
konfiguraci. Varování o chybějícím `services/searxng/.env` se proto nemá objevit.

SearXNG může zobrazit upozornění o vlastnictví bind-mounted adresáře
`/etc/searxng` jako `UNKNOWN:UNKNOWN`. Kontejner i přesto běží a konfigurace je
záměrně ponechaná čitelná pro uživatele notebooku. Upozornění Valkey o memory
overcommit je systémové doporučení; pro jeho odstranění lze jednorázově použít:

```bash
sudo sysctl -w vm.overcommit_memory=1
printf 'vm.overcommit_memory=1\n' | sudo tee /etc/sysctl.d/99-searxng.conf
```

Použití launcheru vyžaduje grafické prostředí s terminálovým emulátorem, například GNOME Terminal, Konsole nebo XFCE Terminal. Pokud žádný podporovaný emulátor není nalezen, skript vypíše ruční příkazy.

Kontrola API:

```bash
curl http://127.0.0.1:8000/health
```

Logy:

```bash
tail -f ~/FootballAnalysisEngine/logs/api.log
tail -f ~/FootballAnalysisEngine/logs/worker.log
tail -f ~/FootballAnalysisEngine/logs/ollama.log
```

## 8. Spuštění menu a zadání zápasu

Otevřete ještě jeden běžný terminál:

```bash
cd ~/FootballAnalysisEngine
.venv/bin/python menu.py
```

V menu použijte:

```text
1. Přidat nový zápas
2. Spustit analýzu pro zápas
3. Zobrazit zápasy s analýzou
4. Zobrazit výsledky analýzy
5. Zkontrolovat stav analýzy
```

Zadejte přesně:

- domácí tým,
- hostující tým,
- soutěž,
- datum a čas zápasu,
- časové pásmo, obvykle `Europe/Prague`.

Po uložení zápasu spusťte analýzu volbou `2`.

## 9. Co aplikace během analýzy provádí

Pipeline postupně provede:

1. profil domácího týmu,
2. profil hostujícího týmu,
3. aktuální formu a poslední výsledky,
4. domácí a venkovní výkonnost,
5. góly, xG a xGA, pokud jsou dostupné,
6. automatické doplnění historických zápasů,
7. H2H historii,
8. absence, sestavy, motivaci a únavu,
9. počasí, rozhodčího, rivalitu a herní styl,
10. výpočet očekávaných gólů,
11. pravděpodobnosti 1-X-2,
12. pravděpodobnostní rozdělení přesných skóre,
13. volitelnou Ollama syntézu,
14. audit cutoffu, konfliktů a zdrojů.

`CONFLICTED` u research domény není automaticky technická chyba. Znamená, že zdroje obsahují rozporná tvrzení. Systém je označí a použije pouze ověřitelnou nebo novější část dat.

## 10. Jak číst výsledek

Za použitelný statistický výsledek považujte zejména tyto položky:

```text
Nejpravděpodobnější skóre: X:Y
Očekávané góly: domácí A | hosté B
Pravděpodobnosti 1-X-2: ...
Historické zápasy ve vzorku: N
model poisson-context-v3
```

Zkontrolujte také, že oba týmy mají nenulový `Sample`, například:

```text
Baník Ostrava   form_points   ...   Sample 5
Sparta Praha    form_points   ...   Sample 5
```

Pokud je `Historické zápasy ve vzorku: 0` nebo má jeden tým `Sample 0`, výsledek je pouze priorní odhad s nízkou důvěrou a je nutné doplnit historii.

Pokud je AI nedostupná, může být výsledek například:

```text
AI analýza: insufficient_data
Důvod: Ollama timeout
Přesný statistický tip: dostupný
```

To není chyba predikčního modelu. Ollama slouží pouze jako vysvětlující textová vrstva.

## 11. Ruční import historických dat

Automatické doplnění je zapnuté přes `FAE_AUTO_HISTORY=1`. Pokud soutěž není v automatickém katalogu, použijte CSV:

```bash
cd ~/FootballAnalysisEngine
.venv/bin/python scripts/import_history_csv.py \
  --csv ~/Downloads/historie.csv \
  --competition 'Česká Chance Liga' \
  --timezone Europe/Prague
```

CSV musí obsahovat datum, domácí tým, hostující tým a konečný výsledek. Běžné názvy sloupců jsou `Date`, `HomeTeam`, `AwayTeam`, `FTHG`, `FTAG`.

## 12. Vyčištění databáze před novým testem

Tento příkaz smaže všechny staré zápasy, běhy, research úlohy a predikce. Nejprve zastavte procesy:

```bash
cd ~/FootballAnalysisEngine
./scripts/stop_all.sh
cp database/football.db database/football_backup_$(date +%Y%m%d_%H%M%S).db 2>/dev/null || true
rm -f database/football.db
.venv/bin/python scripts/init_database.py
```

Potom znovu spusťte vše:

```bash
./scripts/start_all_terminals.sh
```

## 13. Samsung Note 9

Note 9 je volitelný pomocný worker v Termuxu. Je vhodný pro `SEARCH`, `CRAWL` a `TEST`. Na notebooku musí zůstat API, SQLite worker, statistika, audit a Ollama.

Na notebooku zjistěte IP adresu:

```bash
hostname -I
```

Na Note 9 v Termuxu nastavte adresu notebooku a token z `.env`:

```bash
export FAE_SERVER_URL=http://IP_ADRESA_NOTEBOOKU:8000
export WORKER_API_TOKEN=TOKEN_ZE_SOUBORU_ENV
python scripts/note9_worker.py
```

Neposílejte token do veřejných služeb. Note 9 musí být ve stejné důvěryhodné síti jako notebook.

## 14. Zastavení všeho po skončení práce

```bash
cd ~/FootballAnalysisEngine && ./scripts/stop_all.sh
```

Při dalším spuštění vždy začněte znovu tímto příkazem a následně použijte:

```bash
cd ~/FootballAnalysisEngine && ./scripts/start_all_terminals.sh
```

## 15. Diagnostika

Stav API:

```bash
curl -s http://127.0.0.1:8000/health
```

Stav volitelných služeb:

```bash
python3 scripts/preflight.py
```

Poslední chyby workeru:

```bash
grep -E 'ERROR|WARNING|FAILED|timeout|Traceback' logs/worker.log | tail -n 80
```

Pokud se objeví `Max cycles (3) reached`, zkontrolujte auditní důvody a zda není stará verze projektu. Aktuální verze nepoužívá samotné staré důkazy jako důvod k opakování celého výzkumu. Po aktualizaci projektu spusťte nový běh zápasu.

Pokud se objeví `address already in use`, nejprve spusťte:

```bash
cd ~/FootballAnalysisEngine
./scripts/stop_all.sh
./scripts/start_all_terminals.sh
```

Jestli port 11434 stále odpovídá, Ollama pravděpodobně běží jako systémová
služba. To není chyba; launcher ji rozpozná a ponechá běžící instanci.
