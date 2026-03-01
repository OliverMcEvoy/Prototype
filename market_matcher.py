"""
Cross-platform event matching for arbitrage detection.

Matches Betfair events against Polymarket markets using:
  - Team name alias dictionary
  - Token-level partial matching
  - Sport-scoped pre-filtering
  - Date proximity window (±36h)
"""

from typing import List, Optional, Tuple, Dict
from difflib import SequenceMatcher
import re
from datetime import datetime, timedelta, timezone

from models import Event, PolymarketEvent, Outcome
from config import Config


# Team name alias table. Maps variant → canonical for fuzzy matching.
# Add entries here when match_debug.txt shows missed matches.
TEAM_ALIASES: Dict[str, List[str]] = {
    # English football
    "manchester united": ["man utd", "man united", "manchester utd", "mufc"],
    "manchester city": ["man city", "man c", "mcfc"],
    "tottenham hotspur": ["spurs", "tottenham", "thfc"],
    "wolverhampton": ["wolves", "wolverhampton wanderers"],
    "nottingham forest": ["nott'm forest", "notts forest", "nffc"],
    "west bromwich": ["west brom", "wba"],
    "queens park rangers": ["qpr"],
    "sheffield united": ["sheff utd", "sheffield utd"],
    "sheffield wednesday": ["sheff wed", "sheffield wed"],
    "bournemouth": ["afc bournemouth", "afcb"],
    "brighton": ["brighton & hove albion", "brighton hove"],
    "newcastle": ["newcastle united", "nufc"],
    "west ham": ["west ham united", "whu"],
    "leicester": ["leicester city", "lcfc"],
    "ipswich": ["ipswich town"],
    "luton": ["luton town"],
    # Spanish football
    "real madrid": ["real madrid cf"],
    "atletico madrid": ["atletico de madrid", "atl madrid"],
    "real betis": ["real betis balompie"],
    "athletic bilbao": ["athletic club"],
    "deportivo alaves": ["alaves"],
    "real sociedad": ["r sociedad"],
    # Italian football
    "ac milan": ["milan"],
    "inter milan": ["inter", "internazionale", "fc internazionale"],
    "juventus": ["juve"],
    "as roma": ["roma"],
    "ss lazio": ["lazio"],
    # German football
    "borussia dortmund": ["bvb", "dortmund"],
    "borussia mgladbach": ["b. monchengladbach", "mgladbach", "gladbach"],
    "rb leipzig": ["rbl", "rasenball"],
    "bayer leverkusen": ["leverkusen"],
    "eintracht frankfurt": ["frankfurt"],
    "werder bremen": ["werder"],
    # French football
    "paris saint-germain": ["psg", "paris sg", "paris saint germain"],
    "olympique lyonnais": ["lyon", "ol"],
    "olympique marseille": ["marseille", "om"],
    "stade rennais": ["rennes"],
    # Portuguese football
    "sl benfica": ["benfica"],
    "fc porto": ["porto"],
    "sporting cp": ["sporting lisbon", "sporting"],
    # Dutch football
    "ajax": ["afc ajax", "ajax amsterdam"],
    "psv": ["psv eindhoven"],
    "feyenoord": ["feyenoord rotterdam"],
    # US sports
    "los angeles lakers": ["lakers", "la lakers"],
    "golden state warriors": ["warriors", "gsw"],
    "boston celtics": ["celtics"],
    "new york knicks": ["knicks"],
    "chicago bulls": ["bulls"],
    "dallas mavericks": ["mavs", "mavericks"],
    "miami heat": ["heat"],
    "phoenix suns": ["suns"],
    # Tennis (players sometimes listed differently)
    "novak djokovic": ["djokovic"],
    "carlos alcaraz": ["alcaraz"],
    "jannik sinner": ["sinner"],
    # Cricket
    "india": ["team india", "ind"],
    "england": ["eng", "england cricket"],
    "australia": ["aus", "australia cricket"],
    "west indies": ["windies", "wi"],
    "south africa": ["sa", "proteas"],
    "new zealand": ["nz", "black caps"],
    "pakistan": ["pak"],
    "sri lanka": ["sl", "lanka"],
    "bangladesh": ["ban"],
    # Draw / tie
    "draw": ["the draw", "tie", "drawn", "x"],
}

# Build reverse lookup: variant → canonical
_ALIAS_LOOKUP: Dict[str, str] = {}
for canonical, variants in TEAM_ALIASES.items():
    _ALIAS_LOOKUP[canonical] = canonical
    for v in variants:
        _ALIAS_LOOKUP[v] = canonical


def _canonicalise(name: str) -> str:
    """Return the canonical form of a team/player name, or the original if unknown."""
    return _ALIAS_LOOKUP.get(name.lower().strip(), name.lower().strip())


class MarketMatcher:
    """Matches events across different platforms for arbitrage opportunities."""

    DEFAULT_THRESHOLD = 0.35

    def __init__(self, similarity_threshold: float = None):
        self.similarity_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else getattr(Config, "FUZZY_MATCH_THRESHOLD", self.DEFAULT_THRESHOLD)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_matches(
        self, traditional_events: List[Event], polymarket_events: List[PolymarketEvent]
    ) -> List[Tuple[Event, PolymarketEvent, float]]:
        """
        Find matching events between Betfair and Polymarket.

        Returns list of (betfair_event, polymarket_event, score) tuples
        where score >= self.similarity_threshold.
        """
        matches: List[Tuple[Event, PolymarketEvent, float]] = []

        print(
            f"\n[MATCHING] {len(traditional_events)} Betfair vs "
            f"{len(polymarket_events)} Polymarket  (threshold={self.similarity_threshold})"
        )

        # Pre-group Polymarket events by sport category for fast lookup
        poly_by_sport: Dict[str, List[PolymarketEvent]] = {}
        for pe in polymarket_events:
            key = (pe.sport_category if hasattr(pe, "sport_category") else "").lower()
            poly_by_sport.setdefault(key, []).append(pe)
        poly_by_sport["all"] = polymarket_events  # fallback

        for trad_event in traditional_events:
            # Only search Polymarket events in the same sport, plus a small
            # window around the Betfair kick-off time
            sport_key = trad_event.category.lower() if trad_event.category else "all"
            candidates = poly_by_sport.get(sport_key) or polymarket_events

            # Date pre-filter: Polymarket end_date should be within 3 days
            # of Betfair commence_time (avoids comparing totally unrelated events)
            if trad_event.commence_time:
                bf_time = trad_event.commence_time
                if bf_time.tzinfo is None:
                    bf_time = bf_time.replace(tzinfo=timezone.utc)
                candidates = [
                    pe
                    for pe in candidates
                    if pe.end_date is None
                    or (
                        abs(
                            (
                                (
                                    pe.end_date.replace(tzinfo=timezone.utc)
                                    if pe.end_date.tzinfo is None
                                    else pe.end_date
                                )
                                - bf_time
                            ).total_seconds()
                        )
                        <= 3 * 86400
                    )
                ]

            best = self._find_best_match(trad_event, candidates)
            if best:
                poly_event, score = best
                if score >= self.similarity_threshold:
                    matches.append((trad_event, poly_event, score))

        matched_bfids = {bf.id for bf, _, _ in matches}
        print(
            f"[MATCHING] {len(matches)} matches  "
            f"({len(matched_bfids)} unique Betfair events)"
        )
        return matches

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_best_match(
        self, trad_event: Event, poly_events: List[PolymarketEvent]
    ) -> Optional[Tuple[PolymarketEvent, float]]:
        best_match = None
        best_score = 0.0
        for pe in poly_events:
            score = self._calculate_similarity(trad_event, pe)
            if score > best_score:
                best_score = score
                best_match = pe
        return (
            (best_match, best_score)
            if best_match and best_score >= self.similarity_threshold
            else None
        )

    def _calculate_similarity(
        self, trad_event: Event, poly_event: PolymarketEvent
    ) -> float:
        """
        Multi-signal similarity score (0–1).

        Signals:
          1. Both team names present in Polymarket question / outcomes (+0.55 bonus)
          2. Canonical alias matching for team names
          3. Token-overlap Jaccard on normalised names
          4. SequenceMatcher string similarity
          5. Date proximity (±6h = 1.0, ±36h = 0.5, >3d = 0.0)
        """
        # Strip competition prefix from Polymarket question
        poly_question = poly_event.question
        poly_match_part = (
            poly_question.split(":", 1)[1].strip()
            if ":" in poly_question
            else poly_question
        )

        poly_text = self._normalise(poly_question)
        poly_match_text = self._normalise(poly_match_part)

        # Polymarket sports events carry team names in outcomes list:
        # e.g. outcomes = ["Real Madrid", "Getafe", "Draw"]
        # Combine all outcome names into a searchable string
        poly_outcomes_text = self._normalise(
            " ".join(poly_event.outcomes if poly_event.outcomes else [])
        )

        # ---- Canonicalise Betfair team names ----
        home_raw = trad_event.home_team
        away_raw = trad_event.away_team
        home_can = _canonicalise(home_raw)
        away_can = _canonicalise(away_raw)

        # ---- Check presence of each team in Polymarket data ----
        # We check: question text, match part, outcomes, AND canonical variants
        poly_combined = f"{poly_text} {poly_match_text} {poly_outcomes_text}"

        def _team_in_poly(team_raw: str, team_can: str) -> bool:
            tl = team_raw.lower()
            if tl in poly_combined or team_can in poly_combined:
                return True
            # Token-level: any single token of the team name found?
            for tok in re.split(r"[\s\-]+", tl):
                if len(tok) > 3 and tok in poly_combined:
                    return True
            # Alias reverse: check if any known alias of this canonical appears
            aliases = TEAM_ALIASES.get(team_can, [])
            return any(a in poly_combined for a in aliases)

        home_found = _team_in_poly(home_raw, home_can)
        away_found = _team_in_poly(away_raw, away_can)

        # Hard gate: for sports events BOTH teams must be detectable
        if not (home_found and away_found):
            return 0.0

        score = 0.0

        # Signal 1: Both teams present (+0.55 is the dominant signal)
        score += 0.55

        # Signal 2: String similarity on team-pair vs Polymarket match part
        trad_pair = self._normalise(f"{home_raw} {away_raw}")
        seq_sim = max(
            self._seq_sim(trad_pair, poly_match_text),
            self._seq_sim(self._normalise(f"{home_can} {away_can}"), poly_match_text),
        )
        score += seq_sim * 0.20  # up to +0.20

        # Signal 3: Jaccard token overlap
        trad_tokens = self._tokens(trad_pair)
        poly_tokens = self._tokens(poly_match_text)
        if trad_tokens and poly_tokens:
            jaccard = len(trad_tokens & poly_tokens) / len(trad_tokens | poly_tokens)
            score += jaccard * 0.15  # up to +0.15

        # Signal 4: Date proximity
        if poly_event.end_date and trad_event.commence_time:
            score += (
                self._date_score(trad_event.commence_time, poly_event.end_date) * 0.10
            )

        return min(score, 1.0)

    # ------------------------------------------------------------------
    # Outcome alignment (for arbitrage engine)
    # ------------------------------------------------------------------

    def align_outcomes(
        self, trad_event: Event, poly_event: PolymarketEvent
    ) -> List[Tuple[str, str]]:
        """
        Return list of (betfair_runner_name, polymarket_outcome_name) pairs
        where the two names refer to the same real-world team/player.

        Used by the arbitrage engine to decide which outcomes to compare.
        """
        pairs: List[Tuple[str, str]] = []
        used_poly: set = set()

        for outcome in trad_event.outcomes:
            bf_can = _canonicalise(outcome.name)
            best_poly: Optional[str] = None
            best_score = 0.0
            for pm_outcome in poly_event.outcomes:
                if pm_outcome in used_poly:
                    continue
                pm_can = _canonicalise(pm_outcome)
                # Direct canonical match
                if bf_can == pm_can:
                    best_poly = pm_outcome
                    best_score = 1.0
                    break
                # Alias match
                s = self._seq_sim(bf_can, pm_can)
                if s > best_score:
                    best_score = s
                    best_poly = pm_outcome
            if best_poly and best_score >= 0.5:
                pairs.append((outcome.name, best_poly))
                used_poly.add(best_poly)

        return pairs

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _normalise(self, text: str) -> str:
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _tokens(self, text: str) -> set:
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
            "win",
            "winner",
            "match",
            "game",
            "fc",
            "afc",
            "sc",
            "cf",
            "ac",
            "as",
            "us",
        }
        return {w for w in text.split() if len(w) > 2 and w not in stop}

    def _seq_sim(self, s1: str, s2: str) -> float:
        return SequenceMatcher(None, s1, s2).ratio()

    def _date_score(self, bf_time: datetime, pm_time: datetime) -> float:
        """1.0 within 6h, 0.5 at 36h, 0.0 beyond 3 days."""
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

    # ------------------------------------------------------------------
    # create_combined_event — unchanged contract, improved outcome alignment
    # ------------------------------------------------------------------

    def create_combined_event(
        self, trad_event: Event, poly_event: PolymarketEvent
    ) -> Event:
        """
        Merge Betfair and Polymarket outcomes into one Event.

        For sports markets Polymarket outcomes are team names (not Yes/No),
        so we tag each Polymarket outcome with the platform name and treat
        them as additional price sources for the same real-world outcome.
        """
        decimal_odds = poly_event.to_decimal_odds()
        poly_outcomes: List[Outcome] = []
        for pm_name, odds in zip(poly_event.outcomes, decimal_odds):
            if odds > 1.0:
                poly_outcomes.append(
                    Outcome(
                        name=pm_name,
                        price=odds,
                        bookmaker="Polymarket",
                        last_update=datetime.now(),
                    )
                )

        combined = Event(
            id=f"{trad_event.id}_combined",
            sport=trad_event.sport,
            commence_time=trad_event.commence_time,
            home_team=trad_event.home_team,
            away_team=trad_event.away_team,
            outcomes=trad_event.outcomes + poly_outcomes,
            category=trad_event.category,
            description=f"{trad_event} / Polymarket: {poly_event.question}",
            match_quality=1.0,
        )
        return combined

    # ------------------------------------------------------------------
    # Legacy helpers kept for compatibility
    # ------------------------------------------------------------------

    def _extract_keywords(self, text: str) -> set:
        return self._tokens(text)

    def _string_similarity(self, s1: str, s2: str) -> float:
        return self._seq_sim(s1, s2)

    def _time_similarity(self, time1: datetime, time2: datetime) -> float:
        return self._date_score(time1, time2)

    def match_by_category(self, category, traditional_events, polymarket_events):
        return self.find_matches(traditional_events, polymarket_events)

    def _get_category_keywords(self, category: str) -> List[str]:
        return []

    def _normalize_text(self, text: str) -> str:
        return self._normalise(text)

    def find_matches(
        self, traditional_events: List[Event], polymarket_events: List[PolymarketEvent]
    ) -> List[Tuple[Event, PolymarketEvent, float]]:
        """
        Find matching events between traditional bookmakers and Polymarket.

        Args:
            traditional_events: Events from traditional bookmakers
            polymarket_events: Events from Polymarket

        Returns:
            List of tuples (traditional_event, polymarket_event, similarity_score)
        """
        matches = []

        print(
            f"\n[MATCHING] Starting to match {len(traditional_events)} traditional events against {len(polymarket_events)} Polymarket markets"
        )
        print(f"[MATCHING] Similarity threshold: {self.similarity_threshold}")

        for trad_event in traditional_events:
            best_match = self._find_best_match(trad_event, polymarket_events)
            if best_match:
                poly_event, score = best_match
                if score >= self.similarity_threshold:
                    matches.append((trad_event, poly_event, score))

        print(
            f"[MATCHING] {len(matches)}/{len(traditional_events)} matched (threshold={self.similarity_threshold})"
        )
        return matches

    def _find_best_match(
        self, trad_event: Event, poly_events: List[PolymarketEvent]
    ) -> Optional[Tuple[PolymarketEvent, float]]:
        """Find the best matching Polymarket event for a traditional event."""
        best_match = None
        best_score = 0.0

        for poly_event in poly_events:
            score = self._calculate_similarity(trad_event, poly_event)
            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                best_match = poly_event

        return (best_match, best_score) if best_match else None

    def _calculate_similarity(
        self, trad_event: Event, poly_event: PolymarketEvent
    ) -> float:
        """
        Calculate similarity score between traditional and Polymarket events.

        Returns:
            Similarity score between 0 and 1
        """
        scores = []

        # Polymarket sports titles look like "T20 World Cup: India vs West Indies"
        # Strip the competition prefix (everything before the colon) to isolate team names
        poly_question = poly_event.question
        if ":" in poly_question:
            poly_match_part = poly_question.split(":", 1)[1].strip()
        else:
            poly_match_part = poly_question

        # Compare event names/questions
        trad_text = self._normalize_text(
            f"{trad_event.home_team} {trad_event.away_team} {trad_event.sport}"
        )
        poly_text = self._normalize_text(poly_question)
        poly_match_text = self._normalize_text(poly_match_part)

        # Check if team names appear in Polymarket question (full or match part)
        home_lower = trad_event.home_team.lower()
        away_lower = trad_event.away_team.lower()
        home_in_poly = home_lower in poly_text or home_lower in poly_match_text
        away_in_poly = away_lower in poly_text or away_lower in poly_match_text

        # Also check if Polymarket outcome names match team names
        # (e.g. outcomes=["India","West Indies"] vs home_team="India")
        poly_outcomes_lower = [o.lower() for o in poly_event.outcomes]
        if not home_in_poly:
            home_in_poly = any(
                home_lower in o or o in home_lower for o in poly_outcomes_lower
            )
        if not away_in_poly:
            away_in_poly = any(
                away_lower in o or o in away_lower for o in poly_outcomes_lower
            )

        # STRICT REQUIREMENT: For sports events, BOTH team names must be present
        # This prevents false matches like "FC Volendam vs Groningen" matching "Beth Van Duyne"
        if trad_event.sport and trad_event.sport.lower() not in [
            "polymarket",
            "prediction",
        ]:
            if not (home_in_poly and away_in_poly):
                return 0.0  # No match if both teams aren't mentioned

        # Direct string similarity (use match part for sports to avoid low scores from prefix)
        name_similarity = max(
            self._string_similarity(trad_text, poly_text),
            self._string_similarity(
                self._normalize_text(f"{trad_event.home_team} {trad_event.away_team}"),
                poly_match_text,
            ),
        )
        scores.append(name_similarity * 0.3)  # 30% weight

        if home_in_poly and away_in_poly:
            scores.append(0.6)  # 60% bonus if both teams found (key signal)
        elif home_in_poly or away_in_poly:
            scores.append(0.25)  # 25% bonus if one team mentioned

        # Check for keyword matches
        trad_keywords = self._extract_keywords(trad_text)
        poly_keywords = self._extract_keywords(poly_text)

        if trad_keywords and poly_keywords:
            keyword_match = len(trad_keywords & poly_keywords) / max(
                len(trad_keywords), len(poly_keywords)
            )
            scores.append(keyword_match * 0.15)  # 15% weight

        # Compare time proximity (if available)
        if poly_event.end_date:
            time_similarity = self._time_similarity(
                trad_event.commence_time, poly_event.end_date
            )
            scores.append(time_similarity * 0.1)  # 10% weight

        return min(sum(scores), 1.0)

    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison."""
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _extract_keywords(self, text: str) -> set:
        """Extract significant keywords from text."""
        # Remove common words
        stop_words = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "will",
            "be",
            "is",
            "are",
            "was",
            "were",
            "vs",
            "versus",
            "win",
            "winner",
            "match",
            "game",
            "event",
        }

        words = text.split()
        keywords = {w for w in words if len(w) > 2 and w not in stop_words}
        return keywords

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using SequenceMatcher."""
        return SequenceMatcher(None, s1, s2).ratio()

    def _time_similarity(self, time1: datetime, time2: datetime) -> float:
        """Calculate similarity based on time proximity."""
        # Handle None values
        if time1 is None or time2 is None:
            return 0.0

        # Make both timezone-aware or both timezone-naive
        if time1.tzinfo is None and time2.tzinfo is not None:
            # Make time1 aware (assume UTC)
            from datetime import timezone

            time1 = time1.replace(tzinfo=timezone.utc)
        elif time1.tzinfo is not None and time2.tzinfo is None:
            # Make time2 aware (assume UTC)
            from datetime import timezone

            time2 = time2.replace(tzinfo=timezone.utc)

        time_diff = abs((time1 - time2).total_seconds())

        # Events within 1 day = 100% similarity
        # Events within 1 week = 50% similarity
        # Beyond 1 week = 0% similarity

        if time_diff <= 86400:  # 1 day
            return 1.0
        elif time_diff <= 604800:  # 1 week
            return 1.0 - ((time_diff - 86400) / 518400)  # Linear decay
        else:
            return 0.0

    def match_by_category(
        self,
        category: str,
        traditional_events: List[Event],
        polymarket_events: List[PolymarketEvent],
    ) -> List[Tuple[Event, PolymarketEvent, float]]:
        """
        Find matches within a specific category.

        Args:
            category: Market category (politics, entertainment, etc.)
            traditional_events: Traditional bookmaker events
            polymarket_events: Polymarket events

        Returns:
            List of matched event pairs
        """
        # Filter events by category
        filtered_trad = [
            e
            for e in traditional_events
            if e.category and category.lower() in e.category.lower()
        ]

        # Polymarket doesn't have explicit categories in our model,
        # so we use keyword matching
        category_keywords = self._get_category_keywords(category)
        filtered_poly = [
            p
            for p in polymarket_events
            if any(kw in p.question.lower() for kw in category_keywords)
        ]

        return self.find_matches(filtered_trad, filtered_poly)

    def _get_category_keywords(self, category: str) -> List[str]:
        """Get keywords associated with a market category."""
        keyword_map = {
            "politics": [
                "election",
                "president",
                "senate",
                "congress",
                "vote",
                "political",
            ],
            "entertainment": [
                "oscar",
                "grammy",
                "emmy",
                "award",
                "movie",
                "film",
                "actor",
            ],
            "crypto": ["bitcoin", "ethereum", "crypto", "blockchain", "btc", "eth"],
            "finance": ["stock", "market", "economy", "gdp", "inflation", "rate"],
            "sports": ["game", "match", "championship", "league", "cup", "tournament"],
            "science": ["climate", "space", "technology", "research", "discovery"],
            "business": ["company", "merger", "ipo", "earnings", "ceo"],
        }
        return keyword_map.get(category.lower(), [])

    def create_combined_event(
        self, trad_event: Event, poly_event: PolymarketEvent
    ) -> Event:
        """
        Create a combined event with outcomes from both platforms.

        Args:
            trad_event: Traditional bookmaker event
            poly_event: Polymarket event

        Returns:
            Combined Event with all outcomes
        """
        # Convert Polymarket prices to outcomes
        poly_outcomes = []
        decimal_odds = poly_event.to_decimal_odds()

        for outcome_name, odds in zip(poly_event.outcomes, decimal_odds):
            if odds > 0:  # Valid odds
                poly_outcome = Outcome(
                    name=outcome_name,
                    price=odds,
                    bookmaker="Polymarket",
                    last_update=datetime.now(),
                )
                poly_outcomes.append(poly_outcome)

        # Combine outcomes
        all_outcomes = trad_event.outcomes + poly_outcomes

        # Create combined event
        combined = Event(
            id=f"{trad_event.id}_combined",
            sport=trad_event.sport,
            commence_time=trad_event.commence_time,
            home_team=trad_event.home_team,
            away_team=trad_event.away_team,
            outcomes=all_outcomes,
            category=trad_event.category,
            description=f"{trad_event} / Polymarket: {poly_event.question}",
            match_quality=1.0,  # Will be set by caller based on similarity score
        )

        return combined
