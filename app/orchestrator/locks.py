import sqlite3
import logging

logger = logging.getLogger(__name__)

class DeadlockDetector:
    @staticmethod
    def would_cause_cycle(conn: sqlite3.Connection, job_id_pk: int, depends_on_job_id_pk: int) -> bool:
        if job_id_pk == depends_on_job_id_pk:
            return True

        visited = set()
        queue = [depends_on_job_id_pk]

        cursor = conn.cursor()
        while queue:
            curr = queue.pop(0)
            if curr == job_id_pk:
                return True
            visited.add(curr)

            cursor.execute("SELECT depends_on_job_id FROM job_dependencies WHERE job_id = ?", (curr,))
            rows = cursor.fetchall()
            for r in rows:
                dep = r[0]
                if dep not in visited:
                    queue.append(dep)

        return False
