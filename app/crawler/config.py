"""Načítání `config/crawler.yaml` (TODO 5.3) s bezpečnými výchozími hodnotami.

Chybějící/poškozený soubor nikdy nevyhodí výjimku – použijí se výchozí hodnoty.
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "crawler.yaml"


@dataclass(frozen=True)
class CrawlerSettings:
    timeout_seconds: float = 20.0
    connect_timeout_seconds: float = 10.0
    max_retries: int = 3
    max_content_size_mb: float = 10.0
    follow_redirects: bool = True
    max_redirects: int = 5
    user_agent: str = "FootballAnalysisEngine/1.0"
    rate_limit_interval_seconds: float = 2.0
    javascript_enabled: bool = True
    javascript_timeout_seconds: float = 30.0


def _num(value: Any, default: float, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > minimum else default


def load_crawler_settings(path: Optional[Path] = None) -> CrawlerSettings:
    """Načte nastavení crawleru; neplatné hodnoty nahradí výchozími (s varováním u poškozeného souboru)."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    defaults = CrawlerSettings()
    if not config_path.exists():
        return defaults
    try:
        raw: Dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("[CRAWLER] Nelze načíst %s (%s) – používám výchozí hodnoty.", config_path, exc)
        return defaults
    section = raw.get("crawler") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        return defaults
    rate = section.get("rate_limit") if isinstance(section.get("rate_limit"), dict) else {}
    js = section.get("javascript") if isinstance(section.get("javascript"), dict) else {}
    user_agent = section.get("user_agent")
    try:
        retries = int(section.get("max_retries", defaults.max_retries))
    except (TypeError, ValueError):
        retries = defaults.max_retries
    try:
        max_redirects = int(section.get("max_redirects", defaults.max_redirects))
    except (TypeError, ValueError):
        max_redirects = defaults.max_redirects
    return CrawlerSettings(
        timeout_seconds=_num(section.get("timeout_seconds"), defaults.timeout_seconds),
        connect_timeout_seconds=_num(section.get("connect_timeout_seconds"), defaults.connect_timeout_seconds),
        max_retries=retries if retries >= 1 else defaults.max_retries,
        max_content_size_mb=_num(section.get("max_content_size_mb"), defaults.max_content_size_mb),
        follow_redirects=bool(section.get("follow_redirects", defaults.follow_redirects)),
        max_redirects=max_redirects if max_redirects >= 0 else defaults.max_redirects,
        user_agent=str(user_agent).strip() if isinstance(user_agent, str) and user_agent.strip() else defaults.user_agent,
        rate_limit_interval_seconds=_num(rate.get("interval_seconds"), defaults.rate_limit_interval_seconds),
        javascript_enabled=bool(js.get("enabled", defaults.javascript_enabled)),
        javascript_timeout_seconds=_num(js.get("timeout_seconds"), defaults.javascript_timeout_seconds),
    )
