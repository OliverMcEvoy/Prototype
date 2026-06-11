from unittest.mock import patch

from backend.service import run_live_scan
from backend.models import ArbitrageOpportunity, Event, Outcome, PolymarketEvent
from datetime import datetime, timezone

NOW = datetime(2026, 6, 10, tzinfo=timezone.utc)


class FakeBetfairClient:
    def login(self):
        return True

    def get_odds(self, sport_hints=None, days_ahead=7, min_hours_ahead=0):
        return [
            Event(
                id="bf-1",
                sport="Soccer",
                commence_time=NOW,
                home_team="Portugal",
                away_team="Nigeria",
                outcomes=[
                    Outcome("Portugal", 2.5, "Betfair Exchange", NOW),
                    Outcome("Nigeria", 3.0, "Betfair Exchange", NOW),
                ],
                category="soccer",
            )
        ]

    def get_politics_markets(self, days_ahead=400):
        return []

    def get_last_error(self):
        return None


class FakePolymarketClient:
    def get_sports_markets(self, sport_hint=None, active_only=True, min_volume=0):
        return [
            PolymarketEvent(
                id="pm-1",
                question="Portugal vs Nigeria",
                outcomes=["Portugal", "Nigeria"],
                prices=[0.55, 0.45],
                end_date=NOW,
                volume=1000,
                liquidity=200,
                sport_category="soccer",
            )
        ]

    def get_politics_markets(self, active_only=True, min_volume=0):
        return []


class FakeMarketMatcher:
    def __init__(self, similarity_threshold=0.35):
        self.similarity_threshold = similarity_threshold

    def find_matches(self, traditional_events, polymarket_events):
        return [(traditional_events[0], polymarket_events[0], 0.91)]


class FakeArbitrageEngine:
    def compare_markets(self, traditional_events, polymarket_events):
        opportunity = ArbitrageOpportunity(
            event=traditional_events[0],
            best_outcomes=traditional_events[0].outcomes,
            total_stake=100.0,
            stake_distribution={"Betfair Exchange": 50.0},
            profit=5.0,
            profit_percentage=5.0,
            roi=5.0,
        )
        return [opportunity]


def test_run_live_scan_serializes_live_payload():
    with patch(
        "backend.service._make_betfair_client", return_value=FakeBetfairClient()
    ), patch(
        "backend.service.PolymarketClient", return_value=FakePolymarketClient()
    ), patch(
        "backend.service.MarketMatcher", FakeMarketMatcher
    ), patch(
        "backend.service.ArbitrageEngine", return_value=FakeArbitrageEngine()
    ):
        payload = run_live_scan()

    assert payload["ok"] is True
    assert payload["betfair_event_count"] == 1
    assert payload["polymarket_event_count"] == 1
    assert payload["matched_pair_count"] == 1
    assert payload["opportunity_count"] == 1
