"""Command-line entry point for an auditable exact-score prediction.

Examples:
  python run_analysis.py --rows-file recent.json --home-team-id 10 --away-team-id 20
  python run_analysis.py --db database/football.db --match-id 42 --run-id 7 \
      --home-team-id 10 --away-team-id 20 --cutoff 2026-10-12T00:00:00

The direct JSON mode is useful for batch jobs; the SQLite mode uses the same
cutoff-safe repository and snapshot persistence as the worker pipeline.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from app.statistics.engine import StatisticalEngine
from app.statistics.score_predictor import ExactScorePredictor


def _context(path: str | None) -> Dict[str, Any]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Context JSON musí být objekt s klíči home_context, away_context a match_context.")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Football Analysis Engine – predikce přesného skóre")
    parser.add_argument("--rows-file", help="JSON soubor s historickými zápasy pro přímý výpočet")
    parser.add_argument("--db", default="database/football.db", help="SQLite databáze pro pipeline režim")
    parser.add_argument("--match-id", type=int)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--home-team-id", type=int, required=True)
    parser.add_argument("--away-team-id", type=int, required=True)
    parser.add_argument("--cutoff", help="ISO cutoff; povinný v SQLite režimu")
    parser.add_argument("--context-file", help="JSON s volitelnými kontextovými faktory")
    args = parser.parse_args()
    context = _context(args.context_file)

    if args.rows_file:
        rows = json.loads(Path(args.rows_file).read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise ValueError("Historická data musí být JSON pole.")
        result = ExactScorePredictor.predict(
            rows, args.home_team_id, args.away_team_id,
            h2h_rows=context.get("h2h_rows"),
            home_context=context.get("home_context"),
            away_context=context.get("away_context"),
            match_context=context.get("match_context"),
        )
    else:
        missing = [name for name, value in (("--match-id", args.match_id), ("--run-id", args.run_id), ("--cutoff", args.cutoff)) if value is None]
        if missing:
            parser.error("V SQLite režimu jsou povinné: " + ", ".join(missing))
        result = StatisticalEngine(args.db).run_match_statistics(
            match_id=args.match_id, run_id=args.run_id,
            home_team_id=args.home_team_id, away_team_id=args.away_team_id,
            cutoff_datetime=args.cutoff,
            home_context=context.get("home_context"),
            away_context=context.get("away_context"),
            match_context=context.get("match_context"),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
