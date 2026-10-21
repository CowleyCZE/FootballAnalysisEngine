# Spuštění na Lenovo ThinkBook / Linux Mint 22.3

Projekt je navržen jako **bezplatný lokální systém**. Nepoužívá placenou API ani cloudový model pro predikční jádro. Pro živé informace potřebuje internet, protože vyhledává veřejné zdroje přes lokální SearXNG. Výsledky jsou uloženy v SQLite.

## Co je automatické

Po vytvoření analýzy orchestrátor vytvoří úlohy pro profily domácího a hostujícího týmu, H2H, statistiky, AI syntézu a audit. Worker je průběžně odebírá ze SQLite fronty, provádí retry/recovery a ukládá výsledek. Research worker provádí dotaz → výběr zdroje → crawl → parser → evidence → claims → cutoff/conflict validaci.

## Kompatibilita s přiloženým notebookem

| Komponenta | Stav |
|---|---|
| Intel i5-1135G7, x86_64, 8 GB RAM | Vhodné pro SQLite, FastAPI, crawl, statistiky a lehký lokální model |
| Linux Mint 22.3 / Ubuntu 24.04 základ | Podporovaný prostředím projektu |
| Přesné skóre a statistiky | Fungují i bez Ollama a Dockeru |
| SearXNG | Volitelná lokální služba; potřebná pro automatické živé vyhledávání |
| Ollama | Volitelná lokální AI; výchozí model je `qwen2.5:3b`, vhodnější pro 8 GB RAM než 7B |
| Samsung Note 9 | Volitelný vzdálený worker (zatím **nedostává žádnou práci**, viz níže), ne pro těžkou AI |

Na disku s volným místem kolem 44 GiB je nutné hlídat velikost Ollama modelu a Docker image SearXNG. Model se nestahuje automaticky, aby setup nepřekvapil spotřebou dat a místa.

## Instalace a kontrola

```bash
./init.sh
.venv/bin/python scripts/preflight.py
```

`preflight.py` je read-only kontrola. Chybějící SearXNG nebo Ollama označí jako volitelné; neznamená to chybu predikčního jádra.

Pro lokální autonomní API + worker:

```bash
./scripts/run_local.sh
```

Pro automatické živé vyhledávání spusťte SearXNG přes `scripts/network_setup.sh` (Docker Compose) a ověřte endpoint:

```bash
curl 'http://127.0.0.1:8080/search?q=football&format=json'
```

Pro lokální AI:

```bash
ollama serve
ollama pull qwen2.5:3b
export OLLAMA_MODEL=qwen2.5:3b
```

Výchozí notebookové nastavení je `OLLAMA_TIMEOUT=60` a
`OLLAMA_MAX_RETRIES=1`. Kontext pro 3B model je omezen na 24 claims, 3 důkazy
na claim a 500 znaků výňatku, aby se model na 8GB RAM nezasekl na příliš
velkém promptu. Limity lze změnit v `.env`.

Bez Ollama se AI vrstva bezpečně označí jako `insufficient_data`, ale už
nezablokuje celý běh. Audit uloží varování `ai_analysis_unavailable` a
statistická i přesně-skórová predikce zůstane dostupná. Aplikace v tomto režimu
nevymýšlí žádná náhradní fotbalová fakta.

## Samsung Galaxy Note 9

Telefon je technicky připraven jako úsporný pomocný worker pro `SEARCH`, `CRAWL` a `TEST`. **Aktuální omezení:** orchestrátor vytváří pouze monolitické joby typu `RESEARCH` (search → crawl → evidence → claims probíhá v jednom jobu na notebooku) a samostatné joby `SEARCH`/`CRAWL` nevznikají. Note 9 proto v běžném provozu žádnou práci nedostane; použije se jen pro `TEST` (ověření spojení). Rozdělení researche na `SEARCH`/`CRAWL` joby je zatím nerealizovaný plán. Nehostuje API ani Ollama. Na telefonu v Termuxu:

```bash
pkg update
pkg install python
pip install requests urllib3
export FAE_SERVER_URL='http://IP_NOTEBOOKU:8000'
export WORKER_API_TOKEN='stejný-token-jako-na-notebooku'
python scripts/note9_worker.py
```

Ve výchozím nastavení Note 9 přijímá pouze `TEST`, `SEARCH` a `CRAWL`. To je záměrné: statistiky, audit, orchestraci a Ollama ponechává notebooku. IP adresa se nastavuje přes `FAE_SERVER_URL`, není pevně zapsaná ve zdrojovém kódu. API otevřete do LAN pouze s tokenem a na důvěryhodné domácí síti.

## Důležité omezení

„Zdarma“ zde znamená bez placených API: SearXNG a Ollama běží lokálně, veřejné webové zdroje ale vyžadují internet a mohou měnit dostupnost nebo omezovat crawl. Projekt proto vždy vrací stav, zdroje, cutoff, warnings a audit místo tvrzení, že data existují, pokud je skutečně nezískal.
