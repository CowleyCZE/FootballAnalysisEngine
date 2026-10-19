import time
from urllib.parse import urlparse

class DomainRateLimiter:
    def __init__(self, interval_seconds: float = 2.0):
        self.interval_seconds = interval_seconds
        self.last_request_time: dict[str, float] = {}

    def wait_for_domain(self, url: str):
        domain = urlparse(url).netloc
        now = time.time()
        if domain in self.last_request_time:
            elapsed = now - self.last_request_time[domain]
            if elapsed < self.interval_seconds:
                time.sleep(self.interval_seconds - elapsed)
        self.last_request_time[domain] = time.time()