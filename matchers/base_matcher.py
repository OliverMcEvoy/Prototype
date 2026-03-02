"""
matchers/base_matcher.py
========================
Abstract base class for all sport-specific market matchers.

Every subclass must implement  score(bf_event, pm_event) -> float
and may override THRESHOLD and COMPETITION_PREFIXES.

Shared utilities live here so each sport module stays lean.
"""

import re
import unicodedata
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from models import Event, PolymarketEvent


# ---------------------------------------------------------------------------
# Tokens so generic they must not be used alone to identify a team/player
# ---------------------------------------------------------------------------
GENERIC_TOKENS: FrozenSet[str] = frozenset(
    {
        "real",
        "city",
        "united",
        "new",
        "south",
        "north",
        "east",
        "west",
        "club",
        "the",
        "san",
        "los",
        "las",
        "de",
        "da",
        "del",
        "di",
        "von",
        "van",
        "le",
        "la",
        "el",
        "st",
        "saint",
        "fc",
        "afc",
        "sc",
        "cf",
        "sk",
        "ac",
        "as",
        "us",
        "bsc",
        "fk",
        "nk",
    }
)

# ---------------------------------------------------------------------------
# Common official prefixes added by clubs (but stripped on Betfair / shorthand)
# ---------------------------------------------------------------------------
_CLUB_PREFIXES_RE = re.compile(
    r"^(?:"
    r"1\.\s+fc\s+|"  # 1. FC Koeln
    r"1\.\s+fsv\s+|"  # 1. FSV Mainz
    r"1\.\s+fc\s+|"
    r"kks\s+|kks\s+|"
    r"krc\s+|"
    r"gnk\s+|hnk\s+|nk\s+|"  # Croatian
    r"mfk\s+|gks\s+|"
    r"rcd\s+|ud\s+|sd\s+|ad\s+|cd\s+|cf\s+|"  # Spanish
    r"asc\s+|ssc\s+|ssd\s+|asd\s+|us\s+|ss\s+|"  # Italian
    r"sk\s+|fk\s+|bk\s+|ik\s+|if\s+|"  # Scandinavian
    r"ac\s+|as\s+|fc\s+|afc\s+|sc\s+|bsc\s+|"  # Generic
    r"vfl\s+|vfb\s+|sv\s+|bv\s+|tsv\s+|fsv\s+|"  # German
    r"club\s+|atletico\s+de\s+|"
    r"olympique\s+de\s+|"
    r"sporting\s+cp\s+|"
    r"sport\s+lisboa\s+e\s+benfica|"  # special case → benfica
    r")",
    re.IGNORECASE,
)

_CLUB_SUFFIXES_RE = re.compile(
    r"\s+(?:"
    r"fc|afc|cf|sc|fk|sk|bsc|ac|as|sd|bv|sv|tsv|fsv|vfl|vfb|"
    r"calcio|fussball|football|futbol|sport|wanderers|"
    r"1919|1905|1910|1921|1923|1948|1960|1907|1909|"  # founding years
    r")\s*$",
    re.IGNORECASE,
)

# Women / youth markers
_GENDER_RE = re.compile(r"\s*\(w\)\s*|\s+women\s*|\s+w\b", re.IGNORECASE)
_YOUTH_RE = re.compile(
    r"\s+(?:u\d{2}|u-\d{2}|youth|reserve|res|b|ii|iii|reserves|junior|"
    r"under-?\d{2}|am\.|amateur)\s*$",
    re.IGNORECASE,
)


class BaseSportMatcher(ABC):
    """Abstract base for sport-specific event matchers."""

    THRESHOLD: float = 0.35

    # Override in subclasses — list of competition name prefixes present in PM
    # questions that should be stripped before matching team names.
    # E.g. "KHL: " or "Six Nations: "
    COMPETITION_PREFIXES: List[str] = []

    # Sport-specific alias tables — {canonical: [variant, ...]}
    # Used by _build_lookup() to create a flat reverse map.
    ALIASES: Dict[str, List[str]] = {}

    def __init__(self) -> None:
        self._alias_lookup: Dict[str, str] = self._build_lookup()

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def score(self, bf_event: Event, pm_event: PolymarketEvent) -> float:
        """Return a similarity score in [0, 1]."""

    # ------------------------------------------------------------------
    # Shared text utilities
    # ------------------------------------------------------------------

    def _normalise(self, text: str) -> str:
        """ASCII-fold, lowercase, collapse whitespace."""
        text = (
            unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii")
        )
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _strip_competition_prefix(self, question: str) -> str:
        """Strip league/competition prefixes from a PM question string."""
        for prefix in self.COMPETITION_PREFIXES:
            if question.lower().startswith(prefix.lower()):
                return question[len(prefix) :].strip()
        # Generic colon-separated prefix: "League: Team A vs Team B"
        if ":" in question:
            parts = question.split(":", 1)
            # Only strip if it looks like a competition name (no "vs" in prefix part)
            if len(parts[0]) < 60 and "vs" not in parts[0].lower():
                return parts[1].strip()
        return question

    def _clean_team_name(self, name: str) -> str:
        """Strip common official prefixes/suffixes and gender/youth markers."""
        n = _GENDER_RE.sub(" ", name).strip()
        n = _YOUTH_RE.sub("", n).strip()
        n = _CLUB_PREFIXES_RE.sub("", n).strip()
        n = _CLUB_SUFFIXES_RE.sub("", n).strip()
        return n

    def _canonicalise(self, name: str) -> str:
        """Return canonical form using alias lookup; fall back to cleaned name."""
        n = self._normalise(self._clean_team_name(name))
        return self._alias_lookup.get(n, n)

    def _build_lookup(self) -> Dict[str, str]:
        """Build flat {variant → canonical} from ALIASES."""
        lookup: Dict[str, str] = {}
        for canonical, variants in self.ALIASES.items():
            lookup[canonical] = canonical
            for v in variants:
                lookup[v.lower()] = canonical
        return lookup

    # ------------------------------------------------------------------
    # Team-presence detection helpers
    # ------------------------------------------------------------------

    def _team_in_text(self, team_raw: str, poly_combined: str) -> bool:
        """
        Return True if the Betfair team name can be detected in poly_combined.

        Detection order (short-circuits on first match):
          1. Exact canonical in poly text
          2. Any alias present in poly text
          3. All distinctive tokens present individually
          4. Reverse-nickname check: any single poly word resolves
             (via alias lookup) to the same canonical
        """
        team_can = self._canonicalise(team_raw)

        # 1. Direct canonical / raw match
        if team_can in poly_combined or self._normalise(team_raw) in poly_combined:
            return True

        # 2. Alias forward check
        for alias in self.ALIASES.get(team_can, []):
            if alias.lower() in poly_combined:
                return True

        # 3. Token presence — for multi-word teams ALL tokens must appear
        #    (including generic words like "real", "city") to prevent
        #    "Real Madrid" matching against "Atletico Madrid" via just "madrid".
        #    For single-word teams, we require the one distinctive token.
        tl = self._normalise(team_raw)
        raw_tokens = [t for t in re.split(r"[\s\-/]+", tl) if len(t) > 2]
        if len(raw_tokens) >= 2:
            # Multi-word team: every token must appear (strict)
            if all(t in poly_combined for t in raw_tokens):
                return True
        else:
            # Single-word team: require the token is distinctive (non-generic)
            distinctive = [
                t for t in raw_tokens if t not in GENERIC_TOKENS and len(t) > 3
            ]
            if distinctive and all(t in poly_combined for t in distinctive):
                return True

        # 4. Reverse-nickname: check if any space-separated word in poly
        #    resolves via alias_lookup to the same canonical as the BF team.
        poly_words = [w for w in poly_combined.split() if len(w) > 2]
        for word in poly_words:
            if self._alias_lookup.get(word) == team_can:
                return True

        return False

    # ------------------------------------------------------------------
    # Scoring building blocks
    # ------------------------------------------------------------------

    def _date_score(self, bf_time: datetime, pm_time: datetime) -> float:
        """1.0 within 6 h → 0.5 at 36 h → 0.0 beyond 3 d."""
        if bf_time.tzinfo is None:
            bf_time = bf_time.replace(tzinfo=timezone.utc)
        if pm_time.tzinfo is None:
            pm_time = pm_time.replace(tzinfo=timezone.utc)
        diff = abs((bf_time - pm_time).total_seconds())
        if diff <= 6 * 3600:
            return 1.0
        elif diff <= 36 * 3600:
            return 1.0 - ((diff - 6 * 3600) / (30 * 3600)) * 0.5
        elif diff <= 3 * 86400:
            return max(0.0, 0.5 - ((diff - 36 * 3600) / (36 * 3600)) * 0.5)
        return 0.0

    def _seq_sim(self, s1: str, s2: str) -> float:
        return SequenceMatcher(None, s1, s2).ratio()

    def _token_jaccard(self, a: str, b: str) -> float:
        stop = {
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
            "vs",
            "versus",
            "fc",
            "afc",
            "sc",
            "cf",
            "ac",
        }
        ta = {w for w in a.split() if len(w) > 2 and w not in stop}
        tb = {w for w in b.split() if len(w) > 2 and w not in stop}
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    # ------------------------------------------------------------------
    # Standard two-team scoring kernel (reused by most sport matchers)
    # ------------------------------------------------------------------

    def _standard_score(
        self,
        bf_event: Event,
        pm_event: PolymarketEvent,
        pm_question_override: Optional[str] = None,
    ) -> float:
        """
        Core two-team scoring shared by soccer/basketball/hockey etc.

        Returns 0.0 immediately if EITHER team is not detectable in PM text.
        """
        # Build PM search text
        pm_q = pm_question_override or pm_event.question
        pm_q_clean = self._strip_competition_prefix(pm_q)
        poly_text = self._normalise(pm_q)
        poly_match = self._normalise(pm_q_clean)
        poly_outcomes = self._normalise(" ".join(pm_event.outcomes or []))
        poly_combined = f"{poly_text} {poly_match} {poly_outcomes}"

        home_found = self._team_in_text(bf_event.home_team, poly_combined)
        away_found = self._team_in_text(bf_event.away_team, poly_combined)

        if not (home_found and away_found):
            return 0.0

        score = 0.55  # Both teams present — dominant signal

        # String similarity on normalised pair vs PM match part
        bf_pair = self._normalise(f"{bf_event.home_team} {bf_event.away_team}")
        seq = max(
            self._seq_sim(bf_pair, poly_match),
            self._seq_sim(
                self._normalise(
                    f"{self._canonicalise(bf_event.home_team)} "
                    f"{self._canonicalise(bf_event.away_team)}"
                ),
                poly_match,
            ),
        )
        score += seq * 0.20

        # Jaccard on tokens
        score += self._token_jaccard(bf_pair, poly_match) * 0.15

        # Date proximity
        if pm_event.end_date and bf_event.commence_time:
            score += self._date_score(bf_event.commence_time, pm_event.end_date) * 0.10

        return min(score, 1.0)
