from app.research.source_selector import SourceSelector


class FakeRegistry:
    def __init__(self):
        self.data = {
            "official.example": {
                "domain": "official.example",
                "source_type": "official",
                "authority": 1.0,
            },
            "news.example": {
                "domain": "news.example",
                "source_type": "news",
                "authority": 0.8,
            },
        }

    def get_domain_info(self, url):
        domain = url.split("//", 1)[1].split("/", 1)[0]
        return self.data.get(
            domain,
            {"domain": domain, "source_type": "unknown", "authority": 0.2},
        )


def test_selector_ranks_before_domain_limit():
    selector = SourceSelector(FakeRegistry(), max_per_domain=1)

    results = [
        {
            "url": "https://official.example/low",
            "title": "Official low",
            "content": "",
            "relevance": 10,
        },
        {
            "url": "https://official.example/high",
            "title": "Official high",
            "content": "",
            "relevance": 90,
        },
        {
            "url": "https://news.example/article",
            "title": "News",
            "content": "",
            "relevance": 80,
        },
    ]

    selected = selector.select_candidates(results)

    assert [item["url"] for item in selected] == [
        "https://official.example/low",
        "https://news.example/article",
    ]


def test_selector_normalizes_tracking_parameters_before_selection():
    selector = SourceSelector(FakeRegistry(), max_per_domain=3)

    results = [
        {
            "url": "https://official.example/article?utm_source=x",
            "title": "Article",
            "content": "",
            "relevance": 50,
        }
    ]

    selected = selector.select_candidates(results)

    assert selected[0]["url"] == "https://official.example/article"
