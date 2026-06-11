"""
matchers/icehockey_matcher.py
==============================
Ice Hockey market matcher — NHL, AHL, KHL, SHL, DEL, Liiga, etc.

Key problems solved:
  • PM uses NICKNAME ONLY for NHL: "Red Wings vs. Predators", "Flyers vs. Maple Leafs"
  • BF uses full city+name: "Detroit Red Wings vs. Nashville Predators"
  • KHL / SHL / AHL / DEL events carry a league prefix in PM questions:
      "KHL: Amur Khabarovsk vs. Neftekhimik Nizhnekamsk"
      "SHL: Örebro HK vs. Djurgårdens IF"
      "AHL: Laval Rocket vs. Belleville Senators"
  • Strip the league prefix, then match normally
"""

from typing import Dict, List

from backend.models import Event, PolymarketEvent
from backend.matchers.base_matcher import BaseSportMatcher


# ---------------------------------------------------------------------------
# All 32 NHL teams — full canonical → list of nickname aliases
# ---------------------------------------------------------------------------
_NHL_ALIASES: Dict[str, List[str]] = {
    "anaheim ducks": ["ducks"],
    "boston bruins": ["bruins"],
    "buffalo sabres": ["sabres"],
    "calgary flames": ["flames"],
    "carolina hurricanes": ["hurricanes", "canes"],
    "chicago blackhawks": ["blackhawks", "hawks"],
    "colorado avalanche": ["avalanche", "avs"],
    "columbus blue jackets": ["blue jackets", "jackets"],
    "dallas stars": ["stars"],
    "detroit red wings": ["red wings", "wings"],
    "edmonton oilers": ["oilers"],
    "florida panthers": ["panthers"],
    "los angeles kings": ["kings", "la kings"],
    "minnesota wild": ["wild"],
    "montreal canadiens": ["canadiens", "habs"],
    "nashville predators": ["predators", "preds"],
    "new jersey devils": ["devils"],
    "new york islanders": ["islanders"],
    "new york rangers": ["rangers"],
    "ottawa senators": ["senators", "sens"],
    "philadelphia flyers": ["flyers"],
    "pittsburgh penguins": ["penguins", "pens"],
    "san jose sharks": ["sharks"],
    "seattle kraken": ["kraken"],
    "st louis blues": ["blues", "st. louis blues"],
    "tampa bay lightning": ["lightning", "bolts"],
    "toronto maple leafs": ["maple leafs", "leafs"],
    "utah hockey club": ["utah hc", "utah", "utah hockey"],
    "vancouver canucks": ["canucks"],
    "vegas golden knights": ["golden knights", "knights", "vgk"],
    "washington capitals": ["capitals", "caps"],
    "winnipeg jets": ["jets"],
}

# KHL teams (some appear on Betfair)
_KHL_ALIASES: Dict[str, List[str]] = {
    "amur khabarovsk": ["amur"],
    "neftekhimik nizhnekamsk": ["neftekhimik"],
    "lokomotiv yaroslavl": ["lokomotiv", "loko yaroslavl"],
    "cska moscow": ["cska"],
    "spartak moscow": ["spartak"],
    "dynamo moscow": ["dynamo", "dinamo moscow"],
    "dynamo minsk": ["dinamo minsk", "hk dynamo minsk"],
    "jokerit helsinki": ["jokerit"],
    "severstal cherepovets": ["severstal"],
    "traktor chelyabinsk": ["traktor"],
    "ak bars kazan": ["ak bars"],
    "metallurg magnitogorsk": ["metallurg mg", "metallurg"],
    "salavat yulaev ufa": ["salavat yulaev", "salavat"],
    "shl orebro": ["orebro hk", "örebro hk"],
    "djurgaarden": ["djurgårdens if", "djurgarden if"],
    "leksand": ["leksands if"],
    "frolunda": ["frolunda gothenburg", "frölunda gothenburg"],
    "modo": ["modo hockey"],
}

# Combine
_ALL_ICE_HOCKEY_ALIASES: Dict[str, List[str]] = {}
_ALL_ICE_HOCKEY_ALIASES.update(_NHL_ALIASES)
_ALL_ICE_HOCKEY_ALIASES.update(_KHL_ALIASES)


class IceHockeyMatcher(BaseSportMatcher):
    """Match ice hockey markets across Betfair and Polymarket."""

    THRESHOLD = 0.35
    ALIASES = _ALL_ICE_HOCKEY_ALIASES

    # League prefixes that PM prepends to non-NHL events
    COMPETITION_PREFIXES = [
        "KHL: ",
        "SHL: ",
        "AHL: ",
        "DEL: ",
        "CEHL: ",
        "Liiga: ",
        "Mestis: ",
        "NL: ",  # National League (Switzerland)
        "EIHL: ",  # Elite Ice Hockey League (UK)
        "VHL: ",  # Russian 2nd div
        "MHL: ",  # Russian youth
        "Extraliga: ",
        "SM-Liiga: ",
        "GET-ligaen: ",
        "Allsvenskan: ",
        "QMJHL: ",
        "OHL: ",
        "WHL: ",
        "BCHL: ",
        "ECHL: ",
        "NCAA Ice Hockey: ",
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
