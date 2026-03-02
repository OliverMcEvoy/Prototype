"""
matchers/rugby_matcher.py
==========================
Rugby market matcher — Six Nations, Premiership Rugby, URC,
Top 14 (Ligue Nationale de Rugby), Super Rugby Pacific, etc.

Key problem solved:
  • PM prefixes questions with the competition name:
      "Six Nations: Ireland vs Wales"
      "United Rugby Championship: Edinburgh vs Ulster"
      "Premiership Rugby: Bath vs Saracens"
      "Top 14: ASM Clermont Auvergne vs Montpellier"
      "Super Rugby Pacific: Blues vs Crusaders"
      "Rugby World Cup: South Africa vs New Zealand"
  • BF uses plain matchup: "Ireland vs Wales", "Bath vs Saracens"
  • Strip the competition prefix, then match normally
  • Handle long club names (ASM Clermont Auvergne → Clermont)
"""

from typing import Dict, List

from models import Event, PolymarketEvent
from matchers.base_matcher import BaseSportMatcher


class RugbyMatcher(BaseSportMatcher):
    """Match rugby union / league markets across Betfair and Polymarket."""

    THRESHOLD = 0.35

    ALIASES: Dict[str, List[str]] = {
        # Super Rugby Pacific / Club rugby
        "crusaders": ["canterbury crusaders"],
        "chiefs": ["waikato chiefs"],
        "blues": ["auckland blues"],
        "hurricanes": ["wellington hurricanes"],
        "highlanders": ["otago highlanders"],
        "brumbies": ["act brumbies"],
        "waratahs": ["nsw waratahs", "nsw"],
        "reds": ["queensland reds"],
        "rebels": ["melbourne rebels"],
        "force": ["western force", "western force fc"],
        "stormers": ["dhl stormers"],
        "sharks": ["cell c sharks", "hollywoodbets sharks"],
        "lions": ["emirates lions"],
        "bulls": ["vodacom bulls"],
        # Premiership Rugby (England)
        "bath": ["bath rugby"],
        "bristol": ["bristol bears"],
        "exeter": ["exeter chiefs"],
        "gloucester": ["gloucester rugby"],
        "harlequins": ["harlequins fc", "quins"],
        "leicester": ["leicester tigers"],
        "london irish": ["irish"],
        "newcastle": ["newcastle falcons"],
        "northampton": ["northampton saints", "saints"],
        "sale sharks": ["sale"],
        "saracens": ["saracens fc"],
        "wasps": ["wasps fc"],
        "worcester": ["worcester warriors"],
        # URC — United Rugby Championship
        "edinburgh": ["edinburgh rugby"],
        "glasgow": ["glasgow warriors"],
        "ulster": ["ulster rugby"],
        "leinster": ["leinster rugby"],
        "munster": ["munster rugby"],
        "connacht": ["connacht rugby"],
        "zebre parma": ["zebre"],
        "benetton": ["benetton rugby", "benetton treviso"],
        "cardiff": ["cardiff rugby", "cardiff blues"],
        "ospreys": ["ospreys rugby"],
        "dragons": ["newport gwent dragons"],
        "scarlets": ["scarlets rugby"],
        "dpw griffons": ["griffons"],
        "cell c sharks": ["sharks rugby"],
        # Top 14 (France)
        "clermont": ["asm clermont auvergne", "clermont auvergne"],
        "toulouse": ["stade toulousain", "stade toulousain fc"],
        "montpellier": ["mhp montpellier", "montpellier herault rugby"],
        "bordeaux bègleS": ["union bordeaux-bègleS", "bordeaux begles"],
        "la rochelle": ["stade rochelais"],
        "paris": ["stade francais", "stade francais paris"],
        "lyon": ["lyon rugby", "lOU rugby"],
        "toulon": ["rc toulon"],
        "grenoble": ["fc grenoble rugby"],
        "racing 92": ["racing metro 92"],
        "brive": ["ca brive"],
        "perpignan": ["usa perpignan"],
        "castres": ["castres olympique", "co castres"],
        "agen": ["su agen"],
        # National / international teams (Six Nations etc.)
        "ireland": ["ireland rugby", "ireland national"],
        "england": ["england rugby", "england national"],
        "wales": ["wales rugby", "wales national"],
        "scotland": ["scotland rugby", "scotland national"],
        "france": ["france rugby", "france national", "les bleus"],
        "italy": ["italy rugby", "azzurri"],
        "south africa": ["springboks", "south africa rugby"],
        "new zealand": ["all blacks", "new zealand rugby"],
        "australia": ["wallabies", "australia rugby"],
        "argentina": ["pumas", "argentina rugby", "los pumas"],
        "fiji": ["fiji rugby", "flying fijians"],
        "samoa": ["samoa rugby"],
        "tonga": ["tonga rugby"],
        "japan": ["japan rugby", "brave blossoms"],
        "georgia": ["georgia rugby", "lelos"],
        "namibia": ["namibia rugby"],
    }

    COMPETITION_PREFIXES = [
        # International
        "Rugby World Cup: ",
        "Rugby World Cup ",
        "Six Nations: ",
        "Six Nations ",
        "Autumn Nations Cup: ",
        "Autumn Nations Series: ",
        "Pacific Nations Cup: ",
        "The Rugby Championship: ",
        "Rugby Championship: ",
        # Club competitions
        "United Rugby Championship: ",
        "URC: ",
        "Premiership Rugby: ",
        "Gallagher Premiership: ",
        "Top 14: ",
        "Ligue Nationale de Rugby: ",
        "Super Rugby Pacific: ",
        "Super Rugby: ",
        "Super Rugby Trans-Tasman: ",
        "Champions Cup: ",
        "Heineken Champions Cup: ",
        "European Rugby Champions Cup: ",
        "Challenge Cup: ",
        "European Challenge Cup: ",
        "EPCR Challenge Cup: ",
        "Pro14: ",
        "Pro12: ",
        "Currie Cup: ",
        "Vodacom Cup: ",
        "ITM Cup: ",
        "National Rugby League: ",
        "NRL: ",
        "Super League: ",
        "Rugby League World Cup: ",
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
