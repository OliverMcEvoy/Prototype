"""
Polymarket API client.

Two APIs:
  GET /markets              — politics, crypto, general events
  GET /events?series_id=X  — individual sports match markets
"""

import requests
from datetime import datetime
from typing import List, Optional, Set
from models import PolymarketEvent
from config import Config


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
            if not series_id:
                continue
            raw_events = self._fetch_series_events(series_id, active_only=active_only)
            for event_data in raw_events:
                poly_event = self._parse_sports_event(event_data)
                if poly_event and poly_event.volume >= min_volume:
                    all_events.append(poly_event)

        print(f"[SPORTS API] Total sports match events: {len(all_events)}")
        return all_events

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
        Convert a Polymarket sports event (from /events?series_id=X) into a PolymarketEvent.

        Each event can have multiple markets (match-winner, toss, most-sixes, etc.).
        We only keep the primary match-winner market.
        """
        import json as _json

        slug = event_data.get("slug", "")
        title = event_data.get("title", "")

        # Skip secondary sub-markets that are grouped under the main event slug
        skip_slug_keywords = [
            "toss-match",
            "most-sixes",
            "team-top-batter",
            "more-markets",
            "completed",
        ]
        if any(kw in slug for kw in skip_slug_keywords):
            return None

        markets = event_data.get("markets", [])
        main_market = None
        for m in markets:
            if m.get("closed", False):
                continue
            if not m.get("active", True):
                continue
            q = m.get("question", "").lower()
            # Skip sub-markets that appear inside the event
            if any(
                kw in q
                for kw in [
                    "who wins the toss",
                    "most sixes",
                    "top batter",
                    "completed match",
                    "toss?",
                ]
            ):
                continue
            main_market = m
            break

        if not main_market:
            return None

        # Parse outcomes (JSON string → list)
        outcomes_raw = main_market.get("outcomes", [])
        prices_raw = main_market.get("outcomePrices", [])
        try:
            outcomes = (
                _json.loads(outcomes_raw)
                if isinstance(outcomes_raw, str)
                else list(outcomes_raw)
            )
        except Exception:
            return None
        try:
            prices_parsed = (
                _json.loads(prices_raw)
                if isinstance(prices_raw, str)
                else list(prices_raw)
            )
            prices = [float(p) for p in prices_parsed]
        except Exception:
            return None

        if not outcomes or len(outcomes) < 2 or not prices:
            return None

        # Parse end/game date
        end_date = None
        for date_field in ("endDateIso", "endDate", "gameStartTime"):
            date_str = event_data.get(date_field) or main_market.get(date_field)
            if date_str:
                try:
                    end_date = datetime.fromisoformat(
                        str(date_str).replace("Z", "+00:00")
                    )
                    break
                except Exception:
                    continue

        volume = float(main_market.get("volumeNum") or main_market.get("volume") or 0)
        liquidity = float(
            main_market.get("liquidityNum") or main_market.get("liquidity") or 0
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

                event = PolymarketEvent(
                    id=market_data.get("id", market_data.get("market_id", "")),
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
