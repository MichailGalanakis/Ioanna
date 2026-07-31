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
from .costs import contribution_frequency_cost, minimum_viable_contribution
from .kelly import (
    DEFAULT_SIZER,
    KellySizer,
    SizingResult,
    continuous_kelly,
    discrete_kelly,
    kelly_from_odds,
)
from .shadow import (
    Direction,
    Gate2Report,
    Outcome,
    Proposal,
    Resolution,
    ShadowLedger,
)

__all__ = [
    "BINANCE_PERP",
    "BINANCE_SPOT",
    "BPS",
    "DEFAULT_SIZER",
    "IBKR_EUROPE",
    "CostModel",
    "Direction",
    "FeeSchedule",
    "Gate2Report",
    "KellySizer",
    "Outcome",
    "Proposal",
    "Resolution",
    "ShadowLedger",
    "SizingResult",
    "continuous_kelly",
    "contribution_frequency_cost",
    "discrete_kelly",
    "funding_arb_costs",
    "kelly_from_odds",
    "minimum_viable_contribution",
]
