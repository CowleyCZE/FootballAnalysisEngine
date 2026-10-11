#!/usr/bin/env python3
"""Lehký a autentizovaný worker FootballAnalysisEngine pro Termux / Note 9.

Vyžaduje proměnnou WORKER_API_TOKEN. Token se záměrně neukládá do config.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


CONFIG_FILE = Path(__file__).with_name("config.json")
DEFAULT_CONFIG = {
    "worker_id": "note9-01",
    "worker_name": "Samsung Galaxy Note 9",
    "worker_version": "1.1.0-note9",
    "server_url": "http://192.168.31.135:8000",
    "heartbeat_interval": 30,
    "poll_interval": 5,
    "request_timeout": 30,
    "max_retries": 3,
    # Neuvádějte "generic": mohl by získat úlohu, kterou telefon neumí.
    "capabilities": ["TEST", "SEARCH", "CRAWL"],
}


def sanitize_url(url: str) -> str:
    """Masks query parameters and credentials in URLs for logging."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc
        if "@" in netloc:
            userinfo, host = netloc.split("@", 1)
            if ":" in userinfo:
                user = userinfo.split(":", 1)[0]
                netloc = f"{user}:***@{host}"
            else:
                netloc = f"***@{host}"
        path = parsed.path or "/"
        query_str = "?[redacted]" if parsed.query else ""
        return f"{parsed.scheme}://{netloc}{path}{query_str}"
    except Exception:
        return "[sanitized-url]"


def sanitize_text(text: str, token: str | None = None) -> str:
    """Removes secret tokens and credentials from output/error messages."""
    if not text:
        return ""
    if token and token in text:
        text = text.replace(token, "[REDACTED_TOKEN]")
    env_token = os.environ.get("WORKER_API_TOKEN", "").strip()
    if env_token and env_token in text:
        text = text.replace(env_token, "[REDACTED_TOKEN]")
    return text


def log(message: str) -> None:
    clean_msg = sanitize_text(message)
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {clean_msg}", flush=True)


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log(f"Vytvořen {CONFIG_FILE}; zkontrolujte server_url.")
        return dict(DEFAULT_CONFIG)
    try:
        user_config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Nelze načíst {CONFIG_FILE}: {exc}") from exc
    if not isinstance(user_config, dict):
        raise RuntimeError("config.json musí obsahovat JSON objekt.")
    return DEFAULT_CONFIG | user_config


class TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.in_title = tag.lower() == "title"

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self.parts).split())[:500]


class Note9Worker:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.server_url = str(config["server_url"]).rstrip("/")
        parsed = urlparse(self.server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError("server_url musí být platná http(s) URL.")
        self.worker_id = str(config["worker_id"])
        self.worker_name = str(config["worker_name"])
        self.worker_version = str(config["worker_version"])
        self.capabilities = [str(c) for c in config["capabilities"] if str(c) in {"TEST", "SEARCH", "CRAWL"}]
        if not self.capabilities:
            raise RuntimeError("capabilities musí obsahovat alespoň TEST, SEARCH nebo CRAWL.")
        self.poll_interval = max(1.0, float(config["poll_interval"]))
        self.heartbeat_interval = max(5.0, float(config["heartbeat_interval"]))
        self.timeout = max(5.0, float(config["request_timeout"]))
        self.max_retries = max(1, int(config["max_retries"]))
        self.running = True
        token = os.environ.get("WORKER_API_TOKEN", "").strip()
        if not token:
            raise RuntimeError("Chybí WORKER_API_TOKEN. Nastavte ho před spuštěním workeru.")
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[502, 503, 504],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": f"FootballAnalysisEngine-Note9-Worker/{self.worker_version}",
            "X-Worker-Token": token,
        })
        self.last_heartbeat = 0.0
        self.is_online = False
        self.consecutive_failures = 0

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.server_url}{path}"
        safe_url = sanitize_url(url)
        error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                if response.status_code == 401:
                    raise RuntimeError("HTTP 401 Unauthorized: WORKER_API_TOKEN is invalid or rejected by server.")
                elif response.status_code == 503:
                    raise RuntimeError("HTTP 503 Service Unavailable: Server token is missing or service is unavailable.")
                response.raise_for_status()
                if not self.is_online:
                    log(f"Spojení se serverem navázáno/obnoveno (ONLINE): {safe_url}")
                    self.is_online = True
                self.consecutive_failures = 0
                return response
            except requests.RequestException as exc:
                error = exc
                if attempt < self.max_retries:
                    time.sleep(min(2 ** (attempt - 1), 4))

        # Všechny pokusy selhaly
        if self.is_online:
            err_msg = sanitize_text(str(error))
            log(f"Spojení se serverem přerušeno (OFFLINE): {err_msg}")
            self.is_online = False
        self.consecutive_failures += 1
        raise error or RuntimeError(f"HTTP požadavek selhal: {method} {safe_url}")

    def register(self) -> None:
        response = self.request("POST", "/api/workers/register", json={
            "worker_id": self.worker_id,
            "worker_name": self.worker_name,
            "worker_version": self.worker_version,
            "capabilities": self.capabilities,
        })
        log(f"Registrace u serveru {sanitize_url(self.server_url)}: {response.json().get('status', 'ok')}")

    def heartbeat(self, force: bool = False) -> None:
        if not force and time.monotonic() - self.last_heartbeat < self.heartbeat_interval:
            return
        self.request("POST", "/api/workers/heartbeat", json={"worker_id": self.worker_id, "status": "online"})
        self.last_heartbeat = time.monotonic()

    def claim(self) -> dict[str, Any] | None:
        data = self.request("POST", "/api/jobs/claim", json={
            "worker_id": self.worker_id,
            "capabilities": self.capabilities,
        }).json()
        if data.get("status") == "no_job":
            return None
        job = data.get("job")
        if data.get("status") != "job_assigned" or not isinstance(job, dict):
            raise RuntimeError(f"Neplatná odpověď claim: {data}")
        return job

    def submit(self, job_id: str, status: str, result: dict[str, Any] | None = None, error: str | None = None) -> None:
        body: dict[str, Any] = {"worker_id": self.worker_id, "status": status}
        if result is not None:
            body["result"] = result
        if error:
            body["error"] = sanitize_text(error)
        response = self.request("POST", f"/api/jobs/{job_id}/result", json=body)
        log(f"Odeslání výsledku jobu {job_id} ({status}): HTTP {response.status_code}")

    @staticmethod
    def run_test(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "COMPLETED",
            "message": "Note 9 worker provedl TEST úlohu.",
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "payload_keys": sorted(payload.keys()),
        }

    def run_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        if not query:
            raise ValueError("SEARCH úloha nemá query; nelze vrátit falešný úspěch.")
        log(f"SEARCH start: query='{query}', tým='{payload.get('team') or ''}', doména='{payload.get('domain') or ''}'")
        proxy_payload = {
            "query": query,
            "language": str(payload.get("language") or "en"),
            "priority": int(payload.get("priority") or 50),
            "time_range": payload.get("time_range"),
            "reason": str(payload.get("reason") or ""),
            "team": str(payload.get("team") or ""),
            "topic_terms": list(payload.get("topic_terms") or []),
            "data_cutoff_at": payload.get("data_cutoff_at") or payload.get("cutoff"),
        }
        result = self.request("POST", "/api/internal/search", json=proxy_payload).json()
        if result.get("status") != "COMPLETED":
            raise RuntimeError(f"Vyhledávací proxy nevrátila COMPLETED: {result}")
        results_cnt = len(result.get("results") or [])
        log(f"SEARCH dokončen: nalezeno {results_cnt} výsledků pro query='{query}'")
        return result

    def run_crawl(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("CRAWL úloha neobsahuje platnou http(s) URL.")
        safe_c_url = sanitize_url(url)
        log(f"CRAWL start: cíl={safe_c_url}")
        response = requests.get(url, timeout=self.timeout, headers={"User-Agent": self.session.headers["User-Agent"]})
        response.raise_for_status()
        # Omezíme přenášený obsah; telefon netvrdí, že provedl plný Playwright crawl.
        content = response.content[:1_000_000]
        text = response.text[:200_000]
        parser = TitleParser()
        try:
            parser.feed(text)
        except Exception:
            pass
        title_str = parser.title or None
        log(f"CRAWL dokončen: host/path={parsed.netloc}{parsed.path}, HTTP {response.status_code}, délka={len(response.content)} B, titul='{title_str[:60] if title_str else 'N/A'}'")
        return {
            "status": "COMPLETED",
            "url": url,
            "final_url": response.url,
            "status_code": response.status_code,
            "content_length": len(response.content),
            "content_hash": hashlib.sha256(content).hexdigest(),
            "title": title_str,
            "used_playwright": False,
            "truncated": len(response.content) > len(content),
        }

    def process(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("id") or job.get("job_id") or "")
        job_type = str(job.get("job_type") or "").upper()
        payload = job.get("payload") or {}
        domain = str(payload.get("domain") or "")
        attempt = job.get("attempt_number") or payload.get("_job_attempt_number") or 1
        domain_info = f", doména={domain}" if domain else ""

        if not job_id or not isinstance(payload, dict):
            raise RuntimeError(f"Neplatná úloha ze serveru: {job}")

        log(f"Převzat job ID={job_id}, typ={job_type}{domain_info}, pokus={attempt}")

        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "TEST": self.run_test,
            "SEARCH": self.run_search,
            "CRAWL": self.run_crawl,
        }
        handler = handlers.get(job_type)
        if handler is None:
            self.submit(job_id, "FAILED", error=f"Note 9 nepodporuje typ úlohy {job_type}.")
            return
        try:
            result = handler(payload)
            self.submit(job_id, "SUCCESS", result=result)
            log(f"Úloha {job_id} ({job_type}) úspěšně dokončena.")
        except Exception as exc:
            err_msg = f"{type(exc).__name__}: {exc}"
            self.submit(job_id, "FAILED", error=err_msg)
            log(f"Úloha {job_id} ({job_type}) selhala: {sanitize_text(err_msg)}")

    def run(self) -> None:
        import random
        log(f"Start Note9Worker ID={self.worker_id}, Name='{self.worker_name}', Ver={self.worker_version}, Server={sanitize_url(self.server_url)}, Schopnosti={', '.join(self.capabilities)}")
        while self.running:
            try:
                if not self.is_online and self.consecutive_failures == 0:
                    try:
                        self.register()
                        self.heartbeat(force=True)
                    except Exception:
                        pass

                self.heartbeat()
                job = self.claim()
                if job:
                    self.process(job)
                else:
                    time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                err_text = str(exc)
                if "401" in err_text or "503" in err_text:
                    if self.consecutive_failures <= 1:
                        log(f"Server vrátil chybový status: {sanitize_text(err_text)}")
                backoff = min(60.0, (2 ** min(self.consecutive_failures, 6)) + random.uniform(0.5, 2.0))
                time.sleep(backoff)
        log(f"Ukončování Note9Worker ID={self.worker_id}...")


def main() -> None:
    try:
        worker = Note9Worker(load_config())
    except Exception as exc:
        print(f"CHYBA konfigurace: {exc}", file=sys.stderr)
        raise SystemExit(2)
    signal.signal(signal.SIGINT, lambda *_: setattr(worker, "running", False))
    signal.signal(signal.SIGTERM, lambda *_: setattr(worker, "running", False))
    worker.run()


if __name__ == "__main__":
    main()
