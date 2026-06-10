"""
matchers/cricket_matcher.py
============================
Cricket market matcher — ICC events, bilateral series, T20 leagues.

Key problems solved:
  • PM uses complex competition prefixes:
      "T20 Series West Indies vs Sri Lanka, Women: West Indies vs Sri Lanka"
      "T20 World Cup: South Africa vs New Zealand"
      "ODI Series New Zealand vs Zimbabwe, Women: New Zealand vs Zimbabwe"
      "First Round Pool A: Zimbabwe vs Scotland"
  • BF uses gender suffix "(W)": "West Indies W vs Sri Lanka W"
  • Strip competition prefix, extract team names, map gender markers
  • Country name normalisations (WI = West Indies, Eng = England, etc.)
"""

from typing import Dict, List

from backend.models import Event, PolymarketEvent
from backend.matchers.base_matcher import BaseSportMatcher


class CricketMatcher(BaseSportMatcher):
    """Match cricket markets across Betfair and Polymarket."""

    THRESHOLD = 0.35

    ALIASES: Dict[str, List[str]] = {
        # Full names ↔ Betfair abbreviations
        "west indies": ["wi", "windies", "west indies cricket"],
        "south africa": ["sa", "proteas"],
        "new zealand": ["nz", "black caps", "blackcaps"],
        "sri lanka": ["sl", "sri lanka cricket"],
        "bangladesh": ["ban", "tigers", "bangladesh cricket"],
        "afghanistan": ["afg"],
        "zimbabwe": ["zim"],
        "scotland": ["sco"],
        "ireland": ["ire"],
        "netherlands": ["ned", "holland"],
        "nepal": ["nep"],
        "oman": ["oma"],
        "namibia": ["nam"],
        "united arab emirates": ["uae"],
        "papua new guinea": ["png"],
        "canada": ["can"],
        "usa": ["united states", "united states of america"],
        # Women marker normalizations
        "west indies women": ["west indies w", "wi women", "windies women"],
        "south africa women": ["south africa w", "sa women"],
        "new zealand women": ["new zealand w", "nz women", "white ferns"],
        "india women": ["india w"],
        "australia women": ["australia w", "aus women"],
        "england women": ["england w"],
        "sri lanka women": ["sri lanka w"],
        "pakistan women": ["pakistan w", "pak women"],
        "bangladesh women": ["bangladesh w", "ban women"],
        "ireland women": ["ireland w"],
        "scotland women": ["scotland w"],
        # IPL / BBL / CPL / PSL teams
        "mumbai indians": ["mi"],
        "chennai super kings": ["csk"],
        "royal challengers bangalore": ["rcb", "royal challengers bengaluru"],
        "kolkata knight riders": ["kkr"],
        "sunrisers hyderabad": ["srh"],
        "rajasthan royals": ["rr"],
        "punjab kings": ["pbks", "kxip"],
        "lucknow super giants": ["lsg"],
        "gujarat titans": ["gt"],
        "delhi capitals": ["dc", "delhi daredevils"],
        "sydney sixers": ["sixers"],
        "sydney thunder": ["thunder"],
        "melbourne stars": ["stars"],
        "melbourne renegades": ["renegades"],
        "hobart hurricanes": ["hurricanes"],
        "adelaide strikers": ["strikers"],
        "brisbane heat": ["heat"],
        "perth scorchers": ["scorchers"],
    }

    COMPETITION_PREFIXES = [
        "T20 World Cup: ",
        "T20 World Cup ",
        "ICC T20 World Cup: ",
        "ICC Men's T20 World Cup: ",
        "ICC Cricket World Cup: ",
        "ICC World Cup: ",
        "ICC Champions Trophy: ",
        "ICC Test Championship: ",
        "Champions Trophy: ",
        "World Cup: ",
        "One Day International: ",
        "Test Series: ",
        "ODI Series: ",
        "T20 Series: ",
        "T20I Series: ",
        "Test Match: ",
        "Super 8: ",
        "Super 6: ",
        "Group Stage: ",
        "Qualifier: ",
        "Semi-Final: ",
        "Final: ",
        "First Round Pool A: ",
        "First Round Pool B: ",
        "First Round Pool C: ",
        "First Round Pool D: ",
        "First Round: ",
        "Second Round: ",
        "IPL: ",
        "BBL: ",
        "CPL: ",
        "PSL: ",
        "The Hundred: ",
        "Vitality Blast: ",
        "Rachael Heyhoe Flint Trophy: ",
    ]

    def score(self, bf_event: Event, pm_event: PolymarketEvent) -> float:
        pm_q = pm_event.question

        # PM cricket questions often have format:
        # "T20 Series WI vs SL, Women: West Indies vs Sri Lanka"
        # We want the part AFTER the final colon when present
        pm_q_clean = self._extract_match_part(pm_q)

        poly_text = self._normalise(pm_q)
        poly_match = self._normalise(pm_q_clean)
        poly_outcomes = self._normalise(" ".join(pm_event.outcomes or []))
        poly_combined = f"{poly_text} {poly_match} {poly_outcomes}"

        # Normalise BF team names — strip "(W)" gender marker
        home_norm = self._normalise_cricket_team(bf_event.home_team or "")
        away_norm = self._normalise_cricket_team(bf_event.away_team or "")

        if not home_norm or not away_norm:
            return 0.0

        home_found = self._team_in_text(home_norm, poly_combined)
        away_found = self._team_in_text(away_norm, poly_combined)

        if not (home_found and away_found):
            # Try normalised versions (with "women" equivalent to "w")
            home_women = self._with_women_suffix(home_norm, bf_event.home_team or "")
            away_women = self._with_women_suffix(away_norm, bf_event.away_team or "")
            home_found = self._team_in_text(home_women, poly_combined)
            away_found = self._team_in_text(away_women, poly_combined)
            if not (home_found and away_found):
                return 0.0

        score = 0.55

        bf_pair = f"{home_norm} {away_norm}"
        seq = self._seq_sim(bf_pair, poly_match)
        score += seq * 0.20
        score += self._token_jaccard(bf_pair, poly_match) * 0.15

        if pm_event.end_date and bf_event.commence_time:
            score += self._date_score(bf_event.commence_time, pm_event.end_date) * 0.10

        return min(score, 1.0)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _extract_match_part(self, question: str) -> str:
        """
        For questions like:
          "T20 Series West Indies vs Sri Lanka, Women: West Indies vs Sri Lanka"
        Return the part after the last colon, which is the actual match.
        For questions without colon, strip any known prefix.
        """
        if ":" in question:
            # Take everything after the LAST colon as the match text
            return question.rsplit(":", 1)[-1].strip()
        return self._strip_competition_prefix(question)

    def _normalise_cricket_team(self, team: str) -> str:
        """
        Strip "(W)" / "Women" suffix and return the canonical team name.
        E.g. "West Indies W" → "west indies", "South Africa Women" → "south africa"
        """
        import re

        t = re.sub(r"\s*\(w\)\s*$", "", team, flags=re.IGNORECASE)
        t = re.sub(r"\s+women\s*$", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+women's\s*$", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+w\s*$", "", t, flags=re.IGNORECASE)
        return self._normalise(t)

    def _with_women_suffix(self, team_norm: str, team_raw: str) -> str:
        """Return the 'women' variant of a team name if BF uses (W)."""
        if "(w)" in team_raw.lower() or " w " in f" {team_raw.lower()} ":
            return f"{team_norm} women"
        return team_norm
