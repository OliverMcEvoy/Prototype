"""
matchers/politics_matcher.py
=============================
Politics / election / referendum market matcher.

This encapsulates the logic that was previously implemented inline inside
MarketMatcher._calculate_politics_similarity().  It scores a Betfair
binary-market event against a Polymarket prediction-market event.

Scoring approach:
  • Token overlap (Jaccard similarity) of the question text                  → up to 0.40
  • SequenceMatcher ratio on normalised questions                             → up to 0.30
  • Shared named entities (detected by capitalised words ≥4 chars)           → up to 0.20
  • Year / date mentions in common                                            → up to 0.10
"""

import re
from typing import Dict, List, Set

from backend.models import Event, PolymarketEvent
from backend.matchers.base_matcher import BaseSportMatcher

# Political question stop-words (very common, add no signal)
_POLITICS_STOP = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "will",
        "who",
        "what",
        "when",
        "where",
        "which",
        "win",
        "wins",
        "winning",
        "vote",
        "votes",
        "election",
        "elect",
        "president",
        "presidential",
        "prime",
        "minister",
        "chancellor",
        "party",
        "candidate",
        "seat",
        "seats",
        "majority",
        "parliament",
        "senate",
        "congress",
        "house",
        "referendum",
        "be",
        "become",
        "next",
        "first",
        "second",
        "new",
        "general",
        "federal",
        "state",
        "lead",
        "leader",
        "leadership",
    ]
)

_YEAR_RE = re.compile(r"\b(20\d{2})\b")


class PoliticsMatcher(BaseSportMatcher):
    """Match politics / election prediction markets."""

    THRESHOLD = 0.25  # Lower threshold — politics questions are often
    # loosely worded on BF vs PM

    ALIASES: Dict[str, List[str]] = {}
    COMPETITION_PREFIXES: List[str] = []

    def score(self, bf_event: Event, pm_event: PolymarketEvent) -> float:
        """
        Score a Betfair politics event against a Polymarket event.
        Uses the event name / market name on the BF side and the question
        on the PM side.
        """
        bf_text = self._normalise(self._bf_full_text(bf_event))
        pm_text = self._normalise(pm_event.question)
        pm_outcomes = self._normalise(" ".join(pm_event.outcomes or []))
        pm_combined = f"{pm_text} {pm_outcomes}"

        if not bf_text or not pm_text:
            return 0.0

        # Token sets (filtering stop words)
        bf_tokens = self._politics_tokens(bf_text)
        pm_tokens = self._politics_tokens(pm_combined)

        if not bf_tokens or not pm_tokens:
            return 0.0

        # 1. Token overlap (Jaccard)
        intersection = bf_tokens & pm_tokens
        union = bf_tokens | pm_tokens
        jaccard = len(intersection) / len(union) if union else 0.0
        score = jaccard * 0.40

        # 2. Sequence similarity
        seq = self._seq_sim(bf_text, pm_text)
        score += seq * 0.30

        # 3. Named-entity bonus — capitalised words in original text
        bf_entities = self._named_entities(bf_event.name or "")
        pm_entities = self._named_entities(pm_event.question)
        shared_entities = bf_entities & pm_entities
        entity_score = min(len(shared_entities) / max(len(bf_entities), 1), 1.0)
        score += entity_score * 0.20

        # 4. Shared year bonus
        bf_years = set(_YEAR_RE.findall(bf_event.name or ""))
        pm_years = set(_YEAR_RE.findall(pm_event.question))
        if bf_years & pm_years:
            score += 0.10

        return min(score, 1.0)

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _bf_full_text(self, event: Event) -> str:
        """Concatenate all available BF event text fields."""
        parts = [
            event.name or "",
            event.home_team or "",
            event.away_team or "",
            event.sport or "",
        ]
        return " ".join(p for p in parts if p)

    def _politics_tokens(self, text: str) -> Set[str]:
        tokens = set(re.findall(r"\b[a-z]{3,}\b", text))
        return tokens - _POLITICS_STOP

    def _named_entities(self, text: str) -> Set[str]:
        """Extract likely named entities (capitalised multi-char words)."""
        raw = re.findall(r"\b[A-Z][a-z]{2,}\b", text)
        return {w.lower() for w in raw if w.lower() not in _POLITICS_STOP}
