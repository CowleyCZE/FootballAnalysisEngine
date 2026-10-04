from urllib.parse import urlparse


class SearchSourceRegistry:
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
        "arsenal.com": "official_club",
        "chelsea.com": "official_club",
        "premierleague.com": "official_league",
        "uefa.com": "official_league",
        "bbc.com": "major_news",
        "skysports.com": "major_news",
        "livesport.cz": "aggregator",
        "eurofotbal.cz": "aggregator",
        "ruik.cz": "major_news",
    }

    def get_info(self, url: str) -> dict:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        source_type = self.DOMAINS.get(domain, "unknown")
        return {
            "domain": domain,
            "source_type": source_type,
            "authority": self.SOURCE_TYPES.get(source_type, 0.2),
        }
