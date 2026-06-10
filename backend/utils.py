"""
Utility functions for odds conversion and calculations.
"""

from typing import List


def decimal_to_fractional(decimal_odds: float) -> str:
    """Convert decimal odds to fractional format."""
    if decimal_odds <= 1.0:
        return "N/A"

    numerator = decimal_odds - 1
    denominator = 1

    # Find best fraction approximation
    for i in range(1, 100):
        frac = numerator * i
        if abs(frac - round(frac)) < 0.01:
            return f"{int(round(frac))}/{i}"

    return f"{numerator:.2f}/1"


def decimal_to_american(decimal_odds: float) -> str:
    """Convert decimal odds to American format."""
    if decimal_odds <= 1.0:
        return "N/A"

    if decimal_odds >= 2.0:
        american = (decimal_odds - 1) * 100
        return f"+{int(american)}"
    else:
        american = -100 / (decimal_odds - 1)
        return f"{int(american)}"


def implied_probability(decimal_odds: float) -> float:
    """Calculate implied probability from decimal odds."""
    if decimal_odds <= 0:
        return 0.0
    return 1.0 / decimal_odds


def calculate_arbitrage(odds_list: List[float]) -> dict:
    """
    Calculate if there's an arbitrage opportunity.

    Args:
        odds_list: List of decimal odds for each outcome

    Returns:
        Dictionary with arbitrage information
    """
    if not odds_list or any(o <= 0 for o in odds_list):
        return {
            "is_arbitrage": False,
            "total_implied_probability": 0,
            "profit_percentage": 0,
            "stake_distribution": [],
        }

    # Calculate total implied probability
    total_implied_prob = sum(implied_probability(odds) for odds in odds_list)

    # Arbitrage exists if total implied probability < 1
    is_arbitrage = total_implied_prob < 1.0

    # Calculate profit percentage
    profit_percentage = (
        ((1.0 / total_implied_prob) - 1.0) * 100 if is_arbitrage else 0.0
    )

    # Calculate optimal stake distribution (for £100 total stake)
    total_stake = 100.0
    stake_distribution = []

    if is_arbitrage:
        for odds in odds_list:
            stake = (total_stake / total_implied_prob) * implied_probability(odds)
            payout = stake * odds
            profit = payout - total_stake
            stake_distribution.append(
                {"stake": stake, "odds": odds, "payout": payout, "profit": profit}
            )

    return {
        "is_arbitrage": is_arbitrage,
        "total_implied_probability": total_implied_prob,
        "profit_percentage": profit_percentage,
        "stake_distribution": stake_distribution,
        "total_stake": total_stake,
    }


def normalize_team_name(name: str) -> str:
    """Normalize team/outcome names for comparison."""
    return name.lower().strip().replace("  ", " ")
