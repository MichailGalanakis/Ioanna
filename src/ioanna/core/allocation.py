"""Target allocation and drift.

The passive core: a fixed set of target weights, and a measurement of how far
the actual portfolio has wandered from them. Everything the rebalancer does is
a reaction to the numbers computed here.

Weights are Decimal and must sum to exactly 1. Not "approximately 1" -- a
tolerance here would silently absorb the kind of typo that leaves 3% of the
portfolio permanently unallocated.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class Drift:
    """How far one holding sits from its target."""

    instrument: str
    target_weight: Decimal
    current_weight: Decimal
    current_value: Decimal
    target_value: Decimal

    @property
    def absolute(self) -> Decimal:
        """Deviation in weight points. Positive means overweight."""
        return self.current_weight - self.target_weight

    @property
    def relative(self) -> Decimal:
        """Deviation as a fraction of the target weight.

        Infinite for a holding with a zero target -- something held that the
        allocation does not call for at all, which no relative band can
        express and which should always be flagged.
        """
        if self.target_weight == 0:
            return Decimal("Infinity") if self.current_value > 0 else Decimal(0)
        return self.absolute / self.target_weight

    @property
    def value_gap(self) -> Decimal:
        """Currency needed to reach target. Positive means underweight."""
        return self.target_value - self.current_value


@dataclass(frozen=True)
class TargetAllocation:
    """A set of instruments and the fraction of the portfolio each should hold."""

    weights: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        if not self.weights:
            raise ValueError("allocation must contain at least one instrument")

        for instrument, weight in self.weights.items():
            if weight < 0:
                raise ValueError(f"negative weight for {instrument!r}")
            if weight > 1:
                raise ValueError(f"weight above 1 for {instrument!r}")

        total = sum(self.weights.values())
        if total != Decimal(1):
            raise ValueError(
                f"weights must sum to exactly 1, got {total}. A near-miss here "
                "leaves part of the portfolio permanently unallocated."
            )

    @property
    def instruments(self) -> frozenset[str]:
        return frozenset(self.weights)

    def drifts(self, holdings: Mapping[str, Decimal]) -> dict[str, Drift]:
        """Drift for every instrument, by market value.

        Holdings not present in the allocation are included with a target
        weight of zero, so a position that should not exist cannot hide by
        being absent from the target.
        """
        for instrument, value in holdings.items():
            if value < 0:
                raise ValueError(f"negative holding value for {instrument!r}")

        total = sum(holdings.values())
        if total <= 0:
            raise ValueError("portfolio has no value to allocate")

        universe = self.instruments | frozenset(holdings)
        out: dict[str, Drift] = {}

        for instrument in sorted(universe):
            target_weight = self.weights.get(instrument, Decimal(0))
            current_value = holdings.get(instrument, Decimal(0))
            out[instrument] = Drift(
                instrument=instrument,
                target_weight=target_weight,
                current_weight=current_value / total,
                current_value=current_value,
                target_value=total * target_weight,
            )
        return out

    def target_values(
        self, total_value: Decimal, holdings: Mapping[str, Decimal] | None = None
    ) -> dict[str, Decimal]:
        """Currency value each instrument should hold at a given portfolio size.

        Instruments held but not in the allocation target zero, which is what
        makes them show up as sells rather than being quietly ignored.
        """
        universe = self.instruments | frozenset(holdings or {})
        return {
            instrument: total_value * self.weights.get(instrument, Decimal(0))
            for instrument in sorted(universe)
        }
