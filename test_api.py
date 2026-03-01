"""
test_api.py — Standalone API diagnostic script.

Calls Betfair and Polymarket directly, dumps raw JSON structure so you can
see exactly what fields are returned and diagnose matching problems.

Usage (from project root with venv active):
    python test_api.py [--sport soccer|basketball|cricket|all] [--limit 5]
"""

import argparse
import json
import sys
import os
from datetime import datetime, timezone
from typing import Any

# ── allow running from project root without installing the package ──────────
sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from betfair_client import BetfairClient
from polymarket_client import PolymarketClient

# ── pretty-print helpers ────────────────────────────────────────────────────


def _pp(obj: Any, indent: int = 2) -> str:
    return json.dumps(obj, indent=indent, default=str, ensure_ascii=False)


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def sub(title: str) -> None:
    print(f"\n--- {title} ---")


# ── Betfair diagnostics ─────────────────────────────────────────────────────


def test_betfair(sport: str, limit: int) -> None:
    section("BETFAIR EXCHANGE API")

    client = BetfairClient(
        Config.BETFAIR_USERNAME, Config.BETFAIR_PASSWORD, Config.BETFAIR_APP_KEY
    )

    sub("Authentication")
    ok = client.login()
    if not ok:
        print(f"  ❌  Login failed: {client.get_last_error()}")
        return
    print("  ✅  Login successful")

    # Map sport name → hint
    sport_hints = None if sport == "all" else [sport]
    sub(f"Raw events (sport={sport}, limit={limit})")

    events = client.get_odds(sport_hints=sport_hints, days_ahead=7, min_hours_ahead=0)
    print(f"  Total events returned: {len(events)}")

    for ev in events[:limit]:
        print(f"\n  Event: {ev.home_team} vs {ev.away_team}")
        print(f"    id           : {ev.id}")
        print(f"    sport        : {ev.sport}")
        print(f"    category     : {ev.category}")
        print(f"    commence_time: {ev.commence_time}")
        print(f"    outcomes ({len(ev.outcomes)}):")
        for o in ev.outcomes[:6]:
            print(f"      [{o.bookmaker:18s}] {o.name:30s}  @ {o.price:.3f}")

    # Show sport distribution
    sub("Sport category breakdown (all events)")
    from collections import Counter

    sport_counts = Counter(ev.category for ev in events)
    for cat, cnt in sorted(sport_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:25s}: {cnt}")


# ── Polymarket diagnostics ──────────────────────────────────────────────────


def test_polymarket(sport: str, limit: int) -> None:
    section("POLYMARKET SPORTS API")

    client = PolymarketClient()

    sub("/sports series list")
    series = client._get_sports_series()
    if not series:
        print("  ❌  Could not fetch /sports")
        return

    print(f"  Total series: {len(series)}")

    # Show TBD or invalid entries
    bad = [
        s
        for s in series
        if not s.get("series") or str(s.get("series", "")).upper() == "TBD"
    ]
    print(f"  Entries with missing/TBD series_id: {len(bad)}")
    for b in bad[:5]:
        print(f"    {b}")

    # Show sport code distribution
    from collections import Counter

    code_dist = Counter(s.get("sport", "?") for s in series)
    sub("Top sport codes in /sports")
    for code, cnt in code_dist.most_common(20):
        category = client._code_to_category(code)
        print(f"  {code:15s}  [{category:18s}]  {cnt} series")

    sub(f"Fetching sports markets (hint={sport}, limit={limit} shown)")
    sport_hint = None if sport == "all" else sport
    events = client.get_sports_markets(
        sport_hint=sport_hint, active_only=True, min_volume=0
    )
    print(f"  Total events: {len(events)}")

    # Volume distribution
    zero_vol = sum(1 for e in events if e.volume == 0)
    low_vol = sum(1 for e in events if 0 < e.volume < 1000)
    med_vol = sum(1 for e in events if 1000 <= e.volume < 10000)
    high_vol = sum(1 for e in events if e.volume >= 10000)
    print(f"\n  Volume distribution:")
    print(
        f"    $0          : {zero_vol:5d} events  ← previously excluded by volume filter!"
    )
    print(f"    $1 – $999   : {low_vol:5d} events  ← previously excluded")
    print(f"    $1k – $10k  : {med_vol:5d} events")
    print(f"    $10k+       : {high_vol:5d} events")

    # Sport category distribution
    from collections import Counter

    cat_dist = Counter(getattr(e, "sport_category", "") or "unknown" for e in events)
    sub("Events by sport_category")
    for cat, cnt in sorted(cat_dist.items(), key=lambda x: -x[1]):
        print(f"  {cat:20s}: {cnt}")

    # No-date events
    no_date = [e for e in events if e.end_date is None]
    print(f"\n  Events with no end_date: {len(no_date)} (pass date filter)")

    sub(f"Sample events (first {limit})")
    for ev in events[:limit]:
        print(f"\n  Question    : {ev.question}")
        print(f"  id          : {ev.id}")
        print(f"  sport_cat   : {getattr(ev, 'sport_category', 'N/A')}")
        print(f"  end_date    : {ev.end_date}")
        print(f"  volume      : ${ev.volume:,.0f}")
        print(f"  outcomes    : {ev.outcomes}")
        print(f"  prices      : {[f'{p:.3f}' for p in ev.prices]}")
        dec_odds = ev.to_decimal_odds()
        print(f"  decimal odds: {[f'{o:.2f}' for o in dec_odds]}")


# ── Cross-platform date alignment check ─────────────────────────────────────


def test_date_alignment(sport: str) -> None:
    section("DATE ALIGNMENT CHECK (Betfair commence_time vs Polymarket end_date)")

    bf_client = BetfairClient(
        Config.BETFAIR_USERNAME, Config.BETFAIR_PASSWORD, Config.BETFAIR_APP_KEY
    )
    if not bf_client.login():
        print(f"  ❌  Betfair login failed")
        return

    pm_client = PolymarketClient()

    sport_hints = None if sport == "all" else [sport]
    bf_events = bf_client.get_odds(
        sport_hints=sport_hints, days_ahead=7, min_hours_ahead=0
    )
    pm_events = pm_client.get_sports_markets(
        sport_hint=None if sport == "all" else sport, min_volume=0
    )

    print(f"\n  BF events : {len(bf_events)}")
    print(f"  PM events : {len(pm_events)}")

    now = datetime.now(timezone.utc)

    # Histogram of date differences between BF and PM events that might match
    # (Sample: first 200 BF × first 200 PM to keep it fast)
    diffs = []
    for bf in bf_events[:200]:
        bf_t = bf.commence_time
        if bf_t.tzinfo is None:
            bf_t = bf_t.replace(tzinfo=timezone.utc)
        for pm in pm_events[:200]:
            if pm.end_date is None:
                continue
            pm_t = pm.end_date
            if pm_t.tzinfo is None:
                pm_t = pm_t.replace(tzinfo=timezone.utc)
            diff_h = abs((bf_t - pm_t).total_seconds()) / 3600
            diffs.append(diff_h)

    if diffs:
        diffs.sort()
        n = len(diffs)
        buckets = [(0, 6), (6, 24), (24, 72), (72, 168), (168, 999999)]
        print("\n  Pairwise |BF_time − PM_end_date| distribution (200×200 sample):")
        for lo, hi in buckets:
            cnt = sum(1 for d in diffs if lo <= d < hi)
            label = f"< {hi}h" if hi < 999999 else f"\u2265 {lo}h"
            pct = cnt / n * 100
            print(f"    {label:15s}: {cnt:6d}  ({pct:.1f}%)")


# ── Entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="API diagnostic tool")
    parser.add_argument(
        "--sport",
        default="soccer",
        choices=[
            "all",
            "soccer",
            "basketball",
            "tennis",
            "cricket",
            "icehockey",
            "americanfootball",
            "baseball",
            "rugby",
            "mma",
        ],
        help="Sport to test (default: soccer)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of sample events to show (default: 5)",
    )
    parser.add_argument(
        "--betfair-only", action="store_true", help="Only run Betfair tests"
    )
    parser.add_argument(
        "--polymarket-only", action="store_true", help="Only run Polymarket tests"
    )
    parser.add_argument("--dates", action="store_true", help="Run date alignment check")
    args = parser.parse_args()

    run_bf = not args.polymarket_only
    run_pm = not args.betfair_only

    if run_bf:
        test_betfair(args.sport, args.limit)
    if run_pm:
        test_polymarket(args.sport, args.limit)
    if args.dates:
        test_date_alignment(args.sport)


if __name__ == "__main__":
    main()
