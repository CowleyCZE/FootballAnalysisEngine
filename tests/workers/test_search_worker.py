from unittest.mock import MagicMock, patch
from app.workers.search_worker import SearchWorker


def test_search_worker_requires_query():
    try:
        SearchWorker.execute({})
    except ValueError as exc:
        assert str(exc) == "SEARCH job requires a non-empty query"
    else:
        raise AssertionError("Expected ValueError")


def test_search_worker_uses_proxy():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "status": "COMPLETED",
        "query": "Arsenal vs Chelsea line-up",
        "results": [{"title": "Lineup news", "url": "https://example.com/lineup"}],
        "result_count": 1,
        "source": "notebook_proxy"
    }

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        payload = {
            "query": "Arsenal vs Chelsea line-up",
            "use_proxy": True,
            "search_api_url": "http://notebook:8000/api/internal/search"
        }
        res = SearchWorker.execute(payload)
        assert res["status"] == "COMPLETED"
        assert res["source"] == "notebook_proxy"
        assert len(res["results"]) == 1
        mock_post.assert_called_once()
