#!/usr/bin/env python3
"""Create/update the private local SearXNG configuration safely."""
from __future__ import annotations

import os
import secrets
import sys
import tempfile
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TARGET = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else ROOT / f"services/searxng/runtime-config-{os.getuid()}/settings.yml"
)
TEMPLATE = ROOT / "services/searxng/core-config/settings.yml"
SEARCH_ENGINES = ("bing", "seznam", "yep", "yahoo")


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    try:
        source_text = TARGET.read_text(encoding="utf-8") if TARGET.exists() else TEMPLATE.read_text(encoding="utf-8")
    except PermissionError:
        # SearXNG's Docker entrypoint normally chowns mounted configuration to
        # its internal user. Recover from older runs using the tracked template.
        print("Existující konfigurace není čitelná; obnovuji ji z projektové šablony.")
        source_text = TEMPLATE.read_text(encoding="utf-8")
    config = yaml.safe_load(source_text) or {}

    defaults = config.get("use_default_settings", True)
    if not isinstance(defaults, dict):
        defaults = {}
    engine_defaults = defaults.setdefault("engines", {})
    if not isinstance(engine_defaults, dict):
        engine_defaults = {}
        defaults["engines"] = engine_defaults
    engine_defaults["keep_only"] = list(SEARCH_ENGINES)
    config["use_default_settings"] = defaults

    server = config.setdefault("server", {})
    if not isinstance(server, dict):
        server = {}
        config["server"] = server
    # The real key is held in the private Docker env file, not this config,
    # because SearXNG runs as a different UID and owns the mounted file.
    server["secret_key"] = "managed-by-SEARXNG_SECRET-environment"

    # These were each verified against the running local SearXNG instance.
    config["engines"] = [{"name": name, "disabled": False} for name in SEARCH_ENGINES]

    fd, temp_name = tempfile.mkstemp(prefix=".settings-", dir=str(TARGET.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.safe_dump(config, handle, allow_unicode=True, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        # No secret is stored here; the container must be able to read it as
        # its unprivileged searxng user. FORCE_OWNERSHIP=false keeps ownership.
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, TARGET)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    print("Místní SearXNG konfigurace nastavena na ověřené enginy: " + ", ".join(SEARCH_ENGINES))
    env_path = ROOT / "services/searxng/.env"
    env_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    secret = ""
    found_secret = False
    updated_lines = []
    for line in env_lines:
        if line.partition("=")[0].strip() == "SEARXNG_SECRET":
            secret = line.partition("=")[2].strip().strip('"\'')
            found_secret = True
            updated_lines.append(line)
        else:
            updated_lines.append(line)
    if not found_secret or not secret:
        secret = secrets.token_hex(32)
        if found_secret:
            updated_lines = [
                f"SEARXNG_SECRET={secret}" if line.partition("=")[0].strip() == "SEARXNG_SECRET" else line
                for line in updated_lines
            ]
        else:
            updated_lines.append(f"SEARXNG_SECRET={secret}")
    fd, env_temp = tempfile.mkstemp(prefix=".searxng-env-", dir=str(env_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(updated_lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(env_temp, 0o600)
        os.replace(env_temp, env_path)
    finally:
        if os.path.exists(env_temp):
            os.unlink(env_temp)

    print("Tajný klíč uložen odděleně do .env s oprávněním 600; v YAML konfiguraci není.")


if __name__ == "__main__":
    main()
