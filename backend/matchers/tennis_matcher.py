"""
matchers/tennis_matcher.py
===========================
Tennis market matcher — ATP / WTA / ITF singles and doubles.

Key problems solved:
  • PM prefixes questions with venue or tournament names:
      "Kigali: Jay Clarke vs Calvin Hemery"
      "BNP Paribas Open, Qualification: Joanna Garland vs Taylor Townsend"
      "Thionville: Hugo Gaston vs Daniil Glinka"
      "Hersonissos: Nikoloz Basilashvili vs Lukas Klein"
  • BF has the plain matchup: "Jay Clarke vs Calvin Hemery"
  • Strip everything before the last colon/dash when the prefix contains
    venue-like words, then match on player names
  • Accented characters are normalised to ASCII in the base class
  • Doubles events (A/B vs C/D) are handled separately with relaxed scoring
  • Player order may be reversed between BF and PM — try both orientations
"""

import re
from typing import Optional

from backend.models import Event, PolymarketEvent
from backend.matchers.base_matcher import BaseSportMatcher


# These words strongly suggest the part before ":" is a venue / round prefix
_VENUE_WORDS = frozenset(
    [
        "open",
        "classic",
        "championship",
        "cup",
        "international",
        "masters",
        "invitational",
        "qualification",
        "qualifier",
        "first round",
        "second round",
        "third round",
        "quarterfinal",
        "semifinal",
        "final",
        "atp",
        "wta",
        "itf",
    ]
)

# Common diacritics and their ASCII equivalents not always handled by NFD
_EXTRA_TRANSL = str.maketrans(
    {
        "ł": "l",
        "ø": "o",
        "æ": "ae",
        "þ": "th",
        "ð": "d",
        "ß": "ss",
        "ı": "i",
    }
)


class TennisMatcher(BaseSportMatcher):
    """Match tennis markets across Betfair and Polymarket."""

    THRESHOLD = 0.35
    ALIASES: dict = {}  # Tennis has no team aliases
    COMPETITION_PREFIXES: list = []  # We strip via a smarter heuristic below

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def score(self, bf_event: Event, pm_event: PolymarketEvent) -> float:
        pm_players_str = self._extract_players_string(pm_event.question)
        poly_text = self._normalise_tennis(pm_players_str)
        poly_outcomes = self._normalise_tennis(" ".join(pm_event.outcomes or []))
        poly_combined = f"{poly_text} {poly_outcomes}"

        # Is this a doubles event?
        is_doubles = self._is_doubles(bf_event.home_team or "")
        if is_doubles:
            return self._score_doubles(bf_event, poly_combined)

        home_norm = self._normalise_tennis(bf_event.home_team or "")
        away_norm = self._normalise_tennis(bf_event.away_team or "")

        if not home_norm or not away_norm:
            return 0.0

        home_found = self._player_in_text(home_norm, poly_combined)
        away_found = self._player_in_text(away_norm, poly_combined)

        if not (home_found and away_found):
            return 0.0

        score = 0.55
        bf_pair = f"{home_norm} {away_norm}"
        seq = self._seq_sim(bf_pair, poly_text)
        score += seq * 0.25
        score += self._token_jaccard(bf_pair, poly_text) * 0.10

        if pm_event.end_date and bf_event.commence_time:
            score += self._date_score(bf_event.commence_time, pm_event.end_date) * 0.10

        return min(score, 1.0)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _normalise_tennis(self, text: str) -> str:
        """Normalise player names with extra diacritic handling."""
        text = text.translate(_EXTRA_TRANSL)
        return self._normalise(text)

    def _extract_players_string(self, question: str) -> str:
        """
        Strip the tournament / venue prefix from a PM tennis question.

        Handles formats like:
          "Kigali: Jay Clarke vs Calvin Hemery"
          "BNP Paribas Open, Qualification: Joanna Garland vs Taylor Townsend"
          "ATP Indian Wells Masters: Player A vs Player B"
        """
        if ":" not in question:
            return question

        prefix, rest = question.split(":", 1)

        # Only strip if the prefix looks like a venue / tournament header
        prefix_norm = prefix.lower()
        is_venue = any(w in prefix_norm for w in _VENUE_WORDS)
        is_short = len(prefix.split()) <= 5  # venue names are short

        if is_venue or is_short:
            return rest.strip()

        return question

    def _is_doubles(self, player_string: str) -> bool:
        """Return True if the player string looks like a doubles pair (A/B)."""
        return "/" in player_string

    def _player_in_text(self, player_norm: str, poly_combined: str) -> bool:
        """
        Check whether a player name appears in the poly text.

        Strategy (in order):
        1. Full normalised name exact substring match
        2. Last-name-only match (for name abbreviation mismatches)
        3. First + last token both present
        """
        if player_norm in poly_combined:
            return True

        parts = player_norm.split()
        if not parts:
            return False

        # Last name match (most reliable)
        last = parts[-1]
        if len(last) > 3 and last in poly_combined:
            return True

        # First + last both present
        if len(parts) >= 2:
            first = parts[0]
            if len(first) > 1 and first in poly_combined and last in poly_combined:
                return True

        return False

    def _score_doubles(self, bf_event: Event, poly_combined: str) -> float:
        """
        Relaxed scoring for doubles matches — just needs last names of all
        four players to appear in the PM text.
        """

        def _extract_last_names(pair: str):
            # pair format: "Smith/Jones" or "Smith - Jones"
            names = re.split(r"[/\-]", pair)
            return [n.strip().split()[-1].lower() for n in names if n.strip()]

        home_pair = self._normalise_tennis(bf_event.home_team or "")
        away_pair = self._normalise_tennis(bf_event.away_team or "")

        home_lnames = _extract_last_names(home_pair)
        away_lnames = _extract_last_names(away_pair)

        all_lnames = home_lnames + away_lnames
        if not all_lnames:
            return 0.0

        found = sum(1 for n in all_lnames if n in poly_combined)
        ratio = found / len(all_lnames)

        if ratio < 0.75:
            return 0.0

        return min(0.50 + ratio * 0.20, 1.0)
