"""TODO 5.2 – init.sh generuje náhodný token a nikdy nezapisuje výchozí řetězec."""
import os
import re
import subprocess
import sys
from pathlib import Path

INIT_SH = Path(__file__).resolve().parents[1] / "init.sh"
PLACEHOLDER = "change-this-secure-token-in-production"


def _env_section() -> str:
    text = INIT_SH.read_text(encoding="utf-8")
    start = text.index('say "3. Konfigurace .env"')
    end = text.index('say "4. Inicializace databáze"')
    return text[start:end]


def _run_section(cwd: Path):
    script = (
        "set -Eeuo pipefail\n"
        "say() { :; }; note() { :; }; warn() { echo \"WARN: $*\"; }\n"
        f"PYTHON='{sys.executable}'\n" + _env_section()
    )
    return subprocess.run(["bash", "-c", script], cwd=cwd, capture_output=True, text=True, check=True)


def _read_env(path: Path) -> dict:
    return dict(line.split("=", 1) for line in path.read_text().splitlines() if "=" in line and not line.startswith("#"))


def test_script_never_writes_default_token_into_new_env():
    assert f"WORKER_API_TOKEN={PLACEHOLDER}" not in _env_section().replace("'", "").split("sed -i")[0]


def test_new_env_gets_random_token_of_sufficient_length(tmp_path):
    _run_section(tmp_path)
    env = _read_env(tmp_path / ".env")
    assert env["WORKER_API_TOKEN"] == env["API_SECRET_TOKEN"]
    assert env["WORKER_API_TOKEN"] != PLACEHOLDER
    assert len(env["WORKER_API_TOKEN"]) >= 40
    assert re.fullmatch(r"[A-Za-z0-9_\-]+", env["WORKER_API_TOKEN"])
    assert (os.stat(tmp_path / ".env").st_mode & 0o777) == 0o600


def test_two_runs_generate_different_tokens(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    _run_section(a); _run_section(b)
    assert _read_env(a / ".env")["WORKER_API_TOKEN"] != _read_env(b / ".env")["WORKER_API_TOKEN"]


def test_existing_env_with_placeholder_is_upgraded_but_custom_token_kept(tmp_path):
    (tmp_path / ".env").write_text(f"WORKER_API_TOKEN={PLACEHOLDER}\nAPI_SECRET_TOKEN={PLACEHOLDER}\nFAE_AUTO_HISTORY=1\nOLLAMA_TIMEOUT=60\n")
    out = _run_section(tmp_path)
    env = _read_env(tmp_path / ".env")
    assert env["WORKER_API_TOKEN"] != PLACEHOLDER and env["API_SECRET_TOKEN"] != PLACEHOLDER
    assert "WARN" in out.stdout

    keep = tmp_path / "keep"
    keep.mkdir()
    (keep / ".env").write_text("WORKER_API_TOKEN=muj-vlastni-token\nAPI_SECRET_TOKEN=muj-vlastni-token\nFAE_AUTO_HISTORY=1\nOLLAMA_TIMEOUT=60\n")
    _run_section(keep)
    assert _read_env(keep / ".env")["WORKER_API_TOKEN"] == "muj-vlastni-token"
