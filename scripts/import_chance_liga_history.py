from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

# Umožní přímé spuštění: python scripts/import_chance_liga_history.py
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx
from bs4 import BeautifulSoup

from app.crawler.chance_liga_history import diagnose_schedule_html, fetch_season_schedule, parse_schedule_html, season_label
from app.crawler.chance_liga_xg import enrich_records_with_xg
from app.database.history_import import audit_history_import, import_history_records
from app.database.schema import initialize_database


async def run(
    seasons: list[int],
    db_path: str,
    skip_xg: bool = False,
    save_debug_html: bool = True,
) -> dict[str, object]:
    initialize_database(db_path)
    all_records: list[dict[str, object]] = []
    season_reports: list[dict[str, object]] = []
    xg_report = {"matches_with_url": 0, "xg_enriched": 0}

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for year in seasons:
            season, html = await fetch_season_schedule(year, client)
            records = parse_schedule_html(html, season)
            diagnostics = diagnose_schedule_html(html)

            if save_debug_html:
                debug_dir = Path("data/debug")
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / f"chance_liga_{year}.html").write_text(html, encoding="utf-8")

            season_reports.append(
                {
                    "season": season,
                    "parsed_records": len(records),
                    "diagnostics": diagnostics,
                }
            )
            all_records.extend(records)

        if not skip_xg:
            xg_report = await enrich_records_with_xg(all_records, client)

    with sqlite3.connect(db_path) as conn:
        import_result = import_history_records(
            conn,
            all_records,
            competition="Chance Liga",
        )
        audit = audit_history_import(conn, competition="Chance Liga")

    return {
        "seasons": [season_label(year) for year in seasons],
        "season_reports": season_reports,
        "parsed_records": len(all_records),
        "xg_report": xg_report,
        "import_result": import_result,
        "audit": audit,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Import historie Chance Ligy do SQLite")
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=[2023, 2024, 2025],
        help="Startovní roky sezón, např. 2023 2024 2025",
    )
    parser.add_argument(
        "--db",
        default="data/football_analysis.db",
        help="Cesta k SQLite databázi",
    )
    parser.add_argument(
        "--skip-xg",
        action="store_true",
        help="Přeskočí doplnění xG z detailů zápasů",
    )
    parser.add_argument(
        "--no-debug-html",
        action="store_true",
        help="Neukládá stažené HTML do data/debug",
    )
    args = parser.parse_args()

    report = asyncio.run(
        run(
            args.seasons,
            args.db,
            skip_xg=args.skip_xg,
            save_debug_html=not args.no_debug_html,
        )
    )
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
