"""
test_politics_system.py — System / integration tests for the politics feature.

These tests call the REAL Betfair and Polymarket APIs using credentials from
.env and verify that the complete pipeline works end-to-end:

  1. Betfair login succeeds
  2. get_politics_markets() returns markets with the expected structure
  3. Polymarket get_politics_markets() returns markets with the expected structure
  4. find_politics_matches() produces at least 2 cross-platform matches
  5. ArbitrageEngine.compare_markets() runs cleanly on the politics events

⚠️  Requires network access and valid Betfair credentials in .env
    Tests are skipped automatically if credentials are missing.

Usage:
    python -m pytest test_politics_system.py -v
    python -m pytest test_politics_system.py -v -s      # show print output
"""

import sys
import os
import time
import unittest
from datetime import datetime, timezone, timedelta
from typing import List

sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from betfair_client import BetfairClient
from polymarket_client import PolymarketClient
from market_matcher import MarketMatcher
from arbitrage_engine import ArbitrageEngine
from models import Event, PolymarketEvent, Outcome, ArbitrageOpportunity

# ---------------------------------------------------------------------------
# Skip condition — no point running if creds are missing
# ---------------------------------------------------------------------------

_HAVE_CREDS = bool(
    Config.BETFAIR_USERNAME and Config.BETFAIR_PASSWORD and Config.BETFAIR_APP_KEY
)
_SKIP_REASON = (
    "Betfair credentials not set — add BETFAIR_USERNAME, BETFAIR_PASSWORD, "
    "BETFAIR_APP_KEY to .env to run system tests"
)


def _bf_client() -> BetfairClient:
    return BetfairClient(
        Config.BETFAIR_USERNAME, Config.BETFAIR_PASSWORD, Config.BETFAIR_APP_KEY
    )


# ---------------------------------------------------------------------------
# 1. Betfair politics API
# ---------------------------------------------------------------------------


@unittest.skipUnless(_HAVE_CREDS, _SKIP_REASON)
class TestBetfairPoliticsAPI(unittest.TestCase):
    """Live call to Betfair get_politics_markets()."""

    @classmethod
    def setUpClass(cls):
        cls.client = _bf_client()
        ok = cls.client.login()
        if not ok:
            raise unittest.SkipTest(
                f"Betfair login failed: {cls.client.get_last_error()}"
            )
        print(f"\n[SYSTEM] Betfair login OK")
        cls.markets = cls.client.get_politics_markets(days_ahead=400)
        print(f"[SYSTEM] Betfair politics markets returned: {len(cls.markets)}")

    # ── count ────────────────────────────────────────────────────────────────

    def test_returns_at_least_one_market(self):
        """Betfair event type 2378961 must have at least one open market."""
        self.assertGreater(
            len(self.markets),
            0,
            "No Betfair political markets returned — check event type ID 2378961 "
            "is accessible on your account (browse betfair.com/exchange/plus/politics)",
        )

    # ── data types ───────────────────────────────────────────────────────────

    def test_all_items_are_event_objects(self):
        for m in self.markets:
            self.assertIsInstance(m, Event, f"Expected Event, got {type(m)}")

    def test_all_events_have_politics_category(self):
        for m in self.markets:
            self.assertEqual(
                m.category,
                "politics",
                f"Market {m.id} has category='{m.category}', expected 'politics'",
            )

    def test_all_events_have_string_id(self):
        for m in self.markets:
            self.assertIsInstance(m.id, str)
            self.assertTrue(m.id, f"Event id must be non-empty")

    def test_all_events_have_home_team(self):
        for m in self.markets:
            self.assertIsInstance(m.home_team, str)
            self.assertTrue(m.home_team, f"home_team must be non-empty for {m.id}")

    def test_all_events_have_at_least_two_outcomes(self):
        """
        Every politics market must have back/lay prices for at least 2 runners
        (required for any arbitrage to be possible).
        """
        for m in self.markets:
            self.assertGreaterEqual(
                len(m.outcomes),
                2,
                f"Market {m.id} ({m.home_team}) has only {len(m.outcomes)} outcomes",
            )

    def test_all_outcomes_have_positive_prices(self):
        for m in self.markets:
            for o in m.outcomes:
                self.assertGreater(
                    o.price,
                    1.0,
                    f"Outcome '{o.name}' in {m.id} has price {o.price} ≤ 1.0 "
                    "(invalid decimal odds)",
                )

    def test_outcomes_have_betfair_bookmakers(self):
        """Outcomes should be labelled 'Betfair Exchange' or 'Betfair Lay'."""
        valid = {"Betfair Exchange", "Betfair Lay"}
        for m in self.markets:
            for o in m.outcomes:
                self.assertIn(
                    o.bookmaker,
                    valid,
                    f"Unexpected bookmaker '{o.bookmaker}' in market {m.id}",
                )

    def test_commence_times_are_datetimes(self):
        """
        Betfair 'NONSPORT' politics markets use their creation date as
        commence_time, which can be years in the past for long-running markets
        (e.g. an outright leadership market opened in 2023 for an election in
        2025).  Just verify the field is a valid datetime with timezone info.
        """
        for m in self.markets:
            self.assertIsInstance(
                m.commence_time,
                datetime,
                f"Market {m.id} commence_time is not a datetime",
            )
            self.assertIsNotNone(
                m.commence_time.tzinfo,
                f"Market {m.id} commence_time has no timezone info",
            )

    def test_unique_market_ids(self):
        ids = [m.id for m in self.markets]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate market IDs returned")

    # ── sample output ────────────────────────────────────────────────────────

    def test_print_sample(self):
        """Not a real assertion — prints first 5 markets for manual inspection."""
        print(f"\n{'─'*60}")
        print(f"  Sample Betfair political markets (first 5):")
        print(f"{'─'*60}")
        for m in self.markets[:5]:
            runners = [o.name for o in m.outcomes if o.bookmaker == "Betfair Exchange"]
            print(f"  [{m.id}] {m.home_team} | runners: {runners[:4]}")
        self.assertTrue(True)  # always passes


# ---------------------------------------------------------------------------
# 2. Polymarket politics API
# ---------------------------------------------------------------------------


class TestPolymarketPoliticsAPI(unittest.TestCase):
    """Live call to Polymarket get_politics_markets() — no credentials needed."""

    @classmethod
    def setUpClass(cls):
        cls.client = PolymarketClient()
        cls.markets = cls.client.get_politics_markets(active_only=True, min_volume=0)
        print(f"\n[SYSTEM] Polymarket politics markets returned: {len(cls.markets)}")

    # ── count ────────────────────────────────────────────────────────────────

    def test_returns_at_least_one_market(self):
        """Polymarket must have at least one active political market."""
        self.assertGreater(
            len(self.markets),
            0,
            "No Polymarket political markets returned — the API endpoint or "
            "tag slugs may have changed",
        )

    # ── data types ───────────────────────────────────────────────────────────

    def test_all_items_are_polymarket_event_objects(self):
        for m in self.markets:
            self.assertIsInstance(
                m, PolymarketEvent, f"Expected PolymarketEvent, got {type(m)}"
            )

    def test_all_events_have_politics_sport_category(self):
        for m in self.markets:
            self.assertEqual(
                m.sport_category,
                "politics",
                f"Market {m.id} has sport_category='{m.sport_category}'",
            )

    def test_all_events_have_non_empty_question(self):
        for m in self.markets:
            self.assertIsInstance(m.question, str)
            self.assertTrue(m.question.strip(), f"Empty question for market {m.id}")

    def test_all_events_have_at_least_one_outcome(self):
        for m in self.markets:
            self.assertGreaterEqual(
                len(m.outcomes),
                1,
                f"Market {m.id} ('{m.question[:60]}') has no outcomes",
            )

    def test_outcomes_and_prices_same_length(self):
        for m in self.markets:
            self.assertEqual(
                len(m.outcomes),
                len(m.prices),
                f"Market {m.id}: {len(m.outcomes)} outcomes but {len(m.prices)} prices",
            )

    def test_prices_are_valid_probabilities(self):
        for m in self.markets:
            for p in m.prices:
                self.assertGreaterEqual(p, 0.0, f"Negative price in {m.id}")
                self.assertLessEqual(p, 1.0, f"Price > 1.0 in {m.id}")

    def test_volume_is_non_negative(self):
        for m in self.markets:
            self.assertGreaterEqual(m.volume, 0.0, f"Negative volume in {m.id}")

    def test_unique_market_ids(self):
        ids = [m.id for m in self.markets]
        self.assertEqual(
            len(ids), len(set(ids)), "Duplicate market IDs from Polymarket"
        )

    def test_to_decimal_odds_does_not_crash(self):
        """to_decimal_odds() must work for every returned market."""
        for m in self.markets:
            try:
                odds = m.to_decimal_odds()
            except Exception as exc:
                self.fail(f"to_decimal_odds() raised for {m.id}: {exc}")
            self.assertEqual(len(odds), len(m.prices))

    # ── sample output ────────────────────────────────────────────────────────

    def test_print_sample(self):
        print(f"\n{'─'*60}")
        print(f"  Sample Polymarket political markets (first 5):")
        print(f"{'─'*60}")
        for m in self.markets[:5]:
            print(
                f"  [{m.id[:12]}] {m.question[:55]!r:57s} "
                f"vol=${m.volume:>10,.0f}  outcomes={m.outcomes}"
            )
        self.assertTrue(True)


# ---------------------------------------------------------------------------
# 3. End-to-end matching
# ---------------------------------------------------------------------------


@unittest.skipUnless(_HAVE_CREDS, _SKIP_REASON)
class TestPoliticsMatchingEndToEnd(unittest.TestCase):
    """
    Full pipeline test: Betfair → Polymarket → find_politics_matches()

    Requires both APIs to return data and expects at least 2 matched pairs.
    """

    @classmethod
    def setUpClass(cls):
        # ── Betfair ──────────────────────────────────────────────────────────
        cls.bf_client = _bf_client()
        ok = cls.bf_client.login()
        if not ok:
            raise unittest.SkipTest(
                f"Betfair login failed: {cls.bf_client.get_last_error()}"
            )

        cls.bf_markets = cls.bf_client.get_politics_markets(days_ahead=400)
        print(f"\n[SYSTEM] Betfair politics: {len(cls.bf_markets)} markets")

        if not cls.bf_markets:
            raise unittest.SkipTest(
                "Betfair returned 0 political markets — cannot run matching test. "
                "Verify event type 2378961 is accessible on your account."
            )

        # ── Polymarket ───────────────────────────────────────────────────────
        cls.pm_client = PolymarketClient()
        cls.pm_markets = cls.pm_client.get_politics_markets(
            active_only=True, min_volume=0
        )
        print(f"[SYSTEM] Polymarket politics: {len(cls.pm_markets)} markets")

        if not cls.pm_markets:
            raise unittest.SkipTest(
                "Polymarket returned 0 political markets — cannot run matching test."
            )

        # ── Matching ─────────────────────────────────────────────────────────
        cls.matcher = MarketMatcher()
        cls.matches = cls.matcher.find_politics_matches(cls.bf_markets, cls.pm_markets)
        print(f"[SYSTEM] Matched pairs: {len(cls.matches)}")

        # ── Arbitrage engine ─────────────────────────────────────────────────
        cls.engine = ArbitrageEngine(min_profit_threshold=0.0)
        cls.opportunities = cls.engine.compare_markets(cls.bf_markets, cls.pm_markets)
        print(f"[SYSTEM] Arbitrage opportunities: {len(cls.opportunities)}")

    # ── match count ──────────────────────────────────────────────────────────

    def test_at_least_two_matches_found(self):
        """
        The core requirement: cross-platform matching must find ≥ 2 political
        event pairs across Betfair and Polymarket.
        """
        self.assertGreaterEqual(
            len(self.matches),
            2,
            f"Expected ≥ 2 politics matches but only got {len(self.matches)}.\n"
            f"  Betfair markets  : {len(self.bf_markets)}\n"
            f"  Polymarket markets: {len(self.pm_markets)}\n"
            f"Matches found: "
            + "\n".join(
                f"  {score:.3f}  BF={bf.home_team}  PM={pm.question[:60]}"
                for bf, pm, score in self.matches
            ),
        )

    # ── result structure ──────────────────────────────────────────────────────

    def test_each_match_is_a_three_tuple(self):
        for item in self.matches:
            self.assertEqual(len(item), 3)
            bf_ev, pm_ev, score = item
            self.assertIsInstance(bf_ev, Event)
            self.assertIsInstance(pm_ev, PolymarketEvent)
            self.assertIsInstance(score, float)

    def test_scores_within_valid_range(self):
        for bf_ev, pm_ev, score in self.matches:
            self.assertGreaterEqual(score, 0.0, f"Score below 0 for {bf_ev.id}")
            self.assertLessEqual(score, 1.0, f"Score above 1 for {bf_ev.id}")

    def test_scores_meet_politics_threshold(self):
        """All returned matches must meet the 0.30 politics threshold."""
        THRESHOLD = 0.30
        for bf_ev, pm_ev, score in self.matches:
            self.assertGreaterEqual(
                score,
                THRESHOLD,
                f"Match ({bf_ev.id}, {pm_ev.id}) has score {score:.3f} < {THRESHOLD}",
            )

    # ── deduplication ────────────────────────────────────────────────────────

    def test_no_betfair_event_matched_twice(self):
        bf_ids = [bf.id for bf, _, _ in self.matches]
        self.assertEqual(
            len(bf_ids),
            len(set(bf_ids)),
            "Same Betfair event appeared in more than one match (dedup failed)",
        )

    def test_no_polymarket_event_matched_twice(self):
        pm_ids = [pm.id for _, pm, _ in self.matches]
        self.assertEqual(
            len(pm_ids),
            len(set(pm_ids)),
            "Same Polymarket event appeared in more than one match (dedup failed)",
        )

    # ── category integrity ────────────────────────────────────────────────────

    def test_matched_bf_events_have_politics_category(self):
        for bf_ev, _, _ in self.matches:
            self.assertEqual(
                bf_ev.category,
                "politics",
                f"Matched BF event {bf_ev.id} has category='{bf_ev.category}'",
            )

    def test_matched_pm_events_have_politics_category(self):
        for _, pm_ev, _ in self.matches:
            self.assertEqual(
                pm_ev.sport_category,
                "politics",
                f"Matched PM event {pm_ev.id} has sport_category='{pm_ev.sport_category}'",
            )

    # ── arbitrage engine ──────────────────────────────────────────────────────

    def test_compare_markets_does_not_crash(self):
        """ArbitrageEngine.compare_markets() must complete without raising."""
        try:
            opps = self.engine.compare_markets(self.bf_markets, self.pm_markets)
        except Exception as exc:
            self.fail(f"compare_markets() raised: {exc}")
        self.assertIsInstance(opps, list)

    def test_all_opportunities_are_arbitrage_opportunity_objects(self):
        for opp in self.opportunities:
            self.assertIsInstance(opp, ArbitrageOpportunity)

    def test_all_opportunity_profits_are_numeric(self):
        for opp in self.opportunities:
            self.assertIsInstance(opp.profit_percentage, float)
            self.assertGreaterEqual(
                opp.profit_percentage, self.engine.min_profit_threshold
            )

    # ── detailed output ───────────────────────────────────────────────────────

    def test_print_all_matches(self):
        """Not a real assertion — pretty-prints every match for manual review."""
        print(f"\n{'═'*70}")
        print(f"  POLITICS MATCHED PAIRS  ({len(self.matches)} total)")
        print(f"{'═'*70}")
        for rank, (bf_ev, pm_ev, score) in enumerate(
            sorted(self.matches, key=lambda x: -x[2]), start=1
        ):
            runners = [
                o.name for o in bf_ev.outcomes if o.bookmaker == "Betfair Exchange"
            ]
            print(f"\n  #{rank}  Score: {score:.3f}")
            print(f"  BF : {bf_ev.home_team}  [{bf_ev.id}]")
            print(f"       Runners: {runners[:6]}")
            print(f"  PM : {pm_ev.question[:70]}")
            print(f"       Outcomes: {pm_ev.outcomes[:6]}")
            print(
                f"       Volume: ${pm_ev.volume:,.0f}  |  Liquidity: ${pm_ev.liquidity:,.0f}"
            )

        if self.opportunities:
            print(f"\n{'─'*70}")
            print(f"  ARBITRAGE OPPORTUNITIES  ({len(self.opportunities)} found)")
            print(f"{'─'*70}")
            for opp in self.opportunities[:5]:
                print(
                    f"  {opp.profit_percentage:.2f}%  {opp.event.description or opp.event.id}"
                )
        else:
            print(f"\n  No arbitrage opportunities at current odds.")

        self.assertTrue(True)


# ---------------------------------------------------------------------------
# 4. Data-pipeline regression: what goes in must be usable
# ---------------------------------------------------------------------------


@unittest.skipUnless(_HAVE_CREDS, _SKIP_REASON)
class TestPoliticsDataPipelineRegression(unittest.TestCase):
    """
    Regression tests that ensure the data returned by the two APIs can
    actually flow through the downstream code (display helpers, odds
    conversion, etc.) without crashing.
    """

    @classmethod
    def setUpClass(cls):
        bf = _bf_client()
        if not bf.login():
            raise unittest.SkipTest(f"Betfair login failed: {bf.get_last_error()}")
        cls.bf_markets = bf.get_politics_markets(days_ahead=400)
        cls.pm_markets = PolymarketClient().get_politics_markets(
            active_only=True, min_volume=0
        )

    def test_bf_event_repr_does_not_crash(self):
        for m in self.bf_markets:
            try:
                _ = repr(m)
            except Exception as exc:
                self.fail(f"repr(Event) raised for {m.id}: {exc}")

    def test_pm_event_to_decimal_odds_non_zero_prices(self):
        """to_decimal_odds() must return finite positive floats for non-zero prices."""
        import math

        for m in self.pm_markets:
            odds = m.to_decimal_odds()
            for i, (p, o) in enumerate(zip(m.prices, odds)):
                if p > 0:
                    self.assertGreater(
                        o, 1.0, f"{m.id} outcome {i}: price {p} → odds {o}"
                    )
                    self.assertFalse(
                        math.isinf(o), f"{m.id} outcome {i}: infinite odds"
                    )

    def test_bf_market_ids_are_valid_betfair_format(self):
        """Betfair market IDs should look like '1.XXXXXXXXX'."""
        import re

        pattern = re.compile(r"^\d+\.\d+$")
        for m in self.bf_markets:
            self.assertRegex(
                m.id,
                pattern,
                f"Market ID '{m.id}' doesn't match Betfair format '1.XXXXXXXXX'",
            )

    def test_bf_runner_names_are_non_empty_strings(self):
        for m in self.bf_markets:
            for o in m.outcomes:
                self.assertIsInstance(o.name, str)
                self.assertTrue(o.name.strip(), f"Empty runner name in market {m.id}")

    def test_pm_question_is_a_question(self):
        """
        A well-formed Polymarket political question should contain at least
        one of: 'will', 'who', 'which', 'what', 'how many', '?' — or just
        have a non-trivial length.  This guards against empty/malformed data.
        """
        for m in self.pm_markets:
            self.assertGreater(
                len(m.question),
                5,
                f"Suspiciously short question '{m.question}' for market {m.id}",
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
