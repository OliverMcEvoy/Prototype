"""
matchers/__init__.py
====================
Package entry-point.  Provides a factory that returns the appropriate
sport-specific matcher instance for a given sport category string.

The factory uses a cached singleton per sport so matcher objects (and their
pre-built alias lookups) are only constructed once per process.
"""

from functools import lru_cache
from typing import Optional

from backend.matchers.base_matcher import BaseSportMatcher
from backend.matchers.soccer_matcher import SoccerMatcher
from backend.matchers.basketball_matcher import BasketballMatcher
from backend.matchers.icehockey_matcher import IceHockeyMatcher
from backend.matchers.tennis_matcher import TennisMatcher
from backend.matchers.cricket_matcher import CricketMatcher
from backend.matchers.americanfootball_matcher import AmericanFootballMatcher
from backend.matchers.baseball_matcher import BaseballMatcher
from backend.matchers.rugby_matcher import RugbyMatcher
from backend.matchers.mma_matcher import MMAMatcher
from backend.matchers.politics_matcher import PoliticsMatcher

__all__ = [
    "SoccerMatcher",
    "BasketballMatcher",
    "IceHockeyMatcher",
    "TennisMatcher",
    "CricketMatcher",
    "AmericanFootballMatcher",
    "BaseballMatcher",
    "RugbyMatcher",
    "MMAMatcher",
    "PoliticsMatcher",
    "get_matcher",
]

# Betfair category string → matcher class
_SPORT_MAP = {
    "soccer": SoccerMatcher,
    "football": SoccerMatcher,
    "basketball": BasketballMatcher,
    # Betfair sometimes files Euroleague basketball under "americanfootball"
    # so we use the generic AmericanFootballMatcher there and let the
    # BasketballMatcher handle "basketball" explicitly.
    "americanfootball": AmericanFootballMatcher,
    "icehockey": IceHockeyMatcher,
    "tennis": TennisMatcher,
    "cricket": CricketMatcher,
    "rugbyunion": RugbyMatcher,
    "rugbyleague": RugbyMatcher,
    "rugby": RugbyMatcher,
    "mma": MMAMatcher,
    "mixedmartialarts": MMAMatcher,
    "ufc": MMAMatcher,
    "baseball": BaseballMatcher,
    "politics": PoliticsMatcher,
}


@lru_cache(maxsize=None)
def _build_matcher(sport_key: str) -> BaseSportMatcher:
    """Build (and cache) a matcher instance for the given normalised sport key."""
    cls = _SPORT_MAP.get(sport_key, SoccerMatcher)
    return cls()


def get_matcher(sport_category: Optional[str]) -> BaseSportMatcher:
    """
    Return the appropriate matcher for *sport_category*.

    Parameters
    ----------
    sport_category : str | None
        The Betfair event category (lowercased).  Unknown categories fall back
        to SoccerMatcher (the most general two-team matcher).

    Returns
    -------
    BaseSportMatcher
        A cached singleton instance.
    """
    key = (sport_category or "").lower().replace(" ", "").replace("_", "")
    return _build_matcher(key)
