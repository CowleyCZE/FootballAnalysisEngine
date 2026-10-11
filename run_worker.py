import argparse
import logging
from pathlib import Path

from app.workers.daemon import WorkerDaemon

REPO_ROOT = Path(__file__).resolve().parent

DEFAULT_CAPABILITIES = [
    "RESEARCH",
    "SEARCH",
    "CRAWL",
    "STATISTICS",
    "AI_ANALYSIS",
    "AUDIT",
]


def resolve_db_path(db_path_str: str) -> str:
    path = Path(db_path_str)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Football Analysis Engine worker")
    parser.add_argument("--worker-id", default="worker-1")
    parser.add_argument("--capabilities", nargs="+", default=DEFAULT_CAPABILITIES)
    parser.add_argument("--db", default="database/football.db")
    parser.add_argument("--poll", type=float, default=2.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db_abs = resolve_db_path(args.db)

    WorkerDaemon(
        worker_id=args.worker_id,
        capabilities=args.capabilities,
        db_path=db_abs,
        poll_interval=args.poll,
    ).run_forever()


if __name__ == "__main__":
    main()
