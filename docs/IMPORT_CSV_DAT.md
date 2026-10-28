# Import a automatická aktualizace CSV

Import CSV v `database/data_csv/` a povolených exportů v kořeni projektu:

```bash
python3 -m app.statistics.csv_data_sync --import-existing
```

Importer ukládá výsledky a zápasové statistiky do `matches` a `match_statistics`,
xG-only řádky do `match_xg_observations` a sezonní souhrny do
`team_season_snapshots`. Názvy týmů propojuje přes `config/team_aliases.yaml`;
Artis Brno a Zbrojovka Brno jsou samostatné týmy. Opakovaný import zápasy
neduplikuje, chybějící metriky nepřepisují uložené hodnoty a starší záznamy se
nemazají.

Do importu patří také kořenový export `molcup_vysledek.csv` (MOL Cup) a
`zapasy_xg.csv` (historická xG pozorování). Alias týmu se sjednocuje na jedno
`teams.id`; před sloučením duplicitních utkání se ověřuje shoda výsledků a
statistik. Kontrolu rozsahu databáze lze spustit bez změny dat:

```bash
python3 scripts/audit_team_allowlist.py
```

Kontrola porovnává databázi s CSV ve `database/data_csv/`, kořenovými exporty
a zachovává také historické účastníky Chance Ligy doložené jejich ligovými
utkáními.

U každého zápasu pole `matches.kickoff_time_known` rozlišuje skutečný čas
dodaný zdrojem (`1`) od dopočítaného poledne použitého jen jako technická
náhrada (`0`). Zdroj přesného času je v `kickoff_time_source`; import bez času
nepřepíše již potvrzený čas. `matches.venue` uchovává stadion konkrétního
zápasu. Domácí stadion týmu, město a souřadnice jsou v `team_stadiums`.

Chybějící souřadnice lze doplnit jednorázově přes Nominatim:

```bash
python3 scripts/enrich_team_stadiums.py
```

Skript požadavky dávkuje sériově (nejvýše jeden za sekundu), ukládá zdroj,
URL a atribuci OpenStreetMap a při dalším běhu přeskočí stadiony se souřadnicemi.

Před statistickou predikcí se kontroluje stáří zdrojů. Po překročení limitu se
příslušný downloader spustí v dočasné složce a jeho CSV se připojí do databáze.
Původní soubory v `database/data_csv/` zůstávají nedotčené.

| Zdroj | Limit stáří |
| --- | ---: |
| Rozpis a výsledky Chance Ligy | 24 hodin |
| xG Chance Ligy | 7 dní |
| Evropské poháry českých klubů | 24 hodin |
| MOL Cup | 7 dní |

Při chybě stahování se predikce nezastaví; použije dosavadní databázi a další
pokus proběhne nejdříve za 6 hodin. Stav a datum poslední aktualizace:

```bash
python3 -m app.statistics.csv_data_sync --status
```

Vynucené stažení všech zdrojů:

```bash
python3 -m app.statistics.csv_data_sync --refresh
```

Automatiku lze vypnout proměnnou `FAE_AUTO_CSV_SYNC=0`.
