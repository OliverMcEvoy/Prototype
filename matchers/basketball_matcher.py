"""
matchers/basketball_matcher.py
================================
Basketball market matcher — NBA, WNBA, EuroLeague, NCAAB / NCAA.

Key problems solved:
  • Polymarket NBA events use NICKNAME ONLY: "Rockets vs. Wizards"
  • Betfair uses full city+name:  "Houston Rockets vs. Washington Wizards"
  • NCAAB events include mascot names: "Duke Blue Devils vs. NC State Wolfpack"
    vs Betfair's "Duke vs NC State"
  • EuroLeague / Euroleague events are close but sometimes differ in
    spacing / diacritics
"""

from typing import Dict, List

from models import Event, PolymarketEvent
from matchers.base_matcher import BaseSportMatcher


# ---------------------------------------------------------------------------
# Full canonical → nickname mapping for ALL NBA teams.
# PM uses ONLY the nickname; BF uses full city+name.
# ---------------------------------------------------------------------------
_NBA_ALIASES: Dict[str, List[str]] = {
    "atlanta hawks": ["hawks"],
    "boston celtics": ["celtics"],
    "brooklyn nets": ["nets"],
    "charlotte hornets": ["hornets"],
    "chicago bulls": ["bulls"],
    "cleveland cavaliers": ["cavaliers", "cavs"],
    "dallas mavericks": ["mavericks", "mavs"],
    "denver nuggets": ["nuggets"],
    "detroit pistons": ["pistons"],
    "golden state warriors": ["warriors", "gsw"],
    "houston rockets": ["rockets"],
    "indiana pacers": ["pacers"],
    "los angeles clippers": ["clippers", "la clippers"],
    "los angeles lakers": ["lakers", "la lakers"],
    "memphis grizzlies": ["grizzlies"],
    "miami heat": ["heat"],
    "milwaukee bucks": ["bucks"],
    "minnesota timberwolves": ["timberwolves", "wolves"],
    "new orleans pelicans": ["pelicans"],
    "new york knicks": ["knicks"],
    "oklahoma city thunder": ["thunder", "okc thunder"],
    "orlando magic": ["magic"],
    "philadelphia 76ers": ["76ers", "sixers"],
    "phoenix suns": ["suns"],
    "portland trail blazers": ["trail blazers", "blazers"],
    "sacramento kings": ["kings", "sac kings"],
    "san antonio spurs": ["spurs"],
    "toronto raptors": ["raptors"],
    "utah jazz": ["jazz"],
    "washington wizards": ["wizards"],
}

# WNBA — PM uses nickname only for these too
_WNBA_ALIASES: Dict[str, List[str]] = {
    "atlanta dream": ["dream"],
    "chicago sky": ["sky"],
    "connecticut sun": ["sun"],
    "dallas wings": ["wings"],
    "golden state valkyries": ["valkyries"],
    "indiana fever": ["fever"],
    "las vegas aces": ["aces"],
    "los angeles sparks": ["sparks"],
    "minnesota lynx": ["lynx"],
    "new york liberty": ["liberty"],
    "phoenix mercury": ["mercury"],
    "seattle storm": ["storm"],
    "washington mystics": ["mystics"],
}

# NCAAB — mascot names used by PM, BF typically uses school name
_NCAAB_ALIASES: Dict[str, List[str]] = {
    "duke": ["duke blue devils"],
    "north carolina": ["north carolina tar heels", "unc tar heels", "unc"],
    "nc state": ["nc state wolfpack", "north carolina state wolfpack"],
    "kentucky": ["kentucky wildcats"],
    "kansas": ["kansas jayhawks"],
    "gonzaga": ["gonzaga bulldogs"],
    "villanova": ["villanova wildcats"],
    "arizona": ["arizona wildcats"],
    "iowa": ["iowa hawkeyes"],
    "indiana": ["indiana hoosiers"],
    "ohio state": ["ohio state buckeyes"],
    "michigan": ["michigan wolverines", "michigan state spartans"],
    "michigan state": ["michigan state spartans"],
    "auburn": ["auburn tigers"],
    "alabama": ["alabama crimson tide"],
    "tennessee": ["tennessee volunteers", "tennessee vols"],
    "connecticut": ["uconn huskies", "uconn"],
    "ucla": ["ucla bruins"],
    "florida": ["florida gators"],
    "houston": ["houston cougars"],
    "baylor": ["baylor bears"],
    "san diego state": ["sdsu aztecs"],
    "marquette": ["marquette golden eagles"],
    "arkansas": ["arkansas razorbacks"],
    "oregon": ["oregon ducks"],
    "texas": ["texas longhorns"],
    "texas tech": ["texas tech red raiders"],
    "seton hall": ["seton hall pirates"],
    "providence": ["providence friars"],
    "creighton": ["creighton bluejays"],
    "illinois": ["illinois fighting illini"],
    "iowa state": ["iowa state cyclones"],
    "southern california": ["usc trojans", "usc"],
    "purdue": ["purdue boilermakers"],
    "virginia": ["virginia cavaliers"],
    "michigan wolverines": ["michigan"],
    "st john s": ["st. john's red storm", "st johns"],
    "xavier": ["xavier musketeers"],
    "butler": ["butler bulldogs"],
    "wichita state": ["wichita state shockers"],
}

# Combine all
_ALL_BASKETBALL_ALIASES: Dict[str, List[str]] = {}
_ALL_BASKETBALL_ALIASES.update(_NBA_ALIASES)
_ALL_BASKETBALL_ALIASES.update(_WNBA_ALIASES)
_ALL_BASKETBALL_ALIASES.update(_NCAAB_ALIASES)


class BasketballMatcher(BaseSportMatcher):
    """Match basketball markets (NBA, WNBA, EuroLeague, NCAAB)."""

    THRESHOLD = 0.35
    ALIASES = _ALL_BASKETBALL_ALIASES

    # Competition prefixes common in PM basketball questions
    COMPETITION_PREFIXES = [
        "EuroLeague: ",
        "Euroleague: ",
        "EuroCup: ",
        "FIBA: ",
        "FIBA World Cup: ",
        "Olympics: ",
        "Summer Olympics: ",
        "NCAAB: ",
        "NCAA: ",
        "NBA: ",
        "WNBA: ",
        "BCL: ",  # Basketball Champions League
        "VTB United League: ",
        "VTB League: ",
        "ACB: ",  # Liga ACB Spain
        "Bundesliga: ",
        "Lega Basket: ",
        "LNB Pro A: ",
        "Turkish BSL: ",
        "BSL: ",
        "KBL: ",
        "CBA: ",
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
