# TODO_OPRAVY – Technický plán a backlog FootballAnalysisEngine

Stav k: 4. listopadu 2026  
Aktuální testovací stav: **743+ passed, 1 warning**  
Referenční rámec: `PROJECT_REPAIR_HANDOFF.md`, běhy M976 až M979 (`Chance Liga`).

---

## 📌 Pravidla vývoje (Mandatorní)
1. **Test-Driven:** Před změnou přečíst modul i testy. Po každém kroku musí `pytest -q` projít zeleně (přidat regresní test nového chování).
2. **Konzistence a integrita:** Žádná vymyšlená ani fallbacková data. Cutoff se nikdy neodvozuje ani neposouvá do budoucnosti.
3. **Schéma:** Změny DB schématu výhradně přes `database/schema.sql` / `research_schema.sql` + `_migrate_legacy_schema`.
4. **Jazyk:** Interní kód, komentáře a dokumentace v češtině/angličtině dle konvence repozitáře.

---

## 🏛️ UZAVŘENÉ FÁZE (Stabilní základ systému)

<details>
<summary><b>Klikněte pro zobrazení dokončených fází 0–8 a 10</b></summary>

- [x] **Fáze 0 – Rozhodnutí o toku:** Uživatel zadal zápas = důvěryhodný match identity (`RESOLVED`). Tok bez `MatchResolver`.
- [x] **Fáze 1 – Propojení vrstev:**
  - AI kontext dostává kompletní výstup statistického modelu (predikce + snapshoty). Prompt zakazuje měnit tip.
  - Audit validuje soulad mezi textem a tipem skóre (`prediction_contradiction` WARNING).
  - API vrací predikci (tip, 1-X-2, xG, top-3 skóre, faktory) a reálné audit nálezy.
- [x] **Fáze 2 – Statistický model v7+tuned:**
  - Výpočet celoligového průměru gólů před cutoffem, normalizace na sílu soupeře (shrinkage).
  - Absenční multiplikátory (jen ověřená data s ≥ 2 zdroji).
  - Striktní ochrana proti úniku budoucích dat (data leakage) před výkopem.
  - Backtest engine s výpočtem Brierova skóre, log-loss a MAE gólů.
  - Normalizace a aliasy týmů v `config/team_aliases.yaml` (Sparta ≠ Sparta B, Zlín = FASTAV Zlín).
  - Fail-closed pravidlo při absenci historie (`INSUFFICIENT_DATA` → `UNRESOLVED`).
- [x] **Fáze 3 – Stabilizace rešerše:**
  - Nezávislé uvolňování jobů v `DependencyScheduler` (terminální stavy SUCCESS/FAILED neblokují pipeline).
  - Spouštění `STATISTICS` po research doménách.
  - Subjekt claimů vázaný na doménu, podpora češtiny a diakritiky v extrakci.
  - Registr zdrojů (`config/source_registry.yaml`) s váhami autority.
- [x] **Fáze 4 – Audit & Konzistence:**
  - Kontrola čerstvosti (freshness) vůči cutoff datu.
  - Generický `ConsistencyChecker` kontrolující bilanci W-D-L, body a gólový diferenciál.
  - Sjednocený `ConflictDetector`.
- [x] **Fáze 5 – Bezpečnost a API:**
  - Zabezpečení API: odmítnutí defaultního tokenu, náhodný token při instalaci.
  - Konfigurace HTTP crawleru, timeoutů a limitů přenosu.
- [x] **Fáze 6–8 – Hygiena testů, úklid mrtvého kódu a dokumentace:**
  - Izolace proměnných prostředí přes `conftest.py` autouse fixture.
  - Rychlé DB fixture šablony (doba běhu celé sady testů < 25 s).
  - Odstraněn veškerý mrtvý kód (staré job modely, nevyužité query buildery, duplicitní routery).
- [x] **Fáze 10 – Zrychlení research pipeline:**
  - Paralelní stahování a paralelní vyhledávání v SearXNG s procesním zámkem rozestupů.
  - Playwright se spouští pouze u stránek vyžadujících JS/SPA render.
  - Odstraněna doména WEATHER (vyhodnocena jako neefektivní šum).
  - Deterministický záložní režim AI (`_deterministic_result`) při selhání LLM.

</details>

---

## 🔴 AKTUÁLNÍ BACKLOG OPRAV A STABILIZACE (Priorita 1)

### 11. Datová integrita a obnova feedů
- [x] **11.33 Oprava selhání aktualizace soutěžních CSV (`csv_data_sync`):** *(hotovo, `pytest -q`: 771 passed; testy `tests/statistics/test_csv_feed_refresh_failures.py`)*
  - *Nález (běh M979):* Varování *„Aktualizace soutěžních CSV selhala; predikce pokračovala s již uloženými daty.“*
  - *Úkol:* Ověřit exekuci `database/data_csv/stahni_chanceliga.py`. Přidat timeout, zachytávání `stderr`, kontrolu návratového kódu a validaci integrity staženého CSV před přepsáním stávajícího. V případě chyby zapsat do logu přesný traceback, ne pouze obecné varování.
  - *Test:* Regresní test simulující síťovou chybu downloaderu a nevalidní CSV formát.
- [x] **11.34 Pokrytí xG a odstranění prázdných metrik (N/A):** *(hotovo, `pytest -q`: 774 passed; import: `xg_backfilled`=1; testy `tests/statistics/test_xg_backfill_and_unsupported.py`. Pokrytí xG v sezóně 2026-2027 ověřeno na reálné DB: 100 % u všech 16 týmů (celohistorické ~16 %, feed má xG jen od 2026-27).)*
  - *Nález:* Metriky `npxg_for_ewma`, `npxg_against_ewma`, `npxgd_ewma` a `game_state_adj_xg` hlásí `N/A (sample 0)`, přičemž xG pokrytí u Bohemians bylo jen 60 %.
  - *Úkol:* 
    1. Pokud zdrojový feed neobsahuje souřadnice střel ani penalty pro výpočet `npxG`, tyto metriky ve výstupech a v menu zřetelně označit jako nepodporované danou ligou (aby nemátly uživatele ani audit).
    2. Doplnit mapování zápasů a chybějící xG záznamy pro venkovní týmy, aby pokrytí dosahovalo ≥ 90 %.
- [x] **11.35 Odstranění pravěké evidence (Stale Evidence 140 000+ hodin):** *(hotovo, `pytest -q`: 778 passed; `app/research/staleness.py`, `ClaimValidator` (`reject_reason=STALE_REJECTED`), `ContextBuilder._drop_stale_evidence`; testy `tests/research/test_stale_evidence_cutoff.py`)*
  - *Nález:* V běhu M979 prošly do systému důkazy ID 15983 a 15984 se stářím přes 16 let.
  - *Úkol:* V `ContextBuilder` a `ResearchEngine` zavést striktní absolutní cutoff: žádný důkaz pro časově senzitivní domény (sestavy, absence, forma, motivace) nesmí být starší než 365 dní. U statických domén (H2H, rivalita) zavést limit 10 let (cca 87 600 h). Starší záznamy automaticky označit jako `STALE_REJECTED`.

### 12. Čištění informačního šumu v rešerši (Search & Extraction Noise)
- [x] **12.1 Blokování politického a komunálního šumu v Brně:** *(hotovo, `pytest -q`: 794 passed; `is_municipal_noise` v `relevance_filter.py`; testy `tests/research/test_municipal_noise.py`)*
  - *Nález:* Do evidence zápasu Artis Brno pronikly články z brněnského magistrátu (*„Budoucí brněnský primátor Hruška chce zlepšit komunikaci...“*).
  - *Úkol:* Do `app/research/relevance_filter.py` doplnit detekci a penalizaci komunální politiky, magistrátních zpráv, dopravních uzavírek a městských zakázek u vyhledávacích dotazů obsahujících město v názvu klubu.
- [x] **12.2 Blokování cizojazyčného právního a sázkového balastu:** *(hotovo, `pytest -q`: 794 passed; `relevance_filter.py`, `EvidenceExtractor(competition=...)`; testy `tests/research/test_foreign_language_noise.py`)*
  - *Nález:* Evidence obsahuje francouzské varování o hazardu (*„Les jeux d’argent et de hasard peuvent être dangereux...“*).
  - *Úkol:* V `HTMLParser` a `EvidenceExtractor` detekovat jazyk extrahovaného fragmentu. Pokud zápas hrají české týmy v Chance Lize, ignorovat odstavce ve francouzštině, španělštině a nizozemštině, pokud nejde o mezinárodní pohár. Rozšířit `BOILERPLATE_MARKERS` o legislativní fráze pro hazard.
- [x] **12.3 Striktní validace rivality a derby (`PAIR_DOMAINS` leak):** *(implementováno: `app/research/rivalry_guard.py`, napojeno v `ResearchEngine` po validaci claimů (`reject_reason` `REJECTED_FOREIGN_DERBY` / `REJECTED_RIVALRY_PAIR`); testy `tests/research/test_rivalry_guard.py` – ověřeno 3. 11. 2026: uživatel `pytest -q` = 799 passed, napojení v `ResearchEngine` zkontrolováno čtením kódu)*
  - *Nález:* V zápase Artis Brno vs. Bohemians se v claimu objevilo „Vršovické derby“ (Bohemians vs. Slavia).
  - *Úkol:* V doméně `RIVALRY` vyžadovat současný výskyt obou konkrétních soupeřů v bezprostředním kontextu tvrzení. Pokud se text zmiňuje o derby, ale druhým subjektem je Slavia místo Artisu, claim musí být okamžitě zamítnut (`REJECTED_FOREIGN_DERBY`).

### 13. AI vrstva a halucinace lokálního LLM
- [x] **13.1 Ochrana proti halucinacím národních týmů:** *(hotovo 3. 11. 2026, nespuštěno u uživatele – ověřit `pytest -q`, očekávám 799 + 7; v pracovní kopii z GitHubu prošlo 749 passed)*
  - *Nález:* AI vygenerovala text *„Česká fotbalová reprezentace bude hrát doma proti reprezentaci Rakouska...“* v ligovém utkání.
  - *Úkol:* 
    1. V `ai_worker.py` doplnit okamžitý validační filtr: Pokud ligový zápas obsahuje tvrzení o národních týmech („reprezentace“, „národní tým“, cizí státy), text se považuje za fatální halucinaci.
    2. Povolit a otestovat vzdálený fallback (11.17 – Groq / OpenAI API) pro případy, kdy lokální model 3B selže nebo začne halucinovat.
  - *Hotovo 3. 11. 2026:* (1) `ai_worker._national_team_mentions` + kontrola v `_compose_result`: zmínka o reprezentaci / národním týmu (CZ i EN, bez diakritiky, i ve faktorech a `uncertainties`) v klubovém zápase zamítne celý AI výstup (`Halucinace národních týmů…`), opravná iterace se nespouští a nastoupí deterministický závěr (11.29); výjimka pro mezinárodní/reprezentační soutěže (kvalifikace, MS, EURO, Nations League, přátelák), prázdná soutěž = klubová (fail-closed). Testy `tests/ai/test_national_team_guard.py` (7). (2) Vzdálený fallback: kód 11.17 je hotový a řízen `FAE_LLM_PROVIDER=groq` + `GROQ_API_KEY`; podle rozhodnutí 1C ze 2. 11. 2026 zůstává vypnutý, tedy beze změny.
- [ ] **13.2 Prezentace rozporu mezi matem. modem a vybraným tipem:**
  - *Nález:* Statistický model uvádí jako nejčetnější stav skóre 1:1 (10,6 %), ale hlavní tip je 1:2 (9,2 %).
  - *Úkol:* V textech predikce zřetelně rozlišit **Mode Score** (nejčastější jednotlivý výsledek) od **Outcome-Consistent Tip** (nejpravděpodobnější skóre v rámci nejpravděpodobnějšího sázkového výsledku 1-X-2: Bohemians 46,2 %). Přidat vysvětlující popisek do API a CLI výstupu.

---

## 🚀 POKROČILÉ FUNKCE PROFESIONÁLNÍHO SYSTÉMU (Priorita 2 & 3)

### 14. Value Betting & Market Integration (+EV Engine)
*Úspěšný predikční systém se nepozná podle toho, že „trefí skóre“, ale podle toho, že dlouhodobě překonává bookmakery.*
- [ ] **14.1 Import tržních kurzů (Odds Feed):**
  - Rozšířit schéma o tabulku `market_odds` (`match_id`, `bookmaker`, `market_type`, `odds_home`, `odds_draw`, `odds_away`, `recorded_at`).
  - Implementovat stahování otevíracích a aktuálních kurzů pro Chance Ligu (přes TheOddsAPI nebo scraping sázkových kanceláří Fortuna/Tipsport/Pinnacle).
- [ ] **14.2 Výpočet očekávané hodnoty (+EV):**
  - Implementovat modul `app/betting/value_finder.py`:
    $$\text{EV} = (P_{\text{model}} \times \text{Kurz}) - 1$$
  - Identifikace hodnotných sázek (např. $\text{EV} > +0.03$, tj. 3% hrana nad trhem).
  - Porovnání modelové pravděpodobnosti s trhem očištěným o marži bookmakera (Shinova metoda nebo rovnoměrné odstranění marže).
- [ ] **14.3 Sledování Closing Line Value (CLV):**
  - Měření kvality predikce vůči uzavíracímu kurzu (Closing Odds) Pinnacle. Pokud model stabilně předbíhá pohyb kurzu (beats the closing line), je matematicky ziskový bez ohledu na krátkodobou smůlu.

### 15. Risk & Bankroll Management (Kellyho kritérium)
- [ ] **15.1 Fractional Kelly Staking Engine:**
  - Implementovat modul `app/betting/staking.py`:
    $$f^* = \frac{b \cdot p - q}{b}$$
    kde $b = \text{kurz} - 1$, $p = \text{modelová pravděpodobnost}$, $q = 1 - p$.
  - Použít konzervativní zlomkové Kellyho kritérium (např. Quarter-Kelly: $0.25 \cdot f^*$).
  - Bezpečnostní stropy: Maximální sázka na jeden zápas (např. 2,5 % celkového bankrollu), stop-loss mechanismus při sérii proher.

### 16. Plně automatizovaný Settlement & Kalibrační smyčka
- [ ] **16.1 Automatický Settlement Worker:**
  - Vytvořit samostatný servis/úlohu, která po odehrání utkání automaticky stáhne oficiální výsledek, zapíše jej do `matches`, vyhodnotí všechny uložené předzápasové predikce a spočítá P&L, Brier Score a log-loss.
- [ ] **16.2 Detekce Model Driftu & Kalibrace:**
  - Sledování klouzavého Brierova skóre a Expected Calibration Error (ECE) za posledních 50 zápasů.
  - Automatické varování při poklesu predikční schopnosti (např. změna trendu průměru gólů v soutěži, zavedení nových pravidel, zimní terény).

### 17. Pokročilé situační faktory (Modern Football Analytics)
- [ ] **17.1 Schedule Congestion & Travel Fatigue:**
  - Kvantifikace odpočinku týmů (počet hodin od posledního soutěžního utkání). Týmy hrající čtvrtek v pohárech a neděli v lize penalizovat na očekávané intenzitě/xG.
- [ ] **17.2 Efekt výměny trenéra („New Manager Bounce“):**
  - Automatická detekce odvolání/jmenování trenéra před zápasem a dočasná úprava nejistoty modelu (zvýšení rozptylu).
- [ ] **17.3 Segmentace standardních situací (Set-Piece vs. Open Play):**
  - Rozdělení xG na šance ze hry a ze standardních situací. Zohlednění silných defenziv při bránění rohů proti slabým útokům ze hry.

---

## 📋 PŘEHLEDNÝ STATUS AKTUÁLNÍCH BĚHŮ

| Zápas | Běh (Run ID) | Výsledek Pipeline | Stav AI | Stav Statistika | Poznámka |
|---|---|---|---|---|---|
| **Artis Brno – Bohemians** | `20261103_192610_M979_73fe` | **COMPLETED** | FALLBACK (selhalo) | SUCCESS (1:2) | AI selhala na Rakousku; CSV update selhal; 16y stará evidence. |
| **Zlín – Slovácko** | `20261102_044903_M976_6f8d` | **COMPLETED** | COMPLETE | SUCCESS (1:1) | Deterministický závěr v pořádku; vyřazen šum z RIVALRY. |
| **Slovácko – Teplice** | `20261030_192701_M944_f8cb` | **COMPLETED** | COMPLETE | SUCCESS (1:1) | Stabilizováno, vyřešeny duplicity týmů. |
