# FootballAnalysisEngine na jiné Wi-Fi (Linux Mint)

Po připojení notebooku a případně Samsungu Note 9 ke stejné Wi-Fi spusťte
z kořene projektu interaktivního pomocníka:

```bash
git switch football-engine
git pull --ff-only
./scripts/network_setup.sh
```

Pomocník zjistí aktivní výchozí rozhraní notebooku, IPv4/CIDR a bránu. Docker,
bridge, veth a Tailscale záměrně odmítne jako výchozí LAN připojení. IPv4
telefonu žádá pouze pro volitelnou kontrolu spojení; repozitář neprokazuje, že
telefon hostuje službu.

## Co repozitář skutečně spouští

1. `scripts/init_database.py` vytvoří či aktualizuje místní SQLite databázi.
2. Volitelný SearXNG Docker Compose poskytuje lokální vyhledávání; výchozí
   adresa repozitáře je `127.0.0.1:8080`.
3. FastAPI se spouští jako `uvicorn app.main:app`; výchozí port místní proxy
   v repozitáři je `8000`.
4. `scripts/run_worker.py` spouští místního pull-based workera.
5. Ollama je volitelná; její výchozí adresa v aplikaci je `127.0.0.1:11434`.
   Pomocník model nestahuje automaticky.

Při prvním spuštění SearXNG vytvoří pomocník ignorovaný soubor
`services/searxng/local-config/settings.yml` a šablonový tajný klíč nahradí
náhodným místním klíčem. Tajné údaje se do Gitu neukládají.

## Přístup z telefonu a bezpečnost

Nechte API dostupné pouze lokálně, pokud ho telefon skutečně nepotřebuje. Při
zvolení LAN přístupu pomocník vyžaduje, aby už byl v terminálu nastaven
`WORKER_API_TOKEN` nebo `API_SECRET_TOKEN`; poté FastAPI naváže na LAN. Novou
hodnotu zvolte lokálně a neukládejte ji do Gitu:

```bash
export WORKER_API_TOKEN='replace-with-a-long-random-secret'
./scripts/network_setup.sh
```

Jediné neověřené endpointy jsou kontroly stavu. Chráněná API volání musí
odesílat `X-Worker-Token` (nebo Bearer token). Skript nemění pravidla
firewallu, nepoužívá `sudo` a neotevírá port na telefonu.

## Užitečné příkazy

```bash
curl -fsS http://127.0.0.1:8000/health
tail -f logs/api.log
tail -f logs/worker.log
pkill -f 'uvicorn app.main:app'
pkill -f 'scripts/run_worker.py'
```

Pokud se SearXNG nepřipraví, použijte:

```bash
cd services/searxng
docker compose logs --tail=100 core
```

Pokud telefon po zpřístupnění LAN nedosáhne na notebook, nejprve ověřte, že
obě zařízení jsou na stejné Wi-Fi a router nemá zapnutou izolaci klientů. Poté
otestujte `http://IP_NOTEBOOKU:8000/health`. Teprve potom ručně prověřte
případné pravidlo firewallu.
