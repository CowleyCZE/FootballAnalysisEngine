import threading
import time
from urllib.parse import urlparse


class DomainRateLimiter:
    """Minimální odstup mezi požadavky na stejnou doménu; bezpečné i při paralelním crawlu."""

    def __init__(self, interval_seconds: float = 2.0):
        self.interval_seconds = interval_seconds
        self.last_request_time: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait_for_domain(self, url: str):
        domain = urlparse(url).netloc
        # Termín dalšího povoleného požadavku se rezervuje pod zámkem, spí se mimo něj:
        # vlákna na stejnou doménu se tak řadí za sebe a ostatní domény neblokují.
        with self._lock:
            now = time.time()
            slot = max(now, self.last_request_time.get(domain, 0.0) + self.interval_seconds)
            self.last_request_time[domain] = slot
        delay = slot - now
        if delay > 0:
            time.sleep(delay)
