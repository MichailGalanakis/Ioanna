"""The passive core, wired end to end.

Ties together the five pieces built so far: the schedule says money is due,
the rebalancer says where it goes, the governor says whether the order is
allowed, the journal records why before it leaves, and the tax ledger records
the cost basis when it fills.

The ordering is the point. Every order is reviewed *and* journalled before it
can be sent, and neither step is reachable from the strategy side -- a
strategy cannot skip the governor by calling something else, because there is
nothing else to call.

Note the hypotheses here are generated mechanically from the allocation
policy, not written by a model. That is deliberate: it demonstrates the
journal works for rule-based decisions too, and it means the passive core
carries the same audit trail as anything the research layer will later
propose. A rebalance that cannot state which band it breached does not
execute.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Mapping

from ..governor import (
    Decision,
    Governor,
    OrderRequest,
    PortfolioState,
    Side,
)
from ..journal import Hypothesis, Journal
from .allocation import TargetAllocation
from .dca import Contribution, ContributionSchedule, next_contribution
from .rebalance import Action, ActionKind, RebalancePlan, Rebalancer, Trigger
from .taxlots import TaxLedger


@dataclass(frozen=True)
class OrderIntent:
    """One planned order, with the governor's verdict attached.

    Refused intents are kept rather than dropped. A cycle that produced four
    orders and had one refused is a different event from a cycle that produced
    three, and only the first is worth investigating.
    """

    action: Action
    order: OrderRequest
    decision: Decision
    position_id: int | None = None

    @property
    def approved(self) -> bool:
        return self.decision.approved


@dataclass(frozen=True)
class CycleResult:
    ran_at: datetime
    contribution: Contribution | None
    plan: RebalancePlan
    intents: tuple[OrderIntent, ...]

    @property
    def approved(self) -> tuple[OrderIntent, ...]:
        return tuple(i for i in self.intents if i.approved)

    @property
    def refused(self) -> tuple[OrderIntent, ...]:
        return tuple(i for i in self.intents if not i.approved)

    @property
    def did_nothing(self) -> bool:
        return not self.intents


class PassiveCore:
    """Runs one DCA/rebalance cycle at a time.

    Stateless between cycles by design: holdings, cash and the last
    contribution date are passed in, so the authoritative state stays with the
    reconciliation layer rather than being cached here where it could drift
    from what the broker actually holds.
    """

    def __init__(
        self,
        allocation: TargetAllocation,
        schedule: ContributionSchedule,
        governor: Governor,
        journal: Journal,
        ledger: TaxLedger,
        rebalancer: Rebalancer | None = None,
        venue: str = "ibkr",
        pillar: str = "core",
    ) -> None:
        self.allocation = allocation
        self.schedule = schedule
        self.governor = governor
        self.journal = journal
        self.ledger = ledger
        self.rebalancer = rebalancer or Rebalancer(allocation)
        self.venue = venue
        self.pillar = pillar

    # -- one cycle ----------------------------------------------------------

    def run_cycle(
        self,
        prices: Mapping[str, Decimal],
        quantities: Mapping[str, Decimal],
        last_contribution: date,
        now: datetime | None = None,
        trades_today: int = 0,
        peak_equity: Decimal | None = None,
        liquidity: Mapping[str, Decimal] | None = None,
        allow_sales: bool = True,
    ) -> CycleResult:
        """Plan, review and journal. Does not send anything.

        Execution is a separate call (`settle`) so that a cycle can be run and
        inspected without side effects at the broker -- which is what shadow
        mode needs, and what Gate 1 is verified against.
        """
        ts = now or datetime.now(timezone.utc)

        held = {i: q for i, q in quantities.items() if q > 0}
        missing = sorted(set(held) - set(prices))
        if missing:
            raise ValueError(
                f"no price for held instrument(s): {', '.join(missing)}. "
                "Valuing a portfolio with a gap in it would understate every "
                "weight that depends on the total."
            )

        holdings = {i: q * prices[i] for i, q in held.items()}

        contribution = next_contribution(
            self.schedule, last_contribution, ts.date()
        )
        cash = contribution.amount if contribution else Decimal(0)

        if not holdings and cash == 0:
            raise ValueError("no holdings and no contribution due")

        plan = self.rebalancer.plan(holdings, cash, allow_sales=allow_sales)

        equity = sum(holdings.values(), Decimal(0)) + cash
        peak = peak_equity if peak_equity is not None else equity

        # State advances as the cycle proceeds. Reviewing every order against
        # the state at the top of the cycle would let a plan with six orders
        # through a five-order budget, and would measure each position limit
        # as though the other orders in the same cycle did not exist.
        positions = dict(holdings)
        pillar_total = sum(holdings.values(), Decimal(0))
        trades = trades_today

        intents = []
        for action in plan.actions:
            state = PortfolioState(
                equity=equity,
                peak_equity=peak,
                positions=dict(positions),
                pillar_exposure={self.pillar: pillar_total},
                trades_today=trades,
            )
            intent = self._review_and_journal(
                action, plan, prices, state, liquidity, ts
            )
            intents.append(intent)

            if not intent.approved:
                continue

            delta = (
                action.value
                if action.kind is ActionKind.BUY
                else -action.value
            )
            positions[action.instrument] = max(
                Decimal(0), positions.get(action.instrument, Decimal(0)) + delta
            )
            pillar_total = max(Decimal(0), pillar_total + delta)
            if not intent.order.reduce_only:
                trades += 1

        return CycleResult(
            ran_at=ts,
            contribution=contribution,
            plan=plan,
            intents=tuple(intents),
        )

    def _review_and_journal(
        self,
        action: Action,
        plan: RebalancePlan,
        prices: Mapping[str, Decimal],
        state: PortfolioState,
        liquidity: Mapping[str, Decimal] | None,
        ts: datetime,
    ) -> OrderIntent:
        price = prices.get(action.instrument)
        if price is None or price <= 0:
            raise ValueError(f"no usable price for {action.instrument!r}")

        order = OrderRequest(
            instrument=action.instrument,
            venue=self.venue,
            side=Side.BUY if action.kind is ActionKind.BUY else Side.SELL,
            quantity=action.value / price,
            reference_price=price,
            strategy_pillar=self.pillar,
            # Sells in the core are position reductions, which keeps them
            # legal during a halt and out of the daily trade budget.
            reduce_only=action.kind is ActionKind.SELL,
            venue_liquidity=(liquidity or {}).get(action.instrument),
        )

        decision = self.governor.review(order, state)
        if not decision.approved:
            return OrderIntent(action, order, decision, position_id=None)

        position_id = self.journal.open_position(
            instrument=action.instrument,
            venue=self.venue,
            side=order.side.value,
            quantity=order.quantity,
            entry_price=price,
            strategy_pillar=self.pillar,
            hypothesis=self._hypothesis(action, plan, ts),
            opened_at=ts,
        )
        return OrderIntent(action, order, decision, position_id=position_id)

    # -- the written record -------------------------------------------------

    def _hypothesis(
        self, action: Action, plan: RebalancePlan, ts: datetime
    ) -> Hypothesis:
        """Generate the pre-trade record from the allocation policy.

        Mechanical, but not boilerplate: the drift figures and the band that
        was breached are the actual reason this order exists, and recording
        them is what makes a later "why did we sell in March" answerable.
        """
        drift = plan.drifts[action.instrument]
        target_pct = drift.target_weight * 100
        current_pct = drift.current_weight * 100
        band_pct = self.rebalancer.bands.threshold_for(drift.target_weight) * 100

        if action.trigger is Trigger.CONTRIBUTION:
            text = (
                f"Scheduled contribution. Allocation policy directs new "
                f"capital toward underweight holdings; {action.instrument} "
                f"sits at {current_pct:.2f}% against a {target_pct:.2f}% "
                f"target, so {action.value:.2f} of the contribution is "
                f"allocated here."
            )
            counter = (
                "Contributing on a schedule buys at whatever price the market "
                "offers today, including near a peak. Accepted as policy: "
                "there is no evidence that timing entries beats contributing "
                "consistently, and waiting for a better price is the decision "
                "this system exists to avoid making."
            )
            invalidation = (
                "The target allocation is revised, or contributions stop."
            )
        elif action.trigger is Trigger.BAND_BREACH:
            text = (
                f"{action.instrument} has drifted to {current_pct:.2f}% "
                f"against a {target_pct:.2f}% target, outside its "
                f"{band_pct:.2f} point tolerance band. Threshold rebalancing "
                f"restores the target weight."
            )
            counter = (
                "This sale realises a capital gain taxable at 15%, and the "
                "contribution-first path did not close the gap this cycle. "
                "Rebalancing also sells the better performer, which costs "
                "return if the trend continues."
                if action.kind is ActionKind.SELL
                else
                "The band may be breached by a temporary move that would "
                "revert on its own, making this order pure cost. The band "
                "width is the accepted trade-off between that risk and "
                "letting the allocation drift indefinitely."
            )
            invalidation = (
                "The holding returns inside its band before the order fills."
            )
        else:  # UNTARGETED
            text = (
                f"{action.instrument} is held at {current_pct:.2f}% of the "
                f"portfolio but carries no target weight in the allocation. "
                f"Liquidating in full."
            )
            counter = (
                "The position may have been opened deliberately by another "
                "pillar and simply not reflected in this allocation. Check "
                "before executing that this is genuinely an orphan holding."
            )
            invalidation = "The allocation is revised to include this holding."

        return Hypothesis(
            text=text,
            supporting_data={
                "target_weight": str(drift.target_weight),
                "current_weight": str(drift.current_weight),
                "value_gap": str(drift.value_gap),
                "band_threshold": str(
                    self.rebalancer.bands.threshold_for(drift.target_weight)
                ),
                "trigger": action.trigger.value,
                "breaches_this_cycle": sorted(plan.breaches),
            },
            counter_argument=counter,
            invalidation=invalidation,
            exit_plan=(
                "Held indefinitely as part of the passive core. Position is "
                "reduced only when its weight breaches the tolerance band, or "
                "when the target allocation changes. No time-based exit."
            ),
        )

    # -- after the fill -----------------------------------------------------

    def settle(
        self,
        intent: OrderIntent,
        fill_price: Decimal,
        fill_quantity: Decimal,
        at: datetime | None = None,
        fees: Decimal = Decimal(0),
    ) -> None:
        """Record a fill against the tax ledger.

        Called by the execution layer once the broker confirms. Cost basis is
        recorded here and nowhere else, so a fill that never reaches this
        method is a hole in the tax record -- which is why reconciliation
        compares ledger quantities against broker positions every cycle.
        """
        if not intent.approved:
            raise ValueError("cannot settle an order the governor refused")
        if fill_quantity <= 0:
            raise ValueError("fill quantity must be positive")

        ts = at or datetime.now(timezone.utc)

        if intent.order.side is Side.BUY:
            self.ledger.acquire(
                intent.action.instrument, fill_quantity, fill_price, ts, fees
            )
        else:
            self.ledger.dispose(
                intent.action.instrument, fill_quantity, fill_price, ts, fees
            )
