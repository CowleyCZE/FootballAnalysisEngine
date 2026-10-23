#!/usr/bin/env python3
"""Run one pull-based Football Analysis Engine worker on this machine.

Recommended command to run a worker from the repository root:
    python3 scripts/run_worker.py --worker-id worker-1
"""

import argparse
import logging
import os
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.workers.daemon import WorkerDaemon


DEFAULT_CAPABILITIES = ["RESEARCH", "SEARCH", "CRAWL", "STATISTICS", "AI_ANALYSIS", "AUDIT"]


def load_env_file(env_path: Path) -> None:
    """Načte KEY=VALUE z .env (bez přepsání už nastavených proměnných)."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def resolve_db_path(db_path_str: str) -> str:
    path = Path(db_path_str)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-id", default=f"notebook-{socket.gethostname()}")
    parser.add_argument("--db-path", default="database/football.db")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument(
        "--capability",
        action="append",
        choices=DEFAULT_CAPABILITIES,
        help="Capability to serve; repeat it. Defaults to all capabilities.",
    )
    args = parser.parse_args()
    load_env_file(REPO_ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db_abs = resolve_db_path(args.db_path)

    WorkerDaemon(
        worker_id=args.worker_id,
        capabilities=args.capability or DEFAULT_CAPABILITIES,
        db_path=db_abs,
        poll_interval=args.poll_interval,
    ).run_forever()


if __name__ == "__main__":
    main()
