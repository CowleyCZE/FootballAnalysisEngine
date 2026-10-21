"""TODO 5.1 – každá cesta /api/analysis/* je zaregistrována právě jednou."""
from collections import Counter

from app.main import app


def _all_routes(application):
    routes = []
    for r in application.routes:
        if hasattr(r, "methods") and hasattr(r, "path"):
            routes.append(r)
        elif hasattr(r, "original_router"):
            for sub_r in getattr(r.original_router, "routes", []):
                if hasattr(sub_r, "methods") and hasattr(sub_r, "path"):
                    routes.append(sub_r)
    return routes


def test_no_duplicate_method_path_registrations():
    pairs = Counter()
    for route in _all_routes(app):
        for method in getattr(route, "methods", None) or []:
            pairs[(method, route.path)] += 1
    duplicates = {k: v for k, v in pairs.items() if v > 1 and k[0] != "HEAD"}
    # /health a /api/health sdílí funkci, ale jde o různé cesty – duplicitou je jen stejná dvojice.
    assert duplicates == {}


def test_analysis_start_registered_once_and_router_extras_present():
    paths = [(m, r.path) for r in _all_routes(app) for m in (getattr(r, "methods", None) or [])]
    assert paths.count(("POST", "/api/analysis/start")) == 1
    assert ("GET", "/api/analysis/{run_id}") in paths
    assert ("GET", "/api/analysis/{run_id}/readiness") in paths
    assert ("POST", "/api/analysis/{run_id}/cancel") in paths


def test_router_orchestrator_is_lazy_and_uses_current_db_path(tmp_path, monkeypatch):
    import app.api.server as server_module
    from app.database.schema import initialize_database
    from app.orchestrator import router as router_module

    assert not hasattr(router_module, "orchestrator")  # žádná instance při importu
    db = str(tmp_path / "lazy.db")
    initialize_database(db)
    monkeypatch.setattr(server_module, "DB_PATH", db)
    assert router_module.get_orchestrator().db_path == db
