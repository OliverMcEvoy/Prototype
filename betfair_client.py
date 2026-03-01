"""
Betfair Exchange API client.

Auth: POST identitysso.betfair.com/api/login → session_token
API:  api.betfair.com/exchange/betting/rest/v1.0/
"""

import requests
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Set

from models import Event, Outcome
from config import Config


class BetfairClient:
    """Client for Betfair Exchange API — UK regulated betting exchange."""

    LOGIN_URL = "https://identitysso.betfair.com/api/login"
    API_BASE = "https://api.betfair.com/exchange/betting/rest/v1.0"

    # Polymarket sport-hint → Betfair event type ID
    POLYMARKET_TO_BETFAIR: Dict[str, str] = {
        "soccer": "1",
        "tennis": "2",
        "cricket": "4",
        "rugby": "5",
        "basketball": "7514",
        "americanfootball": "7522",
        "baseball": "7511",
        "icehockey": "7524",
        "mma": "26420387",
    }

    # Politics has its own event type handled separately via get_politics_markets()
    POLITICS_EVENT_TYPE_ID = "2378961"

    BETFAIR_TO_POLYMARKET: Dict[str, str] = {
        v: k for k, v in POLYMARKET_TO_BETFAIR.items()
    }
    # Add politics separately so _build_events assigns correct category
    BETFAIR_TO_POLYMARKET["2378961"] = "politics"

    BETFAIR_SPORT_NAMES: Dict[str, str] = {
        "1": "Soccer",
        "2": "Tennis",
        "4": "Cricket",
        "5": "Rugby Union",
        "7514": "Basketball",
        "7522": "American Football",
        "7511": "Baseball",
        "7524": "Ice Hockey",
        "26420387": "MMA",
        "2378961": "Politics",
    }

    UI_SPORT_OPTIONS: Dict[str, str] = {
        "All Sports": "all",
        "Soccer": "soccer",
        "Cricket": "cricket",
        "Tennis": "tennis",
        "Basketball": "basketball",
        "American Football": "americanfootball",
        "Baseball": "baseball",
        "Ice Hockey": "icehockey",
        "MMA": "mma",
        "Rugby": "rugby",
    }

    def __init__(self, username: str, password: str, app_key: str):
        """
        Initialise the Betfair Exchange client.

        Args:
            username: Betfair account username / email
            password: Betfair account password
            app_key:  Betfair App Key (Delayed is free, Live needs approval)
        """
        self.username = username
        self.password = password
        self.app_key = app_key
        self.session_token: Optional[str] = None
        self.session = requests.Session()
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------ auth

    def login(self) -> bool:
        """Authenticate with Betfair and store the session token."""
        headers = {
            "X-Application": self.app_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Accept-Encoding": "identity",  # avoid gzip so Session can parse JSON reliably
        }
        data = {"username": self.username, "password": self.password}
        try:
            # Use requests.post directly (not self.session) for login —
            # the session object is kept for Exchange API calls only.
            resp = requests.post(self.LOGIN_URL, data=data, headers=headers, timeout=10)
            resp.raise_for_status()
            result = self._safe_json(resp)
            if result and result.get("status") == "SUCCESS":
                self.session_token = result["token"]
                self._last_error = None
                print("[BETFAIR] Login successful")
                return True
            else:
                self._last_error = (
                    result.get("error", "Unknown login error")
                    if result
                    else "Empty response"
                )
                print(f"[BETFAIR] Login failed: {self._last_error}")
                return False
        except requests.RequestException as e:
            self._last_error = str(e)
            print(f"[BETFAIR] Login error: {e}")
            return False

    def is_connected(self) -> bool:
        """Return True if a session token is currently held."""
        return self.session_token is not None

    def get_last_error(self) -> Optional[str]:
        """Return the last error message, if any."""
        return self._last_error

    def _ensure_logged_in(self) -> bool:
        """Ensure we have a valid session, logging in if necessary."""
        if not self.session_token:
            return self.login()
        return True

    def _safe_json(self, resp: requests.Response):
        """Parse JSON from response, handling gzip/encoding edge-cases."""
        import json, gzip

        try:
            return resp.json()
        except Exception:
            pass
        # Fallback: manual gzip decode
        try:
            raw = resp.content
            if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    # --------------------------------------------------------- raw API calls

    def _api_call(self, operation: str, params: dict) -> Optional[list]:
        """
        Make an authenticated POST to the Betfair Exchange REST API.

        Args:
            operation: API operation name (e.g. 'listEvents')
            params:    Request body as a dict

        Returns:
            Parsed JSON response (list or dict), or None on error.
        """
        if not self._ensure_logged_in():
            return None

        url = f"{self.API_BASE}/{operation}/"
        headers = {
            "X-Authentication": self.session_token,
            "X-Application": self.app_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            resp = self.session.post(url, json=params, headers=headers, timeout=15)

            # Session expired — re-login and retry once
            if resp.status_code == 401:
                self.session_token = None
                if not self.login():
                    return None
                resp = self.session.post(url, json=params, headers=headers, timeout=15)

            resp.raise_for_status()
            return self._safe_json(resp)

        except requests.RequestException as e:
            self._last_error = str(e)
            print(f"[BETFAIR] API error ({operation}): {e}")
            return None

    # -------------------------------------------------- intermediate helpers

    def _list_events(
        self,
        event_type_ids: List[str],
        days_ahead: int = 14,
        min_hours_ahead: float = 6,
    ) -> List[dict]:
        """
        List upcoming events for the given Betfair event-type IDs.

        Args:
            event_type_ids:   Betfair event-type IDs to query.
            days_ahead:       Upper bound — how many days ahead to include.
            min_hours_ahead:  Lower bound — skip events starting sooner than
                              this many hours from now (default 6h).

        Returns raw dicts: {'event': {...}, 'marketCount': N}
        """
        now = datetime.now(timezone.utc)
        start_from = now + timedelta(hours=min_hours_ahead)
        end_time = now + timedelta(days=days_ahead)

        params = {
            "filter": {
                "eventTypeIds": event_type_ids,
                "marketStartTime": {
                    "from": start_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            },
            "maxResults": 1000,
            "sort": "OPEN_DATE",
        }

        result = self._api_call("listEvents", params)
        return result or []

    def _list_market_catalogue(self, event_ids: List[str]) -> List[dict]:
        """
        Fetch Match Odds / Moneyline market catalogues for given event IDs.

        Batches requests in groups of 500 event IDs to stay within Betfair
        API limits while retrieving catalogues for all events.

        Returns raw market dicts including runner names.
        """
        if not event_ids:
            return []

        all_markets: List[dict] = []
        # Betfair recommends no more than 500 event IDs per filter call
        for i in range(0, len(event_ids), 500):
            batch = event_ids[i : i + 500]
            params = {
                "filter": {
                    "eventIds": batch,
                    # Match Odds = football/rugby h2h;  Moneyline = US sports h2h
                    "marketTypeCodes": ["MATCH_ODDS", "MONEYLINE"],
                },
                "marketProjection": [
                    "EVENT",
                    "RUNNER_DESCRIPTION",
                    "MARKET_START_TIME",
                    "EVENT_TYPE",
                ],
                "maxResults": 1000,
                "sort": "FIRST_TO_START",
            }
            result = self._api_call("listMarketCatalogue", params)
            if result:
                all_markets.extend(result)

        return all_markets

    def _list_market_book(self, market_ids: List[str]) -> List[dict]:
        """
        Fetch the best available *back* prices for given market IDs.

        Processes in batches of 40 (Betfair limit per call).
        """
        if not market_ids:
            return []

        all_books: List[dict] = []
        for i in range(0, len(market_ids), 40):
            batch = market_ids[i : i + 40]
            params = {
                "marketIds": batch,
                "priceProjection": {
                    "priceData": ["EX_BEST_OFFERS"],
                    "exBestOffersOverrides": {
                        "bestPricesDepth": 3,  # top 3 prices for both back and lay
                        "rollupModel": "STAKE",
                        "rollupLimit": 0,
                    },
                    "virtualise": False,
                },
                "orderProjection": "EXECUTABLE",
                "matchProjection": "NO_ROLLUP",
            }
            result = self._api_call("listMarketBook", params)
            if result:
                all_books.extend(result)

        return all_books

    # ------------------------------------------------ public entry points

    def get_odds(
        self,
        sport_hints: Optional[List[str]] = None,
        days_ahead: int = 14,
        min_hours_ahead: float = 6,
    ) -> List[Event]:
        """
        Fetch Betfair Exchange odds for sports matching the given sport hints.

        sport_hints are Polymarket-style sport prefixes such as
        'soccer', 'cricket', 'basketball', etc.  Pass None (or ['all'])
        to fetch all supported sports.

        Args:
            sport_hints:      List of sport keywords aligned with Polymarket codes.
            days_ahead:       How many calendar days ahead to include (upper bound).
            min_hours_ahead:  Skip events starting sooner than this many hours
                              from now. Default 6h (catches today's evening games).

        Returns:
            List of Event objects containing back AND lay odds from Betfair Exchange.
        """
        # Resolve sport hints → Betfair event type IDs
        if not sport_hints or sport_hints == ["all"]:
            event_type_ids = list(self.POLYMARKET_TO_BETFAIR.values())
        else:
            id_set: Set[str] = set()
            for hint in sport_hints:
                hint_lower = hint.lower()
                for poly_sport, bf_id in self.POLYMARKET_TO_BETFAIR.items():
                    if poly_sport in hint_lower or hint_lower in poly_sport:
                        id_set.add(bf_id)
            event_type_ids = list(id_set)

        if not event_type_ids:
            print(f"[BETFAIR] No event type IDs for sport hints: {sport_hints}")
            return []

        print(
            f"[BETFAIR] Querying event types {event_type_ids} "
            f"(+{min_hours_ahead}h to +{days_ahead} days ahead)"
        )

        # Step 1 — list events
        raw_events = self._list_events(event_type_ids, days_ahead, min_hours_ahead)
        print(f"[BETFAIR] {len(raw_events)} events found")
        if not raw_events:
            return []

        # Step 2 — get match odds market catalogues
        event_ids = [e["event"]["id"] for e in raw_events if "event" in e]
        markets = self._list_market_catalogue(event_ids)
        print(f"[BETFAIR] {len(markets)} Match Odds markets found")
        if not markets:
            return []

        # Step 3 — get live best-back prices
        market_ids = [m["marketId"] for m in markets]
        books = self._list_market_book(market_ids)

        # Index books by market ID
        book_index: Dict[str, dict] = {b["marketId"]: b for b in books}

        # Step 4 — assemble Event objects
        events = self._build_events(markets, book_index)
        print(f"[BETFAIR] Returning {len(events)} events with valid odds")
        return events

    def get_remaining_requests(self) -> Optional[int]:
        """Betfair has no fixed request quota."""
        return None

    def get_politics_markets(self, days_ahead: int = 400) -> List[Event]:
        """
        Fetch political prediction markets from Betfair Exchange.

        Uses event type 2378961 (Politics) with WINNER / OUTRIGHT_WINNER /
        NEXT_WINNER market types, which are the standard types for political
        markets on Betfair (not MATCH_ODDS which is sports-only).

        Args:
            days_ahead: How far ahead to scan (default 400 days to cover
                        elections that are months away).

        Returns:
            List of Event objects with category='politics'.
        """
        if not self._ensure_logged_in():
            return []

        now = datetime.now(timezone.utc)
        end_time = now + timedelta(days=days_ahead)

        params = {
            "filter": {
                "eventTypeIds": [self.POLITICS_EVENT_TYPE_ID],
                "marketStartTime": {
                    "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "to": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
            },
            "maxResults": 1000,
            "sort": "OPEN_DATE",
        }
        raw_events = self._api_call("listEvents", params) or []
        print(f"[BETFAIR POLITICS] {len(raw_events)} events found")
        if not raw_events:
            return []

        event_ids = [e["event"]["id"] for e in raw_events if "event" in e]

        all_markets: List[dict] = []
        for i in range(0, len(event_ids), 500):
            batch = event_ids[i : i + 500]
            result = self._api_call(
                "listMarketCatalogue",
                {
                    "filter": {
                        "eventIds": batch,
                        # No marketTypeCodes filter — political markets use a wide
                        # variety of types (WINNER, OUTRIGHT_WINNER, NEXT_WINNER,
                        # SPECIAL, MATCH_ODDS, etc.) that vary by region and event.
                        # Filtering by type would silently exclude valid markets.
                    },
                    "marketProjection": [
                        "EVENT",
                        "RUNNER_DESCRIPTION",
                        "MARKET_START_TIME",
                        "EVENT_TYPE",
                        "MARKET_DESCRIPTION",
                    ],
                    "maxResults": 1000,
                    "sort": "FIRST_TO_START",
                },
            )
            if result:
                all_markets.extend(result)
                # Debug: show the market types actually returned so the filter can be
                # tuned if needed (visible in app.py sidebar caption and terminal).
                types_seen = {m.get("description", {}).get("marketType", "?") for m in result}
                print(f"[BETFAIR POLITICS] market types in batch: {sorted(types_seen)}")

        print(f"[BETFAIR POLITICS] {len(all_markets)} markets found")
        if not all_markets:
            return []

        market_ids = [m["marketId"] for m in all_markets]
        books = self._list_market_book(market_ids)
        book_index = {b["marketId"]: b for b in books}

        events = self._build_events(all_markets, book_index)
        print(f"[BETFAIR POLITICS] {len(events)} valid political markets with odds")
        return events

    # ------------------------------------------------ model building

    def _build_events(
        self, markets: List[dict], book_index: Dict[str, dict]
    ) -> List[Event]:
        """Convert Betfair market + book data into canonical Event objects."""
        events: List[Event] = []

        for market in markets:
            market_id = market.get("marketId", "")
            book = book_index.get(market_id)
            if not book:
                continue

            # ---- metadata ----
            event_type = market.get("eventType", {})
            event_type_id = event_type.get("id", "")
            sport_name = self.BETFAIR_SPORT_NAMES.get(
                event_type_id, event_type.get("name", "Unknown")
            )

            start_time_str = market.get("marketStartTime", "")
            try:
                commence_time = datetime.fromisoformat(
                    start_time_str.replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                commence_time = datetime.now(timezone.utc)

            # ---- runners ----
            # Build a selectionId → runnerName map from the catalogue
            runner_name_map: Dict[int, str] = {
                r["selectionId"]: r.get("runnerName", "Unknown")
                for r in market.get("runners", [])
            }

            outcomes: List[Outcome] = []
            runner_names: List[str] = []

            for runner_book in book.get("runners", []):
                if runner_book.get("status") != "ACTIVE":
                    continue

                sel_id = runner_book.get("selectionId")
                runner_name = runner_name_map.get(sel_id, f"Runner {sel_id}")

                ex = runner_book.get("ex", {})

                # Best available BACK price and available size
                available_to_back = ex.get("availableToBack", [])
                best_back = (
                    float(available_to_back[0].get("price", 0.0))
                    if available_to_back
                    else 0.0
                )
                back_size = sum(float(l.get("size", 0.0)) for l in available_to_back)

                # Best available LAY price (what the market will accept to lay)
                available_to_lay = ex.get("availableToLay", [])
                best_lay = (
                    float(available_to_lay[0].get("price", 0.0))
                    if available_to_lay
                    else 0.0
                )
                lay_size = sum(float(l.get("size", 0.0)) for l in available_to_lay)

                if best_back <= 1.0 and best_lay <= 1.0:
                    continue  # No usable prices at all

                if best_back > 1.0:
                    outcomes.append(
                        Outcome(
                            name=runner_name,
                            price=best_back,
                            bookmaker="Betfair Exchange",
                            last_update=datetime.now(timezone.utc),
                            volume=back_size,
                        )
                    )

                if best_lay > 1.0:
                    # Store lay as a separate Outcome with negative-convention flag:
                    # price stored as the lay decimal odds so the engine can
                    # compute implied probability = 1/lay_odds for the layer.
                    outcomes.append(
                        Outcome(
                            name=runner_name,
                            price=best_lay,
                            bookmaker="Betfair Lay",
                            last_update=datetime.now(timezone.utc),
                            volume=lay_size,
                        )
                    )

                if runner_name not in runner_names:
                    runner_names.append(runner_name)

            # Need at least 2 sides for arbitrage
            if len(outcomes) < 2:
                continue

            poly_sport = self.BETFAIR_TO_POLYMARKET.get(event_type_id, "sports")

            # Capture market name + parent event name so downstream text
            # matching (especially district codes like "CA-22") has something
            # to work with beyond just the runner names.
            market_name = market.get("marketName", "")
            event_obj = market.get("event") or {}
            event_name = event_obj.get("name", "") if isinstance(event_obj, dict) else ""
            desc_parts = [p for p in [event_name, market_name] if p and p.strip()]
            description = " — ".join(desc_parts) if desc_parts else None

            events.append(
                Event(
                    id=market_id,
                    sport=sport_name,
                    commence_time=commence_time,
                    home_team=runner_names[0],
                    away_team=runner_names[1],
                    outcomes=outcomes,
                    category=poly_sport,
                    description=description,
                )
            )

        return events
