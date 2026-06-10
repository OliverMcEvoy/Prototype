"""
matchers/baseball_matcher.py
=============================
Baseball market matcher — MLB, KBO, NPB.

PM and BF names are usually consistent for MLB but need alias support
for common abbreviations and city-vs-nickname mismatches.
"""

from typing import Dict, List

from backend.models import Event, PolymarketEvent
from backend.matchers.base_matcher import BaseSportMatcher


_MLB_ALIASES: Dict[str, List[str]] = {
    # American League East
    "baltimore orioles": ["orioles"],
    "boston red sox": ["red sox"],
    "new york yankees": ["yankees", "ny yankees"],
    "tampa bay rays": ["rays"],
    "toronto blue jays": ["blue jays", "jays"],
    # American League Central
    "chicago white sox": ["white sox"],
    "cleveland guardians": ["guardians", "cleveland"],
    "detroit tigers": ["tigers"],
    "kansas city royals": ["royals"],
    "minnesota twins": ["twins"],
    # American League West
    "houston astros": ["astros"],
    "los angeles angels": ["angels", "la angels"],
    "athletics": ["oakland athletics", "a's"],
    "seattle mariners": ["mariners"],
    "texas rangers": ["rangers", "tx rangers"],
    # National League East
    "atlanta braves": ["braves"],
    "miami marlins": ["marlins"],
    "new york mets": ["mets", "ny mets"],
    "philadelphia phillies": ["phillies"],
    "washington nationals": ["nationals", "nats"],
    # National League Central
    "chicago cubs": ["cubs"],
    "cincinnati reds": ["reds"],
    "milwaukee brewers": ["brewers"],
    "pittsburgh pirates": ["pirates"],
    "st louis cardinals": ["cardinals", "st. louis cardinals"],
    # National League West
    "arizona diamondbacks": ["diamondbacks", "d-backs"],
    "colorado rockies": ["rockies"],
    "los angeles dodgers": ["dodgers", "la dodgers"],
    "san diego padres": ["padres"],
    "san francisco giants": ["giants", "sf giants"],
    # KBO
    "doosan bears": ["bears"],
    "samsung lions": ["lions", "samsung"],
    "nc dinos": ["nc", "dinos"],
    "kt wiz": ["kt", "wiz"],
    "hanwha eagles": ["hanwha", "eagles"],
    "kia tigers": ["kia", "kia tigers"],
    "lotte giants": ["lotte", "giants"],
    "sk wyverns": ["sk", "wyverns"],
    "lg twins": ["lg", "twins"],
    "ssg landers": ["ssg", "landers"],
}


class BaseballMatcher(BaseSportMatcher):
    """Match baseball markets across Betfair and Polymarket."""

    THRESHOLD = 0.35
    ALIASES = _MLB_ALIASES

    COMPETITION_PREFIXES = [
        "MLB: ",
        "World Series: ",
        "NLCS: ",
        "ALCS: ",
        "NLDS: ",
        "ALDS: ",
        "Wild Card: ",
        "KBO: ",
        "NPB: ",
        "World Baseball Classic: ",
        "WBC: ",
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
