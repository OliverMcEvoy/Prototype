"""
Arbitrage detection engine for identifying profitable betting opportunities.

Cross-platform strategy:
  Back arbitrage  — back outcome A on Betfair, back "A wins" on Polymarket
                    at prices whose combined implied probability < 1.0

  Lay arbitrage   — Polymarket prices outcome A at implied probability P.
                    If the Betfair lay price L satisfies P > 1/L then
                    laying on Betfair while backing "A wins" on Polymarket
                    locks in a risk-free profit.

  For sports events Polymarket outcomes are team names (e.g. "Real Madrid",
  "Getafe", "Draw"), NOT binary Yes/No.  The engine resolves which Betfair
  runner corresponds to which Polymarket outcome via MarketMatcher.align_outcomes().
"""

from typing import List, Dict, Tuple, Optional
from models import Event, Outcome, ArbitrageOpportunity, PolymarketEvent
from utils import calculate_arbitrage, normalize_team_name


class ArbitrageEngine:
    """Engine for detecting and calculating arbitrage opportunities."""

    def __init__(self, min_profit_threshold: float = 0.0):
        self.min_profit_threshold = min_profit_threshold

    # ------------------------------------------------------------------
    # Single-platform arbitrage (unchanged)
    # ------------------------------------------------------------------

    def find_arbitrage_opportunities(
        self, events: List[Event]
    ) -> List[ArbitrageOpportunity]:
        opportunities = []
        for event in events:
            opp = self.check_event_arbitrage(event)
            if opp and opp.is_profitable(self.min_profit_threshold):
                opportunities.append(opp)
        opportunities.sort(key=lambda x: x.profit_percentage, reverse=True)
        return opportunities

    def check_event_arbitrage(self, event: Event) -> Optional[ArbitrageOpportunity]:
        """Check a single combined Event for back-back arbitrage."""
        best_odds = self._find_best_back_odds(event.outcomes)
        if len(best_odds) < 2:
            return None
        odds_list = [o.price for o in best_odds.values()]
        arb = calculate_arbitrage(odds_list)
        if not arb["is_arbitrage"]:
            return None

        stake_dist: Dict[str, float] = {}
        best_list: List[Outcome] = []
        for (name, outcome), stake_info in zip(
            best_odds.items(), arb["stake_distribution"]
        ):
            stake_dist[f"{outcome.name} ({outcome.bookmaker})"] = stake_info["stake"]
            best_list.append(outcome)

        total_stake = arb["total_stake"]
        profit_pct = arb["profit_percentage"]
        return ArbitrageOpportunity(
            event=event,
            best_outcomes=best_list,
            total_stake=total_stake,
            stake_distribution=stake_dist,
            profit=total_stake * (profit_pct / 100),
            profit_percentage=profit_pct,
            roi=profit_pct,
        )

    # ------------------------------------------------------------------
    # Cross-platform arbitrage
    # ------------------------------------------------------------------

    def compare_markets(
        self, traditional_events: List[Event], polymarket_events: List
    ) -> List[ArbitrageOpportunity]:
        """
        Compare Betfair and Polymarket for arbitrage, using both back-back
        and lay-back strategies.

        For each matched pair:
          1. Back-back: best Betfair back price vs best Polymarket implied odds
             → standard implied-probability sum check
          2. Lay-back: Betfair lay price vs Polymarket back price
             → profit if Polymarket implied prob > 1/lay_odds
        """
        from market_matcher import MarketMatcher

        matcher = MarketMatcher()
        matches = matcher.find_matches(traditional_events, polymarket_events)

        opportunities: List[ArbitrageOpportunity] = []

        for trad_event, poly_event, similarity in matches:
            # --- Back-back arbitrage ---
            back_opp = self._check_back_back(
                trad_event, poly_event, similarity, matcher
            )
            if back_opp and back_opp.is_profitable(self.min_profit_threshold):
                back_opp.event.description = (
                    f"[BACK-BACK] {similarity:.1%} match: {back_opp.event.description}"
                )
                opportunities.append(back_opp)

            # --- Lay-back arbitrage ---
            lay_opps = self._check_lay_back(trad_event, poly_event, similarity)
            for lo in lay_opps:
                if lo.is_profitable(self.min_profit_threshold):
                    lo.event.description = (
                        f"[LAY-BACK] {similarity:.1%} match: {lo.event.description}"
                    )
                    opportunities.append(lo)

        opportunities.sort(key=lambda x: x.profit_percentage, reverse=True)
        return opportunities

    # ------------------------------------------------------------------
    # Back-back strategy
    # ------------------------------------------------------------------

    def _check_back_back(
        self,
        trad_event: Event,
        poly_event,
        similarity: float,
        matcher,
    ) -> Optional[ArbitrageOpportunity]:
        """
        Build a combined event merging aligned outcomes, then run standard
        implied-probability arbitrage check.

        Outcome alignment:
          Betfair runner "Real Madrid"  ↔  Polymarket outcome "Real Madrid"
          Betfair runner "Getafe"       ↔  Polymarket outcome "Getafe"
          Betfair runner "The Draw"     ↔  Polymarket outcome "Draw"  (if present)

        The BEST price across both platforms is used for each outcome.
        """
        # Get aligned pairs: [(bf_runner_name, pm_outcome_name), ...]
        aligned = matcher.align_outcomes(trad_event, poly_event)

        if not aligned:
            return None

        # Build a synthetic combined event with the best price per aligned outcome
        pm_decimal_odds = poly_event.to_decimal_odds()
        pm_price_map = {
            name: odds
            for name, odds in zip(poly_event.outcomes, pm_decimal_odds)
            if odds > 1.0
        }
        from datetime import datetime

        synthetic_outcomes: List[Outcome] = []
        for bf_runner_name, pm_outcome_name in aligned:
            # Best Betfair back price for this runner
            bf_backs = [
                o
                for o in trad_event.outcomes
                if o.name == bf_runner_name and o.bookmaker == "Betfair Exchange"
            ]
            bf_best = max(bf_backs, key=lambda o: o.price) if bf_backs else None

            # Polymarket odds for the aligned outcome
            pm_odds = pm_price_map.get(pm_outcome_name)
            pm_out = (
                Outcome(
                    name=pm_outcome_name,
                    price=pm_odds,
                    bookmaker="Polymarket",
                    last_update=datetime.now(),
                )
                if pm_odds and pm_odds > 1.0
                else None
            )

            # Pick whichever is better
            if bf_best and pm_out:
                best = bf_best if bf_best.price >= pm_out.price else pm_out
            elif bf_best:
                best = bf_best
            elif pm_out:
                best = pm_out
            else:
                continue

            synthetic_outcomes.append(best)

        if len(synthetic_outcomes) < 2:
            return None

        # For any Betfair back runner that was NOT covered by the aligned pairs
        # (e.g. the "No" side of a binary PM market, or a runner whose name
        # failed fuzzy alignment), add its best Betfair back price so the full
        # implied-probability sum is computed correctly.
        from market_matcher import _canonicalise as _can

        covered_cans = {_can(o.name) for o in synthetic_outcomes}
        seen_extra: set = set(covered_cans)
        for o in trad_event.outcomes:
            if o.bookmaker == "Betfair Lay":
                continue
            bf_can = _can(o.name)
            if bf_can in seen_extra:
                continue
            seen_extra.add(bf_can)
            # Best Betfair back price for this uncovered runner
            bf_backs = [
                x
                for x in trad_event.outcomes
                if x.bookmaker == "Betfair Exchange" and _can(x.name) == bf_can
            ]
            if bf_backs:
                synthetic_outcomes.append(max(bf_backs, key=lambda x: x.price))

        # Sanity check: a valid cross-platform arb needs outcomes from at least
        # two different bookmakers. If every outcome's best price happens to sit
        # on the same platform the implied-probability arithmetic is meaningless.
        platforms_used = {o.bookmaker for o in synthetic_outcomes}
        if len(platforms_used) < 2:
            return None

        combined = Event(
            id=f"{trad_event.id}_combined",
            sport=trad_event.sport,
            commence_time=trad_event.commence_time,
            home_team=trad_event.home_team,
            away_team=trad_event.away_team,
            outcomes=synthetic_outcomes,
            category=trad_event.category,
            description=f"{trad_event} / Polymarket: {poly_event.question}",
            match_quality=similarity,
        )
        return self.check_event_arbitrage(combined)

    # ------------------------------------------------------------------
    # Lay-back strategy
    # ------------------------------------------------------------------

    def _resolve_binary_pm_name(
        self, pm_name: str, pm_question: str, trad_event: Event
    ) -> Optional[str]:
        """
        For binary Yes/No Polymarket markets, resolve 'Yes' to the actual team
        name by searching for a Betfair runner name within the question text.
        Returns None for 'No' outcomes or if no team can be identified.
        """
        from market_matcher import _canonicalise

        if pm_name.lower() not in {"yes", "no"}:
            return pm_name  # already a real team/outcome name
        if pm_name.lower() == "no":
            return None  # 'No' has no direct team mapping
        # Scan question for a Betfair runner name
        q_can = _canonicalise(pm_question)
        for outcome in trad_event.outcomes:
            team_can = _canonicalise(outcome.name)
            if team_can in self._DRAW_VARIANTS:
                continue
            if team_can and team_can in q_can:
                return outcome.name
        return None

    def _check_lay_back(
        self,
        trad_event: Event,
        poly_event,
        similarity: float,
    ) -> List[ArbitrageOpportunity]:
        """
        Lay-back: for each outcome where Polymarket prices it higher than
        the Betfair market does, we can:
          - Back the outcome on Polymarket (buy at Polymarket price)
          - Lay it on Betfair (act as bookmaker, collect if outcome doesn't happen)

        Profit condition:
          poly_price > 1 / bf_lay_odds
          i.e. Polymarket implied probability > Betfair implied probability for that outcome

        Each such pair produces a standalone ArbitrageOpportunity.
        """
        from datetime import datetime as _dt

        opps: List[ArbitrageOpportunity] = []

        pm_decimal_odds = poly_event.to_decimal_odds()
        for pm_name, pm_odds in zip(poly_event.outcomes, pm_decimal_odds):
            if pm_odds <= 1.0:
                continue

            # Resolve binary Yes/No outcomes to the actual team name
            effective_name = self._resolve_binary_pm_name(
                pm_name, poly_event.question, trad_event
            )
            if effective_name is None:
                continue  # skip "No" and unresolvable binaries

            pm_prob = 1.0 / pm_odds  # implied probability from Polymarket price

            # Find matching Betfair LAY price for this outcome
            from market_matcher import _canonicalise

            pm_can = _canonicalise(effective_name)

            for outcome in trad_event.outcomes:
                if outcome.bookmaker != "Betfair Lay":
                    continue
                bf_can = _canonicalise(outcome.name)
                if bf_can != pm_can and pm_can not in bf_can and bf_can not in pm_can:
                    continue

                lay_price = outcome.price
                if lay_price <= 1.0:
                    continue

                lay_implied = 1.0 / lay_price  # bookmaker's implied probability

                # Lay-back is profitable when Polymarket pays MORE than
                # what the layer pays out on Betfair.
                # Net profit per £1 on Polymarket:
                #   If outcome happens: win (1/pm_price - 1) on Polymarket,
                #                       lose (lay_price - 1) on Betfair
                #   If outcome doesn't: lose £1 on Polymarket,
                #                       keep liability stake on Betfair
                # For a £1 back on Polymarket, we lay £(pm_odds / lay_odds)
                # on Betfair so that both legs pay out the same.
                # Simplified: profit % = (1 - pm_implied/lay_implied) * 100

                if pm_prob <= lay_implied:
                    continue  # No edge

                profit_pct = (1.0 - pm_prob / lay_implied) * 100.0
                if profit_pct <= 0:
                    continue

                # Stake distribution: scale to £100 total
                pm_stake = 100.0 * lay_implied  # back on Polymarket
                bf_lay_stake = 100.0 * pm_prob  # lay liability on Betfair

                synthetic_event = Event(
                    id=f"{trad_event.id}_lay_{effective_name}",
                    sport=trad_event.sport,
                    commence_time=trad_event.commence_time,
                    home_team=trad_event.home_team,
                    away_team=trad_event.away_team,
                    outcomes=[
                        Outcome(effective_name, pm_odds, "Polymarket", _dt.now()),
                        Outcome(outcome.name, lay_price, "Betfair Lay", _dt.now()),
                    ],
                    category=trad_event.category,
                    description=(
                        f"LAY {outcome.name} on Betfair @ {lay_price:.2f} / "
                        f"BACK {effective_name} on Polymarket @ {pm_odds:.2f}"
                    ),
                    match_quality=similarity,
                )

                opp = ArbitrageOpportunity(
                    event=synthetic_event,
                    best_outcomes=[
                        Outcome(effective_name, pm_odds, "Polymarket", _dt.now()),
                        Outcome(outcome.name, lay_price, "Betfair Lay", _dt.now()),
                    ],
                    total_stake=pm_stake + bf_lay_stake,
                    stake_distribution={
                        f"{effective_name} (Polymarket Back)": pm_stake,
                        f"{outcome.name} (Betfair Lay)": bf_lay_stake,
                    },
                    profit=(pm_stake + bf_lay_stake) * (profit_pct / 100),
                    profit_percentage=profit_pct,
                    roi=profit_pct,
                )
                opps.append(opp)

        return opps

    # ------------------------------------------------------------------
    # Candidate-level binary arb (multi-candidate elections)
    # ------------------------------------------------------------------

    def check_candidate_arb(
        self,
        bf_event: Event,
        runner_name: str,
        pm_binary_event: PolymarketEvent,
        similarity: float,
    ) -> List[ArbitrageOpportunity]:
        """
        For a multi-candidate election where a single Betfair runner is matched
        to a Polymarket binary YES/NO market about that specific candidate.

        Two strategies are checked:

        Strategy A — Back BF + Buy NO on Polymarket:
            Betfair underestimates this candidate vs Polymarket.
            Combined implied probability: 1/BF_back + PM_NO < 1
            Condition:   PM_YES > 1 / BF_back
            Profit %:    (BF_back × PM_YES − 1) / (1 + BF_back × PM_NO) × 100

        Strategy B — Lay BF + Buy YES on Polymarket:
            Polymarket is more bullish than Betfair's lay market.
            Condition:   PM_YES > 1 / BF_lay
            Profit %:    (1 − BF_lay_implied / PM_YES) × 100
        """
        from datetime import datetime as _dt

        opps: List[ArbitrageOpportunity] = []

        # BF prices for this specific runner only
        bf_backs = [
            o for o in bf_event.outcomes
            if o.bookmaker == "Betfair Exchange" and o.name == runner_name
        ]
        bf_lays = [
            o for o in bf_event.outcomes
            if o.bookmaker == "Betfair Lay" and o.name == runner_name
        ]
        if not bf_backs:
            return []

        bf_back_price = max(o.price for o in bf_backs)
        bf_lay_price  = max((o.price for o in bf_lays), default=None)

        # PM binary prices: find YES / NO indices
        pm_outcomes = pm_binary_event.outcomes or []
        pm_prices   = pm_binary_event.prices   or []
        if len(pm_outcomes) < 2 or len(pm_prices) < 2:
            return []

        yes_idx = next((i for i, o in enumerate(pm_outcomes) if o.lower() == "yes"), 0)
        no_idx  = 1 - yes_idx
        pm_yes  = pm_prices[yes_idx]   # probability in [0, 1] that candidate wins
        pm_no   = pm_prices[no_idx]    # probability in [0, 1] that candidate loses

        if pm_yes <= 0 or pm_no <= 0:
            return []

        bf_implied = 1.0 / bf_back_price
        runner_key = runner_name.replace(" ", "_")

        # ── Strategy A: Back BF + Buy NO on PM ───────────────────────────────
        # Arb when PM is more bullish on the candidate than BF is.
        # Combined implied: 1/BF_back + PM_NO  (since PM_NO = the "no" leg)
        # Arb condition: 1/BF_back + PM_NO < 1  ↔  PM_YES > 1/BF_back
        if pm_yes > bf_implied:
            raw_profit  = bf_back_price * pm_yes - 1.0
            denominator = 1.0 + bf_back_price * pm_no
            profit_pct  = raw_profit / denominator * 100.0

            if profit_pct > 0:
                bf_stake   = 100.0 / denominator
                pm_no_cost = 100.0 - bf_stake  # = bf_stake × BF_back × pm_no

                synthetic = Event(
                    id=f"{bf_event.id}_back_no_{runner_key}",
                    sport=bf_event.sport,
                    commence_time=bf_event.commence_time,
                    home_team=runner_name,
                    away_team="(all others)",
                    outcomes=[
                        Outcome(runner_name,           bf_back_price, "Betfair Exchange", _dt.now()),
                        Outcome(f"NO — {runner_name}", 1.0 / pm_no,  "Polymarket",       _dt.now()),
                    ],
                    category=bf_event.category,
                    description=(
                        f"BACK {runner_name} on Betfair @ {bf_back_price:.2f} "
                        f"(BF implied {bf_implied:.1%}) + "
                        f"BUY NO on Polymarket @ {pm_no:.2f} "
                        f"(PM YES = {pm_yes:.1%})"
                    ),
                    match_quality=similarity,
                )
                opps.append(ArbitrageOpportunity(
                    event=synthetic,
                    best_outcomes=[
                        Outcome(runner_name,           bf_back_price, "Betfair Exchange", _dt.now()),
                        Outcome(f"NO — {runner_name}", 1.0 / pm_no,  "Polymarket",       _dt.now()),
                    ],
                    total_stake=100.0,
                    stake_distribution={
                        f"Back {runner_name} (Betfair)":        round(bf_stake, 2),
                        f"Buy NO — {runner_name} (Polymarket)": round(pm_no_cost, 2),
                    },
                    profit=100.0 * profit_pct / 100.0,
                    profit_percentage=profit_pct,
                    roi=profit_pct,
                ))

        # ── Strategy B: Lay BF + Buy YES on PM ───────────────────────────────
        if bf_lay_price and bf_lay_price > 1.0:
            lay_implied = 1.0 / bf_lay_price
            if pm_yes > lay_implied:
                profit_pct   = (1.0 - lay_implied / pm_yes) * 100.0
                if profit_pct > 0:
                    pm_yes_dec   = 1.0 / pm_yes
                    pm_stake     = 100.0 * lay_implied
                    bf_lay_stake = 100.0 * pm_yes

                    synthetic = Event(
                        id=f"{bf_event.id}_lay_yes_{runner_key}",
                        sport=bf_event.sport,
                        commence_time=bf_event.commence_time,
                        home_team=runner_name,
                        away_team="(all others)",
                        outcomes=[
                            Outcome(f"YES — {runner_name}", pm_yes_dec,   "Polymarket",  _dt.now()),
                            Outcome(runner_name,            bf_lay_price, "Betfair Lay", _dt.now()),
                        ],
                        category=bf_event.category,
                        description=(
                            f"LAY {runner_name} on Betfair @ {bf_lay_price:.2f} "
                            f"(lay implied {lay_implied:.1%}) + "
                            f"BUY YES on Polymarket @ {pm_yes:.2f}"
                        ),
                        match_quality=similarity,
                    )
                    opps.append(ArbitrageOpportunity(
                        event=synthetic,
                        best_outcomes=[
                            Outcome(f"YES — {runner_name}", pm_yes_dec,   "Polymarket",  _dt.now()),
                            Outcome(runner_name,            bf_lay_price, "Betfair Lay", _dt.now()),
                        ],
                        total_stake=pm_stake + bf_lay_stake,
                        stake_distribution={
                            f"Buy YES — {runner_name} (Polymarket)": round(pm_stake, 2),
                            f"Lay {runner_name} (Betfair)":          round(bf_lay_stake, 2),
                        },
                        profit=(pm_stake + bf_lay_stake) * (profit_pct / 100),
                        profit_percentage=profit_pct,
                        roi=profit_pct,
                    ))

        return opps

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    _DRAW_VARIANTS: set = {"the draw", "draw", "tie", "drawn", "x"}

    def _outcome_key(self, name: str) -> str:
        """Normalise outcome name for deduplication; maps draw variants to 'draw'."""
        n = normalize_team_name(name)
        return "draw" if n in self._DRAW_VARIANTS else n

    def _find_best_back_odds(self, outcomes: List[Outcome]) -> Dict[str, Outcome]:
        """
        For back-back arbitrage: find the best BACK price for each unique outcome.
        Lay outcomes (bookmaker='Betfair Lay') are excluded here — they are handled
        separately in _check_lay_back.
        Draw variants ('The Draw', 'draw', 'tie') are merged under the key 'draw'.
        """
        best: Dict[str, Outcome] = {}
        for outcome in outcomes:
            if outcome.bookmaker == "Betfair Lay":
                continue  # lays handled separately
            key = self._outcome_key(outcome.name)
            if key not in best or outcome.price > best[key].price:
                best[key] = outcome
        return best

    # Keep old name for any callers
    def _find_best_odds(self, outcomes: List[Outcome]) -> Dict[str, Outcome]:
        return self._find_best_back_odds(outcomes)

    def calculate_optimal_stakes(
        self, opportunity: ArbitrageOpportunity, total_investment: float
    ) -> Dict[str, float]:
        odds_list = [o.price for o in opportunity.best_outcomes]
        total_implied = sum(1.0 / o for o in odds_list)
        return {
            f"{o.name} ({o.bookmaker})": round(
                (total_investment / total_implied) * (1.0 / o.price), 2
            )
            for o in opportunity.best_outcomes
        }

    def find_niche_opportunities(
        self, polymarket_events: List, min_volume: float = 1000.0
    ) -> List[ArbitrageOpportunity]:
        opportunities = []
        for poly_event in polymarket_events:
            if poly_event.volume < min_volume:
                continue
            if not poly_event.prices or all(p <= 0 for p in poly_event.prices):
                continue
            event = self._polymarket_to_event(poly_event)
            if len(event.outcomes) < 2:
                continue
            opp = self.check_event_arbitrage(event)
            if opp and opp.is_profitable(self.min_profit_threshold):
                opportunities.append(opp)
        return opportunities

    def _polymarket_to_event(self, poly_event) -> Event:
        from datetime import datetime

        outcomes = []
        for name, odds in zip(poly_event.outcomes, poly_event.to_decimal_odds()):
            if odds > 0:
                outcomes.append(
                    Outcome(
                        name=name,
                        price=odds,
                        bookmaker="Polymarket",
                        last_update=datetime.now(),
                    )
                )
        return Event(
            id=poly_event.id,
            sport="Polymarket",
            commence_time=poly_event.end_date or datetime.now(),
            home_team=poly_event.outcomes[0] if poly_event.outcomes else "Yes",
            away_team=poly_event.outcomes[1] if len(poly_event.outcomes) > 1 else "No",
            outcomes=outcomes,
            category="prediction_market",
            description=poly_event.question,
            match_quality=1.0,
        )

    def _find_matching_polymarket_event(self, trad_event, poly_events):
        for pe in poly_events:
            if (
                trad_event.home_team.lower() in pe.get("question", "").lower()
                or trad_event.away_team.lower() in pe.get("question", "").lower()
            ):
                return pe
        return None
