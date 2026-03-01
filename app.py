"""
Streamlit dashboard for Betfair × Polymarket cross-platform arbitrage.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from typing import List
import time

from config import Config
from betfair_client import BetfairClient
from polymarket_client import PolymarketClient
from arbitrage_engine import ArbitrageEngine
from models import ArbitrageOpportunity
from utils import decimal_to_fractional, decimal_to_american

# Polymarket sport-code slug prefix → URL league path
_PM_SLUG_TO_PATH = {
    # Soccer
    "epl": "premier-league",
    "bun": "bundesliga",
    "lal": "la-liga",
    "ucl": "champions-league",
    "uel": "europa-league",
    "efl": "championship",
    "fl1": "ligue-1",
    "sea": "serie-a",
    "itc": "serie-a",
    "mls": "mls",
    "arg": "liga-profesional",
    "bra": "brasileirao",
    "ere": "eredivisie",
    "tur": "super-lig",
    "por": "primeira-liga",
    "mex": "liga-mx",
    "jap": "j-league",
    "kor": "k-league",
    "col": "colombia-primera-a",
    "uwcl": "womens-champions-league",
    # Basketball
    "nba": "nba",
    "wnba": "wnba",
    "ncaab": "ncaa-basketball",
    "cbb": "ncaa-basketball",
    "euroleague": "euroleague",
    # American football
    "nfl": "nfl",
    "cfb": "college-football",
    # Baseball
    "mlb": "mlb",
    "kbo": "kbo",
    # Tennis
    "atp": "atp",
    "wta": "wta",
    # Ice hockey
    "nhl": "nhl",
    "shl": "shl",
    "khl": "khl",
    # MMA
    "ufc": "ufc",
    # Rugby
    "ruprem": "premiership-rugby",
    "ruurc": "united-rugby-championship",
    "rueuchamp": "european-rugby-champions-cup",
    # Cricket
    "cricipl": "ipl",
    "crint": "cricket",
    "t20": "cricket",
    "odi": "cricket",
}

# Betfair sport category → exchange URL sport path
_BF_SPORT_PATH = {
    "soccer": "football",
    "tennis": "tennis",
    "cricket": "cricket",
    "rugby": "rugby-union",
    "basketball": "basketball",
    "americanfootball": "american-football",
    "baseball": "baseball",
    "icehockey": "ice-hockey",
    "mma": "mixed-martial-arts",
}


def _polymarket_url(slug: str) -> str:
    """Construct a direct Polymarket event URL from the event slug."""
    if not slug:
        return ""
    prefix = slug.split("-")[0].lower()
    path = _PM_SLUG_TO_PATH.get(prefix, "")
    if path:
        return f"https://polymarket.com/sports/{path}/{slug}"
    return f"https://polymarket.com/event/{slug}"


def _betfair_url(market_id: str, category: str) -> str:
    """Construct a direct Betfair Exchange market URL."""
    # Strip suffixes added by the arbitrage engine (_combined, _lay_TeamName)
    base_id = market_id.split("_combined")[0].split("_lay_")[0]
    if not base_id:
        return ""
    sport_path = _BF_SPORT_PATH.get(category or "", "")
    if sport_path:
        return f"https://www.betfair.com/exchange/plus/{sport_path}/market/{base_id}"
    return f"https://www.betfair.com/exchange/plus/market/{base_id}"


# Helper to extract searchable team keywords
def extract_team_keywords(team_name: str) -> List[str]:
    """Extract core keywords from team name for flexible searching."""
    # Remove common prefixes
    prefixes = ["fc", "afc", "bsc", "us", "ac", "as", "real", "club", "cd", "cf"]
    name_lower = team_name.lower()
    words = name_lower.split()

    # Filter out prefixes and short words
    keywords = [w for w in words if w not in prefixes and len(w) > 2]

    # Also return full name without prefixes
    clean_name = " ".join(keywords)

    return keywords + [clean_name] if keywords else [team_name.lower()]


# Page configuration
st.set_page_config(
    page_title="Betfair × Polymarket Arbitrage",
    layout="wide",
    initial_sidebar_state="expanded",
)


def init_session_state():
    """Initialize session state variables."""
    if "last_update" not in st.session_state:
        st.session_state.last_update = None
    if "opportunities" not in st.session_state:
        st.session_state.opportunities = []
    if "polymarket_opportunities" not in st.session_state:
        st.session_state.polymarket_opportunities = []
    if "cross_platform_opportunities" not in st.session_state:
        st.session_state.cross_platform_opportunities = []
    if "matched_pairs" not in st.session_state:
        st.session_state.matched_pairs = []
    if "active_tab" not in st.session_state:
        st.session_state.active_tab = "betfair"
    if "cand_matches" not in st.session_state:
        st.session_state.cand_matches = []
    if "cand_opportunities" not in st.session_state:
        st.session_state.cand_opportunities = []


def _write_match_debug_file(
    betfair_events: List,
    poly_events: List,
    opportunities: List,
    sport_label: str,
) -> None:
    """
    Write a plain-text comparison file so event-name matching can be
    inspected and the matching algorithm tuned.

    Output: match_debug.txt in the project root.
    Each section is clearly separated so it can be read at a glance.
    """
    import os
    from market_matcher import MarketMatcher
    from models import Event, PolymarketEvent as PMEvent

    path = os.path.join(os.path.dirname(__file__), "match_debug.txt")
    matcher = MarketMatcher()

    # Build a quick lookup of which Betfair events were matched
    matched_bf_ids: set = set()
    matched_poly_ids: set = set()
    match_pairs = []

    # Re-run match to capture all pairs (opportunities may be 0 if no arb)
    raw_matches = matcher.find_matches(betfair_events, poly_events)
    for bf_ev, pm_ev, score in raw_matches:
        matched_bf_ids.add(bf_ev.id)
        matched_poly_ids.add(pm_ev.id)
        match_pairs.append((bf_ev, pm_ev, score))

    with open(path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write(
            f"MATCH DEBUG — Sport: {sport_label}   "
            f"Scanned: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        f.write("=" * 80 + "\n\n")

        # ---- Section 1: Betfair events ----
        f.write(f"BETFAIR EXCHANGE EVENTS  ({len(betfair_events)} total)\n")
        f.write("-" * 80 + "\n")
        for ev in sorted(betfair_events, key=lambda e: e.commence_time):
            matched_marker = "✓" if ev.id in matched_bf_ids else " "
            f.write(
                f"  [{matched_marker}] {ev.commence_time.strftime('%d %b %Y %H:%M')}  "
                f"{ev.sport:20s}  {ev.home_team} vs {ev.away_team}\n"
            )
        f.write("\n")

        # ---- Section 2: Polymarket events ----
        f.write(f"POLYMARKET EVENTS  ({len(poly_events)} total)\n")
        f.write("-" * 80 + "\n")
        _UTC = timezone.utc

        def _pm_sort_key(p):
            d = p.end_date
            if d is None:
                return datetime.min.replace(tzinfo=_UTC)
            return d if d.tzinfo is not None else d.replace(tzinfo=_UTC)

        for pm in sorted(poly_events, key=_pm_sort_key):
            matched_marker = "✓" if pm.id in matched_poly_ids else " "
            date_str = (
                pm.end_date.strftime("%d %b %Y %H:%M") if pm.end_date else "No date"
            )
            f.write(f"  [{matched_marker}] {date_str}  {pm.question}\n")
        f.write("\n")

        # ---- Section 3: Matched pairs (with similarity score) ----
        f.write(f"MATCHED PAIRS  ({len(match_pairs)} matches above threshold)\n")
        f.write("-" * 80 + "\n")
        for bf_ev, pm_ev, score in sorted(match_pairs, key=lambda x: -x[2]):
            f.write(f"  Score {score:.3f}\n")
            f.write(
                f"    Betfair:     {bf_ev.home_team} vs {bf_ev.away_team}  "
                f"({bf_ev.sport}, {bf_ev.commence_time.strftime('%d %b %Y')})\n"
            )
            f.write(f"    Polymarket:  {pm_ev.question}\n")
            # Show arbitrage if any
            arb_opps = [
                o
                for o in opportunities
                if o.event.id
                in (bf_ev.id, bf_ev.id + "_combined", pm_ev.id, pm_ev.id + "_combined")
            ]
            if arb_opps:
                best = max(arb_opps, key=lambda o: o.profit_percentage)
                f.write(
                    f"    *** ARBITRAGE: {best.profit_percentage:.3f}% profit ***\n"
                )
            f.write("\n")

        # ---- Section 4: Unmatched Betfair events ----
        unmatched_bf = [e for e in betfair_events if e.id not in matched_bf_ids]
        f.write(f"UNMATCHED BETFAIR EVENTS  ({len(unmatched_bf)})\n")
        f.write("-" * 80 + "\n")
        for ev in sorted(unmatched_bf, key=lambda e: e.commence_time):
            f.write(
                f"  {ev.commence_time.strftime('%d %b %Y %H:%M')}  "
                f"{ev.sport:20s}  {ev.home_team} vs {ev.away_team}\n"
            )
        f.write("\n")

        # ---- Section 5: Unmatched Polymarket events ----
        unmatched_pm = [p for p in poly_events if p.id not in matched_poly_ids]
        f.write(f"UNMATCHED POLYMARKET EVENTS  ({len(unmatched_pm)})\n")
        f.write("-" * 80 + "\n")
        for pm in sorted(unmatched_pm, key=_pm_sort_key):
            date_str = (
                pm.end_date.strftime("%d %b %Y %H:%M") if pm.end_date else "No date"
            )
            f.write(f"  {date_str}  {pm.question}\n")
        f.write("\n")

        f.write("=" * 80 + "\n")
        f.write(
            f"Match rate: {len(match_pairs)}/{len(betfair_events)} Betfair events matched  "
            f"({len(match_pairs)/max(len(betfair_events),1)*100:.1f}%)\n"
        )
        f.write("=" * 80 + "\n")

    print(f"[DEBUG] Match debug file written → {path}")


def main():
    """Main application function."""
    init_session_state()

    st.title("Betfair and Polymarket comparison")

    # ---------------------------------------------------------------- Sidebar
    with st.sidebar:
        st.header("Configuration")

        st.subheader("Betfair Exchange")

        bf_username = st.text_input(
            "Betfair Username / Email",
            value=Config.BETFAIR_USERNAME,
        )
        bf_password = st.text_input(
            "Betfair Password",
            value=Config.BETFAIR_PASSWORD,
            type="password",
        )
        bf_app_key = st.text_input(
            "Betfair App Key",
            value=Config.BETFAIR_APP_KEY,
            type="password",
        )

        # ---- Profit threshold ----
        st.divider()
        min_profit = st.slider(
            "Min Profit Threshold (%)",
            min_value=0.0,
            max_value=10.0,
            value=Config.MIN_PROFIT_THRESHOLD,
            step=0.1,
        )

        # ---- Sport selection ----
        st.divider()
        st.subheader("Sport")

        selected_sport_label = st.selectbox(
            "Sport",
            options=list(Config.SHARED_SPORTS.keys()),
        )
        sport_hint = Config.SHARED_SPORTS[selected_sport_label]  # e.g. 'soccer'

        # When showing all or politics, offer a display filter
        if sport_hint in ("all", "politics"):
            st.caption("Show:")
            show_politics = st.checkbox("Politics", value=True)
            show_sports = st.checkbox(
                "Sports", value=True if sport_hint == "all" else False
            )
        else:
            show_politics = False
            show_sports = True

        days_ahead = st.slider(
            "Look-ahead (days)",
            min_value=1,
            max_value=30,
            value=14,
            step=1,
        )

        # ---- Polymarket filters ----
        st.divider()
        st.subheader("Polymarket Filters")

        min_volume = st.slider(
            "Min Market Volume ($)",
            min_value=0,
            max_value=100000,
            value=1000,
            step=1000,
        )

        # ---- Investment calculator ----
        st.divider()
        st.subheader("Investment")
        investment_amount = st.number_input(
            "Total Investment (£)",
            min_value=10.0,
            max_value=100000.0,
            value=100.0,
            step=10.0,
        )

        gbp_usd_rate = st.number_input(
            "GBP → USD Rate",
            min_value=0.50,
            max_value=3.00,
            value=1.27,
            step=0.01,
            format="%.2f",
            help="Current GBP to USD exchange rate — used to show USD amounts for Polymarket stakes",
        )

        # ---- Scan / refresh controls ----
        st.divider()
        scan_button = st.button(
            "Scan",
            width="stretch",
            type="primary",
        )

        auto_refresh = st.checkbox("Auto-refresh", value=False)
        if auto_refresh:
            refresh_interval = st.slider(
                "Refresh Interval (seconds)",
                min_value=60,
                max_value=300,
                value=120,
                step=30,
            )

        # Last update time
        if st.session_state.last_update:
            st.caption(
                f"Last scan: {st.session_state.last_update.strftime('%H:%M:%S')}"
            )

    # ---------------------------------------------------------------- Validate
    if not bf_username or not bf_password or not bf_app_key:
        st.error(
            "Betfair credentials required. Enter username, password, and App Key in the sidebar."
        )
        st.caption(
            "Get a free Delayed App Key at [developer.betfair.com](https://developer.betfair.com/get-started/#exchange-api)."
        )
        return

    # ---------------------------------------------------------------- Clients
    betfair_client = BetfairClient(bf_username, bf_password, bf_app_key)
    poly_client = PolymarketClient()
    engine = ArbitrageEngine(min_profit_threshold=min_profit)

    # ---------------------------------------------------------------- Scan
    if scan_button or auto_refresh:
        with st.spinner(f"Scanning {selected_sport_label}..."):
            if not betfair_client.login():
                st.error(f"Betfair login failed: {betfair_client.get_last_error()}")
                st.stop()

            from market_matcher import MarketMatcher as _MM

            # ---- Sports scan ----
            trad_events = []
            poly_events = []
            raw_matches = []
            opportunities = []

            scan_sports = sport_hint not in ("politics",)
            scan_politics = sport_hint in ("all", "politics")

            if scan_sports:
                sport_hints = (
                    None if sport_hint in ("all", "politics") else [sport_hint]
                )
                trad_events = betfair_client.get_odds(
                    sport_hints=sport_hints,
                    days_ahead=days_ahead,
                    min_hours_ahead=6,
                )
                st.caption(f"Betfair sports: {len(trad_events)} markets")

                poly_events = poly_client.get_sports_markets(
                    sport_hint=(
                        sport_hint if sport_hint not in ("all", "politics") else None
                    ),
                    active_only=True,
                    min_volume=0,
                )
                st.caption(f"Polymarket sports: {len(poly_events)} markets")

                filtered_out = sum(1 for p in poly_events if p.volume < min_volume)
                if filtered_out:
                    st.caption(
                        f"{filtered_out} Polymarket markets below volume threshold (matching uses all)"
                    )

                opportunities = engine.compare_markets(trad_events, poly_events)
                raw_matches = _MM().find_matches(trad_events, poly_events)

                if raw_matches:
                    arb_msg = (
                        f" — {len(opportunities)} arbitrage opportunities found"
                        if opportunities
                        else " — no arbitrage profit at current odds"
                    )
                    st.success(f"{len(raw_matches)} sports events matched{arb_msg}")
                else:
                    st.info("No sports cross-platform matches found.")

            # ---- Politics scan ----
            pol_bf_events = []
            pol_pm_events = []
            pol_matches = []
            pol_opportunities = []
            cand_matches = []
            cand_opportunities = []

            if scan_politics:
                with st.spinner("Scanning political markets..."):
                    pol_bf_events = betfair_client.get_politics_markets(days_ahead=400)
                    st.caption(f"Betfair politics: {len(pol_bf_events)} markets")

                    pol_pm_events = poly_client.get_politics_markets(
                        active_only=True, min_volume=0
                    )
                    st.caption(f"Polymarket politics: {len(pol_pm_events)} markets")

                    if pol_bf_events and pol_pm_events:
                        matcher = _MM()
                        pol_matches = matcher.find_politics_matches(
                            pol_bf_events, pol_pm_events
                        )
                        # Candidate-level binary matching for multi-candidate races
                        cand_matches = matcher.find_candidate_binary_matches(
                            pol_bf_events, pol_pm_events
                        )
                        cand_opportunities = []
                        for _bf, _runner, _pm, _score in cand_matches:
                            cand_opportunities.extend(
                                engine.check_candidate_arb(_bf, _runner, _pm, _score)
                            )
                        pol_opportunities = engine.compare_markets(
                            pol_bf_events, pol_pm_events
                        )
                        status_parts = []
                        if pol_matches:
                            pol_arb_msg = (
                                f" ({len(pol_opportunities)} arb)"
                                if pol_opportunities
                                else ""
                            )
                            status_parts.append(
                                f"{len(pol_matches)} events matched{pol_arb_msg}"
                            )
                        if cand_matches:
                            cand_arb_msg = (
                                f" ({len(cand_opportunities)} arb)"
                                if cand_opportunities
                                else ""
                            )
                            status_parts.append(
                                f"{len(cand_matches)} candidate races{cand_arb_msg}"
                            )
                        if status_parts:
                            st.success("🗳️ " + " | ".join(status_parts))
                        else:
                            st.info("No political cross-platform matches found.")
                    elif not pol_bf_events:
                        st.warning(
                            "No Betfair political markets found. "
                            "Event type ID 2378961 may not return results for your account region. "
                            "Try browsing betfair.com/exchange/plus/politics to confirm markets exist."
                        )

            # Store everything in session state
            st.session_state.cross_platform_opportunities = opportunities
            st.session_state.matched_pairs = raw_matches
            st.session_state.trad_events = trad_events
            st.session_state.poly_events = poly_events
            st.session_state.pol_bf_events = pol_bf_events
            st.session_state.pol_pm_events = pol_pm_events
            st.session_state.pol_matches = pol_matches
            st.session_state.pol_opportunities = pol_opportunities
            st.session_state.cand_matches = cand_matches
            st.session_state.cand_opportunities = cand_opportunities
            st.session_state.last_update = datetime.now()
            st.session_state.show_politics = show_politics
            st.session_state.show_sports = show_sports

            # Write debug file (sports + politics combined)
            all_bf = trad_events + pol_bf_events
            all_pm = poly_events + pol_pm_events
            all_opps = opportunities + pol_opportunities
            _write_match_debug_file(all_bf, all_pm, all_opps, selected_sport_label)
            st.caption("Debug written to match_debug.txt")

    # Display results
    if hasattr(st.session_state, "cross_platform_opportunities"):
        opportunities = st.session_state.cross_platform_opportunities
        trad_events = st.session_state.get("trad_events", [])
        poly_events = st.session_state.get("poly_events", [])
        matched_pairs = st.session_state.get("matched_pairs", [])

        pol_matches = st.session_state.get("pol_matches", [])
        pol_opportunities = st.session_state.get("pol_opportunities", [])
        pol_bf_events = st.session_state.get("pol_bf_events", [])
        pol_pm_events = st.session_state.get("pol_pm_events", [])
        cand_matches = st.session_state.get("cand_matches", [])
        cand_opportunities = st.session_state.get("cand_opportunities", [])

        # Re-read display filter from session (survives rerun without re-scan)
        _show_pol = st.session_state.get("show_politics", show_politics)
        _show_spo = st.session_state.get("show_sports", show_sports)

        # ---- Apply liquidity filter to displayed results ----
        # Matching always uses all markets; we filter what's *shown* here.
        def _pm_vol(triple):
            """Return the Polymarket event volume from a (bf, pm, score) triple."""
            return triple[1].volume

        matched_pairs_display = [t for t in matched_pairs if _pm_vol(t) >= min_volume]
        pol_matches_display = [t for t in pol_matches if _pm_vol(t) >= min_volume]
        cand_matches_display = [t for t in cand_matches if t[2].volume >= min_volume]
        # Filter candidate opportunities to only those whose PM market passed
        _cand_display_ids = {
            (t[0].id, t[1].replace(" ", "_")) for t in cand_matches_display
        }
        cand_opps_display = [
            o
            for o in cand_opportunities
            if any(
                o.event.id.startswith(f"{bid}_back_no_{rk}")
                or o.event.id.startswith(f"{bid}_lay_yes_{rk}")
                for bid, rk in _cand_display_ids
            )
        ]

        # Filter arbitrage opportunities to only those whose Polymarket event
        # passes the liquidity threshold.
        def _opp_pm_vol(opp):
            # ArbitrageOpportunity.event may be a combined BF event;
            # look for the volume attribute added by the engine, else 0.
            return getattr(opp.event, "_pm_volume", None) or getattr(
                opp, "_pm_volume", 0
            )

        opportunities_display = [
            o
            for o in opportunities
            if _opp_pm_vol(o) >= min_volume or _opp_pm_vol(o) == 0
        ]
        pol_opportunities_display = [
            o
            for o in pol_opportunities
            if _opp_pm_vol(o) >= min_volume or _opp_pm_vol(o) == 0
        ]

        sports_filtered = len(matched_pairs) - len(matched_pairs_display)
        politics_filtered = len(pol_matches) - len(pol_matches_display)
        cand_filtered = len(cand_matches) - len(cand_matches_display)

        # ---- Summary metrics ----
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("🗳️ BF Politics", len(pol_bf_events))
        c2.metric("🗳️ PM Politics", len(pol_pm_events))
        c3.metric("⚽ BF Sports", len(trad_events))
        c4.metric("⚽ PM Sports", len(poly_events))
        c5.metric(
            "💡 Arb Opportunities",
            len(pol_opportunities_display) + len(opportunities_display),
        )

        if sports_filtered + politics_filtered + cand_filtered:
            st.caption(
                f"🔍 Liquidity filter (≥ ${min_volume:,}): hiding "
                f"{sports_filtered} sports + {politics_filtered} politics + "
                f"{cand_filtered} candidate-race matches below threshold."
            )

        # ================================================================
        # POLITICS SECTION  (shown first)
        # ================================================================
        if _show_pol and pol_matches_display:
            st.markdown("## 🗳️ Political Markets")
            st.caption(
                f"{len(pol_matches_display)} political events matched | "
                f"{len(pol_opportunities_display)} arbitrage opportunities"
            )

            if pol_opportunities_display:
                display_cross_platform_opportunities(
                    pol_opportunities_display, investment_amount, gbp_usd_rate
                )
                st.divider()

            display_matched_pairs(
                pol_matches_display, pol_opportunities_display, investment_amount
            )

            if cand_matches_display:
                st.divider()
                display_candidate_binary_matches(
                    cand_matches_display, cand_opps_display, investment_amount
                )
            st.divider()

        elif _show_pol and pol_bf_events and not pol_matches_display:
            st.markdown("## 🗳️ Political Markets")
            no_match_reason = (
                f"All {len(pol_matches)} political matches are below the "
                f"${min_volume:,} liquidity filter."
                if pol_matches
                else f"Betfair has {len(pol_bf_events)} political markets and Polymarket has "
                f"{len(pol_pm_events)} political markets, but no cross-platform matches "
                "were found. The event names may differ significantly across platforms."
            )
            st.info(no_match_reason)

        # ================================================================
        # SPORTS SECTION
        # ================================================================
        if _show_spo:
            if matched_pairs_display:
                st.markdown("## ⚽ Sports Markets")
                st.caption(
                    f"{len(matched_pairs_display)} sports events matched | "
                    f"{len(opportunities_display)} arbitrage opportunities"
                )

                matched_bf_ids = {bf_ev.id for bf_ev, _, _ in matched_pairs_display}
                unmatched = [e for e in trad_events if e.id not in matched_bf_ids]
                if unmatched:
                    with st.expander(
                        f"{len(unmatched)} Betfair sports events unmatched"
                    ):
                        for event in unmatched[:10]:
                            st.text(
                                f"{event.home_team} vs {event.away_team} ({event.sport})"
                            )

                if opportunities_display:
                    display_cross_platform_opportunities(
                        opportunities_display, investment_amount, gbp_usd_rate
                    )
                    st.divider()

                display_matched_pairs(
                    matched_pairs_display, opportunities_display, investment_amount
                )

            elif trad_events:
                st.markdown("## ⚽ Sports Markets")
                st.warning("No cross-platform sports matches found.")
                with st.expander(
                    f"Betfair Events ({len(trad_events)})", expanded=False
                ):
                    display_traditional_events(trad_events)
                with st.expander(
                    f"Polymarket Markets ({len(poly_events)})", expanded=False
                ):
                    display_polymarket_markets(poly_events)

    # Auto-refresh logic
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()

    # Footer
    st.divider()
    st.caption(
        "Verify odds before placing bets. Betfair charges ~5% commission on exchange winnings. "
        "Polymarket requires USDC on Polygon."
    )


def display_matched_pairs(
    matched_pairs: List, opportunities: List[ArbitrageOpportunity], investment: float
):
    """Show every event matched across Betfair and Polymarket, with odds from both sides."""
    import pandas as pd

    # Build a lookup: base Betfair event ID → list of opportunities
    arb_by_bf_id: dict = {}
    for opp in opportunities:
        base_id = opp.event.id.split("_combined")[0].split("_lay_")[0]
        arb_by_bf_id.setdefault(base_id, []).append(opp)

    st.markdown("### Matched Events")
    st.caption(f"{len(matched_pairs)} events matched. ARB = arbitrage detected.")

    for bf_ev, pm_ev, score in sorted(matched_pairs, key=lambda x: x[0].commence_time):
        matched_opps = arb_by_bf_id.get(bf_ev.id, [])
        has_arb = bool(matched_opps)

        label = (
            f"ARB | {bf_ev.sport} | {bf_ev.home_team} vs {bf_ev.away_team} "
            f"| {bf_ev.commence_time.strftime('%d %b %Y, %H:%M')} | {score*100:.0f}% match"
            if has_arb
            else (
                f"{bf_ev.sport} | {bf_ev.home_team} vs {bf_ev.away_team} "
                f"| {bf_ev.commence_time.strftime('%d %b %Y, %H:%M')} | {score*100:.0f}% match"
            )
        )

        with st.expander(label, expanded=has_arb):
            col1, col2 = st.columns(2)

            # --- Betfair side ---
            with col1:
                st.markdown("**Betfair Exchange**")
                # Separate back and lay prices
                back_by_name: dict = {}
                lay_by_name: dict = {}
                for o in bf_ev.outcomes:
                    if o.bookmaker == "Betfair Lay":
                        if o.name not in lay_by_name or o.price < lay_by_name[o.name]:
                            lay_by_name[o.name] = o.price  # best lay = lowest price
                    else:
                        if o.name not in back_by_name or o.price > back_by_name[o.name]:
                            back_by_name[o.name] = o.price

                bf_rows = []
                all_names = sorted(
                    set(list(back_by_name.keys()) + list(lay_by_name.keys()))
                )
                for name in all_names:
                    back = back_by_name.get(name)
                    lay = lay_by_name.get(name)
                    row = {"Outcome": name}
                    if back:
                        row["Back"] = f"{back:.3f}"
                        row["Back imp%"] = f"{100/back:.1f}%"
                    else:
                        row["Back"] = "—"
                        row["Back imp%"] = "—"
                    if lay:
                        row["Lay"] = f"{lay:.3f}"
                        row["Lay imp%"] = f"{100/lay:.1f}%"
                    else:
                        row["Lay"] = "—"
                        row["Lay imp%"] = "—"
                    bf_rows.append(row)
                bf_back_total = sum(1 / p for p in back_by_name.values() if p > 0)
                st.dataframe(pd.DataFrame(bf_rows), hide_index=True, width="stretch")
                if bf_back_total > 0:
                    st.caption(
                        f"Back market total implied: **{bf_back_total*100:.1f}%**"
                    )

            # --- Polymarket side ---
            with col2:
                st.markdown("**Polymarket**")
                pm_rows = []
                pm_total = 0.0
                for name, price in zip(pm_ev.outcomes, pm_ev.prices):
                    if price > 0:
                        dec_odds = 1 / price
                        pm_total += price
                        pm_rows.append(
                            {
                                "Outcome": name,
                                "Price (prob)": f"{price:.3f}",
                                "Odds (decimal)": f"{dec_odds:.3f}",
                                "Implied %": f"{price*100:.1f}%",
                            }
                        )
                st.dataframe(pd.DataFrame(pm_rows), hide_index=True, width="stretch")
                st.caption(f"Polymarket total implied: **{pm_total*100:.1f}%**")
                st.caption(
                    f"📊 Volume: **${pm_ev.volume:,.0f}** | Liquidity: **${pm_ev.liquidity:,.0f}**"
                )

            # Platform links
            _lc1, _lc2 = st.columns(2)
            with _lc1:
                _bf_url = _betfair_url(bf_ev.id, bf_ev.category)
                if _bf_url:
                    st.link_button("Betfair", _bf_url, use_container_width=True)
            with _lc2:
                _pm_url = _polymarket_url(pm_ev.id)
                if _pm_url:
                    st.link_button("Polymarket", _pm_url, use_container_width=True)

            # Show any arb opportunities for this event
            if has_arb:
                for opp in sorted(matched_opps, key=lambda o: -o.profit_percentage):
                    is_lay = "[LAY-BACK]" in (opp.event.description or "")
                    strategy = "Lay-Back" if is_lay else "Back-Back"
                    scaled_profit = investment * (opp.profit_percentage / 100)
                    st.success(
                        f"{strategy}: {opp.profit_percentage:.3f}% — "
                        f"£{investment:.2f} → +£{scaled_profit:.2f}"
                    )
            else:
                st.info(f"No arbitrage at current odds ({score*100:.0f}% match)")


def display_cross_platform_opportunities(
    opportunities: List[ArbitrageOpportunity],
    investment: float,
    gbp_usd_rate: float = 1.27,
):
    """Display cross-platform arbitrage opportunities with clear betting instructions."""
    # Summary metrics
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Opportunities Found", len(opportunities))

    with col2:
        avg_profit = sum(o.profit_percentage for o in opportunities) / len(
            opportunities
        )
        st.metric("Avg Profit %", f"{avg_profit:.2f}%")

    with col3:
        best_profit = max(o.profit_percentage for o in opportunities)
        st.metric("Best Opportunity", f"{best_profit:.2f}%")

    st.divider()

    # Sort by profit percentage
    opportunities.sort(key=lambda x: x.profit_percentage, reverse=True)

    # Build Betfair market ID → Polymarket event lookup for link generation
    _pm_by_bf_id = {
        bf.id: pm for bf, pm, _ in getattr(st.session_state, "matched_pairs", [])
    }

    for idx, opp in enumerate(opportunities, 1):
        desc = opp.event.description or ""
        is_lay_back = desc.startswith("[LAY-BACK]")
        strategy_label = "LAY-BACK" if is_lay_back else "BACK-BACK"

        with st.expander(
            f"{strategy_label} #{idx} | {opp.event.sport} | {opp.profit_percentage:.2f}% | {opp.event.match_quality*100:.0f}% match",
            expanded=idx <= 3,
        ):
            # Event details
            st.markdown(f"### {str(opp.event)}")
            st.caption(opp.event.commence_time.strftime("%d %b %Y, %H:%M"))

            # Platform links
            _bf_mid = opp.event.id.split("_combined")[0].split("_lay_")[0]
            _pm_ev = _pm_by_bf_id.get(_bf_mid)

            # Polymarket volume
            if _pm_ev:
                vol_str = f"${_pm_ev.volume:,.0f}"
                liq_str = f"${_pm_ev.liquidity:,.0f}"
                st.caption(
                    f"📊 Polymarket volume: **{vol_str}** | Liquidity: **{liq_str}**"
                )
            _lc1, _lc2 = st.columns(2)
            with _lc1:
                _bf_url = _betfair_url(_bf_mid, opp.event.category)
                if _bf_url:
                    st.link_button("Betfair", _bf_url, use_container_width=True)
            with _lc2:
                if _pm_ev:
                    _pm_url = _polymarket_url(_pm_ev.id)
                    if _pm_url:
                        st.link_button("Polymarket", _pm_url, use_container_width=True)

            # Profit summary
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Investment", f"£{investment:.2f}")
            with col2:
                st.metric(
                    "Expected Profit",
                    f"£{opp.profit:.2f}",
                    delta=f"{opp.profit_percentage:.2f}%",
                )
            with col3:
                st.metric("Total Return", f"£{investment + opp.profit:.2f}")

            st.divider()

            # Betting instructions
            st.markdown("### Instructions")

            scale = investment / opp.total_stake if opp.total_stake else 1.0
            stake_dist = {k: v * scale for k, v in opp.stake_distribution.items()}
            stake_keys = list(stake_dist.keys())

            if is_lay_back:
                # LAY-BACK: keys are like "Team (Polymarket Back)" and "Team (Betfair Lay)"
                # First find the two legs to show the maths
                pm_leg = next(
                    (o for o in opp.best_outcomes if o.bookmaker == "Polymarket"), None
                )
                lay_leg = next(
                    (o for o in opp.best_outcomes if o.bookmaker == "Betfair Lay"), None
                )
                if pm_leg and lay_leg:
                    pm_prob = 1 / pm_leg.price if pm_leg.price > 0 else 0
                    lay_implied = 1 / lay_leg.price if lay_leg.price > 0 else 0
                    st.caption(
                        f"Polymarket implied: {pm_prob*100:.2f}% | "
                        f"Betfair lay implied: {lay_implied*100:.2f}% | "
                        f"Edge: {(pm_prob - lay_implied)*100:.2f}pp | "
                        f"Profit: {opp.profit_percentage:.3f}%"
                    )
                for label_key, stake in stake_dist.items():
                    is_lay_leg = "(Betfair Lay)" in label_key
                    runner_name = (
                        label_key.replace(" (Betfair Lay)", "")
                        .replace(" (Polymarket Back)", "")
                        .strip()
                    )
                    if is_lay_leg:
                        lay_outcome = next(
                            (
                                o
                                for o in opp.best_outcomes
                                if o.bookmaker == "Betfair Lay"
                                and o.name == runner_name
                            ),
                            None,
                        )
                        lay_price = lay_outcome.price if lay_outcome else 0
                        liability = stake * (lay_price - 1) if lay_price else 0
                        lay_implied_pct = 100 / lay_price if lay_price > 0 else 0
                        st.markdown(
                            f"**Leg 1 — 🔴 LAY — Betfair Exchange**\n"
                            f"- Lay odds: {lay_price:.3f}"
                            f" ({decimal_to_fractional(lay_price) if lay_price else '—'})"
                            f" — implied {lay_implied_pct:.1f}%\n"
                            f"- Stake: £{stake:.2f} | Liability: £{liability:.2f} (must be in your Betfair wallet)\n"
                            f"- **Action: LAY {runner_name} @ {lay_price:.2f} on Betfair Exchange → £{stake:.2f}**"
                        )
                    else:
                        pm_outcome = next(
                            (
                                o
                                for o in opp.best_outcomes
                                if o.bookmaker == "Polymarket" and o.name == runner_name
                            ),
                            None,
                        )
                        pm_price = pm_outcome.price if pm_outcome else 0
                        pm_prob_pct = 100 / pm_price if pm_price > 0 else 0
                        usd_stake = stake * gbp_usd_rate
                        st.markdown(
                            f"**Leg 2 — 🟢 BET (Back) — Polymarket**\n"
                            f"- Odds: {pm_price:.3f}"
                            f" ({decimal_to_fractional(pm_price) if pm_price else '—'})"
                            f" — implied {pm_prob_pct:.1f}%\n"
                            f"- **Action: BET (Back) {runner_name} @ {pm_price:.3f} on Polymarket → £{stake:.2f} (~${usd_stake:.2f} USD)**"
                        )
            else:
                # BACK-BACK: show arbitrage maths then step-by-step instructions
                import pandas as pd

                total_implied = sum(
                    1 / o.price for o in opp.best_outcomes if o.price > 0
                )
                profit_margin = (
                    (1 / total_implied - 1) * 100 if total_implied > 0 else 0
                )

                # ---- Maths summary table ----
                math_rows = []
                for o in opp.best_outcomes:
                    implied_pct = 100 / o.price if o.price > 0 else 0
                    math_rows.append(
                        {
                            "Outcome": o.name,
                            "Platform": (
                                "Betfair"
                                if o.bookmaker != "Polymarket"
                                else "Polymarket"
                            ),
                            "Odds": f"{o.price:.3f}",
                            "Implied %": f"{implied_pct:.2f}%",
                        }
                    )
                st.dataframe(pd.DataFrame(math_rows), hide_index=True, width="stretch")
                st.caption(
                    f"Total implied: {total_implied*100:.2f}% → profit margin {profit_margin:.3f}%"
                )
                st.divider()

                for i, outcome in enumerate(opp.best_outcomes, 1):
                    outcome_stake = stake_dist.get(outcome.name, 0)
                    if outcome_stake == 0 and (i - 1) < len(stake_keys):
                        outcome_stake = stake_dist[stake_keys[i - 1]]

                    implied_pct = 100 / outcome.price if outcome.price > 0 else 0
                    expected_return = outcome_stake * outcome.price

                    if outcome.bookmaker == "Polymarket":
                        platform_header = f"**Leg {i} — 🟢 BET (Back) — Polymarket**"
                        usd_outcome_stake = outcome_stake * gbp_usd_rate
                        action = f"BET (Back) **{outcome.name}** @ {outcome.price:.3f} on Polymarket → £{outcome_stake:.2f} (~${usd_outcome_stake:.2f} USD)"
                    elif outcome.bookmaker == "Betfair Lay":
                        platform_header = f"**Leg {i} — 🔴 LAY — Betfair Exchange**"
                        action = f"LAY **{outcome.name}** @ {outcome.price:.3f} on Betfair Exchange → £{outcome_stake:.2f}"
                    else:
                        platform_header = f"**Leg {i} — 🟢 BACK — Betfair Exchange**"
                        action = f"BACK **{outcome.name}** @ {outcome.price:.3f} on Betfair Exchange → £{outcome_stake:.2f}"

                    gross_payout = outcome_stake * outcome.price
                    if outcome.bookmaker == "Polymarket":
                        usd_gross_payout = gross_payout * gbp_usd_rate
                        payout_note = f"- Gross payout if wins: **£{gross_payout:.2f}** (~${usd_gross_payout:.2f} USD)"
                    elif outcome.bookmaker == "Betfair Lay":
                        liability = outcome_stake * (outcome.price - 1)
                        payout_note = (
                            f"- Liability (upfront): **£{liability:.2f}** | "
                            f"Payout if you win (selection loses): **£{outcome_stake:.2f}**"
                        )
                    else:
                        # Betfair back — ~5% commission on net winnings
                        net_payout = (
                            outcome_stake + (gross_payout - outcome_stake) * 0.95
                        )
                        payout_note = (
                            f"- Gross payout if wins: £{gross_payout:.2f}"
                            f" → net **~£{net_payout:.2f}** after ~5% commission"
                        )

                    st.markdown(
                        f"{platform_header}\n"
                        f"- Odds: {outcome.price:.3f} ({decimal_to_fractional(outcome.price)})"
                        f" — implied {implied_pct:.1f}%\n"
                        f"- Stake: £{outcome_stake:.2f}\n"
                        f"{payout_note}\n"
                        f"- **Action:** {action}"
                    )

                # Outcome guarantee
                st.success(
                    f"Return: ~£{investment * (1 + profit_margin/100):.2f} on £{investment:.2f} "
                    f"(+£{investment * profit_margin/100:.2f})"
                )

            # Warnings
            if opp.event.match_quality < 0.8:
                st.warning(
                    f"Low match quality ({opp.event.match_quality*100:.0f}%) — confirm this is the same event."
                )

            if is_lay_back:
                st.caption(
                    "Lay bets require liability funded upfront. Betfair charges ~5% commission on winnings."
                )

            if any(o.bookmaker == "Polymarket" for o in opp.best_outcomes):
                st.caption("Polymarket requires USDC on Polygon.")

            st.divider()


def display_traditional_events(events: List):
    """Display Betfair Exchange events for manual evaluation."""
    from models import Event

    st.markdown("### Betfair Exchange")

    for event in events:
        if not isinstance(event, Event):
            continue

        with st.container():
            # Event header
            col1, col2 = st.columns([3, 1])

            with col1:
                st.markdown(f"**{str(event)}**")
                st.caption(
                    f"{event.sport} | {event.commence_time.strftime('%d %b %Y, %H:%M')}"
                )

            with col2:
                # Betfair Exchange is always the bookmaker here
                best_outcome = max(event.outcomes, key=lambda o: o.price)
                st.metric("Best Back Price", f"{best_outcome.price:.3f}")

            # Show odds from all bookmakers
            with st.expander("Odds"):
                # Group outcomes by name
                outcome_groups = {}
                for outcome in event.outcomes:
                    if outcome.name not in outcome_groups:
                        outcome_groups[outcome.name] = []
                    outcome_groups[outcome.name].append(outcome)

                for outcome_name, outcomes in outcome_groups.items():
                    st.markdown(f"**{outcome_name}**")

                    odds_data = []
                    for outcome in outcomes:
                        odds_data.append(
                            {
                                "Bookmaker": outcome.bookmaker,
                                "Decimal Odds": f"{outcome.price:.3f}",
                                "Fractional": decimal_to_fractional(outcome.price),
                                "Implied Prob": f"{(1/outcome.price)*100:.1f}%",
                            }
                        )

                    df = pd.DataFrame(odds_data)
                    st.dataframe(df, width="stretch", hide_index=True)

                    # Show best odds
                    best_outcome = max(outcomes, key=lambda x: x.price)
                    st.caption(
                        f"Best: {best_outcome.bookmaker} @ {best_outcome.price:.3f}"
                    )
                    st.markdown("---")

            st.divider()


def display_polymarket_markets(markets: List):
    """Display Polymarket markets even without arbitrage."""
    from models import PolymarketEvent

    st.markdown("### Polymarket Markets")

    markets_displayed = 0
    for market in markets:
        if not isinstance(market, PolymarketEvent):
            continue

        # Skip markets with no outcomes or prices
        if not market.outcomes or not market.prices or len(market.outcomes) == 0:
            continue

        markets_displayed += 1

        with st.container():
            col1, col2 = st.columns([3, 1])

            with col1:
                st.markdown(f"**{market.question}**")
                st.caption(
                    f"Volume: ${market.volume:,.0f} | Liquidity: ${market.liquidity:,.0f}"
                )

            with col2:
                # Calculate if prices sum to more than 1 (potential inefficiency)
                if market.prices:
                    total_prob = sum(market.prices)
                    if total_prob > 1.0:
                        inefficiency = (total_prob - 1.0) * 100
                        st.metric("Inefficiency", f"{inefficiency:.2f}%")
                    else:
                        st.metric("Status", "Efficient")
                else:
                    st.metric("Outcomes", len(market.outcomes))

            # Show outcomes and prices
            with st.expander("Odds", expanded=False):
                if market.outcomes and market.prices:
                    odds_data = []
                    decimal_odds = market.to_decimal_odds()

                    for i, (outcome, price, odds) in enumerate(
                        zip(market.outcomes, market.prices, decimal_odds)
                    ):
                        odds_data.append(
                            {
                                "Outcome": outcome or f"Outcome {i+1}",
                                "Price (Probability)": (
                                    f"${price:.3f}" if price > 0 else "$0.000"
                                ),
                                "Implied Probability": (
                                    f"{price*100:.1f}%" if price > 0 else "0%"
                                ),
                                "Decimal Odds": f"{odds:.2f}" if odds > 1.0 else "N/A",
                                "Fractional": (
                                    decimal_to_fractional(odds) if odds > 1.0 else "N/A"
                                ),
                            }
                        )

                    if odds_data:
                        df = pd.DataFrame(odds_data)
                        st.dataframe(df, width="stretch", hide_index=True)

                        total_implied = sum(market.prices) * 100
                        st.caption(f"Total implied: {total_implied:.2f}%")
                    else:
                        st.warning("No odds data available for this market")
                else:
                    st.warning(
                        f"Market has {len(market.outcomes)} outcomes but no price data"
                    )

                # Show end date if available
                if market.end_date:
                    st.caption(
                        f"**Ends:** {market.end_date.strftime('%Y-%m-%d %H:%M UTC')}"
                    )

            st.divider()

    if markets_displayed == 0:
        st.warning("No markets found.")


def display_candidate_binary_matches(
    cand_matches: List,
    cand_opportunities: List[ArbitrageOpportunity],
    investment: float,
) -> None:
    """
    Display multi-candidate election matches where each Betfair runner is
    compared against a Polymarket binary YES/NO market for that candidate.

    cand_matches: [(bf_event, runner_name, pm_event, score), ...]
    """
    import pandas as pd

    # Build lookup: event_id → list of arb opps
    arb_by_event_runner: dict = {}
    for opp in cand_opportunities:
        arb_by_event_runner.setdefault(opp.event.id, opp)

    st.markdown("### 🎯 Multi-Candidate Races — Candidate vs Binary Market")
    st.caption(
        f"{len(cand_matches)} candidate–market pairs. "
        "Each shows a Betfair runner matched to a Polymarket YES/NO market "
        "for that specific candidate. Spreads arise when the implied probabilities differ."
    )

    for bf_ev, runner, pm_ev, score in sorted(
        cand_matches,
        key=lambda x: -(
            max(
                (
                    o.price
                    for o in x[0].outcomes
                    if o.bookmaker == "Betfair Exchange" and o.name == x[1]
                ),
                default=0,
            )
        ),
    ):
        # BF prices for this runner
        bf_backs = [
            o
            for o in bf_ev.outcomes
            if o.bookmaker == "Betfair Exchange" and o.name == runner
        ]
        bf_lays = [
            o
            for o in bf_ev.outcomes
            if o.bookmaker == "Betfair Lay" and o.name == runner
        ]
        bf_back = max(o.price for o in bf_backs) if bf_backs else None
        bf_lay = max(o.price for o in bf_lays) if bf_lays else None

        # PM YES / NO prices
        pm_outs = pm_ev.outcomes or []
        pm_prices = pm_ev.prices or []
        yes_idx = next((i for i, o in enumerate(pm_outs) if o.lower() == "yes"), 0)
        no_idx = 1 - yes_idx
        pm_yes = pm_prices[yes_idx] if len(pm_prices) > yes_idx else None
        pm_no = pm_prices[no_idx] if len(pm_prices) > no_idx else None

        runner_key = runner.replace(" ", "_")
        back_no_id = f"{bf_ev.id}_back_no_{runner_key}"
        lay_yes_id = f"{bf_ev.id}_lay_yes_{runner_key}"
        arb_opps = [
            o for o in cand_opportunities if o.event.id in (back_no_id, lay_yes_id)
        ]
        has_arb = bool(arb_opps)

        election = bf_ev.description or f"{bf_ev.home_team}/{bf_ev.away_team}"
        bf_implied = f"{100/bf_back:.1f}%" if bf_back else "?"
        pm_yes_pct = f"{pm_yes*100:.1f}%" if pm_yes else "?"

        label = (
            f"{'💰 ARB | ' if has_arb else ''}{runner} — {election} "
            f"| BF {bf_implied} implied vs PM YES {pm_yes_pct} | {score*100:.0f}% match"
        )

        with st.expander(label, expanded=has_arb):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown(f"**Betfair — {runner}**")
                rows = []
                if bf_back:
                    back_vol = next(
                        (
                            o.volume
                            for o in bf_ev.outcomes
                            if o.bookmaker == "Betfair Exchange" and o.name == runner
                        ),
                        0.0,
                    )
                    rows.append(
                        {
                            "Type": "Back",
                            "Price": f"{bf_back:.3f}",
                            "Implied": f"{100/bf_back:.1f}%",
                            "Available": f"£{back_vol:,.0f}",
                        }
                    )
                if bf_lay:
                    lay_vol = next(
                        (
                            o.volume
                            for o in bf_ev.outcomes
                            if o.bookmaker == "Betfair Lay" and o.name == runner
                        ),
                        0.0,
                    )
                    rows.append(
                        {
                            "Type": "Lay",
                            "Price": f"{bf_lay:.3f}",
                            "Implied": f"{100/bf_lay:.1f}%",
                            "Available": f"£{lay_vol:,.0f}",
                        }
                    )
                if rows:
                    st.dataframe(rows, hide_index=True)
                bf_url = _betfair_url(bf_ev.id, bf_ev.category)
                if bf_url:
                    st.link_button("View on Betfair", bf_url, use_container_width=True)

            with col2:
                st.markdown(f"**Polymarket**")
                st.caption(pm_ev.question)
                pm_rows = []
                if pm_yes is not None:
                    pm_rows.append(
                        {
                            "Outcome": "YES",
                            "Prob": f"{pm_yes:.3f}",
                            "Implied": f"{pm_yes*100:.1f}%",
                            "Decimal odds": f"{1/pm_yes:.2f}",
                        }
                    )
                if pm_no is not None:
                    pm_rows.append(
                        {
                            "Outcome": "NO",
                            "Prob": f"{pm_no:.3f}",
                            "Implied": f"{pm_no*100:.1f}%",
                            "Decimal odds": f"{1/pm_no:.2f}",
                        }
                    )
                if pm_rows:
                    st.dataframe(pm_rows, hide_index=True)
                st.caption(
                    f"📊 Volume: ${pm_ev.volume:,.0f} | Liquidity: ${pm_ev.liquidity:,.0f}"
                )
                pm_url = _polymarket_url(pm_ev.event_slug or pm_ev.id)
                if pm_url:
                    st.link_button(
                        "View on Polymarket", pm_url, use_container_width=True
                    )

            if has_arb:
                for opp in sorted(arb_opps, key=lambda o: -o.profit_percentage):
                    strategy = (
                        "Back BF + Buy NO on PM"
                        if "_back_no_" in opp.event.id
                        else "Lay BF + Buy YES on PM"
                    )
                    scaled = investment * (opp.profit_percentage / 100)
                    st.success(
                        f"{strategy}: **{opp.profit_percentage:.3f}%** — "
                        f"£{investment:.2f} → +£{scaled:.2f}"
                    )
                    for leg, stake in opp.stake_distribution.items():
                        scaled_stake = stake * (investment / 100)
                        st.caption(f"  • {leg}: £{scaled_stake:.2f}")
            else:
                if bf_back and pm_yes:
                    spread = abs(pm_yes - 1 / bf_back)
                    st.info(
                        f"No arb yet. Spread: BF implies {100/bf_back:.1f}% vs PM YES {pm_yes*100:.1f}% "
                        f"({spread*100:.1f}pp apart). Watch for price movement."
                    )


if __name__ == "__main__":
    main()
