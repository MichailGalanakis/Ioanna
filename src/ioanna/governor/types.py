"""Core types for the governor.

Everything here is frozen. An order request that has been validated must not
be mutable afterwards -- the whole point of the governor is that what it
approved is what gets sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Rejection(str, Enum):
    """Every way an order can be refused.

    Kept as an enum rather than free text so rejections are countable --
    "how often did we hit the daily trade cap last month" is a question the
    journal needs to answer.
    """

    KILL_SWITCH = "kill_switch_engaged"
    DRAWDOWN_HALT = "max_drawdown_breached"
    VENUE_NOT_ALLOWED = "venue_not_whitelisted"
    INSTRUMENT_NOT_ALLOWED = "instrument_not_whitelisted"
    PILLAR_NOT_ALLOWED = "unknown_strategy_pillar"
    INVALID_ORDER = "malformed_order"
    POSITION_TOO_LARGE = "position_exceeds_limit"
    PILLAR_EXPOSURE_EXCEEDED = "pillar_exposure_exceeds_limit"
    TRADE_BUDGET_EXHAUSTED = "daily_trade_budget_exhausted"
    INSUFFICIENT_LIQUIDITY = "venue_liquidity_below_floor"
    STALE_STATE = "portfolio_state_too_old"


@dataclass(frozen=True)
class Violation:
    reason: Rejection
    detail: str

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{self.reason.value}: {self.detail}"


@dataclass(frozen=True)
class OrderRequest:
    """A proposed order. Produced by the execution layer, never by an LLM."""

    instrument: str
    venue: str
    side: Side
    quantity: Decimal
    reference_price: Decimal
    strategy_pillar: str
    # Orders that can only shrink an existing position. These stay legal when
    # the kill switch is on or a drawdown halt is active -- otherwise a halt
    # would trap us in the very position we want out of.
    reduce_only: bool = False
    # Top-of-book depth on the traded side, in quote currency. None means the
    # caller could not measure it, which the governor treats as failure rather
    # than as permission.
    venue_liquidity: Decimal | None = None

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.reference_price


@dataclass(frozen=True)
class PortfolioState:
    """Snapshot of where we stand, as of `age_seconds` ago.

    Supplied by the reconciliation loop, not by the strategy. If the strategy
    could report its own state it could also lie about it by accident.
    """

    equity: Decimal
    peak_equity: Decimal
    # instrument -> absolute notional currently held
    positions: dict[str, Decimal] = field(default_factory=dict)
    # pillar -> absolute notional currently allocated
    pillar_exposure: dict[str, Decimal] = field(default_factory=dict)
    trades_today: int = 0
    age_seconds: float = 0.0

    @property
    def drawdown(self) -> Decimal:
        """Current drawdown from peak, as a positive fraction."""
        if self.peak_equity <= 0:
            return Decimal(0)
        return max(Decimal(0), (self.peak_equity - self.equity) / self.peak_equity)


@dataclass(frozen=True)
class Decision:
    approved: bool
    violations: tuple[Violation, ...] = ()

    @property
    def reasons(self) -> tuple[Rejection, ...]:
        return tuple(v.reason for v in self.violations)

    def __bool__(self) -> bool:
        return self.approved
