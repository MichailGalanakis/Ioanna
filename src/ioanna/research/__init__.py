"""Research layer: cost modelling, position sizing, shadow-mode evaluation.

Nothing here executes. Phase 2 exists to find out whether a strategy has an
edge that survives realistic costs, before any capital is exposed to it.
"""

from .costs import (
    BINANCE_PERP,
    BINANCE_SPOT,
    BPS,
    IBKR_EUROPE,
    CostModel,
    FeeSchedule,
    funding_arb_costs,
)
from .kelly import (
    DEFAULT_SIZER,
    KellySizer,
    SizingResult,
    continuous_kelly,
    discrete_kelly,
    kelly_from_odds,
)

__all__ = [
    "BINANCE_PERP",
    "BINANCE_SPOT",
    "BPS",
    "DEFAULT_SIZER",
    "IBKR_EUROPE",
    "CostModel",
    "FeeSchedule",
    "KellySizer",
    "SizingResult",
    "continuous_kelly",
    "discrete_kelly",
    "funding_arb_costs",
    "kelly_from_odds",
]
