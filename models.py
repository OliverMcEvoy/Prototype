"""
Data models for the arbitrage betting application.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict


class OddsFormat(Enum):
    """Supported odds formats."""

    DECIMAL = "decimal"
    FRACTIONAL = "fractional"
    AMERICAN = "american"


class Market(Enum):
    """Market types."""

    HEAD_TO_HEAD = "h2h"
    SPREADS = "spreads"
    TOTALS = "totals"


class MarketCategory(Enum):
    """Categories of prediction markets."""

    SPORTS = "sports"
    POLITICS = "politics"
    ENTERTAINMENT = "entertainment"
    CRYPTO = "crypto"
    FINANCE = "finance"
    CURRENT_EVENTS = "current_events"
    SCIENCE = "science"
    POP_CULTURE = "pop_culture"
    BUSINESS = "business"
    AI = "ai"
    OTHER = "other"


@dataclass
class Outcome:
    """Represents a single betting outcome."""

    name: str
    price: float  # Decimal odds
    bookmaker: str
    last_update: datetime


@dataclass
class Event:
    """Represents a sporting or prediction market event."""

    id: str
    sport: str  # Can be sport name or market category
    commence_time: datetime
    home_team: str  # Or outcome A for non-sports
    away_team: str  # Or outcome B for non-sports
    outcomes: List[Outcome]
    category: Optional[str] = None  # Market category (sports, politics, etc.)
    description: Optional[str] = None  # Additional context for niche markets
    match_quality: float = 1.0  # Similarity score for cross-platform matches (0-1)

    def __repr__(self) -> str:
        if self.category and self.category.lower() != "sports":
            return f"{self.sport}: {self.description or f'{self.home_team} vs {self.away_team}'}"
        return f"{self.home_team} vs {self.away_team}"


@dataclass
class ArbitrageOpportunity:
    """Represents an arbitrage betting opportunity."""

    event: Event
    best_outcomes: List[Outcome]  # Best odds for each outcome
    total_stake: float
    stake_distribution: Dict[str, float]  # Bookmaker -> stake amount
    profit: float
    profit_percentage: float
    roi: float

    def is_profitable(self, min_threshold: float = 0.0) -> bool:
        """Check if opportunity meets minimum profit threshold."""
        return self.profit_percentage >= min_threshold

    def get_summary(self) -> str:
        """Get a human-readable summary of the opportunity."""
        outcomes_str = " / ".join(
            [f"{o.name} @ {o.price:.2f} ({o.bookmaker})" for o in self.best_outcomes]
        )
        return (
            f"{self.event} | {outcomes_str} | " f"Profit: {self.profit_percentage:.2f}%"
        )


@dataclass
class PolymarketEvent:
    """Represents a Polymarket prediction market."""

    id: str
    question: str
    outcomes: List[str]
    prices: List[float]  # Prices in probability format (0-1)
    end_date: Optional[datetime]
    volume: float
    liquidity: float
    sport_category: str = ""  # Broad sport category, e.g. 'soccer', 'basketball'

    def to_decimal_odds(self) -> List[float]:
        """Convert Polymarket prices to decimal odds."""
        return [1.0 / price if price > 0 else 0 for price in self.prices]
