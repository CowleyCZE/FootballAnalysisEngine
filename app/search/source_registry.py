from __future__ import annotations

from urllib.parse import urlparse


class SearchSourceRegistry:
    DEFAULT_AUTHORITY = 0.2

    SOURCE_TYPES = {
        "official_club": 1.0,
        "official_league": 1.0,
        "statistical_provider": 0.9,
        "major_news": 0.8,
        "aggregator": 0.5,
        "unknown": 0.2,
    }

    DOMAINS = {
        "sparta.cz": "official_club",
        "slavia.cz": "official_club",
        "fcbayern.com": "official_club",
        "realmadrid.com": "official_club",
        "premierleague.com": "official_league",
        "uefa.com": "official_league",
        "bbc.com": "major_news",
        "bbc.co.uk": "major_news",
        "skysports.com": "major_news",
        "livesport.cz": "aggregator",
        "eurofotbal.cz": "aggregator",
        "ruik.cz": "major_news",
    }

    def get_domain(self, url: str) -> str:
        try:
            domain = urlparse(url).netloc.lower()
        except Exception:
            return ""

        if domain.startswith("www."):
            domain = domain[4:]

        return domain

    def get_source_type(self, url: str) -> str:
        domain = self.get_domain(url)

        if domain in self.DOMAINS:
            return self.DOMAINS[domain]

        return "unknown"

    def get_publisher_id(self, url: str) -> str:
        """Stable publisher identity used for source-independence checks."""
        return self.get_domain(url)

    def get_authority(self, url: str) -> float:
        source_type = self.get_source_type(url)
        return self.SOURCE_TYPES.get(
            source_type,
            self.DEFAULT_AUTHORITY,
        )

    def get_info(self, url: str) -> dict:
        domain = self.get_domain(url)
        source_type = self.get_source_type(url)
        authority = self.SOURCE_TYPES.get(
            source_type,
            self.DEFAULT_AUTHORITY,
        )

        return {
            "domain": domain,
            "source_type": source_type,
            "authority": authority,
        }
