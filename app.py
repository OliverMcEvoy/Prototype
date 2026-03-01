"""
Streamlit dashboard for Betfair × Polymarket cross-platform arbitrage.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
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
        for pm in sorted(poly_events, key=lambda p: (p.end_date or datetime.min)):
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
        for pm in sorted(unmatched_pm, key=lambda p: (p.end_date or datetime.min)):
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
            sport_hints = None if sport_hint == "all" else [sport_hint]

            if not betfair_client.login():
                st.error(f"Betfair login failed: {betfair_client.get_last_error()}")
                st.stop()

            trad_events = betfair_client.get_odds(
                sport_hints=sport_hints,
                days_ahead=days_ahead,
                min_hours_ahead=6,
            )
            st.caption(f"Betfair: {len(trad_events)} markets")

            poly_events = poly_client.get_sports_markets(
                sport_hint=sport_hint if sport_hint != "all" else None,
                active_only=True,
                min_volume=0,
            )
            st.caption(f"Polymarket: {len(poly_events)} markets")

            # Volume filter is for display/arbitrage only — matching uses ALL events
            sports_poly_events = [p for p in poly_events if p.volume >= min_volume]
            filtered_out = len(poly_events) - len(sports_poly_events)
            if filtered_out:
                st.caption(
                    f"{filtered_out} Polymarket markets below volume threshold (matching uses all)"
                )

            # Pass ALL poly_events to matcher so low-volume markets aren't missed
            opportunities = engine.compare_markets(trad_events, poly_events)

            # Run matcher separately to capture ALL matched pairs,
            # not just those with arbitrage profit
            from market_matcher import MarketMatcher as _MM

            raw_matches = _MM().find_matches(trad_events, poly_events)
            matched_count = len(raw_matches)

            if matched_count > 0:
                arb_msg = (
                    f" — {len(opportunities)} arbitrage opportunities found"
                    if opportunities
                    else " — no arbitrage profit at current odds"
                )
                st.success(f"{matched_count} events matched{arb_msg}")
            else:
                st.warning("No cross-platform matches found.")

            st.session_state.cross_platform_opportunities = opportunities
            st.session_state.matched_pairs = raw_matches
            st.session_state.trad_events = trad_events
            st.session_state.poly_events = (
                poly_events  # store all, not just volume-filtered
            )
            st.session_state.last_update = datetime.now()

            # Write comparison debug file so matching can be inspected and tuned
            _write_match_debug_file(
                trad_events, poly_events, opportunities, selected_sport_label
            )
            st.caption("Debug written to match_debug.txt")

    # Display results
    if hasattr(st.session_state, "cross_platform_opportunities"):
        opportunities = st.session_state.cross_platform_opportunities
        trad_events = st.session_state.get("trad_events", [])
        poly_events = st.session_state.get("poly_events", [])

        # Calculate matched events (all raw matches, not just arb opportunities)
        matched_pairs = st.session_state.get("matched_pairs", [])
        matched_trad_count = len(matched_pairs)

        # Show summary stats
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Betfair Events", len(trad_events))
        with col2:
            st.metric("Polymarket Markets", len(poly_events))
        with col3:
            st.metric("Matched Events", matched_trad_count)
        with col4:
            st.metric("Arbitrage Opportunities", len(opportunities))

        # Show info about matching
        if matched_trad_count < len(trad_events) and trad_events:
            matched_bf_ids = {bf_ev.id for bf_ev, _, _ in matched_pairs}
            unmatched = [e for e in trad_events if e.id not in matched_bf_ids]
            with st.expander(f"{len(unmatched)} Betfair events unmatched"):
                for event in unmatched[:10]:
                    st.text(f"{event.home_team} vs {event.away_team} ({event.sport})")

        # Always show matched pairs (even when no arb profit)
        if matched_pairs:
            if opportunities:
                st.success(f"{len(opportunities)} arbitrage opportunities found")
                display_cross_platform_opportunities(
                    opportunities, investment_amount, gbp_usd_rate
                )
                st.divider()

            display_matched_pairs(matched_pairs, opportunities, investment_amount)

        else:
            st.warning("No cross-platform matches found.")
            st.divider()

            col1, col2 = st.columns(2)
            with col1:
                st.metric(
                    "Betfair Events",
                    (
                        len(st.session_state.trad_events)
                        if hasattr(st.session_state, "trad_events")
                        else 0
                    ),
                )
            with col2:
                st.metric(
                    "Polymarket Markets",
                    (
                        len(st.session_state.poly_events)
                        if hasattr(st.session_state, "poly_events")
                        else 0
                    ),
                )

            st.divider()

            if (
                hasattr(st.session_state, "trad_events")
                and st.session_state.trad_events
            ):
                with st.expander(
                    f"Betfair Events ({len(st.session_state.trad_events)})",
                    expanded=True,
                ):
                    display_traditional_events(st.session_state.trad_events)

            if (
                hasattr(st.session_state, "poly_events")
                and st.session_state.poly_events
            ):
                with st.expander(
                    f"Polymarket Markets ({len(st.session_state.poly_events)})",
                    expanded=True,
                ):
                    display_polymarket_markets(st.session_state.poly_events)

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


if __name__ == "__main__":
    main()
