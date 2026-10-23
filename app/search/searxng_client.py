from __future__ import annotations

import os
import tempfile
import time
from typing import IO
from typing import Any

import httpx

class SearXNGClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        # Keep direct ResearchEngine usage consistent with API/worker clients.
        # SEARXNG_PORT is honored when the full URL is not explicitly supplied.
        if base_url is None:
            base_url = os.getenv("SEARXNG_URL") or f"http://127.0.0.1:{os.getenv('SEARXNG_PORT', '8080')}"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.min_interval = max(0.0, float(os.getenv("SEARXNG_MIN_INTERVAL_SECONDS", "2.0")))

    def _acquire_global_slot(self) -> IO[str] | None:
        """Serialize and pace requests across API/worker processes on the host."""
        if self.min_interval <= 0:
            return None
        try:
            import fcntl
        except ImportError:  # pragma: no cover - non-Unix fallback
            time.sleep(self.min_interval)
            return None

        lock_path = os.getenv(
            "SEARXNG_THROTTLE_FILE",
            os.path.join(tempfile.gettempdir(), "football-analysis-engine-searxng.lock"),
        )
        lock_file = open(lock_path, "a+", encoding="ascii")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        lock_file.seek(0)
        try:
            last_request = float(lock_file.read().strip() or "0")
        except ValueError:
            last_request = 0.0
        wait = self.min_interval - (time.time() - last_request)
        if wait > 0:
            time.sleep(wait)
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(str(time.time()))
        lock_file.flush()
        return lock_file

    @staticmethod
    def _release_global_slot(lock_file: IO[str] | None) -> None:
        if lock_file is None:
            return
        import fcntl
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()

    async def search(self, query: str, language: str = "all", page: int = 1, time_range: str | None = None) -> dict:
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "language": language,
            "pageno": page,
        }
        if time_range:
            params["time_range"] = time_range

        # Hold a host-level lock for the entire request: without it, parallel
        # worker processes can flood upstream engines and trigger CAPTCHA/429.
        import asyncio
        lock_file = await asyncio.to_thread(self._acquire_global_slot)
        try:
            # SearXNG botdetection loguje chybu, když chybí X-Forwarded-For/X-Real-IP (přímé volání bez proxy).
            headers = {"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"}
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
                response = await client.get(f"{self.base_url}/search", params=params)
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise RuntimeError(
                        f"SearXNG returned invalid JSON (HTTP {response.status_code})"
                    ) from exc
                if not isinstance(payload, dict) or not isinstance(payload.get("results", []), list):
                    raise RuntimeError("SearXNG returned an unexpected JSON response")
                return payload
        finally:
            await asyncio.to_thread(self._release_global_slot, lock_file)
