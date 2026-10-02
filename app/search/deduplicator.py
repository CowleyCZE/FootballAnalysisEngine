import hashlib
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

TRACKING_PARAMETERS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}

def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    query_items = [
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in TRACKING_PARAMETERS
    ]
    query = urlencode(query_items)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))

def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def deduplicate(results: list) -> list:
    unique = {}
    for result in results:
        canonical = canonicalize_url(result.url)
        key = f"url:{canonical}" if canonical else f"content:{content_hash(result.content)}"
        if key not in unique:
            unique[key] = result
    return list(unique.values())