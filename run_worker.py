import argparse

from app.workers.daemon import WorkerDaemon


DEFAULT_CAPABILITIES = [
    "SEARCH",
    "CRAWL",
    "STATISTICS",
    "AI_ANALYSIS",
    "AUDIT",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Football Analysis Engine worker")
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--capabilities", nargs="+", default=DEFAULT_CAPABILITIES)
    parser.add_argument("--db", default="database/football.db")
    parser.add_argument("--poll", type=float, default=2.0)
    args = parser.parse_args()

    WorkerDaemon(
        worker_id=args.worker_id,
        capabilities=args.capabilities,
        db_path=args.db,
        poll_interval=args.poll,
    ).run_forever()


if __name__ == "__main__":
    main()
