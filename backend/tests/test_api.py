from fastapi.testclient import TestClient
from unittest.mock import patch

from backend.app import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_dashboard_scan_returns_payload():
    fake_payload = {
        "ok": True,
        "sport": "all",
        "threshold": 0.35,
        "investment": 100.0,
        "gbp_usd_rate": 1.27,
        "generated_at": "2026-06-10T00:00:00+00:00",
        "betfair_event_count": 1,
        "polymarket_event_count": 1,
        "matched_pair_count": 1,
        "unmatched_betfair_count": 0,
        "unmatched_polymarket_count": 0,
        "matched_pairs": [],
        "opportunity_count": 0,
        "opportunities": [],
        "sample_betfair_events": [],
        "sample_polymarket_markets": [],
    }

    with patch("backend.app.run_live_scan", return_value=fake_payload):
        response = client.get("/api/dashboard/scan?sport=all")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["betfair_event_count"] == 1
