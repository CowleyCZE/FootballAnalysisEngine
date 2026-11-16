from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path

import httpx

from app.crawler.chance_liga_history import fetch_season_schedule, parse_schedule_html, season_label
from app.database.history_import import audit_history_import, import_history_records
from app.database.schema import initialize_database


async def run(seasons: list[int], db_path: str) -> dict[str, object]:
    initialize_database(db_path)
    all_records: list[dict[str, object]] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        for year in seasons:
            season, html = await fetch_season_schedule(year, client)
            records = parse_schedule_html(html, season)
            all_records.extend(records)

    with sqlite3.connect(db_path) as conn:
        import_result = import_history_records(
            conn,
            all_records,
            competition="Chance Liga",
        )
        audit = audit_history_import(conn, competition="Chance Liga")

    return {
        "seasons": [season_label(year) for year in seasons],
        "parsed_records": len(all_records),
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
    args = parser.parse_args()

    report = asyncio.run(run(args.seasons, args.db))
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
