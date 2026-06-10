"""
test_politics.py — Unit tests for the politics market matching feature.

Tests the following WITHOUT requiring any API access (pure offline unit tests):
  - _calculate_politics_similarity() scoring for various market pairs
  - find_politics_matches() greedy 1:1 matching behaviour
  - Date-filter bypass for politics events inside find_matches()
  - Config / BetfairClient constants
  - TEAM_ALIASES political entries

Usage:
    python -m pytest test_politics.py -v
    # or simply:
    python test_politics.py
"""

import unittest
from datetime import datetime, timezone, timedelta
from typing import List

from backend.models import Event, Outcome, PolymarketEvent
from backend.market_matcher import MarketMatcher, TEAM_ALIASES
from backend.config import Config
from betfair_client import BetfairClient


# ─── Shared timestamps ───────────────────────────────────────────────────────

_NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
_ELECTION_DAY = _NOW + timedelta(days=200)  # elections are months away


# ─── Fixture helpers ─────────────────────────────────────────────────────────


def _outcome(
    name: str, price: float = 3.0, bookmaker: str = "Betfair Exchange"
) -> Outcome:
    return Outcome(name=name, price=price, bookmaker=bookmaker, last_update=_NOW)


def _bf_event(
    runners: List[str],
    event_id: str = "1.000",
    category: str = "politics",
    sport: str = "Politics",
    commence_time: datetime = _ELECTION_DAY,
) -> Event:
    """Build a minimal Betfair politics Event with given runner names."""
    outcomes: List[Outcome] = []
    for name in runners:
        outcomes.append(_outcome(name, price=3.0, bookmaker="Betfair Exchange"))
        outcomes.append(_outcome(name, price=3.1, bookmaker="Betfair Lay"))
    return Event(
        id=event_id,
        sport=sport,
        commence_time=commence_time,
        home_team=runners[0] if runners else "Unknown",
        away_team=runners[1] if len(runners) > 1 else "Unknown",
        outcomes=outcomes,
        category=category,
    )


def _pm_event(
    question: str,
    outcomes: List[str],
    event_id: str = "poly-0",
    sport_category: str = "politics",
    end_date: datetime = _ELECTION_DAY,
    volume: float = 50_000.0,
    prices: List[float] = None,
) -> PolymarketEvent:
    """Build a minimal PolymarketEvent."""
    if prices is None:
        n = len(outcomes) or 1
        prices = [1.0 / n] * len(outcomes)
    return PolymarketEvent(
        id=event_id,
        question=question,
        outcomes=outcomes,
        prices=prices,
        end_date=end_date,
        volume=volume,
        liquidity=volume * 0.2,
        sport_category=sport_category,
    )


# ─── 1. Similarity scoring ────────────────────────────────────────────────────


class TestCalculatePoliticsSimilarity(unittest.TestCase):
    """Tests for MarketMatcher._calculate_politics_similarity()."""

    def setUp(self):
        self.matcher = MarketMatcher()

    # ── happy paths ──────────────────────────────────────────────────────────

    def test_us_house_race_scores_above_threshold(self):
        """Republican/Democrat runners vs Polymarket House 2026 question → high score."""
        bf = _bf_event(
            ["Republican Party", "Democratic Party"],
            event_id="1.001",
        )
        pm = _pm_event(
            "Which party will win the House in 2026?",
            ["Republican", "Democrat", "Other"],
            event_id="poly-001",
        )
        score = self.matcher._calculate_politics_similarity(bf, pm)
        self.assertGreaterEqual(
            score,
            0.35,
            f"US House race should score ≥ 0.35 (party aliases), got {score:.3f}",
        )

    def test_uk_election_scores_above_threshold(self):
        """UK party runners vs Polymarket UK election question → high score."""
        bf = _bf_event(
            ["Labour Party", "Conservative Party", "Liberal Democrats", "Reform UK"],
            event_id="1.002",
        )
        pm = _pm_event(
            "Which party will win the UK 2026 general election?",
            ["Labour", "Conservative", "Lib Dems", "Other"],
            event_id="poly-002",
        )
        score = self.matcher._calculate_politics_similarity(bf, pm)
        self.assertGreaterEqual(
            score,
            0.35,
            f"UK election should score ≥ 0.35 (party aliases), got {score:.3f}",
        )

    def test_identical_runner_names_give_high_score(self):
        """Exact runner name overlap produces maximum runner_ratio contribution."""
        bf = _bf_event(["Republican", "Democrat"], event_id="1.003")
        pm = _pm_event(
            "2026 US Senate: Republican or Democrat?",
            ["Republican", "Democrat"],
            event_id="poly-003",
        )
        score = self.matcher._calculate_politics_similarity(bf, pm)
        self.assertGreaterEqual(
            score,
            0.50,
            f"Exact runner name match should give score ≥ 0.50, got {score:.3f}",
        )

    # ── alias matching ────────────────────────────────────────────────────────

    def test_gop_alias_triggers_republican_match(self):
        """'Republican Party' BF runner matches 'GOP' in PM text via TEAM_ALIASES."""
        bf = _bf_event(["Republican Party", "Democratic Party"], event_id="1.010")
        pm = _pm_event(
            "Will the GOP retain the Senate in 2026?",
            ["Yes", "No"],
            event_id="poly-010",
        )
        score = self.matcher._calculate_politics_similarity(bf, pm)
        self.assertGreater(score, 0.0, "GOP alias should produce non-zero score")

    def test_tory_alias_triggers_conservative_match(self):
        """'Conservative Party' BF runner matches 'Tory' in PM text."""
        bf = _bf_event(["Conservative Party", "Labour Party"], event_id="1.011")
        pm = _pm_event(
            "Will the Tory party hold their seat in the UK by-election?",
            ["Yes", "No"],
            event_id="poly-011",
        )
        score = self.matcher._calculate_politics_similarity(bf, pm)
        self.assertGreater(score, 0.0, "Tory alias should produce non-zero score")

    def test_lib_dems_alias_triggers_liberal_democrats_match(self):
        """'Liberal Democrats' BF runner matches 'Lib Dems' in PM text."""
        bf = _bf_event(["Liberal Democrats", "Labour Party"], event_id="1.012")
        pm = _pm_event(
            "Will the Lib Dems gain seats in the 2026 election?",
            ["Yes", "No"],
            event_id="poly-012",
        )
        score = self.matcher._calculate_politics_similarity(bf, pm)
        self.assertGreater(score, 0.0, "Lib Dems alias should produce non-zero score")

    # ── negative / unrelated ─────────────────────────────────────────────────

    def test_crypto_question_scores_zero(self):
        """Politics runners vs crypto market → score should be near zero."""
        bf = _bf_event(["Donald Trump", "Joe Biden"], event_id="1.020")
        pm = _pm_event(
            "Will Bitcoin reach $100k by end of 2026?",
            ["Yes", "No"],
            event_id="poly-020",
        )
        score = self.matcher._calculate_politics_similarity(bf, pm)
        self.assertLess(
            score,
            0.10,
            f"Unrelated markets should score < 0.10, got {score:.3f}",
        )

    def test_sports_question_scores_low(self):
        """Politics runners vs a football match question → very low score."""
        bf = _bf_event(["Republican Party", "Democratic Party"], event_id="1.021")
        pm = _pm_event(
            "Will Manchester City beat Arsenal in the FA Cup final?",
            ["Yes", "No"],
            event_id="poly-021",
        )
        score = self.matcher._calculate_politics_similarity(bf, pm)
        self.assertLess(
            score,
            0.15,
            f"Politics-vs-football should score < 0.15, got {score:.3f}",
        )

    # ── edge cases ────────────────────────────────────────────────────────────

    def test_binary_yes_no_outcomes_excluded_from_signal3(self):
        """
        When PM outcomes are only [Yes, No], Signal 3 (outcome_ratio) must be
        0.0 (empty list after filtering) rather than 0/2 counting a miss.
        The overall score should still reflect Signal 1 + Signal 2.
        """
        bf = _bf_event(["Republican Party", "Democratic Party"], event_id="1.030")
        pm = _pm_event(
            "Will the Republican Party win the 2026 US Senate?",
            ["Yes", "No"],
            event_id="poly-030",
        )
        # "Republican" should be found via alias in Signal 1
        # outcome_ratio should default to 0.0 (empty non-yes/no list)
        score = self.matcher._calculate_politics_similarity(bf, pm)
        # Score comes entirely from Signal 1 + Signal 2 keyword overlap
        self.assertGreater(
            score, 0.0, "Binary Yes/No market should still score > 0 via Signal 1"
        )
        self.assertLessEqual(score, 1.0)

    def test_score_never_exceeds_one(self):
        """Return value must always be clamped to [0, 1]."""
        bf = _bf_event(["Republican", "Democrat"], event_id="1.031")
        pm = _pm_event(
            "Republican Democrat 2026 election senate house congress republican democrat",
            ["Republican", "Democrat"],
            event_id="poly-031",
        )
        score = self.matcher._calculate_politics_similarity(bf, pm)
        self.assertLessEqual(score, 1.0)
        self.assertGreaterEqual(score, 0.0)

    def test_no_runners_does_not_raise(self):
        """Empty runner list on BF side → graceful 0.0, no exception."""
        bf = _bf_event([], event_id="1.032")
        bf.outcomes = []
        pm = _pm_event(
            "Which party wins 2026?", ["Republican", "Democrat"], event_id="poly-032"
        )
        try:
            score = self.matcher._calculate_politics_similarity(bf, pm)
        except Exception as exc:
            self.fail(f"Empty runners raised an exception: {exc}")
        self.assertLessEqual(score, 1.0)

    def test_no_pm_outcomes_does_not_raise(self):
        """Empty PM outcomes → graceful score, no exception."""
        bf = _bf_event(["Republican Party", "Democratic Party"], event_id="1.033")
        pm = _pm_event("Which party wins 2026?", [], event_id="poly-033")
        try:
            score = self.matcher._calculate_politics_similarity(bf, pm)
        except Exception as exc:
            self.fail(f"Empty PM outcomes raised an exception: {exc}")
        self.assertLessEqual(score, 1.0)


# ─── 2. find_politics_matches() ──────────────────────────────────────────────


class TestFindPoliticsMatches(unittest.TestCase):
    """Tests for MarketMatcher.find_politics_matches()."""

    def setUp(self):
        self.matcher = MarketMatcher()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _us_house_bf(self, event_id="1.201"):
        return _bf_event(
            ["Republican Party", "Democratic Party"],
            event_id=event_id,
        )

    def _uk_election_bf(self, event_id="1.202"):
        return _bf_event(
            ["Labour Party", "Conservative Party", "Liberal Democrats"],
            event_id=event_id,
        )

    def _us_house_pm(self, event_id="poly-201"):
        return _pm_event(
            "Which party will win the House in 2026?",
            ["Republican", "Democrat", "Other"],
            event_id=event_id,
        )

    def _uk_election_pm(self, event_id="poly-202"):
        return _pm_event(
            "Which party will win the UK 2026 general election?",
            ["Labour", "Conservative", "Lib Dems", "Other"],
            event_id=event_id,
        )

    # ── basic matching ────────────────────────────────────────────────────────

    def test_correct_pairs_are_matched(self):
        """US House BF ↔ US House PM and UK election BF ↔ UK election PM."""
        bf_events = [self._us_house_bf("1.201"), self._uk_election_bf("1.202")]
        pm_events = [self._us_house_pm("poly-201"), self._uk_election_pm("poly-202")]

        matches = self.matcher.find_politics_matches(bf_events, pm_events)
        self.assertEqual(len(matches), 2)

        pair_map = {bf.id: pm.id for bf, pm, _ in matches}
        self.assertEqual(
            pair_map.get("1.201"), "poly-201", "US House BF should match US House PM"
        )
        self.assertEqual(
            pair_map.get("1.202"),
            "poly-202",
            "UK election BF should match UK election PM",
        )

    def test_returns_three_element_tuples(self):
        """Each result must be a (Event, PolymarketEvent, float) tuple."""
        matches = self.matcher.find_politics_matches(
            [self._us_house_bf()], [self._us_house_pm()]
        )
        self.assertEqual(len(matches), 1)
        bf_ev, pm_ev, score = matches[0]
        self.assertIsInstance(bf_ev, Event)
        self.assertIsInstance(pm_ev, PolymarketEvent)
        self.assertIsInstance(score, float)

    # ── empty inputs ─────────────────────────────────────────────────────────

    def test_empty_bf_list_returns_empty(self):
        self.assertEqual(
            self.matcher.find_politics_matches([], [self._us_house_pm()]), []
        )

    def test_empty_pm_list_returns_empty(self):
        self.assertEqual(
            self.matcher.find_politics_matches([self._us_house_bf()], []), []
        )

    def test_both_empty_returns_empty(self):
        self.assertEqual(self.matcher.find_politics_matches([], []), [])

    # ── threshold ────────────────────────────────────────────────────────────

    def test_below_threshold_pair_not_matched(self):
        """Completely unrelated BF/PM pair should produce zero matches."""
        bf = _bf_event(["Donald Trump", "Joe Biden"], event_id="1.210")
        pm = _pm_event("Will ETH hit $10k in 2026?", ["Yes", "No"], event_id="poly-210")
        matches = self.matcher.find_politics_matches([bf], [pm])
        self.assertEqual(
            len(matches), 0, "Unrelated politics/crypto pair should not match"
        )

    # ── greedy deduplication ─────────────────────────────────────────────────

    def test_single_pm_event_not_matched_to_two_bf_events(self):
        """Two near-identical BF events compete for the same PM event → one wins."""
        bf1 = _bf_event(["Republican Party", "Democratic Party"], event_id="1.220a")
        bf2 = _bf_event(["Republican Party", "Democratic Party"], event_id="1.220b")
        pm = _pm_event(
            "Which party will win the House in 2026?",
            ["Republican", "Democrat"],
            event_id="poly-220",
        )
        matches = self.matcher.find_politics_matches([bf1, bf2], [pm])
        matched_pm_ids = [pm_ev.id for _, pm_ev, _ in matches]
        self.assertEqual(
            matched_pm_ids.count("poly-220"),
            1,
            "PM event poly-220 should appear in exactly one match",
        )

    def test_single_bf_event_not_matched_to_two_pm_events(self):
        """One BF event competing for two identical PM events → one wins."""
        bf = _bf_event(["Republican Party", "Democratic Party"], event_id="1.221")
        pm1 = _pm_event(
            "Which party will win the House in 2026?",
            ["Republican", "Democrat"],
            event_id="poly-221a",
        )
        pm2 = _pm_event(
            "Which party will win the House in 2026?",
            ["Republican", "Democrat"],
            event_id="poly-221b",
        )
        matches = self.matcher.find_politics_matches([bf], [pm1, pm2])
        matched_bf_ids = [bf_ev.id for bf_ev, _, _ in matches]
        self.assertEqual(
            matched_bf_ids.count("1.221"),
            1,
            "BF event 1.221 should appear in exactly one match",
        )

    # ── date agnosticism ─────────────────────────────────────────────────────

    def test_150_day_time_gap_does_not_prevent_match(self):
        """Politics markets 150 days apart must still match (no date filter)."""
        bf = _bf_event(
            ["Republican Party", "Democratic Party"],
            event_id="1.230",
            commence_time=_NOW + timedelta(days=200),
        )
        pm = _pm_event(
            "Which party will win the House in 2026?",
            ["Republican", "Democrat"],
            event_id="poly-230",
            end_date=_NOW + timedelta(days=350),  # 150-day gap from bf commence
        )
        matches = self.matcher.find_politics_matches([bf], [pm])
        self.assertEqual(
            len(matches), 1, "150-day gap should not prevent politics match"
        )

    def test_pm_event_with_no_end_date_can_match(self):
        """PM event without an end_date should still be eligible for matching."""
        bf = _bf_event(["Republican Party", "Democratic Party"], event_id="1.231")
        pm = _pm_event(
            "Which party will win the House in 2026?",
            ["Republican", "Democrat"],
            event_id="poly-231",
            end_date=None,
        )
        # Should not crash and may return a match
        try:
            matches = self.matcher.find_politics_matches([bf], [pm])
        except Exception as exc:
            self.fail(f"None end_date raised: {exc}")
        # At least no exception; whether it matches depends on score
        self.assertIsInstance(matches, list)

    # ── score properties ─────────────────────────────────────────────────────

    def test_all_scores_between_0_and_1(self):
        """Every returned score must be in [0.0, 1.0]."""
        bf_events = [self._us_house_bf("1.240"), self._uk_election_bf("1.241")]
        pm_events = [self._us_house_pm("poly-240"), self._uk_election_pm("poly-241")]
        matches = self.matcher.find_politics_matches(bf_events, pm_events)
        for _, _, score in matches:
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


# ─── 3. Date-filter bypass inside find_matches() ─────────────────────────────


class TestDateFilterBypassInFindMatches(unittest.TestCase):
    """
    find_matches() applies a ±3-day date filter for sports but bypasses it for
    politics events (where elections are months away).
    """

    def setUp(self):
        self.matcher = MarketMatcher()

    def test_politics_category_bypasses_date_filter(self):
        """
        A politics BF event whose PM counterpart is 150 days further ahead
        must NOT be filtered out by the ±3-day window.
        """
        bf = _bf_event(
            ["Republican Party", "Democratic Party"],
            event_id="1.300",
            category="politics",  # ← triggers bypass
            commence_time=_NOW + timedelta(days=200),
        )
        pm = _pm_event(
            "Which party will win the House in 2026?",
            ["Republican", "Democrat"],
            event_id="poly-300",
            sport_category="politics",
            end_date=_NOW + timedelta(days=350),
        )
        matches = self.matcher.find_matches([bf], [pm])
        self.assertGreater(
            len(matches),
            0,
            "Politics event (category='politics') must bypass the ±3-day date filter",
        )

    def test_sports_event_is_filtered_by_date(self):
        """
        A sports BF event whose PM counterpart is 10 days away must be blocked
        by the ±3-day date filter.
        """
        bf = Event(
            id="1.301",
            sport="Soccer",
            commence_time=_NOW,
            home_team="Manchester City",
            away_team="Arsenal",
            outcomes=[
                _outcome("Manchester City", 2.0),
                _outcome("Draw", 3.5),
                _outcome("Arsenal", 4.0),
            ],
            category="soccer",  # ← sports → date filter applies
        )
        pm = _pm_event(
            "Will Manchester City beat Arsenal?",
            ["Yes", "No"],
            event_id="poly-301",
            sport_category="soccer",
            end_date=_NOW + timedelta(days=10),  # well outside ±3-day window
        )
        matches = self.matcher.find_matches([bf], [pm])
        self.assertEqual(
            len(matches),
            0,
            "Sports event 10 days apart must be blocked by the ±3-day date filter",
        )


# ─── 4. Config / BetfairClient constants ─────────────────────────────────────


class TestPoliticsConstants(unittest.TestCase):
    """Sanity-check that Config and BetfairClient have the expected politics values."""

    def test_politics_key_in_shared_sports(self):
        self.assertIn("Politics", Config.SHARED_SPORTS)

    def test_politics_hint_value(self):
        self.assertEqual(Config.SHARED_SPORTS["Politics"], "politics")

    def test_all_hints_are_non_empty_strings(self):
        for label, hint in Config.SHARED_SPORTS.items():
            self.assertIsInstance(hint, str, f"SHARED_SPORTS['{label}'] must be a str")
            self.assertTrue(hint, f"SHARED_SPORTS['{label}'] must be non-empty")

    def test_betfair_politics_event_type_id(self):
        self.assertEqual(BetfairClient.POLITICS_EVENT_TYPE_ID, "2378961")

    def test_betfair_to_polymarket_contains_politics(self):
        self.assertIn("2378961", BetfairClient.BETFAIR_TO_POLYMARKET)
        self.assertEqual(BetfairClient.BETFAIR_TO_POLYMARKET["2378961"], "politics")

    def test_betfair_sport_names_contains_politics(self):
        self.assertIn("2378961", BetfairClient.BETFAIR_SPORT_NAMES)
        self.assertEqual(BetfairClient.BETFAIR_SPORT_NAMES["2378961"], "Politics")

    def test_politics_event_type_id_is_string(self):
        """Betfair API expects event type IDs as strings."""
        self.assertIsInstance(BetfairClient.POLITICS_EVENT_TYPE_ID, str)


# ─── 5. TEAM_ALIASES political entries ───────────────────────────────────────


class TestPoliticsAliases(unittest.TestCase):
    """Verify political party / candidate aliases exist in TEAM_ALIASES."""

    # US parties
    def test_republican_party_has_gop_alias(self):
        self.assertIn("republican party", TEAM_ALIASES)
        self.assertIn("gop", TEAM_ALIASES["republican party"])

    def test_republican_party_has_republican_alias(self):
        self.assertIn("republican", TEAM_ALIASES["republican party"])

    def test_democratic_party_has_democrat_alias(self):
        self.assertIn("democratic party", TEAM_ALIASES)
        self.assertIn("democrat", TEAM_ALIASES["democratic party"])

    def test_democratic_party_has_dem_alias(self):
        self.assertIn("dem", TEAM_ALIASES["democratic party"])

    # UK parties
    def test_labour_party_alias(self):
        self.assertIn("labour party", TEAM_ALIASES)
        self.assertIn("labour", TEAM_ALIASES["labour party"])

    def test_conservative_party_has_tory_alias(self):
        self.assertIn("conservative party", TEAM_ALIASES)
        self.assertIn("tory", TEAM_ALIASES["conservative party"])

    def test_liberal_democrats_has_lib_dems_alias(self):
        self.assertIn("liberal democrats", TEAM_ALIASES)
        self.assertIn("lib dems", TEAM_ALIASES["liberal democrats"])

    def test_reform_uk_alias(self):
        self.assertIn("reform uk", TEAM_ALIASES)
        self.assertIn("reform", TEAM_ALIASES["reform uk"])

    def test_snp_alias(self):
        self.assertIn("snp", TEAM_ALIASES)

    # Structural
    def test_all_alias_values_are_lists_of_strings(self):
        """Every alias entry must be a list of non-empty strings."""
        for key, aliases in TEAM_ALIASES.items():
            self.assertIsInstance(
                aliases, list, f"TEAM_ALIASES['{key}'] must be a list"
            )
            for alias in aliases:
                self.assertIsInstance(
                    alias, str, f"Alias '{alias}' under '{key}' must be a str"
                )
                self.assertTrue(alias, f"Alias under '{key}' must be non-empty")


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
