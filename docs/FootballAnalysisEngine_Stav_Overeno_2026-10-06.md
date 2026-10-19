# FootballAnalysisEngine — Ověřený stav projektu

**Datum:** 6. 10. 2026  
**Větev:** `fix/part-11-integration`  
**Aktuální lokální ověření:** **65 passed, 0 failed**

## 1. Důležitá interpretace

Zelená testovací sada potvrzuje implementaci a regresní chování testovaných částí. Neznamená automaticky, že jsou v reálném prostředí dostupné SearXNG, Ollama, crawler nebo jiné lokální služby.

Proto jsou níže odděleny:
- **HOTOVO – OVĚŘENO** — implementace existuje a je podpořena testy/reprodukovatelným ověřením.
- **ČÁSTEČNĚ HOTOVO** — významná část je implementována, ale celý cílový tok není prokázán.
- **NEOVĚŘENO** — vyžaduje skutečný acceptance/E2E běh.

## 2. Ověřeně hotové části

| Oblast | Stav | Poznámka |
|---|---|---|
| Match Identity / validace zápasu | HOTOVO – OVĚŘENO | Identity je ověřována před vytvořením pipeline runu. |
| ResearchPlanner | HOTOVO – OVĚŘENO | Povinné/volitelné domény, priority a capabilities jsou zachovány. |
| Atomic ResearchTask → Job dispatch | HOTOVO – OVĚŘENO | ResearchTask a Job se zapisují v jedné SQLite transakci. |
| Worker capability routing | HOTOVO – OVĚŘENO | Worker capability je oddělena od low-level research capabilities. |
| Job lifecycle | HOTOVO – OVĚŘENO | Claim, finish, retry, terminalní stavy a deduplikace jsou testovány. |
| Unified SearchEngine | HOTOVO – OVĚŘENO | Normalizace, deduplikace, relevance, autorita a sportovní filtr. |
| Crawler / parser / document quality | HOTOVO – OVĚŘENO | Obsah, metadata, hash a kvalita dokumentu jsou zpracovávány. |
| Evidence / Claims / cutoff / conflicts | HOTOVO – OVĚŘENO | Evidence-first tok je implementován a testován. |
| Statistics | HOTOVO – OVĚŘENO | Statistická vrstva je pokryta testy. |
| AI evidence-first validace | HOTOVO – OVĚŘENO | Strukturovaný výstup a validace. |
| AI fallback | HOTOVO – OVĚŘENO | Nedostupná Ollama vede k explicitnímu `insufficient_data`, nikoli k vymyšleným datům. |
| Audit | HOTOVO – OVĚŘENO | Auditní kontrola evidence, konfliktů a konzistence. |
| Pipeline state machine | HOTOVO – OVĚŘENO | Centralizované stavy a povolené přechody. |
| Pipeline state history | HOTOVO – OVĚŘENO | Přechody jsou zapisovány do historie. |
| System events | HOTOVO – OVĚŘENO | Lifecycle jobů a stavů vytváří systémové události. |
| SQLite schema / migrations / FK | HOTOVO – OVĚŘENO TESTY | Aktuální testovací sada je zelená. |
| Recovery / scheduler | HOTOVO – OVĚŘENO TESTY | Lifecycle recovery a dependency scheduler jsou testovány. |
| Celá pytest sada | HOTOVO – OVĚŘENO | **65 passed, 0 failed.** |

## 3. Částečně hotové části

### ResearchEngine → skutečný autonomní RESEARCH worker

ResearchEngine již obsahuje tok:

**Query Builder → Search → Source Selection → Crawler → Document Processing → Evidence → Claims → Cutoff/Conflict validation → Persistence**

Jeho integrační testy existují.

Plné produkční napojení skutečného workeru na ResearchEngine však není tímto posledním výsledkem 65/65 samo o sobě prokázáno. Proto tato položka není označena jako kompletní acceptance.

## 4. Neověřené acceptance části

Před označením projektu jako FINAL je nutné skutečně ověřit:

1. SearXNG běží a SearchEngine provede skutečné vyhledávání.
2. Crawler skutečně stáhne vybrané zdroje.
3. Parser vytvoří kvalitní dokumenty a evidence.
4. Ollama běží s podporovaným modelem a AI_ANALYSIS skutečně proběhne.
5. Audit dostane skutečné claims/evidence/statistics a rozhodne PASS/RESEARCH_REQUIRED/UNRESOLVED.
6. Celá pipeline proběhne od Match Identity po COMPLETED/UNRESOLVED bez ručního zásahu.
7. Worker restart, timeout a dočasná nedostupnost lokálních služeb neporuší restart-safe lifecycle.
8. Acceptance test potvrdí autonomní provoz v reálném prostředí.

## 5. Poslední ověřené opravy

- odstranění zdroje SQLite `database is locked` při atomickém dispatchi research tasků,
- zachování dokumentovaných capabilities ResearchPlanneru,
- bezpečný AI fallback při Ollama 404/nedostupnosti,
- explicitní `insufficient_data` bez falešných fotbalových dat,
- bezpečné ukončení pipeline přes audit na `UNRESOLVED`,
- regresní testy pro AI fallback a nedostupnou AI,
- výsledná testovací sada **65/65**.

## 6. Zásada dalšího vývoje

Zelené unit/integration testy nesmí být použity jako náhrada za skutečný acceptance E2E test.

Další změny musí zachovat:
- orchestrátor jako lifecycle source of truth,
- evidence-first přístup,
- cutoff,
- audit,
- žádná falešná fallbacková data,
- idempotentní persistence,
- restart-safe a recovery-safe chování.

