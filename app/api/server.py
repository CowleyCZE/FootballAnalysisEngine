from datetime import datetime, timezone
import json
import sqlite3

from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(
    title="Football Analysis Engine",
    version="0.2.0",
)


DB_PATH = "database/football.db"


def now():
    return datetime.now(timezone.utc).isoformat()


class WorkerRegistration(BaseModel):
    worker_id: str
    worker_name: str
    worker_version: str


class WorkerHeartbeat(BaseModel):
    worker_id: str
    status: str = "online"


class JobResult(BaseModel):
    worker_id: str
    status: str
    result: dict | None = None
    error: str | None = None


@app.get("/")
def root():
    return {
        "system": "Football Analysis Engine",
        "status": "online",
        "version": "0.2.0",
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "timestamp": now(),
    }


@app.get("/api/worker/heartbeat")
def notebook_worker_heartbeat():
    return {
        "status": "online",
        "worker": "notebook",
        "timestamp": now(),
    }


@app.post("/api/workers/register")
def register_worker(worker: WorkerRegistration):

    connection = sqlite3.connect(DB_PATH)

    connection.execute(
        """
        INSERT INTO workers (
            worker_id,
            worker_name,
            worker_version,
            status,
            last_seen,
            updated_at
        )
        VALUES (?, ?, ?, 'online', ?, ?)
        ON CONFLICT(worker_id)
        DO UPDATE SET
            worker_name = excluded.worker_name,
            worker_version = excluded.worker_version,
            status = 'online',
            last_seen = excluded.last_seen,
            updated_at = excluded.updated_at
        """,
        (
            worker.worker_id,
            worker.worker_name,
            worker.worker_version,
            now(),
            now(),
        ),
    )

    connection.commit()
    connection.close()

    return {
        "status": "registered",
        "worker_id": worker.worker_id,
    }


@app.post("/api/workers/heartbeat")
def worker_heartbeat(data: WorkerHeartbeat):

    connection = sqlite3.connect(DB_PATH)

    connection.execute(
        """
        UPDATE workers
        SET status = ?,
            last_seen = ?,
            updated_at = ?
        WHERE worker_id = ?
        """,
        (
            data.status,
            now(),
            now(),
            data.worker_id,
        ),
    )

    connection.commit()
    connection.close()

    return {
        "status": "ok",
        "worker_id": data.worker_id,
        "timestamp": now(),
    }


@app.post("/api/jobs/claim")
def claim_job(data: dict):
    worker_id = data.get("worker_id")
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    # Atomické převzetí úlohy z fronty
    cursor.execute("BEGIN IMMEDIATE")
    cursor.execute("""
        SELECT id, job_type, payload 
        FROM jobs 
        WHERE status = 'queued' 
        ORDER BY priority DESC, created_at ASC 
        LIMIT 1
    """)
    job = cursor.fetchone()

    if not job:
        connection.rollback()
        connection.close()
        return {"status": "no_job"}

    job_id, job_type, payload = job

    cursor.execute("""
        UPDATE jobs 
        SET status = 'claimed', worker_id = ?, claimed_at = ? 
        WHERE id = ?
    """, (worker_id, now(), job_id))

    connection.commit()
    connection.close()

    return {
        "status": "job_assigned",
        "job": {
            "id": job_id,
            "job_type": job_type,
            "payload": json.loads(payload) if payload else {}
        }
    }


@app.post("/api/jobs/{job_id}/result")
def job_result(job_id: int, data: JobResult):
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()

    # Uložení do historie výsledků
    cursor.execute("""
        INSERT INTO job_results (job_id, worker_id, status, result_json)
        VALUES (?, ?, ?, ?)
    """, (job_id, data.worker_id, data.status, json.dumps(data.result)))

    # Aktualizace stavu hlavní úlohy
    new_status = "success" if data.status == "success" else "failed"
    cursor.execute("""
        UPDATE jobs 
        SET status = ?, finished_at = ? 
        WHERE id = ?
    """, (new_status, now(), job_id))

    connection.commit()
    connection.close()

    return {"status": "ok", "job_id": job_id}
