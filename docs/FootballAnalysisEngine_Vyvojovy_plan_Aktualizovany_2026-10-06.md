# FootballAnalysisEngine — Aktualizovaný vývojový plán

**Datum:** 6. 10. 2026  
**Větev:** `fix/part-11-integration`

> Stav je aktualizován podle skutečného kódu a výsledku testů. HOTOVO znamená ověřenou implementaci, nikoli automaticky produkční acceptance.

## Legenda
- ✅ HOTOVO – OVĚŘENO
- ◐ ČÁSTEČNĚ
- ⚠️ NEOVĚŘENO
- ⬜ ZBÝVÁ

## A. Ověřeně splněné body

| Požadavek | Stav | Ověření |
|---|---|---|
| Match Identity / validace zápasu | ✅ | Identity je ověřována před vytvořením pipeline runu. |
| ResearchPlanner – REQUIRED/OPTIONAL domény | ✅ | Implementováno a testováno. |
| ResearchPlanner – priority | ✅ | Implementováno a testováno. |
| ResearchPlanner – capabilities | ✅ | Dokumentované low-level capabilities jsou zachovány. |
| ResearchTask persistence | ✅ | Úlohy jsou persistovány v pipeline runu. |
| Atomic ResearchTask + Job dispatch | ✅ | Jedna SQLite transakce; opraven `database is locked`. |
| Job idempotence / fingerprint | ✅ | Pokryto testy. |
| Job claim / retry / finish | ✅ | Pokryto testy. |
| Worker capability routing | ✅ | Worker capability je oddělena od research capabilities. |
| Unified SearchEngine | ✅ | Jednotná search vrstva. |
| Search normalization | ✅ | Implementováno a testováno. |
| Search deduplication | ✅ | Implementováno a testováno. |
| Relevance / authority | ✅ | Implementováno a testováno. |
| Sport filter | ✅ | Implementováno a testováno. |
| Source selection | ✅ | ResearchEngine vybírá zdroje před crawl. |
| Crawler | ✅ | Implementován a testován. |
| HTML parser / document quality | ✅ | Metadata, text, hash a quality jsou zpracovávány. |
| Evidence extraction | ✅ | Implementováno. |
| Claims | ✅ | Implementováno. |
| Cutoff validation | ✅ | Implementováno a testováno. |
| Conflict detection | ✅ | Implementováno a testováno. |
| Statistics | ✅ | Implementováno a testováno. |
| AI structured schema | ✅ | Pydantic schema + validator. |
| AI evidence-first | ✅ | AI nesmí doplňovat neověřená fakta. |
| AI fallback při nedostupné Ollamě | ✅ | `insufficient_data`; bez falešných dat. |
| Audit | ✅ | Evidence, freshness, konflikty a konzistence. |
| Pipeline state machine | ✅ | Centralizovaný lifecycle. |
| Pipeline state history | ✅ | Přechody se zapisují. |
| System events | ✅ | Lifecycle události se zapisují. |
| Recovery | ✅ | Pokryto testy. |
| Dependency scheduler | ✅ | Pokryto testy. |
| SQLite schema / FK / migrations | ✅ | Aktuální testovací sada je zelená. |
| Plná pytest sada | ✅ | **65 passed, 0 failed.** |

## B. Částečně splněné

### ResearchEngine → skutečný produkční RESEARCH worker
◐ **ČÁSTEČNĚ**

ResearchEngine obsahuje tok:

**Query Builder → Search → Source Selection → Crawler → Document Processor → Evidence → Claims → Validation → Conflict Detection → Persistence**

Existují integrační testy. Plné produkční napojení skutečného workeru na ResearchEngine a celý reálný E2E tok však není výsledkem 65/65 testů prokázán.

## C. Neověřené acceptance body

### Skutečný SearXNG E2E
⚠️ Nutno spustit SearXNG a provést skutečné vyhledávání přes standardní SearchEngine.

### Skutečný crawler/parser E2E
⚠️ Nutno stáhnout skutečný vybraný zdroj a ověřit dokument/evidence persistence.

### Skutečná Ollama E2E
⚠️ Nutno spustit podporovaný lokální model a ověřit úspěšný AI_ANALYSIS → AUDIT tok.

### Kompletní autonomní acceptance
⚠️ Nutno provést celý tok:

**Match Identity → ResearchPlanner → Research Tasks → Search → Source Selection → Crawl/Parse → Evidence/Claims → Statistics → AI → Audit → Finalize**

bez ručního zásahu.

## D. Checklist před FINAL

- ⬜ SearXNG vrací skutečné výsledky.
- ⬜ SearchEngine zpracuje skutečné výsledky.
- ⬜ Source Selection vybere skutečné zdroje.
- ⬜ Crawler stáhne skutečné zdroje.
- ⬜ Parser vytvoří kvalitní dokumenty s metadata/hash.
- ⬜ Evidence/Claims jsou skutečně uloženy.
- ⬜ Cutoff vyřadí nepřípustné informace.
- ⬜ Statistics proběhnou nad reálným kontextem.
- ⬜ Ollama vytvoří validní strukturovaný AI výstup.
- ⬜ Audit ověří skutečný AI výstup proti evidence/claims/statistics.
- ⬜ Pipeline skončí COMPLETED nebo bezpečně UNRESOLVED.
- ⬜ Restart workeru neztratí práci ani nevytvoří duplicity.
- ⬜ Dočasná nedostupnost služby nezpůsobí nekonečné čekání.
- ⬜ Acceptance proběhne bez ručního zásahu.

## E. Zásada proti falešnému dokončení

Samotná existence kódu ani zelený unit test nestačí k označení produkčního požadavku jako FINAL. Požadavky na autonomii, skutečné lokální služby a celý E2E tok musí být dokončeny až po reprodukovatelném acceptance testu.

**Aktuální testovací výsledek: 65 passed, 0 failed.**
