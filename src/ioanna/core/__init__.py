"""The passive core: 70% of the allocation, and the part that compounds.

Deliberately built before anything interesting. A system that cannot reliably
dollar-cost-average into an ETF has no business touching perpetual futures.
"""

from .allocation import Drift, TargetAllocation
from .dca import (
    Contribution,
    ContributionSchedule,
    add_months,
    business_day_before,
    month_end,
    next_contribution,
)
from .rebalance import (
    Action,
    ActionKind,
    RebalanceBands,
    RebalancePlan,
    Rebalancer,
    Trigger,
)
from .runner import CycleResult, OrderIntent, PassiveCore
from .taxlots import Disposal, InsufficientHoldingsError, Lot, TaxLedger

__all__ = [
    "Action",
    "ActionKind",
    "Contribution",
    "ContributionSchedule",
    "CycleResult",
    "Disposal",
    "Drift",
    "InsufficientHoldingsError",
    "Lot",
    "OrderIntent",
    "PassiveCore",
    "RebalanceBands",
    "RebalancePlan",
    "Rebalancer",
    "TargetAllocation",
    "TaxLedger",
    "Trigger",
    "add_months",
    "business_day_before",
    "month_end",
    "next_contribution",
]
