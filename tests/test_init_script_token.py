"""TODO 5.2 – `init.sh` nikdy nezapisuje pevný výchozí token, jen náhodný z `secrets`."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT_SH = ROOT / "init.sh"
PLACEHOLDER = "change-this-secure-token-in-production"


def _text() -> str:
    return INIT_SH.read_text(encoding="utf-8")


def test_init_sh_generates_token_with_secrets():
    text = _text()
    assert "secrets.token_urlsafe(32)" in text


def test_init_sh_never_writes_placeholder_into_env():
    text = _text()
    # Výchozí řetězec smí být jen jako detekční vzor (porovnání/nahrazení), nikdy jako hodnota zapsaná do .env.
    for line in text.splitlines():
        stripped = line.strip()
        if PLACEHOLDER in stripped:
            assert stripped.startswith("PLACEHOLDER_TOKEN=") or "grep" in stripped or "sed" in stripped
    heredoc = re.search(r"cat <<EOF > \.env\n(.*?)\nEOF", text, re.S)
    assert heredoc is not None
    body = heredoc.group(1)
    assert PLACEHOLDER not in body
    assert "WORKER_API_TOKEN=${API_TOKEN}" in body
    assert "API_SECRET_TOKEN=${API_TOKEN}" in body


def test_init_sh_restricts_env_permissions_and_replaces_placeholder():
    text = _text()
    assert "chmod 600 .env" in text
    # Starý .env s výchozím tokenem se přepíše náhodným.
    assert "sed -i" in text and "WORKER_API_TOKEN" in text


def test_init_sh_valid_bash_syntax():
    result = subprocess.run(["bash", "-n", str(INIT_SH)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_no_placeholder_token_in_repo_scripts():
    for path in (ROOT / "scripts").glob("*.sh"):
        content = path.read_text(encoding="utf-8")
        assert f"TOKEN={PLACEHOLDER}" not in content, path.name
