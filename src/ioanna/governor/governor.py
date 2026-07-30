"""The governor.

Deterministic. No LLM call, no network call, no clock read, no randomness --
given the same order and the same state it returns the same decision, which is
what makes it testable and what makes it trustworthy.

Every check runs even after one has already failed, so a rejected order comes
back with the full list of what is wrong with it rather than just the first
problem. Debugging a strategy that trips three limits at once is much easier
when you can see all three.
"""

from __future__ import annotations

from decimal import Decimal

from .limits import Limits
from .types import Decision, OrderRequest, PortfolioState, Rejection, Violation


class Governor:
    """Approves or refuses orders against hard limits.

    The research layer cannot reach this object. It is constructed once at
    startup by the execution layer and its limits are never rebound.
    """

    def __init__(self, limits: Limits) -> None:
        self._limits = limits
        self._kill_switch = False

    # -- kill switch ---------------------------------------------------------

    @property
    def kill_switch_engaged(self) -> bool:
        return self._kill_switch

    def engage_kill_switch(self) -> None:
        """Stop all new risk. Reduce-only orders still pass, so we can exit."""
        self._kill_switch = True

    def release_kill_switch(self) -> None:
        """Deliberately separate from engage, and never called automatically.

        Re-enabling trading after a halt is a human decision made after a root
        cause is understood, not something the system does when it feels
        better.
        """
        self._kill_switch = False

    # -- the check ----------------------------------------------------------

    def review(self, order: OrderRequest, state: PortfolioState) -> Decision:
        violations: list[Violation] = []

        halted = self._kill_switch
        breached = state.drawdown >= self._limits.max_drawdown

        # A reduce-only order during a halt is the escape hatch, so it skips
        # the halt checks -- but still faces every other limit.
        if not (order.reduce_only and (halted or breached)):
            if halted:
                violations.append(
                    Violation(Rejection.KILL_SWITCH, "kill switch is engaged")
                )
            if breached:
                violations.append(
                    Violation(
                        Rejection.DRAWDOWN_HALT,
                        f"drawdown {state.drawdown:.2%} >= limit "
                        f"{self._limits.max_drawdown:.2%}",
                    )
                )

        violations.extend(self._check_wellformed(order))
        violations.extend(self._check_whitelists(order))
        violations.extend(self._check_state_freshness(state))
        violations.extend(self._check_position_size(order, state))
        violations.extend(self._check_pillar_exposure(order, state))
        violations.extend(self._check_trade_budget(order, state))
        violations.extend(self._check_liquidity(order))

        return Decision(approved=not violations, violations=tuple(violations))

    # -- individual checks --------------------------------------------------

    def _check_wellformed(self, order: OrderRequest) -> list[Violation]:
        out = []
        if order.quantity <= 0:
            out.append(
                Violation(
                    Rejection.INVALID_ORDER, f"quantity {order.quantity} is not positive"
                )
            )
        if order.reference_price <= 0:
            out.append(
                Violation(
                    Rejection.INVALID_ORDER,
                    f"reference price {order.reference_price} is not positive",
                )
            )
        if not order.instrument or not order.venue:
            out.append(
                Violation(Rejection.INVALID_ORDER, "instrument and venue are required")
            )
        return out

    def _check_whitelists(self, order: OrderRequest) -> list[Violation]:
        out = []
        if order.venue not in self._limits.allowed_venues:
            out.append(
                Violation(
                    Rejection.VENUE_NOT_ALLOWED, f"venue {order.venue!r} not allowed"
                )
            )
        if order.instrument not in self._limits.allowed_instruments:
            out.append(
                Violation(
                    Rejection.INSTRUMENT_NOT_ALLOWED,
                    f"instrument {order.instrument!r} not allowed",
                )
            )
        if order.strategy_pillar not in self._limits.max_pillar_fraction:
            out.append(
                Violation(
                    Rejection.PILLAR_NOT_ALLOWED,
                    f"pillar {order.strategy_pillar!r} has no configured limit",
                )
            )
        return out

    def _check_state_freshness(self, state: PortfolioState) -> list[Violation]:
        if state.age_seconds > self._limits.max_state_age_seconds:
            return [
                Violation(
                    Rejection.STALE_STATE,
                    f"portfolio state is {state.age_seconds:.0f}s old, limit is "
                    f"{self._limits.max_state_age_seconds:.0f}s",
                )
            ]
        return []

    def _check_position_size(
        self, order: OrderRequest, state: PortfolioState
    ) -> list[Violation]:
        if state.equity <= 0:
            return [Violation(Rejection.INVALID_ORDER, "equity is not positive")]

        current = state.positions.get(order.instrument, Decimal(0))
        projected = self._project(current, order)
        cap = state.equity * self._limits.max_position_fraction

        if projected > cap:
            return [
                Violation(
                    Rejection.POSITION_TOO_LARGE,
                    f"{order.instrument} would reach {projected} vs cap {cap}",
                )
            ]
        return []

    def _check_pillar_exposure(
        self, order: OrderRequest, state: PortfolioState
    ) -> list[Violation]:
        limit = self._limits.max_pillar_fraction.get(order.strategy_pillar)
        if limit is None:
            return []  # already reported by the whitelist check
        if state.equity <= 0:
            return []  # already reported by the position check

        current = state.pillar_exposure.get(order.strategy_pillar, Decimal(0))
        projected = self._project(current, order)
        cap = state.equity * limit

        if projected > cap:
            return [
                Violation(
                    Rejection.PILLAR_EXPOSURE_EXCEEDED,
                    f"pillar {order.strategy_pillar} would reach {projected} "
                    f"vs cap {cap}",
                )
            ]
        return []

    def _check_trade_budget(
        self, order: OrderRequest, state: PortfolioState
    ) -> list[Violation]:
        # Exits do not consume budget. Capping our ability to close positions
        # would turn a cost control into a risk control, pointing the wrong
        # way.
        if order.reduce_only:
            return []
        if state.trades_today >= self._limits.max_trades_per_day:
            return [
                Violation(
                    Rejection.TRADE_BUDGET_EXHAUSTED,
                    f"{state.trades_today} trades today, budget is "
                    f"{self._limits.max_trades_per_day}",
                )
            ]
        return []

    def _check_liquidity(self, order: OrderRequest) -> list[Violation]:
        if self._limits.min_liquidity_multiple == 0:
            return []
        if order.venue_liquidity is None:
            return [
                Violation(
                    Rejection.INSUFFICIENT_LIQUIDITY,
                    "venue liquidity was not measured",
                )
            ]
        required = order.notional * self._limits.min_liquidity_multiple
        if order.venue_liquidity < required:
            return [
                Violation(
                    Rejection.INSUFFICIENT_LIQUIDITY,
                    f"depth {order.venue_liquidity} < required {required}",
                )
            ]
        return []

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _project(current: Decimal, order: OrderRequest) -> Decimal:
        """Exposure after the order fills.

        Positions are tracked as absolute notional, so a reduce-only order
        shrinks the number and anything else grows it. Floored at zero: an
        oversized exit closes the position rather than flipping it, and the
        governor should not read that as new exposure.
        """
        if order.reduce_only:
            return max(Decimal(0), current - order.notional)
        return current + order.notional
