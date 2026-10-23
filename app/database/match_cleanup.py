"""Mazání zápasů včetně všech závislých dat (používá menu volba 7)."""
from __future__ import annotations

import sqlite3
from typing import Iterable, List


def _qs(values: Iterable) -> str:
    return ",".join("?" * len(list(values)))


def _columns(conn: sqlite3.Connection, table: str) -> dict:
    return {r[1]: (r[2] or "").upper() for r in conn.execute(f'PRAGMA table_info("{table}")')}


def delete_matches_cascade(conn: sqlite3.Connection, match_ids: List[int]) -> int:
    """Smaže zápasy a související běhy, joby, claims, audit, predikce, snapshoty i research tabulky.

    Týmy a soutěže zůstávají (sdílí je historie). Zápasy s uloženým výsledkem se nikdy nemažou.
    Vrací počet smazaných zápasů.
    """
    ids = sorted({int(i) for i in match_ids})
    if not ids:
        return 0
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")  # mažeme ručně, od závislostí k zápasům
    try:
        protected = {int(r[0]) for r in conn.execute(
            f"SELECT match_id FROM match_statistics WHERE match_id IN ({_qs(ids)}) "
            "AND home_goals IS NOT NULL AND away_goals IS NOT NULL", ids)}
        ids = [i for i in ids if i not in protected]
        if not ids:
            return 0
        m = _qs(ids)

        run_strs = {r[0] for r in conn.execute(f"SELECT run_id FROM pipeline_runs WHERE match_id IN ({m})", ids) if r[0]}
        run_strs |= {r[0] for r in conn.execute(
            f"SELECT run_id FROM jobs WHERE match_id IN ({m}) AND run_id IS NOT NULL", ids)}
        run_strs = sorted(run_strs)
        r_ph = _qs(run_strs)
        run_ints = [int(r[0]) for r in conn.execute(
            f"SELECT id FROM runs WHERE run_id IN ({r_ph})", run_strs)] if run_strs else []

        job_rows = conn.execute(
            f"SELECT id, job_id FROM jobs WHERE match_id IN ({m})" + (f" OR run_id IN ({r_ph})" if run_strs else ""),
            ids + run_strs).fetchall()
        job_ints = [int(r[0]) for r in job_rows]
        job_strs = [r[1] for r in job_rows if r[1]]

        audit_rows = conn.execute(
            f"SELECT id, audit_id FROM audit_runs WHERE match_id IN ({m})" + (f" OR run_id IN ({r_ph})" if run_strs else ""),
            ids + run_strs).fetchall()
        audit_ints = [int(r[0]) for r in audit_rows]
        audit_strs = [r[1] for r in audit_rows if r[1]]
        if audit_ints:
            issue_sql = f"SELECT id FROM audit_issues WHERE audit_run_id IN ({_qs(audit_ints)})"
            issue_params = list(audit_ints)
            if audit_strs:
                issue_sql += f" OR audit_id IN ({_qs(audit_strs)})"
                issue_params += audit_strs
            issue_ids = [int(r[0]) for r in conn.execute(issue_sql, issue_params)]
            if issue_ids:
                ph = _qs(issue_ids)
                conn.execute(f"DELETE FROM audit_issue_evidence WHERE audit_issue_id IN ({ph})", issue_ids)
                conn.execute(f"DELETE FROM audit_issue_claims WHERE audit_issue_id IN ({ph})", issue_ids)
                conn.execute(f"DELETE FROM audit_issues WHERE id IN ({ph})", issue_ids)
            conn.execute(f"DELETE FROM audit_runs WHERE id IN ({_qs(audit_ints)})", audit_ints)

        claim_sql = f"SELECT id FROM claims WHERE match_id IN ({m})"
        claim_params = list(ids)
        if run_ints:
            claim_sql += f" OR run_id IN ({_qs(run_ints)})"
            claim_params += run_ints
        claim_ids = [int(r[0]) for r in conn.execute(claim_sql, claim_params)]
        if claim_ids:
            ph = _qs(claim_ids)
            conn.execute(f"DELETE FROM claim_evidence WHERE claim_id IN ({ph})", claim_ids)
            conn.execute(f"DELETE FROM claims WHERE id IN ({ph})", claim_ids)
        if job_ints:
            ph = _qs(job_ints)
            conn.execute(
                f"DELETE FROM job_dependencies WHERE job_id IN ({ph}) OR depends_on_job_id IN ({ph})",
                job_ints + job_ints)

        # Ostatní tabulky (vč. research_schema) podle sloupců match_id / run_id / job_id.
        skip = {"matches", "match_statistics", "jobs", "runs", "pipeline_runs", "teams", "competitions"}
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            if table in skip:
                continue
            cols = _columns(conn, table)
            if "match_id" in cols:
                conn.execute(f'DELETE FROM "{table}" WHERE match_id IN ({m})', ids)
            if "run_id" in cols:
                values = run_ints if "INT" in cols["run_id"] else run_strs
                if values:
                    conn.execute(f'DELETE FROM "{table}" WHERE run_id IN ({_qs(values)})', values)
            if "job_id" in cols:
                values = job_ints if "INT" in cols["job_id"] else job_strs
                if values:
                    conn.execute(f'DELETE FROM "{table}" WHERE job_id IN ({_qs(values)})', values)

        if job_ints:
            conn.execute(f"DELETE FROM jobs WHERE id IN ({_qs(job_ints)})", job_ints)
        if run_strs:
            conn.execute(f"DELETE FROM pipeline_runs WHERE run_id IN ({r_ph})", run_strs)
        if run_ints:
            conn.execute(f"DELETE FROM runs WHERE id IN ({_qs(run_ints)})", run_ints)
        conn.execute(f"DELETE FROM matches WHERE id IN ({m})", ids)
        conn.commit()
        return len(ids)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
