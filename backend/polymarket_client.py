"""
Polymarket API client.

Two APIs:
  GET /markets              — politics, crypto, general events
  GET /events?series_id=X  — individual sports match markets
"""

import requests
from datetime import datetime
from typing import List, Optional, Set
from backend.models import PolymarketEvent
from backend.config import Config


class PolymarketClient:
    """Client for Polymarket API."""

    # Map generic sport categories to Polymarket sport codes (from /sports endpoint)
    SPORT_CODE_MAP = {
        "cricket": {
            "crint",
            "t20",
            "odi",
            "test",
            "crban",
            "craus",
            "creng",
            "crind",
            "crpak",
            "crsou",
            "cruae",
            "crnew",
            "cricipl",
            "cricpsl",
            "cricsm",
            "cricbbl",
            "cricbpl",
            "crict20lpl",
            "cricsa20",
            "crwpl20",
            "crwncl",
            "cru19wc",
            "crict20blast",
            "cricilt20",
            "cricmlc",
            "criccpl",
            "criccsat20w",
            "crafgwi20",
            "crbtnmlyhkg20",
            "crwt20wcgq",
        },
        "soccer": {
            "epl",
            "bun",
            "lal",
            "ucl",
            "uel",
            "efl",
            "fl1",
            "sea",
            "col",
            "afc",
            "ere",
            "arg",
            "itc",
            "mex",
            "lcs",
            "lib",
            "tur",
            "mls",
            "bra",
            "jap",
            "kor",
            "ind",
            "nor",
            "den",
            "por",
            "chi",
            "fif",
            "acn",
            "ofc",
            "cof",
            "uef",
            "caf",
            "con",
            "mar1",
            "egy1",
            "cze1",
            "bol1",
            "rou1",
            "bra2",
            "per1",
            "col1",
            "chi1",
            "ukr1",
            "uwcl",
            "wll",
        },
        "basketball": {
            "nba",
            "ncaab",
            "cbb",
            "wnba",
            "cwbb",
            "euroleague",
            "bkcl",
            "bkseriea",
            "bkfr1",
            "bkarg",
            "bkkbl",
            "bkcba",
            "bknbl",
            "bkligend",
        },
        "americanfootball": {"nfl", "cfb"},
        "baseball": {"mlb", "kbo", "wbc"},
        "tennis": {"atp", "wta", "wttmen"},
        "icehockey": {"nhl", "shl", "khl", "ahl", "cehl", "dehl", "snhl"},
        "mma": {"ufc", "zuffa"},
        "esports": {
            "dota2",
            "lol",
            "val",
            "cs2",
            "mlbb",
            "ow",
            "codmw",
            "fifa",
            "pubg",
            "r6siege",
            "rl",
            "wildrift",
            "sc2",
            "sc",
        },
        "rugby": {
            "rusixnat",
            "rueuchamp",
            "ruurc",
            "rusrp",
            "ruchamp",
            "rutopft",
            "ruprem",
        },
        "lacrosse": {"pll", "wll"},
    }

    def __init__(self, base_url: str = None):
        """
        Initialize the Polymarket client.

        Args:
            base_url: Base URL for Polymarket API
        """
        self.base_url = base_url or Config.POLYMARKET_API_URL
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._markets_cache = None  # Cache for prediction markets
        self._sports_series_cache = None  # Cache for /sports series list

    def get_markets(
        self, limit: int = 100, active_only: bool = True, category: Optional[str] = None
    ) -> List[PolymarketEvent]:
        """
        Fetch available prediction markets.

        Args:
            limit: Maximum number of markets to fetch
            active_only: Only fetch active markets
            category: Filter by category (Politics, Crypto, Pop Culture, etc.)

        Returns:
            List of PolymarketEvent objects
        """
        url = f"{self.base_url}/markets"
        params = {"limit": limit, "closed": not active_only}

        if category:
            params["tag"] = category

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            markets = self._parse_markets(data)
            print(f"[POLYMARKET] {len(markets)} markets fetched")
            return markets
        except requests.exceptions.RequestException as e:
            print(f"Error fetching Polymarket markets: {e}")
            return []

    def get_markets_by_category(
        self, category: str, limit: int = 50
    ) -> List[PolymarketEvent]:
        """
        Fetch markets filtered by category.

        Args:
            category: Category name (Politics, Crypto, Sports, etc.)
            limit: Maximum markets to return

        Returns:
            List of PolymarketEvent objects in that category
        """
        return self.get_markets(limit=limit, active_only=True, category=category)

    def get_trending_markets(self, limit: int = 100) -> List[PolymarketEvent]:
        """
        Fetch trending/high-volume markets.

        Args:
            limit: Maximum markets to return

        Returns:
            List of trending PolymarketEvent objects
        """
        markets = self.get_markets(limit=500, active_only=True)

        # Sort by volume and return top markets
        markets.sort(key=lambda m: m.volume, reverse=True)
        return markets[:limit]

    def search_markets(self, query: str) -> List[PolymarketEvent]:
        """Polymarket search API does not filter by query. Returns empty list."""
        return []

    def get_politics_markets(
        self,
        active_only: bool = True,
        min_volume: float = 0,
    ) -> List[PolymarketEvent]:
        """
        Fetch Polymarket political prediction markets.

        Uses two approaches and merges results:

        1. /events endpoint with 'politics' tag — returns multi-outcome events
           such as "Which party will win the House in 2026?" with outcomes
           like ["Republican", "Democrat", "Other"].  This is the same
           structure as sports events and is parsed by _parse_sports_event().

        2. /markets endpoint with tag=Politics — returns individual binary
           Yes/No markets.  These are also included so nothing is missed.
           They are tagged sport_category="politics" and left as-is; the
           matcher handles Yes/No binary political markets the same way it
           handles binary tennis markets.

        Args:
            active_only: Only include active, non-resolved markets.
            min_volume:  Minimum volume threshold.

        Returns:
            List of PolymarketEvent objects with sport_category='politics'.
        """
        seen_ids: set = set()
        all_events: List[PolymarketEvent] = []

        # ── Approach 1: /events with politics-related tag slugs ──────────────
        _POLITICS_TAGS = ("politics", "us-politics", "elections", "political")
        for tag in _POLITICS_TAGS:
            params: dict = {
                "limit": 200,
                "tag_slug": tag,
            }
            if active_only:
                params["active"] = "true"
                params["closed"] = "false"
            try:
                resp = self.session.get(
                    f"{self.base_url}/events", params=params, timeout=10
                )
                if not resp.ok:
                    continue
                data = resp.json() or []
                for ev_data in data:
                    pe = self._parse_sports_event(ev_data)
                    if pe and pe.id not in seen_ids and pe.volume >= min_volume:
                        pe.sport_category = "politics"
                        all_events.append(pe)
                        seen_ids.add(pe.id)
            except Exception as e:
                print(f"[POLITICS] /events error (tag={tag}): {e}")

        print(f"[POLITICS] {len(all_events)} events from /events endpoint")

        # ── Approach 2: /markets with Politics category tag ──────────────────
        try:
            url = f"{self.base_url}/markets"
            params2: dict = {"limit": 500, "closed": not active_only, "tag": "Politics"}
            resp2 = self.session.get(url, params=params2, timeout=10)
            if resp2.ok:
                binary_markets = self._parse_markets(resp2.json())
                for m in binary_markets:
                    if m.id not in seen_ids and m.volume >= min_volume:
                        m.sport_category = "politics"
                        all_events.append(m)
                        seen_ids.add(m.id)
                print(f"[POLITICS] +{len(binary_markets)} from /markets")
        except Exception as e:
            print(f"[POLITICS] /markets error: {e}")

        print(f"[POLITICS] Total political markets: {len(all_events)}")
        return all_events

    # -------------------------------------------------------------------------
    # SPORTS BETTING API  (completely separate from prediction market API above)
    # Individual match markets (e.g. "India vs West Indies") are ONLY here.
    # -------------------------------------------------------------------------

    def get_sports_markets(
        self,
        sport_hint: str = None,
        active_only: bool = True,
        min_volume: float = 0,
    ) -> List[PolymarketEvent]:
        """
        Fetch individual sports match markets from Polymarket's series-based API.

        This is the CORRECT endpoint for sports events like "India vs West Indies".
        The general /markets endpoint does NOT include these.

        Args:
            sport_hint: Traditional odds-API sport key (e.g. 'cricket_icc_men_t20_world_cup',
                        'soccer_epl', 'basketball_nba').  Pass None / 'upcoming' to fetch all.
            active_only: Only fetch active, non-closed events.
            min_volume: Minimum market volume to include.

        Returns:
            List of PolymarketEvent objects (match-winner markets only).
        """
        sports_list = self._get_sports_series()
        if not sports_list:
            print("[SPORTS API] Could not fetch sports series list")
            return []

        relevant_codes = self._get_relevant_sport_codes(sport_hint)
        if relevant_codes:
            relevant_series = [
                s for s in sports_list if s.get("sport", "") in relevant_codes
            ]
            print(
                f"[SPORTS API] sport_hint='{sport_hint}' → {len(relevant_codes)} codes "
                f"→ {len(relevant_series)} series to fetch"
            )
        else:
            relevant_series = sports_list
            print(f"[SPORTS API] Fetching all {len(relevant_series)} sports series")

        all_events: List[PolymarketEvent] = []
        for sport_entry in relevant_series:
            series_id = sport_entry.get("series")
            # Skip entries with no ID or placeholder "TBD" (causes 422 error)
            if not series_id or str(series_id).strip().upper() == "TBD":
                continue
            sport_code = sport_entry.get("sport", "")
            sport_category = self._code_to_category(sport_code)
            raw_events = self._fetch_series_events(series_id, active_only=active_only)
            for event_data in raw_events:
                poly_event = self._parse_sports_event(event_data)
                if poly_event and poly_event.volume >= min_volume:
                    poly_event.sport_category = sport_category
                    all_events.append(poly_event)

        print(f"[SPORTS API] Total sports match events: {len(all_events)}")
        return all_events

    def _code_to_category(self, sport_code: str) -> str:
        """Map a Polymarket sport code (e.g. 'epl', 'nba') to a broad category."""
        for category, codes in self.SPORT_CODE_MAP.items():
            if sport_code in codes:
                return category
        return ""

    def _get_sports_series(self) -> List[dict]:
        """Fetch and cache the list of all Polymarket sport series from /sports."""
        if self._sports_series_cache:
            return self._sports_series_cache

        url = f"{self.base_url}/sports"
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            self._sports_series_cache = resp.json() or []
            print(f"[SPORTS API] Cached {len(self._sports_series_cache)} sport series")
            return self._sports_series_cache
        except Exception as e:
            print(f"[SPORTS API] Error fetching /sports: {e}")
            return []

    def _get_relevant_sport_codes(self, sport_hint: str) -> Set[str]:
        """
        Convert a traditional odds-API sport key into Polymarket sport codes.

        Returns an empty set to mean "fetch all".
        """
        if not sport_hint or sport_hint.strip().lower() in ("upcoming", "all", ""):
            return set()

        hint = sport_hint.lower()
        codes: Set[str] = set()

        for category, category_codes in self.SPORT_CODE_MAP.items():
            if category in hint:
                codes.update(category_codes)

        # Fallback: check if any part of the hint matches a known code directly
        if not codes:
            parts = set(hint.split("_"))
            for category_codes in self.SPORT_CODE_MAP.values():
                codes.update(parts & category_codes)

        return codes

    def _fetch_series_events(
        self, series_id: str, active_only: bool = True
    ) -> List[dict]:
        """
        Fetch ALL events for a single series from /events?series_id=X.

        Paginates automatically using offset so no events are missed even
        in large series (e.g. EPL with 200+ fixtures).
        """
        url = f"{self.base_url}/events"
        page_size = 500  # maximum supported by Polymarket API
        all_events: List[dict] = []
        offset = 0

        while True:
            params: dict = {
                "series_id": str(series_id),
                "limit": page_size,
                "offset": offset,
            }
            if active_only:
                params["active"] = "true"
                params["closed"] = "false"
            try:
                resp = self.session.get(url, params=params, timeout=10)
                resp.raise_for_status()
                page = resp.json() or []
            except Exception as e:
                print(
                    f"[SPORTS API] Error fetching series {series_id} offset {offset}: {e}"
                )
                break

            if not page:
                break

            all_events.extend(page)

            # If fewer results than page_size, we've reached the last page
            if len(page) < page_size:
                break

            offset += page_size

        return all_events

    def _parse_sports_event(self, event_data: dict) -> Optional[PolymarketEvent]:
        """
        Convert a Polymarket sports event into a PolymarketEvent.

        Polymarket sports events come in two structural forms:

        Form A — multi-outcome market (tennis, basketball, hockey, etc.):
          Single market with outcomes like ["Nuggets", "Grizzlies"] or
          ["Stricker", "Grenier"]. Used as-is.

        Form B — per-outcome binary markets (soccer, rugby, etc.):
          Three separate binary Yes/No markets:
            "Will Arsenal win?"                    → Yes price = Arsenal win prob
            "Will Arsenal vs Chelsea end in a draw?" → Yes price = Draw prob
            "Will Chelsea win?"                    → Yes price = Chelsea win prob
          These are reconstructed into a single synthetic 3-outcome market.
        """
        import json as _json
        import re as _re

        slug = event_data.get("slug", "")
        title = event_data.get("title", "")

        _SLUG_SKIP = [
            "toss-match",
            "most-sixes",
            "team-top-batter",
            "more-markets",
            "completed",
        ]
        if any(kw in slug for kw in _SLUG_SKIP):
            return None

        # Sub-market keywords — skip these regardless of form
        _SUB_KWS = [
            "who wins the toss",
            "most sixes",
            "top batter",
            "completed match",
            "toss?",
            "set 1",
            "set 2",
            "set 3",
            "o/u",
            "over/under",
            "spread:",
            "correct score",
            "first goal",
            "first scorer",
            "half time",
            "halftime",
            "ht/ft",
            "half-time",
            "yellow card",
            "red card",
            "total goals",
            "both teams to score",
        ]
        _BINARY = {"yes", "no"}
        _DRAW_KWS = ("draw", "tie")
        _WIN_RE = _re.compile(r"will\s+(.+?)\s+win\b", _re.IGNORECASE)

        def _parse_outcomes_prices(m):
            """Return (outcomes list, prices list) or (None, None) on failure."""
            try:
                outs_raw = m.get("outcomes", [])
                outs = (
                    _json.loads(outs_raw)
                    if isinstance(outs_raw, str)
                    else list(outs_raw)
                )
            except Exception:
                return None, None
            try:
                p_raw = m.get("outcomePrices", [])
                prices = [
                    float(p)
                    for p in (_json.loads(p_raw) if isinstance(p_raw, str) else p_raw)
                ]
            except Exception:
                return None, None
            return outs, prices

        markets = event_data.get("markets", [])
        ref_market = None  # used for date/volume extraction
        outcomes = None
        prices = None

        # --- Path A: look for a non-binary match-result market ---
        for m in markets:
            if m.get("closed", False) or not m.get("active", True):
                continue
            q = m.get("question", "").lower()
            if any(kw in q for kw in _SUB_KWS):
                continue
            outs, ps = _parse_outcomes_prices(m)
            if outs is None or len(outs) < 2 or not ps:
                continue
            if not all(o.lower() in _BINARY for o in outs):
                ref_market = m
                outcomes = outs
                prices = ps
                break

        if outcomes is not None:
            # Non-binary market found — straightforward case (tennis/basketball/hockey)
            pass

        else:
            # --- Path B: reconstruct multi-outcome from binary per-outcome markets ---
            # Soccer: "Will Arsenal win?" + "Will match end in a draw?" + "Will Chelsea win?"
            # Rugby:  same structure
            win_outcomes = []  # [(team_name, yes_price, market)]
            draw_price = None

            for m in markets:
                if m.get("closed", False) or not m.get("active", True):
                    continue
                q_raw = m.get("question", "")
                q = q_raw.lower()
                if any(kw in q for kw in _SUB_KWS):
                    continue
                outs, ps = _parse_outcomes_prices(m)
                if outs is None or len(outs) < 2 or not ps:
                    continue
                if not all(o.lower() in _BINARY for o in outs):
                    continue  # already handled above

                # Get the "Yes" price
                try:
                    yes_idx = [o.lower() for o in outs].index("yes")
                    yes_price = ps[yes_idx]
                except (ValueError, IndexError):
                    yes_price = ps[0]

                if any(kw in q for kw in _DRAW_KWS):
                    draw_price = yes_price
                    if ref_market is None:
                        ref_market = m
                else:
                    m_win = _WIN_RE.search(q_raw)
                    if m_win:
                        team = m_win.group(1).strip()
                        win_outcomes.append((team, yes_price, m))
                        if ref_market is None:
                            ref_market = m

            if len(win_outcomes) < 2:
                return None

            # Build synthetic outcomes: [TeamA, TeamB] + optional Draw
            outcomes = [t for t, _, _ in win_outcomes]
            prices = [p for _, p, _ in win_outcomes]
            if draw_price is not None:
                outcomes.append("Draw")
                prices.append(draw_price)

        if outcomes is None or len(outcomes) < 2 or not prices:
            return None
        if ref_market is None:
            ref_market = markets[0] if markets else {}

        # Parse event date.
        # Priority: startTime (actual match start) > gameStartTime (market-level
        # match start) > endDate (tournament end — too late for tennis/golf) >
        # endDateIso (fallback).
        # Using the match start time is critical for the date pre-filter in
        # MarketMatcher.find_matches(), which allows ±3 days.  Tournament endDate
        # can be 5-7 days after the match, which blows the filter.
        end_date = None
        for date_str in (
            event_data.get("startTime"),
            ref_market.get("gameStartTime"),
            event_data.get("endDate"),
            ref_market.get("endDate"),
            ref_market.get("endDateIso"),
        ):
            if not date_str:
                continue
            try:
                end_date = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
                break
            except Exception:
                continue

        # Aggregate volume/liquidity across all markets in the event
        volume = sum(float(m.get("volumeNum") or m.get("volume") or 0) for m in markets)
        liquidity = sum(
            float(m.get("liquidityNum") or m.get("liquidity") or 0) for m in markets
        )

        return PolymarketEvent(
            id=slug or str(event_data.get("id", "")),
            question=title,
            outcomes=outcomes,
            prices=prices,
            end_date=end_date,
            volume=volume,
            liquidity=liquidity,
        )

    def _parse_markets(self, data: dict) -> List[PolymarketEvent]:
        """Parse API response into PolymarketEvent objects."""
        markets = []

        # Handle both list and dict responses
        market_list = data if isinstance(data, list) else data.get("data", [])

        for idx, market_data in enumerate(market_list):
            try:
                outcomes = []
                prices = []

                import json

                outcomes_raw = market_data.get("outcomes")
                prices_raw = market_data.get("outcomePrices")

                # Parse outcomes (handle JSON string format)
                outcomes_list = []
                if isinstance(outcomes_raw, str):
                    try:
                        outcomes_list = json.loads(outcomes_raw)
                    except Exception:
                        outcomes_list = []
                elif isinstance(outcomes_raw, list):
                    outcomes_list = outcomes_raw

                # Parse prices (handle JSON string format)
                prices_list = []
                if isinstance(prices_raw, str):
                    try:
                        prices_list = json.loads(prices_raw)
                    except Exception:
                        prices_list = []
                elif isinstance(prices_raw, list):
                    prices_list = prices_raw

                # Process outcomes
                if isinstance(outcomes_list, list) and len(outcomes_list) > 0:
                    for outcome in outcomes_list:
                        if isinstance(outcome, str):
                            outcomes.append(outcome)
                        elif isinstance(outcome, dict):
                            outcomes.append(outcome.get("name", "Unknown"))
                        else:
                            outcomes.append(str(outcome))

                # Process prices
                if isinstance(prices_list, list) and len(prices_list) > 0:
                    for price in prices_list:
                        try:
                            prices.append(float(price))
                        except (ValueError, TypeError):
                            prices.append(0.5)

                # Fallback: try tokens format (older API format)
                if not outcomes or not prices:
                    tokens = market_data.get("tokens", [])
                    if tokens and isinstance(tokens, list):
                        for token in tokens:
                            outcome_name = token.get("outcome", token.get("name", ""))
                            if outcome_name:
                                outcomes.append(outcome_name)
                                price = float(
                                    token.get("price", token.get("lastPrice", 0.5))
                                )
                                prices.append(price)

                if not outcomes:
                    continue

                # Ensure prices list matches outcomes list length
                while len(prices) < len(outcomes):
                    prices.append(0.5)

                # Parse end date if available
                end_date = None
                end_date_str = (
                    market_data.get("endDateIso")
                    or market_data.get("end_date_iso")
                    or market_data.get("endDate")
                    or market_data.get("end_time")
                )
                if end_date_str:
                    try:
                        end_date = datetime.fromisoformat(
                            end_date_str.replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                # Extract the parent event slug (e.g. 'next-prime-minister-of-hungary')
                # so URLs point to the event page, not the individual market page.
                _parent_events = market_data.get("events") or []
                _parent_slug = (
                    _parent_events[0].get("slug", "")
                    if _parent_events and isinstance(_parent_events[0], dict)
                    else ""
                ) or ""

                event = PolymarketEvent(
                    id=market_data.get("slug")
                    or market_data.get("id", market_data.get("market_id", "")),
                    question=market_data.get("question", market_data.get("title", "")),
                    outcomes=outcomes,
                    prices=prices,
                    end_date=end_date,
                    volume=float(
                        market_data.get("volume", market_data.get("volumeNum", 0))
                    ),
                    liquidity=float(
                        market_data.get("liquidity", market_data.get("liquidityNum", 0))
                    ),
                    event_slug=_parent_slug or None,
                )

                # Only add if we have valid data
                if event.outcomes and event.prices and len(event.outcomes) > 0:
                    markets.append(event)
            except (ValueError, KeyError, TypeError) as e:
                print(f"[POLYMARKET] Error parsing market {idx}: {e}")
                continue

        print(f"[POLYMARKET] {len(markets)} markets parsed")
        return markets

    def get_market_by_id(self, market_id: str) -> Optional[PolymarketEvent]:
        """
        Fetch a specific market by ID.

        Args:
            market_id: Market identifier

        Returns:
            PolymarketEvent or None
        """
        url = f"{self.base_url}/markets/{market_id}"

        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            parsed = self._parse_markets([data])
            return parsed[0] if parsed else None
        except requests.exceptions.RequestException as e:
            print(f"Error fetching market {market_id}: {e}")
            return None
