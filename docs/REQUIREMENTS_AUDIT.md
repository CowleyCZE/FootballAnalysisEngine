# Audit požadavků – Linux Mint / ThinkBook / Note 9

## Výsledek

| Požadavek | Stav | Vysvětlení |
|---|---|---|
| Automatické vyhledávání týmových informací | **Ano, s lokálním SearXNG** | ResearchPlanner vytváří úlohy pro profily obou týmů a H2H. ResearchWorker provádí search → crawl → evidence → claims. Pro živý běh musí běžet SearXNG a notebook potřebuje internet. |
| Použití Note 9 | **Zatím ne (jen připraveno)** | Termux worker umí odebírat `SEARCH`, `CRAWL` a `TEST`, ale orchestrátor vytváří jen monolitické `RESEARCH` joby, takže telefon v běžném provozu žádnou práci nedostane (pouze `TEST`). Rozdělení na `SEARCH`/`CRAWL` joby není implementováno. Těžké statistiky, audit a Ollama zůstávají na notebooku. Serverová adresa je nastavitelná přes `FAE_SERVER_URL`. |
| Ollama AI | **Ano, lokální** | `OllamaClient` volá lokální `/api/generate`, AIWorker validuje JSON a používá pouze evidence-first kontext. Výchozí model je `qwen2.5:3b`. |
| Autonomní provoz | **Ano po inicializaci** | SQLite fronta, worker polling, retry, heartbeat, recovery a auditní smyčka jsou implementované. `scripts/run_local.sh` spustí API + worker bez placeného cloudu. |
| Bezplatný provoz | **Ano bez placených API** | SearXNG a Ollama mohou běžet lokálně. Internet a veřejné weby nejsou garantovaná služba; při jejich výpadku se vrací explicitní nedostatek dat. |
| Notebook z přílohy | **Ano pro zamýšlené použití** | i5-1135G7/8GB zvládne SQLite, FastAPI, crawl a predikční model. Ollama používá menší 3B model; Docker/SearXNG a model vyžadují volné místo. |

## Ověření provedené v tomto auditu

- `188 passed` v kompletní pytest sadě.
- `bash -n` prošel pro instalační, síťový i lokální spouštěcí skript.
- `scripts/preflight.py` ověřil Python, FastAPI, HTTPX, Pydantic, YAML a SQLite.
- Note 9 worker byl ověřen s nastavitelnou LAN adresou a schopnostmi `TEST`, `SEARCH`, `CRAWL`.
- V aktuálním sandboxu neběžely SearXNG ani Ollama; preflight je označil jako volitelné nedostupné služby, ne jako chybu predikčního jádra.

## Poctivé omezení

Projekt nemůže garantovat čerstvá fakta bez internetového zdroje a nemůže garantovat, že každý veřejný web dovolí crawl. Záměrně proto nevrací vymyšlené týmové informace. Pokud chybí ověřené claims, AI výsledek je `insufficient_data`.

## Oprava research cutoffu

Některé oficiální klubové a ligové stránky neposílají v HTML datum publikace.
Původní tok je proto všechny zahodil a při běžném zadání zápasu skončil po
osmi neúspěšných research jobech jako `UNRESOLVED`. Nyní platí:

- článek s datem po `data_cutoff_at` je stále striktně vyřazen,
- článek bez data je přijat jako `UNVERIFIED_DATE`,
- související claim dostane sníženou důvěru (0,65 násobek),
- audit zapíše středně závažné varování místo blokující chyby,
- H2H dotazy jsou ověřovány proti oběma názvům týmů,
- týmové dotazy používají mírnější identitní práh, protože článek o jednom týmu přirozeně nemusí uvádět soupeře.

## Pokrytí faktorů přesného skóre

Predikce nyní kombinuje historické výsledky a poslední zápasy s exponenciálním
recency weightingem, domácí/venkovní split, góly, xG a xGA. H2H je záměrně
omezeno na 8 zápasů a maximálně 15 % váhy, takže stará vzájemná bilance
nepřeváží aktuální formu.

Research plán navíc obsahuje volitelné domény `REFEREE`, `RIVALRY`,
`STYLE_MATCHUP`, `MOTIVATION_HOME/AWAY` a `TRAVEL_FATIGUE_HOME/AWAY` vedle
lineupů a počasí. Evidence se extrahuje do claims, ukládá do týmových nebo
zápasových snapshotů a statistický engine ji při dostupnosti převádí na
omezené korekce únavy, motivace, rivality, počasí a stylu. Pokud data nejsou
ověřená nebo nejsou dostupná, korekce se nepoužije.
