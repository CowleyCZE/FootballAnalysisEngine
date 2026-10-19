#!/usr/bin/env python3
"""Read-only kontrola připravenosti FootballAnalysisEngine.

Core prediction works without paid APIs. SearXNG and Ollama are optional local
services; their absence is reported explicitly instead of being hidden.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "database" / "football.db"


def http_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def main() -> int:
    checks: dict[str, dict[str, object]] = {}
    checks["python"] = {"ok": True, "detail": os.sys.version.split()[0]}
    for package in ("fastapi", "httpx", "pydantic", "yaml"):
        checks[f"python:{package}"] = {"ok": importlib.util.find_spec(package) is not None}
    checks["sqlite"] = {"ok": DB.exists(), "detail": str(DB)}
    searx = http_json(f"http://127.0.0.1:{os.getenv('SEARXNG_PORT', '8080')}/search?q=football&format=json")
    checks["searxng"] = {"ok": isinstance(searx, dict) and isinstance(searx.get("results"), list), "optional": True}
    ollama = http_json(f"{os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')}/api/tags")
    models = [m.get("name") for m in (ollama or {}).get("models", []) if isinstance(m, dict)]
    desired = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
    checks["ollama"] = {"ok": isinstance(ollama, dict), "optional": True, "models": models, "desired_model": desired, "model_available": desired in models}
    print(json.dumps({"project_root": str(ROOT), "checks": checks}, ensure_ascii=False, indent=2))
    core_ok = all(bool(v.get("ok")) for k, v in checks.items() if not v.get("optional"))
    return 0 if core_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
