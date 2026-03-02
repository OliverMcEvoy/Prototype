"""
matchers/americanfootball_matcher.py
======================================
American football market matcher — NFL, NCAAF, European AF leagues.

Notes:
  • Betfair lists European AF national team games under "American Football"
    (Armenia vs Bulgaria, etc.) — these rarely appear on PM.
  • NFL events on Betfair use full city+nickname; PM usually matches well.
  • Some NCAAF college events need mascot stripping (same as NCAAB).
  • EuroLeague Basketball games that Betfair mislabels as "American Football"
    are redirected to BasketballMatcher via the dispatcher.
"""

from typing import Dict, List

from models import Event, PolymarketEvent
from matchers.base_matcher import BaseSportMatcher


_NFL_ALIASES: Dict[str, List[str]] = {
    "arizona cardinals": ["cardinals", "az cardinals"],
    "atlanta falcons": ["falcons"],
    "baltimore ravens": ["ravens"],
    "buffalo bills": ["bills"],
    "carolina panthers": ["panthers"],
    "chicago bears": ["bears"],
    "cincinnati bengals": ["bengals"],
    "cleveland browns": ["browns"],
    "dallas cowboys": ["cowboys"],
    "denver broncos": ["broncos"],
    "detroit lions": ["lions"],
    "green bay packers": ["packers"],
    "houston texans": ["texans"],
    "indianapolis colts": ["colts"],
    "jacksonville jaguars": ["jaguars", "jags"],
    "kansas city chiefs": ["chiefs"],
    "las vegas raiders": ["raiders", "lv raiders"],
    "los angeles chargers": ["chargers", "la chargers"],
    "los angeles rams": ["rams", "la rams"],
    "miami dolphins": ["dolphins"],
    "minnesota vikings": ["vikings"],
    "new england patriots": ["patriots", "pats"],
    "new orleans saints": ["saints"],
    "new york giants": ["giants", "ny giants"],
    "new york jets": ["jets", "ny jets"],
    "philadelphia eagles": ["eagles"],
    "pittsburgh steelers": ["steelers"],
    "san francisco 49ers": ["49ers", "niners", "sf 49ers"],
    "seattle seahawks": ["seahawks"],
    "tampa bay buccaneers": ["buccaneers", "bucs"],
    "tennessee titans": ["titans"],
    "washington commanders": ["commanders", "washington football team"],
}


class AmericanFootballMatcher(BaseSportMatcher):
    """Match American football markets across Betfair and Polymarket."""

    THRESHOLD = 0.35
    ALIASES = _NFL_ALIASES

    COMPETITION_PREFIXES = [
        "NFL: ",
        "Super Bowl: ",
        "NFC: ",
        "AFC: ",
        "College Football: ",
        "NCAAF: ",
        "NCAA Football: ",
        "CFB: ",
    ]

    def score(self, bf_event: Event, pm_event: PolymarketEvent) -> float:
        pm_q = pm_event.question
        pm_q_clean = self._strip_competition_prefix(pm_q)

        poly_text = self._normalise(pm_q)
        poly_match = self._normalise(pm_q_clean)
        poly_outcomes = self._normalise(" ".join(pm_event.outcomes or []))
        poly_combined = f"{poly_text} {poly_match} {poly_outcomes}"

        home_found = self._team_in_text(bf_event.home_team, poly_combined)
        away_found = self._team_in_text(bf_event.away_team, poly_combined)

        if not (home_found and away_found):
            return 0.0

        score = 0.55

        bf_pair = self._normalise(f"{bf_event.home_team} {bf_event.away_team}")
        bf_pair_can = self._normalise(
            f"{self._canonicalise(bf_event.home_team)} "
            f"{self._canonicalise(bf_event.away_team)}"
        )
        seq = max(
            self._seq_sim(bf_pair, poly_match),
            self._seq_sim(bf_pair_can, poly_match),
        )
        score += seq * 0.20
        score += self._token_jaccard(bf_pair, poly_match) * 0.15

        if pm_event.end_date and bf_event.commence_time:
            score += self._date_score(bf_event.commence_time, pm_event.end_date) * 0.10

        return min(score, 1.0)
