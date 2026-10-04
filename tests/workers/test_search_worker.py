from app.workers.search_worker import SearchWorker


def test_search_worker_requires_query():
    try:
        SearchWorker.execute({})
    except ValueError as exc:
        assert str(exc) == "SEARCH job requires a non-empty query"
    else:
        raise AssertionError("Expected ValueError")
