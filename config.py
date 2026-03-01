"""
Configuration management for the arbitrage betting application.
"""

import os
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration."""

    # Betfair Exchange credentials — developer.betfair.com
    BETFAIR_USERNAME: str = os.getenv("BETFAIR_USERNAME", "")
    BETFAIR_PASSWORD: str = os.getenv("BETFAIR_PASSWORD", "")
    BETFAIR_APP_KEY: str = os.getenv("BETFAIR_APP_KEY", "")

    # Polymarket API — public read access, no key required
    POLYMARKET_API_URL: str = os.getenv(
        "POLYMARKET_API_URL", "https://gamma-api.polymarket.com"
    )

    SHARED_SPORTS = {
        "All Sports": "all",
        "Soccer": "soccer",
        "Cricket": "cricket",
        "Tennis": "tennis",
        "Basketball": "basketball",
        "American Football": "americanfootball",
        "Baseball": "baseball",
        "Ice Hockey": "icehockey",
        "MMA": "mma",
        "Rugby": "rugby",
    }

    POLYMARKET_CATEGORIES = [
        "Politics",
        "Crypto",
        "Pop Culture",
        "Sports",
        "Science",
        "Business",
        "New Markets",
        "AI",
    ]

    REFRESH_INTERVAL: int = int(os.getenv("REFRESH_INTERVAL", "60"))
    MIN_PROFIT_THRESHOLD: float = 0.5
    FUZZY_MATCH_THRESHOLD: float = 0.4

    @classmethod
    def validate(cls) -> bool:
        """Validate that required configuration is present."""
        if not cls.ODDS_API_KEY:
            return False
        return True
