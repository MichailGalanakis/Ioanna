"""Threshold rebalancing, cash-flow first.

Two decisions are encoded here, and both cost real money if made the naive
way.

**Bands, not the calendar.** Rebalancing on a fixed schedule trades whether or
not anything has drifted. Daryanani's *Opportunistic Rebalancing* (Journal of
Financial Planning, 2007) found threshold-based rebalancing worth an extra
30-80bp a year over annual rebalancing, and that the right cadence is to
*check* often while *acting* rarely. Swedroe's 5/25 rule is the usual
formulation: act when a holding drifts by the lesser of 5 percentage points
absolute or 25% of its target weight relative. The relative leg is what makes
small sleeves work -- a 5% target would otherwise have to double before an
absolute 5-point band noticed.

**Contributions before sales.** Selling to rebalance realises a capital gain,
taxed at 15% in Greece. Directing new money at whatever is underweight moves
the portfolio toward target at zero tax cost. So the planner spends the
contribution first and only sells if the bands are still breached afterwards
-- which, during accumulation, is most of the time.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Mapping

from .allocation import Drift, TargetAllocation


class ActionKind(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Trigger(str, Enum):
    CONTRIBUTION = "contribution"
    """New money being allocated. Never a taxable event."""

    BAND_BREACH = "band_breach"
    """A holding outside its tolerance band, requiring a sale."""

    UNTARGETED = "untargeted_holding"
    """Something held that the allocation does not call for at all."""


@dataclass(frozen=True)
class Action:
    instrument: str
    kind: ActionKind
    value: Decimal
    trigger: Trigger
    components: tuple[tuple[Trigger, Decimal], ...] = ()
    """Set when several triggers were merged into one order.

    A contribution and a band breach can both call for buying the same fund
    in the same cycle. They are one order -- sending two would pay two
    commissions for one position change -- but the journal should still show
    that both reasons applied.
    """

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError("action value must be positive")

    @property
    def is_merged(self) -> bool:
        return len(self.components) > 1


@dataclass(frozen=True)
class RebalancePlan:
    actions: tuple[Action, ...]
    drifts: dict[str, Drift]
    breaches: frozenset[str]
    contribution_deployed: Decimal
    cash_remaining: Decimal

    @property
    def is_empty(self) -> bool:
        return not self.actions

    @property
    def requires_sales(self) -> bool:
        """Whether the plan realises gains. Worth surfacing before execution."""
        return any(a.kind is ActionKind.SELL for a in self.actions)

    @property
    def turnover(self) -> Decimal:
        return sum((a.value for a in self.actions), Decimal(0))


@dataclass(frozen=True)
class RebalanceBands:
    """Tolerance bands, in the 5/25 form.

    `absolute` is in weight points (0.05 = 5 percentage points), `relative` is
    a fraction of the target weight (0.25 = 25%). The effective threshold for
    a holding is the smaller of the two, so large sleeves are governed by the
    absolute band and small ones by the relative band.
    """

    absolute: Decimal = Decimal("0.05")
    relative: Decimal = Decimal("0.25")

    def __post_init__(self) -> None:
        if self.absolute <= 0 or self.absolute > 1:
            raise ValueError("absolute band must be in (0, 1]")
        if self.relative <= 0:
            raise ValueError("relative band must be positive")

    def threshold_for(self, target_weight: Decimal) -> Decimal:
        """Drift, in weight points, that this holding may take before acting."""
        if target_weight == 0:
            # Nothing is tolerated in a holding with no target.
            return Decimal(0)
        return min(self.absolute, target_weight * self.relative)

    def is_breached(self, drift: Drift) -> bool:
        if drift.target_weight == 0:
            return drift.current_value > 0
        return abs(drift.absolute) > self.threshold_for(drift.target_weight)


class Rebalancer:
    """Turns a target allocation plus current holdings into an order plan.

    `min_order` suppresses dust. A €3 correction on a €40k portfolio is
    noise that costs a commission to act on, and generating it would make the
    plan look busy while achieving nothing.
    """

    def __init__(
        self,
        allocation: TargetAllocation,
        bands: RebalanceBands | None = None,
        min_order: Decimal = Decimal("50"),
    ) -> None:
        if min_order < 0:
            raise ValueError("min_order must be non-negative")
        self.allocation = allocation
        self.bands = bands or RebalanceBands()
        self.min_order = min_order

    def plan(
        self,
        holdings: Mapping[str, Decimal],
        contribution: Decimal = Decimal(0),
        allow_sales: bool = True,
    ) -> RebalancePlan:
        """Build the order plan.

        Contribution is deployed first, against the post-contribution targets.
        Sales are considered only for bands still breached afterwards, and
        only when `allow_sales` permits -- setting it False gives a
        contribution-only mode that can never realise a gain.
        """
        if contribution < 0:
            raise ValueError("contribution must be non-negative")

        current_total = sum(holdings.values(), Decimal(0))
        if current_total + contribution <= 0:
            raise ValueError("nothing to allocate")

        # Targets are computed against the portfolio as it will be once the
        # contribution lands, so the new money is aimed at where the weights
        # are going rather than where they have been.
        post_total = current_total + contribution
        targets = self.allocation.target_values(post_total, holdings)

        actions: list[Action] = []
        projected = dict(holdings)

        deployed = Decimal(0)
        if contribution > 0:
            buys = self._allocate_contribution(holdings, targets, contribution)
            for instrument, amount in buys.items():
                actions.append(
                    Action(instrument, ActionKind.BUY, amount, Trigger.CONTRIBUTION)
                )
                projected[instrument] = projected.get(instrument, Decimal(0)) + amount
                deployed += amount

        # Re-measure against the portfolio as it will stand after the buys.
        drifts = self.allocation.drifts(projected)
        breaches = frozenset(
            name for name, d in drifts.items() if self.bands.is_breached(d)
        )

        if allow_sales:
            actions.extend(self._correct_breaches(drifts, breaches))

        return RebalancePlan(
            actions=self._merge(actions),
            drifts=drifts,
            breaches=breaches,
            contribution_deployed=deployed,
            cash_remaining=contribution - deployed,
        )

    # -- contribution -------------------------------------------------------

    def _allocate_contribution(
        self,
        holdings: Mapping[str, Decimal],
        targets: Mapping[str, Decimal],
        contribution: Decimal,
    ) -> dict[str, Decimal]:
        """Spend new money on whatever is furthest below target.

        If the contribution cannot close every gap it is split in proportion
        to the gaps, which drives every underweight holding toward target at
        the same rate rather than fully fixing one and ignoring the rest.
        """
        gaps = {
            instrument: targets[instrument] - holdings.get(instrument, Decimal(0))
            for instrument in targets
            if targets[instrument] - holdings.get(instrument, Decimal(0)) > 0
        }
        if not gaps:
            # Everything is at or above target: fall back to target weights so
            # the cash is still invested rather than left sitting.
            gaps = {
                i: w for i, w in self.allocation.weights.items() if w > 0
            }

        total_gap = sum(gaps.values(), Decimal(0))
        if total_gap <= 0:
            return {}

        if total_gap <= contribution:
            # Every gap closes, and the surplus goes in at target weights.
            allocated = dict(gaps)
            surplus = contribution - total_gap
            for instrument, weight in self.allocation.weights.items():
                if weight > 0:
                    allocated[instrument] = (
                        allocated.get(instrument, Decimal(0)) + surplus * weight
                    )
        else:
            allocated = {
                instrument: contribution * (gap / total_gap)
                for instrument, gap in gaps.items()
            }

        return {i: v for i, v in allocated.items() if v >= self.min_order}

    # -- merging ------------------------------------------------------------

    def _merge(self, actions: list[Action]) -> tuple[Action, ...]:
        """Collapse to one order per instrument, netting buys against sells.

        Without this a cycle can emit a contribution buy and a band-breach buy
        for the same fund, which is two commissions for one position change.
        Netting also means a plan can never contain both sides of the same
        instrument -- a shape that would look like wash trading to a broker
        and would be pure cost to us.
        """
        totals: dict[str, Decimal] = {}
        parts: dict[str, list[tuple[Trigger, Decimal]]] = {}

        for action in actions:
            signed = (
                action.value if action.kind is ActionKind.BUY else -action.value
            )
            totals[action.instrument] = totals.get(action.instrument, Decimal(0)) + signed
            parts.setdefault(action.instrument, []).append(
                (action.trigger, signed)
            )

        merged: list[Action] = []
        for instrument in sorted(totals):
            net = totals[instrument]
            if abs(net) < self.min_order:
                # Legs that cancel out leave nothing worth sending.
                continue

            components = tuple(parts[instrument])
            merged.append(
                Action(
                    instrument=instrument,
                    kind=ActionKind.BUY if net > 0 else ActionKind.SELL,
                    value=abs(net),
                    # The largest leg names the order; the rest stay visible
                    # in `components` for the journal.
                    trigger=max(components, key=lambda c: abs(c[1]))[0],
                    components=components,
                )
            )

        # Sells before buys. A rebalance funds its buys from its sells, so
        # sending the buys first asks the broker for cash that has not been
        # raised yet -- and makes the portfolio momentarily larger than it
        # ever actually is, which trips exposure limits that are not really
        # being breached.
        merged.sort(key=lambda a: (a.kind is ActionKind.BUY, a.instrument))
        return tuple(merged)

    # -- band breaches ------------------------------------------------------

    def _correct_breaches(
        self, drifts: Mapping[str, Drift], breaches: frozenset[str]
    ) -> list[Action]:
        """Sell down overweight holdings, buy up underweight ones.

        Only breached holdings are touched. Nudging everything back to exactly
        target on every pass is what threshold rebalancing exists to avoid.
        """
        actions: list[Action] = []

        for name in sorted(breaches):
            drift = drifts[name]
            gap = drift.value_gap

            if drift.target_weight == 0:
                actions.append(
                    Action(
                        name,
                        ActionKind.SELL,
                        drift.current_value,
                        Trigger.UNTARGETED,
                    )
                )
                continue

            if abs(gap) < self.min_order:
                continue

            actions.append(
                Action(
                    name,
                    ActionKind.SELL if gap < 0 else ActionKind.BUY,
                    abs(gap),
                    Trigger.BAND_BREACH,
                )
            )

        return actions
