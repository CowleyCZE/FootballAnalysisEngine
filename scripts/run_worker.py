#!/usr/bin/env python3
"""Run one pull-based Football Analysis Engine worker on this machine."""

import argparse
import logging
import socket
import sys
from pathlib import Path

# When invoked as ``python scripts/run_worker.py``, Python puts scripts/ rather
# than the project root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.workers.daemon import WorkerDaemon


DEFAULT_CAPABILITIES = ["RESEARCH", "SEARCH", "CRAWL", "STATISTICS", "AI_ANALYSIS", "AUDIT"]


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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    WorkerDaemon(
        worker_id=args.worker_id,
        capabilities=args.capability or DEFAULT_CAPABILITIES,
        db_path=args.db_path,
        poll_interval=args.poll_interval,
    ).run_forever()


if __name__ == "__main__":
    main()
