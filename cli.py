import sys
import argparse
import sqlite3
import json
from app.orchestrator.orchestrator import MasterOrchestrator

def main():
    parser = argparse.ArgumentParser(description="Football Analysis Engine Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command")

    # analyze MATCH_ID
    analyze_p = subparsers.add_parser("analyze")
    analyze_p.add_argument("match_id", type=int, help="Match ID to analyze")

    # status RUN_ID
    status_p = subparsers.add_parser("status")
    status_p.add_argument("run_id", type=str, help="Run ID to query")

    # jobs
    subparsers.add_parser("jobs")

    # workers
    subparsers.add_parser("workers")

    # recover
    subparsers.add_parser("recover")

    args = parser.parse_args()
    orchestrator = MasterOrchestrator()

    if args.command == "analyze":
        run_id = orchestrator.start_pipeline(args.match_id)
        print(f"Pipeline initialized successfully.")
        print(f"Run ID: {run_id}")

    elif args.command == "status":
        conn = sqlite3.connect(orchestrator.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM pipeline_runs WHERE run_id = ?", (args.run_id,))
        run = cursor.fetchone()
        if not run:
            print(f"Run ID {args.run_id} not found.")
            return

        cursor.execute("SELECT status, COUNT(*) as cnt FROM jobs WHERE match_id = ? GROUP BY status", (run["match_id"],))
        job_stats = {r["status"]: r["cnt"] for r in cursor.fetchall()}

        print(f"RUN: {run['run_id']}")
        print(f"MATCH ID: {run['match_id']}")
        print(f"STATE: {run['state']}")
        print(f"CYCLE: {run['cycle']} / {run['max_cycles']}")
        print(f"JOBS: {job_stats}")
        conn.close()

    elif args.command == "jobs":
        conn = sqlite3.connect(orchestrator.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT job_id, job_type, status, priority, worker_id FROM jobs ORDER BY id DESC LIMIT 20")
        rows = cursor.fetchall()
        print(f"{'JOB ID':<38} | {'TYPE':<12} | {'STATUS':<10} | {'PRIO':<4} | {'WORKER'}")
        print("-" * 75)
        for r in rows:
            print(f"{r['job_id']:<38} | {r['job_type']:<12} | {r['status']:<10} | {r['priority']:<4} | {r['worker_id']}")
        conn.close()

    elif args.command == "workers":
        conn = sqlite3.connect(orchestrator.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT worker_id, worker_type, status, last_heartbeat FROM workers")
        rows = cursor.fetchall()
        print(f"{'WORKER ID':<15} | {'CAPABILITIES':<30} | {'STATUS':<8} | {'LAST HEARTBEAT'}")
        print("-" * 75)
        for r in rows:
            print(f"{r['worker_id']:<15} | {r['worker_type']:<30} | {r['status']:<8} | {r['last_heartbeat']}")
        conn.close()

    elif args.command == "recover":
        recovered = orchestrator.recovery.recover_dead_workers_and_jobs()
        print(f"Recovery complete. Recovered {recovered} dead or stuck jobs.")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
