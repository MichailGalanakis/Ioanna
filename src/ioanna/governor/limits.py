"""Hard limits.

These are deliberately data, not code, and deliberately not reachable from the
research layer. Loosening a limit is a commit with a diff and a reason, made
when the market is closed and nobody is losing money -- never an inline
decision made at the moment it starts to bind.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Limits:
    # Fraction of equity a single instrument may represent.
    max_position_fraction: Decimal = Decimal("0.05")

    # Fraction of equity each pillar may represent. Missing pillar => refused,
    # so a new strategy cannot start trading just because someone typed a new
    # name into a config file.
    #
    # Zero is allowed and means something different from absent: the pillar is
    # known and deliberately unfunded, which is the correct state for a
    # strategy that has not yet cleared its gates. Reduce-only orders still
    # pass, so a pillar can always be wound down after its budget is cut.
    max_pillar_fraction: dict[str, Decimal] = field(
        default_factory=lambda: {
            "core": Decimal("0.70"),
            "satellite": Decimal("0.25"),
            "exploratory": Decimal("0.05"),
        }
    )

    # Orders per day. The Alpha Arena result -- costs dominating PnL because
    # the agents overtraded -- is the entire reason this exists.
    max_trades_per_day: int = 5

    # Drawdown from peak equity at which everything except reduce-only stops.
    max_drawdown: Decimal = Decimal("0.15")

    # Minimum top-of-book depth, as a multiple of order notional. Trading into
    # a book thinner than this means the fill price is fiction.
    min_liquidity_multiple: Decimal = Decimal("10")

    # A portfolio snapshot older than this cannot be trusted for limit checks.
    max_state_age_seconds: float = 60.0

    allowed_venues: frozenset[str] = frozenset()
    allowed_instruments: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not (Decimal(0) < self.max_position_fraction <= Decimal(1)):
            raise ValueError("max_position_fraction must be in (0, 1]")
        if not (Decimal(0) < self.max_drawdown < Decimal(1)):
            raise ValueError("max_drawdown must be in (0, 1)")
        if self.max_trades_per_day < 0:
            raise ValueError("max_trades_per_day must be non-negative")
        if self.min_liquidity_multiple < 0:
            raise ValueError("min_liquidity_multiple must be non-negative")
        for pillar, frac in self.max_pillar_fraction.items():
            if not (Decimal(0) <= frac <= Decimal(1)):
                raise ValueError(f"pillar fraction for {pillar!r} must be in [0, 1]")


#: The allocation from research/04-architecture.md, with the venue and
#: instrument lists left empty. Empty means nothing is tradeable, which is the
#: correct default for a system that has not chosen its venues yet.
DEFAULT_LIMITS = Limits()
