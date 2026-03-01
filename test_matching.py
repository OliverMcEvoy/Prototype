"""
test_matching.py — Deep-dive matching analysis script.

Fetches live Betfair + Polymarket data, runs the matching algorithm, and
produces a detailed report showing:
  • Overall match rate by sport
  • Near-misses: BF events that almost matched but fell just below threshold
  • False positives: low-confidence matches that are likely wrong
  • Token analysis: why specific events fail to match
  • Suggestions for new aliases to add

Usage (from project root with venv active):
    python test_matching.py [--sport soccer] [--threshold 0.35] [--near-miss 0.25]
    python test_matching.py --sport all --output report.txt
"""

import argparse
import sys
import os
import re
import unicodedata
from datetime import datetime, timezone
from collections import defaultdict, Counter
from typing import List, Tuple, Optional

sys.path.insert(0, os.path.dirname(__file__))

from config import Config
from betfair_client import BetfairClient
from polymarket_client import PolymarketClient
from market_matcher import (
    MarketMatcher,
    _canonicalise,
    TEAM_ALIASES,
    _GENERIC_NAME_TOKENS,
)
from models import Event, PolymarketEvent


# ── helpers ─────────────────────────────────────────────────────────────────


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii")
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _distinctive_tokens(name: str) -> List[str]:
    """Return tokens of a name that are not generic."""
    tl = _norm(name)
    raw = [t for t in re.split(r"[\s\-/]+", tl) if len(t) > 2]
    return [t for t in raw if t not in _GENERIC_NAME_TOKENS and len(t) > 3]


def _section(title: str, f=None) -> None:
    line = "\n" + "=" * 72 + "\n  " + title + "\n" + "=" * 72
    print(line)
    if f:
        f.write(line + "\n")


def _write(text: str, f=None) -> None:
    print(text)
    if f:
        f.write(text + "\n")


# ── scoring internals (mirrors market_matcher logic) ─────────────────────────


def _score_pair(matcher: MarketMatcher, bf_ev: Event, pm_ev: PolymarketEvent) -> float:
    return matcher._calculate_similarity(bf_ev, pm_ev)


def _why_no_match(bf_ev: Event, pm_ev: PolymarketEvent, matcher: MarketMatcher) -> str:
    """Return a human-readable explanation of why two events did not match."""
    poly_q = pm_ev.question
    poly_match_part = poly_q.split(":", 1)[1].strip() if ":" in poly_q else poly_q
    poly_combined = _norm(
        poly_q + " " + poly_match_part + " " + " ".join(pm_ev.outcomes or [])
    )

    reasons = []

    for label, team_raw in [("home", bf_ev.home_team), ("away", bf_ev.away_team)]:
        team_can = _canonicalise(team_raw)
        tl = team_raw.lower()

        if tl in poly_combined or team_can in poly_combined:
            continue  # full match ok

        aliases = TEAM_ALIASES.get(team_can, [])
        if any(a in poly_combined for a in aliases):
            continue  # alias match ok

        dist = _distinctive_tokens(team_raw)
        if dist:
            missing = [t for t in dist if t not in poly_combined]
            if missing:
                reasons.append(f"{label} '{team_raw}' missing tokens {missing} in poly")
        else:
            reasons.append(
                f"{label} '{team_raw}' has no distinctive tokens; "
                f"canonical='{team_can}' not found in poly"
            )

    if not reasons:
        # Both teams found but score still low
        score = _score_pair(matcher, bf_ev, pm_ev)
        reasons.append(
            f"teams found but score={score:.3f} < threshold (date/text mismatch?)"
        )

    return " | ".join(reasons)


# ── main analysis ────────────────────────────────────────────────────────────


def analyse(
    sport: str,
    threshold: float,
    near_miss_threshold: float,
    top_n_near_miss: int,
    output_path: Optional[str],
) -> None:
    out = open(output_path, "w", encoding="utf-8") if output_path else None

    try:
        # ── fetch data ──────────────────────────────────────────────────────
        _section("FETCHING DATA", out)

        bf_client = BetfairClient(
            Config.BETFAIR_USERNAME, Config.BETFAIR_PASSWORD, Config.BETFAIR_APP_KEY
        )
        _write("Logging in to Betfair...", out)
        if not bf_client.login():
            _write(f"ERROR: {bf_client.get_last_error()}", out)
            return

        sport_hints = None if sport == "all" else [sport]
        bf_events = bf_client.get_odds(
            sport_hints=sport_hints, days_ahead=14, min_hours_ahead=0
        )
        _write(f"Betfair events: {len(bf_events)}", out)

        pm_client = PolymarketClient()
        pm_events = pm_client.get_sports_markets(
            sport_hint=None if sport == "all" else sport,
            active_only=True,
            min_volume=0,
        )
        _write(f"Polymarket events: {len(pm_events)}", out)

        # ── run matching ────────────────────────────────────────────────────
        _section("MATCHING RESULTS", out)
        matcher = MarketMatcher(similarity_threshold=threshold)
        matches = matcher.find_matches(bf_events, pm_events)

        matched_bf_ids = {bf.id for bf, _, _ in matches}
        matched_pm_ids = {pm.id for _, pm, _ in matches}
        unmatched_bf = [e for e in bf_events if e.id not in matched_bf_ids]
        unmatched_pm = [e for e in pm_events if e.id not in matched_pm_ids]

        _write(f"\nMatched pairs   : {len(matches)}", out)
        _write(f"Unmatched BF    : {len(unmatched_bf)}", out)
        _write(f"Unmatched PM    : {len(unmatched_pm)}", out)
        _write(f"BF match rate   : {len(matches)/max(len(bf_events),1)*100:.1f}%", out)
        _write(f"PM match rate   : {len(matches)/max(len(pm_events),1)*100:.1f}%", out)

        # ── matched pairs by sport ──────────────────────────────────────────
        _section("MATCHED PAIRS BY SPORT", out)
        by_sport: dict = defaultdict(list)
        for bf, pm, sc in matches:
            by_sport[bf.category or "?"].append((bf, pm, sc))
        for sport_cat, pairs in sorted(by_sport.items()):
            arb_count = sum(1 for bf, pm, sc in pairs if sc >= 0.8)
            _write(
                f"  {sport_cat:20s}: {len(pairs):3d} matches  ({arb_count} high-confidence ≥0.8)",
                out,
            )

        # ── all matched pairs ───────────────────────────────────────────────
        _section("ALL MATCHED PAIRS (sorted by score desc)", out)
        for bf, pm, sc in sorted(matches, key=lambda x: -x[2]):
            _write(
                f"  {sc:.3f}  BF: {bf.home_team} vs {bf.away_team:35s}"
                f"  [{bf.category}]",
                out,
            )
            _write(f"         PM: {pm.question}", out)

        # ── false positives ─────────────────────────────────────────────────
        _section("POTENTIAL FALSE POSITIVES (score < 0.75)", out)
        _write("  These matches may be wrong \u2014 check manually:", out)
        false_pos = [(bf, pm, sc) for bf, pm, sc in matches if sc < 0.75]
        if not false_pos:
            _write("  None found \u2014 all matches have score \u2265 0.75 \u2705", out)
        for bf, pm, sc in sorted(false_pos, key=lambda x: x[2]):
            _write(f"\n  Score {sc:.3f}", out)
            _write(f"    BF: {bf.home_team} vs {bf.away_team}  ({bf.category})", out)
            _write(f"    PM: {pm.question}", out)
            why = _why_no_match(bf, pm, matcher)
            _write(f"    Why matched (low score): {why}", out)

        # ── near-misses ─────────────────────────────────────────────────────
        _section(
            f"NEAR-MISSES: unmatched BF events with best PM score "
            f"[{near_miss_threshold:.2f} – {threshold:.2f})",
            out,
        )
        _write(
            "  These events ALMOST matched \u2014 add aliases or adjust threshold:", out
        )

        near_misses: List[Tuple[Event, PolymarketEvent, float, str]] = []
        for bf_ev in unmatched_bf:
            bf_time = bf_ev.commence_time
            if bf_time and bf_time.tzinfo is None:
                bf_time = bf_time.replace(tzinfo=timezone.utc)

            best_score = 0.0
            best_pm: Optional[PolymarketEvent] = None
            for pm_ev in pm_events:
                # Relaxed date filter for near-miss analysis
                if bf_time and pm_ev.end_date:
                    pm_t = pm_ev.end_date
                    if pm_t.tzinfo is None:
                        pm_t = pm_t.replace(tzinfo=timezone.utc)
                    if abs((bf_time - pm_t).total_seconds()) > 7 * 86400:
                        continue
                sc = matcher._calculate_similarity(bf_ev, pm_ev)
                if sc > best_score:
                    best_score = sc
                    best_pm = pm_ev

            if near_miss_threshold <= best_score < threshold and best_pm:
                why = _why_no_match(bf_ev, best_pm, matcher)
                near_misses.append((bf_ev, best_pm, best_score, why))

        near_misses.sort(key=lambda x: -x[2])
        if not near_misses:
            _write("  No near-misses found.", out)
        for bf_ev, pm_ev, sc, why in near_misses[:top_n_near_miss]:
            _write(f"\n  Score {sc:.3f}  [{bf_ev.category}]", out)
            _write(f"    BF: {bf_ev.home_team} vs {bf_ev.away_team}", out)
            _write(f"    PM: {pm_ev.question}", out)
            _write(f"    Fix: {why}", out)

        # ── alias suggestions ────────────────────────────────────────────────
        _section("ALIAS SUGGESTIONS", out)
        _write("  BF names whose canonical doesn't appear in any PM event:", out)

        alias_candidates: List[Tuple[str, str, str]] = (
            []
        )  # (bf_name, canonical, suggestion)
        for bf_ev in unmatched_bf[:100]:
            for team_raw in [bf_ev.home_team, bf_ev.away_team]:
                can = _canonicalise(team_raw)
                dist = _distinctive_tokens(team_raw)
                if dist:
                    # Check if PM has an event with similar tokens but slightly different name
                    for pm_ev in pm_events[:500]:
                        pm_norm = _norm(
                            pm_ev.question + " " + " ".join(pm_ev.outcomes or [])
                        )
                        # Partial hit: some tokens match
                        hits = [t for t in dist if t in pm_norm]
                        if 0 < len(hits) < len(dist):
                            pm_words = pm_norm.split()
                            suggestion = " ".join(
                                w for w in pm_words if any(h in w for h in hits)
                            )[:60]
                            alias_candidates.append((team_raw, can, suggestion))
                            break

        seen: set = set()
        for bf_name, can, sug in alias_candidates[:40]:
            key = (bf_name, can)
            if key in seen:
                continue
            seen.add(key)
            _write(f"  ALIAS: '{can}': ['{sug}']  # from BF '{bf_name}'", out)

        # ── unmatched BF events (full list) ──────────────────────────────────
        _section("UNMATCHED BETFAIR EVENTS (full list)", out)
        for ev in sorted(
            unmatched_bf, key=lambda e: (e.category or "", e.commence_time)
        ):
            dt = ev.commence_time.strftime("%d %b %H:%M") if ev.commence_time else "?"
            _write(f"  {dt}  {ev.category:18s}  {ev.home_team} vs {ev.away_team}", out)

        # ── unmatched PM events ───────────────────────────────────────────────
        _section("UNMATCHED POLYMARKET EVENTS (full list)", out)
        for ev in sorted(unmatched_pm, key=lambda e: (e.end_date or datetime.min)):
            dt = ev.end_date.strftime("%d %b %H:%M") if ev.end_date else "No date"
            vol = f"${ev.volume:>9,.0f}"
            cat = getattr(ev, "sport_category", "") or "?"
            _write(f"  {dt}  {cat:15s}  {vol}  {ev.question}", out)

        if output_path:
            _write(f"\n✅  Full report written to {output_path}", out)

    finally:
        if out:
            out.close()


# ── entry point ──────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Matching analysis tool")
    parser.add_argument(
        "--sport",
        default="all",
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
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.35,
        help="Match threshold (default: 0.35 — same as app)",
    )
    parser.add_argument(
        "--near-miss",
        type=float,
        default=0.20,
        help="Near-miss score floor (default: 0.20)",
    )
    parser.add_argument(
        "--top-n", type=int, default=30, help="Max near-misses to show (default: 30)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write report to this file (in addition to stdout)",
    )
    args = parser.parse_args()

    analyse(
        sport=args.sport,
        threshold=args.threshold,
        near_miss_threshold=args.near_miss,
        top_n_near_miss=args.top_n,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
