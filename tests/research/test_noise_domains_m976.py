import pytest

from app.search.sport_filter import is_blocked_url


@pytest.mark.parametrize("url", [
    "https://poki.com/en/g/hill-climb-racing-lite?msockid=abc",
    "https://www.zhihu.com/question/303289328",
    "https://storage-cdn.wemod.com/x.exe",
])
def test_non_football_domains_blocked(url):
    assert is_blocked_url(url)


def test_football_domain_not_blocked():
    assert not is_blocked_url("https://www.eurofotbal.cz/chance-liga/2025-2026/preview/fc-zlin-1-fc-slovacko-1067236/")
