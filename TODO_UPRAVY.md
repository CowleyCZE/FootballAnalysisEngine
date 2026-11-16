# TODO_UPRAVY

Cíl: postupně zvýšit přesnost, spolehlivost a užitnost predikcí aplikace FootballAnalysisEngine.

## 1. Kompletní historická data

**Co splnit:**
- Importovat výsledky, góly, data zápasů a základní statistiky pro Chance Ligu za poslední 2–3 sezóny.
- Doplnit xG a xGA pro každý odehraný zápas, pokud je zdroj dostupný.
- Ověřit, že žádný zápas nemá duplicitní záznam, špatné ID týmu nebo budoucí datum.

**Jak splnit:**
- Rozšířit scraper tak, aby stahoval kompletní historii, ne jen posledních 30 zápasů.
- Ukládat data do SQLite v normalizovaných tabulkách `matches`, `teams`, `match_statistics` a `team_match_features`.
- Po importu spustit kontrolní dotazy: počet zápasů, duplikáty, chybějící výsledky, chybějící xG a nevalidní data.
- Přidat test, který ověří, že import nevytvoří duplicitní zápasy a že data jsou chronologicky konzistentní.

**Hotovo, když:**
- Databáze obsahuje kompletní historii bez duplicit.
- xG/xGA jsou dostupné pro maximální možný počet zápasů.
- Import lze opakovaně spustit bez duplikace dat.

## 2. xG rating týmů

**Co splnit:**
- Vytvořit rating útoku a obrany každého týmu na základě xG a xGA, nikoli pouze vstřelených a obdržených gólů.
- Rating musí zohledňovat sílu soupeřů.

**Jak splnit:**
- Přidat modul `app/statistics/team_rating.py`.
- Implementovat iterativní rating nebo ELO z xG rozdílu.
- Použít shrinkage pro týmy s málo zápasy.
- Ukládat rating před každým zápasem, aby nedocházelo k úniku budoucích dat.
- Integrovat rating do `ExactScorePredictor.predict()` jako vstup pro útok a obranu.

**Hotovo, když:**
- Model používá xG rating při predikci.
- Rating je reprodukovatelný a neobsahuje budoucí informace.
- Backtest ukáže, zda rating zlepšil Brier score nebo alespoň nezhoršil výsledky.

## 3. Lepší forma týmů

**Co splnit:**
- Nahradit jednoduchý vážený průměr robustnější měrou formy.
- Forma musí pracovat s xG, xGA, výsledky, domácí/venkovní rozdělením a sílou soupeřů.

**Jak splnit:**
- Přidat EWMA formu pro xG rozdíl, gólový rozdíl a výsledky.
- Posledních 5–8 zápasů má vyšší váhu než starší zápasy.
- Oddělit formu doma a venku, pokud je k dispozici dostatek zápasů.
- Normalizovat formu podle průměrné síly soupeřů.

**Hotovo, když:**
- Predikce používá novou formu.
- Výstup obsahuje vysvětlitelné faktory formy.
- Backtest porovná starou a novou formu a uloží výsledek.

## 4. Kalibrace pravděpodobností

**Co splnit:**
- Zajistit, že modelové pravděpodobnosti 1X2 odpovídají skutečné frekvenci výsledků.

**Jak splnit:**
- Přidat kalibraci pomocí Platt scaling nebo isotonic regression.
- Kalibraci trénovat pouze na historických datech před predikovaným zápasem.
- Ukládat kalibrační model nebo parametry do `config/`.
- Aplikovat kalibraci až po výpočtu pravděpodobností 1X2.

**Hotovo, když:**
- Kalibrační křivka je součástí reportu.
- Brier score po kalibraci je stejný nebo lepší než před kalibrací na holdoutu.
- Kalibrace nepoužívá budoucí data.

## 5. Korekce remíz

**Co splnit:**
- Snížit systematické podcenění remíz v Poissonově modelu.

**Jak splnit:**
- Otestovat bivariate Poisson model.
- Alternativně přidat explicitní draw inflation parametr.
- Parametr ladit pouze na trénovací části a ověřovat na holdoutu.

**Hotovo, když:**
- Model nepodcenuje remízy.
- Brier score a log-loss se na holdoutu nezhorší.
- Změna je dokumentovaná v `docs/backtest_report.json`.

## 6. Rozšířený backtest

**Co splnit:**
- Vytvořit spolehlivé měření kvality modelu.

**Jak splnit:**
- Implementovat rolling walk-forward backtest.
- Pro každý zápas použít pouze data dostupná před výkopem.
- Měřit 1X2 přesnost, Brier score, log-loss, MAE gólů, zásah přesného skóre a kalibraci.
- Rozdělit výsledky podle typu zápasu: favorit, vyrovnaný zápas, vysoké a nízké očekávané góly.
- Ukládat report do `docs/backtest_report.json`.

**Hotovo, když:**
- Backtest lze spustit jedním příkazem.
- Report obsahuje všechny metriky a rozdělení podle typů zápasů.
- Žádná predikce nepoužívá data po výkopu.

## 7. Srovnání s kurzy

**Co splnit:**
- Přidat měření hodnoty tipů vůči tržním kurzům.

**Jak splnit:**
- Ukládat uzavírací kurz, čas kurzu a bookmakera pro každý zápas.
- Spočítat implicitní pravděpodobnost z kurzů a odečíst bookmakerskou marži.
- Porovnat modelovou pravděpodobnost s tržní pravděpodobností.
- Označit tip jako value bet jen při dostatečném edge, například alespoň 3–5 procentních bodů.
- Měřit dlouhodobý zisk, ROI, hit rate a maximal drawdown.

**Hotovo, když:**
- Aplikace umí uložit kurz a vyhodnotit hodnotu tipu.
- Report obsahuje ROI a počet value bets.
- Model negeneruje tip, pokud nemá dostatečnou jistotu nebo hodnotu.

## 8. Kontextové faktory pouze s daty

**Co splnit:**
- Ověřit, zda únava, motivace, rivalita a absence skutečně zlepšují predikce.

**Jak splnit:**
- Ukládat historické kontextové údaje jen tehdy, když jsou ověřitelné.
- Ladit koeficienty kontextu na historických datech, nikoli používat pevné odhady.
- Pokud data chybí, kontext nesmí změnit predikci.
- Otestovat každý faktor samostatně v backtestu.

**Hotovo, když:**
- Každý použitý kontextový faktor má změřený přínos.
- Faktory bez dat nemají vliv na predikci.
- Nepotvrzené faktory jsou vypnuté nebo mají nulovou váhu.

## 9. Kvalita vstupních dat

**Co splnit:**
- Zajistit, že špatná, chybějící nebo nekonzistentní data nepokazí predikci.

**Jak splnit:**
- Přidat validaci typů, rozsahů a formátů dat při importu.
- Detekovat duplicitní zápasy, neplatná data, záporné góly a extrémní xG hodnoty.
- Přidat log chyb importu.
- Přidat testy pro běžné chybné vstupy.

**Hotovo, když:**
- Import odmítne nebo opraví nevalidní data.
- Chyby jsou viditelné v logu.
- Testy pokrývají hlavní chybové scénáře.

## 10. Produkční spolehlivost

**Co splnit:**
- Zajistit stabilní běh API, workerů a databáze.

**Jak splnit:**
- Opravit async použití ve FastAPI.
- Použít správné ošetření databázových spojení.
- Přidat retry logiku pro síťové požadavky.
- Přidat monitoring chyb, časů běhu a stavu workerů.
- Zajistit, že worker neprocesuje stejnou úlohu dvakrát.

**Hotovo, když:**
- API a workery běží stabilně.
- Chyby jsou logované.
- Testy procházejí.
- Databázové spojení se vždy uzavírá korektně.

## 11. Uživatelský výstup tipů

**Co splnit:**
- Zobrazit uživateli jen srozumitelný a použitelný výstup.

**Jak splnit:**
- Zobrazit 1X2 pravděpodobnosti, očekávané góly, nejpravděpodobnější skóre, hlavní faktory a úroveň jistoty.
- Zobrazit varování, pokud je málo dat nebo chybí xG.
- Zobrazit doporučený typ sázky jen tehdy, když je dostatečná hodnota vůči kurzu.
- Neprezentovat přesné skóre jako jistotu.

**Hotovo, když:**
- Uživatel rozumí, proč model doporučil daný tip.
- Výstup obsahuje míru nejistoty.
- Aplikace nedoporučuje sázku bez dostatečných dat.

## 12. Průběžné ladění

**Co splnit:**
- Udržovat model aktuální podle nových výsledků.

**Jak splnit:**
- Po každých přibližně 50 nových dokončených zápasech spustit backtest.
- Parametry zapisovat jen při potvrzeném zlepšení na holdoutu.
- Uchovávat historii všech backtestů.
- Pravidelně kontrolovat, zda se model nezhoršil.

**Hotovo, když:**
- Ladění je opakovatelné.
- Historie ladění je uložená.
- Model nepoužívá parametry, které nebyly ověřené na holdoutu.
