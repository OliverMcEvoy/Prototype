from backend.app import app
from backend.service import run_live_scan


def test_backend_imports():
    assert app.title == "Betfair × Polymarket Backend"
    assert callable(run_live_scan)
