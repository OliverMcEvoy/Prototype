"""
matchers/mma_matcher.py
========================
MMA / UFC market matcher.

Key behaviour:
  • PM uses the card header: "UFC 313: Alex Pereira vs. Magomed Ankalaev"
  • BF uses the same format but sometimes reorders fighters or omits the card number
  • Fighter order is irrelevant for the match — both combinations are tested
  • Strip the "UFC <N>: " prefix if present
"""

import re
from typing import Dict, List

from models import Event, PolymarketEvent
from matchers.base_matcher import BaseSportMatcher


_UFC_EVENT_PREFIX_RE = re.compile(
    r"^(?:UFC\s*\d+:\s*|UFC\s*Fight\s*Night:\s*|PFL\s*\d+:\s*|Bellator\s*\d+:\s*"
    r"|ONE\s*Championship:\s*|RIZIN:\s*|KSW\s*\d+:\s*)",
    re.IGNORECASE,
)


class MMAMatcher(BaseSportMatcher):
    """Match MMA / combat sports markets across Betfair and Polymarket."""

    THRESHOLD = 0.35
    ALIASES: Dict[str, List[str]] = {}  # No team aliases for MMA
    COMPETITION_PREFIXES: List[str] = []  # Handled with regex below

    def score(self, bf_event: Event, pm_event: PolymarketEvent) -> float:
        pm_fighters_str = self._strip_card_prefix(pm_event.question)

        poly_text = self._normalise(pm_fighters_str)
        poly_outcomes = self._normalise(" ".join(pm_event.outcomes or []))
        poly_combined = f"{poly_text} {poly_outcomes}"

        home_norm = self._normalise(bf_event.home_team or "")
        away_norm = self._normalise(bf_event.away_team or "")

        if not home_norm or not away_norm:
            return 0.0

        # Fighter order is irrelevant — test both orientations
        fwd_score = self._two_fighter_score(
            home_norm, away_norm, poly_combined, poly_text
        )
        rev_score = self._two_fighter_score(
            away_norm, home_norm, poly_combined, poly_text
        )
        base = max(fwd_score, rev_score)

        if base < 0.55:
            return 0.0

        if pm_event.end_date and bf_event.commence_time:
            base += self._date_score(bf_event.commence_time, pm_event.end_date) * 0.10

        return min(base, 1.0)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _strip_card_prefix(self, question: str) -> str:
        """Remove 'UFC 313: ' style prefixes from the PM question."""
        return _UFC_EVENT_PREFIX_RE.sub("", question).strip()

    def _fighter_in_text(self, fighter_norm: str, poly_combined: str) -> bool:
        """
        Check whether a fighter name appears in the poly text.
        Tries: full name, last name only, first+last.
        """
        if fighter_norm in poly_combined:
            return True
        parts = fighter_norm.split()
        if not parts:
            return False
        last = parts[-1]
        if len(last) > 3 and last in poly_combined:
            return True
        if len(parts) >= 2:
            first = parts[0]
            if len(first) > 1 and first in poly_combined and last in poly_combined:
                return True
        return False

    def _two_fighter_score(
        self, f1: str, f2: str, poly_combined: str, poly_text: str
    ) -> float:
        f1_found = self._fighter_in_text(f1, poly_combined)
        f2_found = self._fighter_in_text(f2, poly_combined)
        if not (f1_found and f2_found):
            return 0.0
        score = 0.55
        bf_pair = f"{f1} {f2}"
        score += self._seq_sim(bf_pair, poly_text) * 0.25
        score += self._token_jaccard(bf_pair, poly_text) * 0.10
        return score
