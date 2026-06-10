"""Live data orchestration for the backend API."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.arbitrage_engine import ArbitrageEngine
from backend.betfair_client import BetfairClient
from backend.config import Config
from backend.market_matcher import MarketMatcher
from backend.models import ArbitrageOpportunity, Event, Outcome, PolymarketEvent
from backend.polymarket_client import PolymarketClient


def _dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _serialize_outcome(outcome: Outcome) -> Dict[str, Any]:
    return {
        "name": outcome.name,
        "price": outcome.price,
        "bookmaker": outcome.bookmaker,
        "last_update": _dt(outcome.last_update),
        "volume": outcome.volume,
    }


def _serialize_event(event: Event) -> Dict[str, Any]:
    return {
        "id": event.id,
        "sport": event.sport,
        "commence_time": _dt(event.commence_time),
        "home_team": event.home_team,
        "away_team": event.away_team,
        "category": event.category,
        "description": event.description,
        "match_quality": event.match_quality,
        "outcomes": [_serialize_outcome(outcome) for outcome in event.outcomes],
    }


def _serialize_pm_event(event: PolymarketEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "question": event.question,
        "outcomes": list(event.outcomes or []),
        "prices": list(event.prices or []),
        "end_date": _dt(event.end_date),
        "volume": event.volume,
        "liquidity": event.liquidity,
        "sport_category": event.sport_category,
        "event_slug": event.event_slug,
        "decimal_odds": event.to_decimal_odds(),
    }


def _serialize_opportunity(opportunity: ArbitrageOpportunity) -> Dict[str, Any]:
    return {
        "event": _serialize_event(opportunity.event),
        "best_outcomes": [
            _serialize_outcome(outcome) for outcome in opportunity.best_outcomes
        ],
        "total_stake": opportunity.total_stake,
        "stake_distribution": opportunity.stake_distribution,
        "profit": opportunity.profit,
        "profit_percentage": opportunity.profit_percentage,
        "roi": opportunity.roi,
    }


def _make_betfair_client() -> BetfairClient:
    return BetfairClient(
        Config.BETFAIR_USERNAME,
        Config.BETFAIR_PASSWORD,
        Config.BETFAIR_APP_KEY,
    )


def _fetch_events(sport: str) -> tuple[List[Event], List[PolymarketEvent]]:
    bf_client = _make_betfair_client()
    if not bf_client.login():
        raise RuntimeError(bf_client.get_last_error() or "Betfair login failed")

    pm_client = PolymarketClient()

    if sport == "politics":
        bf_events = bf_client.get_politics_markets()
        pm_events = pm_client.get_politics_markets(active_only=True, min_volume=0)
        return bf_events, pm_events

    sport_hints = None if sport == "all" else [sport]
    bf_events = bf_client.get_odds(
        sport_hints=sport_hints, days_ahead=7, min_hours_ahead=0
    )
    pm_events = pm_client.get_sports_markets(
        sport_hint=None if sport == "all" else sport,
        active_only=True,
        min_volume=0,
    )
    return bf_events, pm_events


def run_live_scan(
    sport: str = "all",
    threshold: float = 0.35,
    investment: float = 100.0,
    gbp_usd_rate: float = 1.27,
) -> Dict[str, Any]:
    """Fetch live Betfair + Polymarket data and compute matches/opportunities."""
    matcher = MarketMatcher(similarity_threshold=threshold)
    engine = ArbitrageEngine()

    bf_events, pm_events = _fetch_events(sport)
    matches = matcher.find_matches(bf_events, pm_events)
    opportunities = engine.compare_markets(bf_events, pm_events)

    matched_bf_ids = {bf.id for bf, _, _ in matches}
    matched_pm_ids = {pm.id for _, pm, _ in matches}

    return {
        "ok": True,
        "sport": sport,
        "threshold": threshold,
        "investment": investment,
        "gbp_usd_rate": gbp_usd_rate,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "betfair_event_count": len(bf_events),
        "polymarket_event_count": len(pm_events),
        "matched_pair_count": len(matches),
        "unmatched_betfair_count": len(bf_events) - len(matched_bf_ids),
        "unmatched_polymarket_count": len(pm_events) - len(matched_pm_ids),
        "matched_pairs": [
            {
                "betfair": _serialize_event(bf),
                "polymarket": _serialize_pm_event(pm),
                "similarity": score,
            }
            for bf, pm, score in matches
        ],
        "opportunity_count": len(opportunities),
        "opportunities": [
            _serialize_opportunity(opportunity) for opportunity in opportunities
        ],
        "sample_betfair_events": [_serialize_event(event) for event in bf_events[:12]],
        "sample_polymarket_markets": [
            _serialize_pm_event(event) for event in pm_events[:12]
        ],
    }
