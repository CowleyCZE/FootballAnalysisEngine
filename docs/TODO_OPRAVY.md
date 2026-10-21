# TODO_OPRAVY – kompletní seznam oprav FootballAnalysisEngine

Stav k 20. 10. 2026. Podklad: `PROJECT_REPAIR_HANDOFF.md`, `postup_oprav.txt`, `pytest -q` = 188 passed.
Čísla v závorce `(H#n)` odkazují na body v sekci 5 handoff dokumentu.

## Pravidla (platí pro každý bod)
1. Před změnou přečti modul **i jeho testy** (testy často kodifikují záměr).
2. Po každém bodu: `pytest -q` musí zůstat zelený (≥188 passed) + přidat regresní test nového chování.
3. Odškrtni `[x]` a připiš datum + stručně co se změnilo (řádek „Hotovo:“).
4. Žádné fallback/vymyšlená data, cutoff se nikdy neodvozuje, audit se neslabí kvůli testu.
5. Změny schématu jen přes `database/schema.sql` / `research_schema.sql` + `_migrate_legacy_schema`.
6. Komentáře a komunikace česky.

---

## FÁZE 0 – Rozhodnutí
- [x] **A6 – model „uživatel zápas zadal = důvěryhodný“ ponechán** (rozhodl uživatel).
  - *Jak:* Ponechat auto-`RESOLVED` v `orchestrator._get_match_identity_from_id` a test `test_fail_closed_status_checks` beze změny. Doplnit komentář do kódu a opravit README (MatchResolver není v produkčním toku; schéma toku).
  - *Hotovo:* 20. 10. 2026 – komentář v `orchestrator.py`, README (tok bez MatchResolveru, model v4). Kód ani test nezměněn.

## FÁZE 1 – Propojení statistiky s AI, auditem a API (největší přínos)
- [x] **1.1 AI kontext dostane výstup statistiky (H#1).**
  - *Jak:* V `app/ai/context_builder.py` (`build_context`) a `app/workers/ai_worker.py` načíst `match_predictions` (nejnovější pro `match_id`) + `statistical_snapshots` a předat jako `statistics`. Prompt: AI tip **nesmí měnit**, jen vysvětlit. Test: kontext obsahuje predikci; `data_quality` se nesnižuje, je-li predikce přítomná.
  - *Hotovo:* 20. 10. 2026 – `ContextBuilder.load_prediction_from_db` / `load_snapshots_from_db` / `load_statistical_output` (predikce stejného běhu, jinak nejnovější s `data_cutoff_at` ≤ cutoff; nikdy pozdější), výsledek jde do `statistics["prediction"]` a `statistics["snapshots"]` jen při DB načtení (explicitní `statistics` se nepřepisují). `ai_worker.py`: prompt zakazuje tip měnit. Nové testy `tests/ai/test_ai_statistics_context.py` (6). **Pozor:** `pytest -q` jsem neměl jak spustit (jen přístup k souborům) – před dalším bodem ověřit ≥ 194 passed. Poznámka k 1.3: `prior_only` a `factors` se do `match_predictions` neukládají (jen v návratu `run_statistics`), pro API bude potřeba přidat sloupec `factors_json` přes `schema.sql` + `_migrate_legacy_schema`.
- [x] **1.2 Audit vidí predikci (H#1).**
  - *Jak:* `app/workers/audit_worker.py` / `app/audit/auditor.py` – předat predikci do `ConsistencyChecker`; kontrola, že AI text neodporuje tipu (jen WARNING). Test se zinscenovanou nekonzistencí.
  - *Hotovo:* 20. 10. 2026 – `AuditWorker` načte predikci přes `ContextBuilder.load_statistical_output` (jen s explicitním cutoffem) a předá ji v `statistics["prediction"]`; `ConsistencyChecker.check_prediction_consistency` hlásí `prediction_contradiction` (WARNING, bez výzkumu, nesnižuje skóre auditu), když AI `conclusion`/`key_factors` uvádí jiné skóre než tip – jen ve větách s klíčovými slovy (tip, predikce, očekává, skončí…), časy a historická skóre se ignorují. `auditor.py` beze změny. Nové testy `tests/audit/test_audit_prediction_consistency.py` (8) → očekáváno 202 passed (nespuštěno).
- [x] **1.3 API vrací tip skóre (H#2).**
  - *Jak:* `GET /api/analysis/{run_id}/result` (`app/api/server.py`) doplnit pole `prediction` (nejpravděpodobnější skóre, očekávané góly, 1-X-2, model, počty vzorků, `prior_only`). Test přes TestClient.
  - *Hotovo:* 20. 10. 2026 – `match_predictions.factors_json` (schema.sql + `_ensure_column`), engine ho ukládá; `ContextBuilder.load_prediction_from_db(..., same_run_only=True)` + pole `prediction` v API (None bez predikce; `prior_only` None u starých záznamů bez factors; obsahuje i `top_scores` top-3 → API část 1.5 hotová). Testy `tests/api/test_api_prediction.py` (6) → očekáváno 208 passed (nespuštěno).
- [x] **1.4 `audit_issues` v API nejsou prázdné (H#3).**
  - *Jak:* `AdversarialAuditor.audit` přijme pipeline `run_id` (je v payloadu AUDIT jobu) a ukládá ho do `audit_runs.run_id`; API dotaz podle téhož. Test: po auditu s nálezem API vrátí issue.
  - *Hotovo:* 20. 10. 2026 – `audit(..., pipeline_run_id=)`; `audit_runs.run_id` = pipeline run, `audit_id` = uuid auditu; `AuditWorker` předáv `payload["run_id"]`; API vrací nálezy posledního auditu daného běhu. Testy `tests/api/test_api_audit_issues.py` (3).
- [x] **1.5 Top-3 skóre v API a menu (H#8).**
  - *Jak:* Z `score_probabilities` vzít top-3, přidat do `prediction` a do výpisu v `menu.py` (volba 4).
  - *Hotovo:* 20. 10. 2026 – API `prediction.top_scores` (viz 1.3); `menu.py` vol. 4: „Top-3 skóre“ + upozornění na `prior_only`. Test `tests/test_menu_prediction.py` (1). Celkem očekáváno 212 passed (nespuštěno).

## FÁZE 2 – Přesnost modelu (`app/statistics/`)
- [x] **2.1 Ligový průměr gólů ze celé ligy (H#7).**
  - *Jak:* V `engine.py` dotaz na průměr gólů všech zápasů soutěže ≤ cutoff; předat do `ExactScorePredictor.predict`. Fallback na stávající výpočet jen při prázdné lize (a označit v `factors`). Test s třemi týmy.
  - *Hotovo:* 20. 10. 2026 – kód už existoval (`StatisticsRepository.get_league_goal_stats`, `engine.py` předává `league_stats`, `ExactScorePredictor` má `MIN_LEAGUE_MATCHES=5` a ve `factors` `league_mean_source`/`league_matches`); chyběly testy → `tests/statistics/test_league_stats_and_leakage.py` (4: celá liga, jiná soutěž/po výkopu se nepočítá, prázdná liga, fallback `default`, engine ukládá factors). Očekáváno 216 passed (nespuštěno – ověřit `pytest -q`).
- [x] **2.2 Síla soupeře (H#8).**
  - *Jak:* Útok/obrana týmu normalizovat na ligový průměr a na kvalitu soupeřů (iterativně 2–3 kroky, shrinkage k 1,0). Zvednout verzi modelu na `v5`, aktualizovat testy verze.
  - *Hotovo:* 20. 10. 2026 – `ExactScorePredictor.opponent_ratings` (3 iterace, shrinkage 5 pseudo-zápasů k 1,0, meze 0,6–1,6), `_team_value` dělí góly sílou soupeře, `predict(..., league_rows=)`; `StatisticsRepository.get_league_matches` (jen ≤ cutoff a před výkopem); `factors.opponent_adjusted`; `MODEL_VERSION = poisson-dc-context-v5`. Testy `tests/statistics/test_opponent_strength.py` (7) → očekáváno 223 passed (nespuštěno). Pokud nějaký starý test tvrdí `v4`, změnit na `v5` (README/runbook → 8.1, 8.3).
- [x] **2.3 Absence a sestavy (H#8).**
  - *Jak:* V `research_context.py` použít jen ověřené claims (min. 2 zdroje / validní cutoff); multiplikátor omezit (např. 0,92–1,05) a zapsat do `factors`. Bez claims = beze změny.
  - *Hotovo:* 20. 10. 2026 – `ResearchContextMapper._absence_context`: jen `availability_status` fakta s datem zdroje i evidence ≤ cutoff (bez data = vyřazeno) a ≥ 2 různými vydavateli; UNAVAILABLE/SUSPENDED váha 1, DOUBTFUL 0,5; útočný multiplikátor 1−0,02·váha (min 0,92), obranný 1+0,01·váha (max 1,05). `ExactScorePredictor` zapisuje `factors.context_multipliers` (jen když se liší od 1). Testy `tests/statistics/test_absence_context.py` (5) → očekáváno 228 passed (nespuštěno). Pozn.: české absence v `ClaimBuilder` se zatím nerozpoznávají → bod 3.4.
- [x] **2.4 Únik dat u backtestu (H#9).**
  - *Jak:* V načtení historie vyloučit `scheduled_at ≥ kickoff` cílového zápasu; test: cílový zápas není ve vzorku.
  - *Hotovo:* 20. 10. 2026 – `before_kickoff` v `get_team_recent_matches`/`get_head_to_head`/`get_league_goal_stats` už v kódu byl; regresní test (zápas po výkopu a před cutoffem není ve vzorku: `home_history_matches == 4`, `sample_size == 8`) je v `test_league_stats_and_leakage.py`.
- [x] **2.5 Backtest skript.**
  - *Jak:* `scripts/backtest.py` – pro odehrané zápasy z historie spočítat predikci k datu před výkopem a vypsat přesnost skóre, 1-X-2, log-loss. Jen čtení DB.
  - *Hotovo:* 20. 10. 2026 – `scripts/backtest.py` (`run_backtest`, `main`; volby `--db --competition --min-history --limit`): DB se otvírá `mode=ro` (bez `initialize_database`), predikce jen z dat před výkopem, vypíše přesné skóre, 1-X-2, log-loss, MAE gólů a základny (vždy domácí, rovnoměrně). Testy `tests/test_backtest.py` (3, vč. kontroly nezměněného hashe DB) → očekáváno 231 passed (nespuštěno). Spuštění: `python scripts/backtest.py --db database/football.db`.
- [x] **2.6 Fuzzy slučování týmů (H#10).**
  - *Jak:* `history_autofill._team_id` – přesná normalizovaná shoda + tabulka aliasů (`config/team_aliases.yaml`); substring shoda zrušit. Test: „Sparta Praha“ ≠ „Sparta Praha B“.
  - *Hotovo:* 20. 10. 2026 – `canonical_team_key` / `resolve_team_key` (bez diakritiky, interpunkce a předpon FC/FK/AC…, „B“ a „U19“ se zachovává), `config/team_aliases.yaml`, `_team_id` jen přesná shoda klíče (bez substringu). Testy `tests/statistics/test_team_matching.py` (5). Ověřeno: `pytest -q` = 236 passed (2.5 ověřeno také).
- [x] **2.7 Chování bez historie (H#11).**
  - *Jak:* Sjednotit `COMPLETED_WITH_PRIOR` vs `INSUFFICIENT_DATA` (jedno pravidlo, zdokumentovat v README), upravit `test_reg_6` podle zvoleného pravidla.
  - *Hotovo:* 20. 10. 2026 – zvoleno `INSUFFICIENT_DATA` => `UNRESOLVED` (fail-closed; engine už tak vracel při nulové i jednostranné historii). `orchestrator._is_statistics_data_sufficient`: mrtvá větev přijímající `COMPLETED_WITH_PRIOR` nahrazena explicitním odmítnutím + odmítnutí `prediction.factors.prior_only`. `test_reg_6` již pravidlo kodifikoval (beze změny). README: pravidlo + oprava toku bez MatchResolveru a model `v5` (to, co A6/8.1 hlásily, v README ve skutečnosti nebylo – opraveno teď; 8.1 tedy zbývá jen počet testů). Nové testy `tests/test_no_history_rule.py` (4) → očekáváno 240 passed (nespuštěno – ověřit `pytest -q`).

## FÁZE 3 – Stabilizace researchu
- [x] **3.1 Kaskádové selhání závislostí (H#5).**
  - *Jak:* `app/jobs/` scheduler: závislost splněna při **terminálním** stavu (SUCCESS/FAILED/NO_RESULT), ne jen úspěchu. Test: selhaný home profil neblokuje away.
  - *Hotovo:* 20. 10. 2026 – `app/orchestrator/scheduler.py` (`DependencyScheduler`, ne `app/jobs/`): blokovaný job se uvolní, jakmile jsou všechny závislosti SUCCESS/FAILED/CANCELLED; kaskádové `FAILED "Dependency failed"` odstraněno. Povinný selhaný job dál ruší pipeline (`_are_all_required_jobs_successful`). Testy `tests/orchestrator/test_dependency_scheduler.py` (3) → očekáváno 243 passed (nespuštěno). Pokud některý starý test očekával kaskádové selhání („Dependency failed“), je třeba ho upravit.
- [x] **3.2 STATISTICS po research doménách (H#6).**
  - *Jak:* Přidat do `job_dependencies` STATISTICS → relevantní research joby (terminální stav stačí, timeout). Test pořadí.
  - *Hotovo:* 20. 10. 2026 – 3.1 ověřeno (243 passed). `ResearchPlanner.create_plan`: STATISTICS závisí na všech taskích kromě týmových profilů; uvolňuje se při terminálním stavu (díky 3.1), zaseklou závislost ukončí recovery timeout. Testy `tests/orchestrator/test_statistics_dependencies.py` (2) → očekáváno 245 passed (nespuštěno). Pozor na staré testy, které claimují STATISTICS hned po startu.
- [x] **3.3 Subjekt claimů (H#14).**
  - *Jak:* `ResearchEngine` – subjekt podle domény (HOME/AWAY/obě/zápas), ne „away jinak“. Test pro GENERAL/H2H/WEATHER.
  - *Hotovo:* 20. 10. 2026 – 245 passed ověřeno. `ResearchEngine.subject_team_name` (`*_HOME`→domácí, `*_AWAY`→hosté, ostatní → zápasový subjekt bez týmu); použito pro dotazy i claimy. Testy `tests/research/test_claim_subject.py` (13 parametrů).
- [x] **3.4 Čeština v extrakci a dotazech (H#12).**
  - *Jak:* Regex jmen s diakritikou (`[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+`), české klíčové fráze v `EvidenceExtractor`, česká varianta dotazů v `research_queries.yaml`. Testy na českých větách.
  - *Hotovo:* 20. 10. 2026 – 3.3 ověřeno kontrolou kódu. `claim_builder.NAME_RE` (diakritika) + české stavy nepřítomnosti (zraněn/chybí/otázný/distanc); `evidence_extractor.keywords_for_domain` (EN + české kmeny pro všechny domény); `config/research_queries.yaml`: nový typ `discovery_cs` u každé domény (za `discovery`, takže se vejde do `max_queries`). Testy `tests/research/test_czech_research.py` (5) → očekáváno 263 passed (245 + 13 + 5; nespuštěno).
- [x] **3.5 Registr zdrojů (H#13).**
  - *Jak:* Doplnit `config/source_registry.yaml` (fotbal.cz, fortunaliga.cz, idnes, sport.cz, transfermarkt, fbref…) s důvěryhodností; test načtení.
  - *Hotovo:* 20. 10. 2026 – ~45 domén (české oficiální, statistické, zpravodajství, agregátory); `SearchSourceRegistry.get_source_type` teď rozpozná i subdomény (sport.idnes.cz → idnes.cz), ne přípony typu `evilidnes.cz`. Testy `tests/research/test_source_registry_cz.py` (12 parametrů). Seznam klubových domén je z paměti – při použití zkontrolovat.
- [x] **3.6 HTMLParser a Playwright (H#15).**
  - *Jak:* Jazyk detekovat/z meta, `author`/`canonical` z HTML; do runbooku přidat `playwright install chromium`; fallback loguje varování.
  - *Hotovo:* 20. 10. 2026 – `html_parser`: `detect_language` (`<html lang>`/meta/og:locale, jinak heuristika českých znaků), `extract_canonical` (link rel=canonical/og:url, relativní → absolutní), `extract_author`; metadata se čtou před `decompose()`. `crawler.py`: varování při chybějícím Playwrightu / prohlížeči. Runbook §3a. Testy `tests/research/test_html_parser_meta.py` (4). Pozor: starý test, který čekal `language=="cs"` natvrdo, by teď měl selhat.
- [x] **3.7 Note 9 (H#4).**
  - *Jak:* Zvolit variantu: (a) dokumentaci opravit, že Note 9 zatím nedostává práci; (b) rozdělit RESEARCH na SEARCH/CRAWL joby. Výchozí: (a), zapsat do `REQUIREMENTS_AUDIT.md` + `NOTEBOOK_SETUP.md`.
  - *Hotovo:* 20. 10. 2026 – zvolena varianta (a); oba dokumenty opraveny (Note 9 zatím nedostává žádnou práci, jen `TEST`). Varianta (b) zůstává jako budoucí plán.

## FÁZE 4 – Audit
- [x] **4.1 Freshness vůči cutoffu (H#16).** *Jak:* `FreshnessChecker` počítat věk k `data_cutoff_at` a podle typu domény; test.
  - *Hotovo:* 20. 10. 2026 – 278 passed ověřeno. `calculate_freshness(..., reference_at=cutoff)`; typ dat z predikátu claimu (`data_type_for_predicate`: lineup/injury/statistics/general) místo natvrdo `lineup`; auditor předává `parsed_cutoff`. Testy `tests/test_freshness_cutoff.py` (5). Starý test očekávající `stale_evidence` při věku počítaném k `now()` by se musel upravit.
- [x] **4.2 ConsistencyChecker (H#17).** *Jak:* Odstranit natvrdo „vyhrál 7 z posledních 10“; používat skutečné klíče `match_statistics`; testy upravit na obecnou logiku.
  - *Hotovo:* 20. 10. 2026 – `consistency.py`: bilance z reálné struktury (`home_team.form`/`away_team.form`: W-D-L, body, góly; ploché klíče zůstávají jako kompatibilita); kontroly součtu, bodů = 3V+R, gólového rozdílu; obecný parser tvrzení „vyhrál X z posledních N“ (ověřuje se jen při shodném N). Testy `tests/test_consistency_generic.py` (6).
- [x] **4.3 Sjednotit ConflictDetector (H#18).** *Jak:* Jedna implementace (např. `app/research/conflict_detector.py`), audit ji importuje; testy projdou.
  - *Hotovo:* 20. 10. 2026 – `research/conflict_detector.py` obsahuje i `detect_conflicts` (dicty z DB → nálezy), `audit/conflict_detector.py` je tenký re-export; shodná normalizace klíče (case-insensitive subjekt). Testy `tests/test_conflict_detector_unified.py` (3).

## FÁZE 5 – API / bezpečnost / provoz
- [x] **5.1 Jedna registrace `/api/analysis/start` (H#19).** *Jak:* Ponechat jen jednu (router), `MasterOrchestrator` vytvářet líně s cestou z configu; odstranit duplicitu v `server.py`.
  - *Hotovo:* 20. 10. 2026 – odchylka od návrhu: ponechána verze v `server.py` (má kontrakt, na který se vážou testy a Note 9: `match_id` nebo plná identita, 200 OK; verze v routeru byla stíněná a nikdy se nevolala). Z `orchestrator/router.py` odstraněny duplicitní `POST /start` a `GET /{run_id}`; zbývá readiness + cancel, orchestrátor se vytváří líně přes `get_orchestrator()` nad `server.DB_PATH`. Testy `tests/api/test_single_registration.py` (3). Pozn.: `readiness` počítá s job typem `SEARCH`, který už nevzniká (jsou `RESEARCH`) – samostatný problém, není v TODO.
- [x] **5.2 Náhodný token v `init.sh` (H#20).** *Jak:* `python -c "import secrets;print(secrets.token_urlsafe(32))"`; nikdy nezapisovat výchozí řetězec.
  - *Hotovo:* 21. 10. 2026 – 5.1 ověřeno kontrolou kódu (`server.py` má jedinou `POST /start` a `GET /{run_id}`, router má jen readiness+cancel, import bez cyklu). `init.sh` už náhodný token (`secrets.token_urlsafe(32)`, `chmod 600`, náhrada výchozího tokenu ve starém `.env`) obsahoval; chyběl test → `tests/test_init_script_token.py` (5). Ostatní `scripts/*.sh` pevný token nezapisují.
- [x] **5.3 `config/crawler.yaml` (H#23).** *Jak:* Načítat v `HTTPClient` (timeout, UA, retry) s výchozími hodnotami, nebo soubor odstranit.
  - *Hotovo:* 21. 10. 2026 – `app/crawler/config.py` (`load_crawler_settings`, výchozí hodnoty při chybějícím/poškozeném souboru či neplatných hodnotách); `HTTPClient` bere timeout, connect timeout, retry, UA, redirecty a limit velikosti obsahu z configu (explicitní argumenty mají přednost, signatura kompatibilní); `EngineCrawler` bere interval rate limiteru a JS timeout/enabled. Testy `tests/test_crawler_config.py` (7) → očekáváno 251+ passed (nespuštěno – chybí mi shell k uživatelskému stroji; ověřit `pytest -q`).

## FÁZE 6 – Hygiena testů
- [x] **6.1 Izolace env (H#21).** *Jak:* `conftest.py` autouse fixture: `FAE_AUTO_HISTORY=0`, vyčistit FAE_*/OLLAMA_* přes `monkeypatch`; `menu.py` nenačítá `.env` při importu (přesunout do `main()`).
  - *Hotovo:* 21. 10. 2026 – 311 passed (stav po 5.3) ověřeno uživatelem; 6.1 samotné zatím neběželo. `conftest.py`: autouse fixture `_isolate_environment` (smaže vše `FAE_*`/`OLLAMA_*`, nastaví `FAE_AUTO_HISTORY=0`); `menu._load_local_env()` se volá až z `main()`. Testy `tests/test_env_isolation.py` (3). Pozor: pokud nějaký test spoléhal na hodnoty z `.env`/prostředí, nyní selže – má si je nastavit sám přes `monkeypatch.setenv` (nespuštěno, ověřit `pytest -q`, očekáváno 315 passed s 6.3).
- [x] **6.2 Doba testů.** *Jak:* `pytest --durations=15`, zpomalené testy zrychlit (mock sítě/sleep); cíl < 40 s.
  - *Hotovo:* 21. 10. 2026 – 315 passed ve 119 s → **22,8 s** (ověřeno). Čas tvořila inicializace DB na každý test; `conftest.py`: session `_template_db` + autouse `_fast_database_init` (nová DB = kopie šablony; existující soubory, tedy migrační testy, jdou přes skutečnou inicializaci). Nejpomalejší zbývá `test_note9_worker_remote_disconnected_reconnect_and_no_job` (3 s, záměrný backoff) – necháno.
- [x] **6.3 Absolutní cesty (H#22).** *Jak:* `Path(__file__).resolve().parents[n] / "database/schema.sql"` v `tests/statistics/test_engine.py`.
  - *Hotovo:* 21. 10. 2026 – `SCHEMA_PATH` v `test_engine.py`; test `tests/statistics/test_schema_path.py` (1, s `chdir`). Ostatní testy s relativními cestami jsem neprohledával (chybí grep obsahu) – při selhání z jiného adresáře dopravit stejným způsobem.

## FÁZE 7 – Úklid mrtvého kódu (vždy `grep -rn` importů + celá sada testů)
- [x] **7.1** `app/jobs/worker.py`, `priorities.py`, `JobModel`, `app/orchestrator/task_dispatcher.py`, `locks.py`.
  - *Hotovo:* 21. 10. 2026 – 315 passed ověřeno po první části. Přesunuty `priorities.py`, `task_dispatcher.py`, `locks.py` (`DeadlockDetector` bez použití), `JobModel` odstraněn z `models.py` a `app/jobs/__init__.py`. `BaseWorkerDaemon` (`app/jobs/worker.py`) používaly jen testy (produkční worker je `app.workers.daemon.WorkerDaemon`) → přesunut jako testovací harness do `tests/worker_harness.py`, oba e2e/pipeline testy zachovány (změněn jen import). Oprava docstringu `scripts/run_worker.py`. Ověřit `pytest -q`.
- [x] **7.2** `app/search/source_engine.py`, `query_builder.py`, `app/research/schemas/absences.py`.
  - *Hotovo:* 21. 10. 2026 – přesunuty `app/search/source_engine.py`, `app/search/query_builder.py` (nezaměnit s používaným `app/research/query_builder.py`, ten zůstává), `app/research/schemas/absences.py`. Ověřit `pytest -q`.
- [x] **7.3** `AISynthesizer` + `PromptManager` + `prompts/*`, `app/audit/db.py`.
  - *Hotovo:* 21. 10. 2026 – `AIWorker` používá vlastní prompt přímo v kódu, takže `app/ai/synthesizer.py`, `app/ai/prompts.py`, adresář `prompts/` a export v `app/ai/__init__.py` jsou odstraněny (přesunuty do `~/FAE_removed_7x/`); odstraněn jediný test, který `AISynthesizer` používal (`test_synthesizer_reproducibility_and_db`) → očekáváno **314 passed** (315 − 1). **`app/audit/db.py` ponechán** – importuje ho `app/audit/auditor.py` (`init_audit_tables`). Ověřit `pytest -q`.
- [x] **7.4** Kořenové `run_worker.py`, `test_source_engine.py`, `test_crawler_pipeline.py`, prázdný `tests/statistics/test_splits.py`, `SplitsEngine`, `XGModule`, `StatisticExtractor`.
  - *Hotovo:* 21. 10. 2026 – vše přesunuto do `~/FAE_removed_7x/` (`app/statistics/{xg,splits,extractor}.py` bez importů). README: příkaz workeru opraven na `scripts/run_worker.py`. Ověřit `pytest -q` (při ztrátě testů počet klesl o kořenové test_*.py).
  - *Jak (7.x):* Pro každý soubor `grep -rn "<modul>" --include=*.py .`; bez importů v produkci smazat i související testy; `pytest -q` zelený.

## FÁZE 8 – Dokumentace (handoff sekce 9)
- [x] **8.1** README: model `poisson-dc-context-v4`, schéma bez MatchResolveru, počet testů.
  - *Hotovo:* 21. 10. 2026 – README už měl model **v5** a tok bez MatchResolveru (viz 2.7); doplněn počet testů (315 passed).
- [x] **8.2** `docs/*Stav_Overeno*`, `*Vyvojovy_plan*`: 65 → aktuální počet.
  - *Hotovo:* 21. 10. 2026 – oba dokumenty: 315 passed (s datem; historické „65 k 6. 10.“ zachováno).
- [x] **8.3** `docs/COMPLETE_SETUP_RUNBOOK.md`: model v4, `playwright install chromium`.
  - *Hotovo:* 21. 10. 2026 – Playwright §3a už byl (bod 3.6); model opraven na `poisson-dc-context-v5` (byl `poisson-context-v3`), pravidlo pro chybějící historii sjednoceno (`INSUFFICIENT_DATA` → `UNRESOLVED`).
- [x] **8.4** `scripts/network_setup.sh` (qwen2.5:3b, `OLLAMA_URL`), `docs/Linux_Mint_Network_Setup.md` (jednotná větev).
  - *Hotovo:* 21. 10. 2026 – skript: hláška o modelu `qwen2.5:3b` (z `OLLAMA_MODEL`), adresa Ollamy z `OLLAMA_URL` (fallback `OLLAMA_PORT`) i pro kontrolu `/api/tags`; dokument: odstraněno pevné `git switch football-engine`. Skript nespuštěn (interaktivní) – doporučeno `bash -n scripts/network_setup.sh`.
- [x] **8.5** `postup_oprav.txt` a `PROJECT_REPAIR_HANDOFF.md` aktualizovat podle hotových bodů.
  - *Hotovo:* 21. 10. 2026 – **vynecháno na pokyn uživatele** (soubory nejsou v projektu).
- 8.4 zkontrolováno 21. 10. 2026: skript (`qwen2.5:3b`, `OLLAMA_URL`) i dokument v pořádku; opravena cesta SearXNG configu v `Linux_Mint_Network_Setup.md` (`runtime-config-<uid>-managed`, tak jak ji vytváří skript).

- Ověřeno uživatelem 21. 10. 2026: `pytest -q` = 314 passed, 1 warning (8,13 s) → fáze 6–8 potvrzeny.

## FÁZE 9 – Reálný acceptance (jen na stroji uživatele, ne v cloudu)
- [ ] SearXNG vrací výsledky, `scripts/preflight.py` OK.
- [ ] Source selection → crawler → parser vytvoří dokumenty s hash/metadaty.
- [ ] Evidence/claims uloženy, cutoff vyřadí pozdější zdroje.
- [ ] Statistika nad reálnou historií (`Sample > 0` u obou týmů).
- [ ] Ollama vrací validní JSON; AI_ANALYSIS → AUDIT úspěšně.
- [ ] Pipeline skončí `COMPLETED` nebo `UNRESOLVED` bez zásahu; restart workeru neztratí práci.
- *Jak:* Spustit podle sekce 8 handoffu, výsledky zapsat sem. Teprve potom smí AI napsat „FINAL“.
