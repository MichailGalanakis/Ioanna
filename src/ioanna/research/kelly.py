"""Position sizing.

Kelly maximises the long-run growth rate of capital. It is also, at full size,
far too aggressive to actually run: a full-Kelly bettor with a genuine edge
still spends much of their life in drawdowns exceeding 50%, and that is the
*best* case, where the edge estimate is correct.

It usually is not. Kelly is quadratically sensitive to the edge estimate --
overestimating edge by a factor of two does not halve the growth rate, it can
turn it negative. Since every edge here comes from a backtest, and the whole
of `validation/` exists because backtested edges are systematically
overstated, the estimate should be assumed too high.

Hence fractional Kelly. Quarter Kelly is the default: it gives up about 25% of
the theoretical growth rate in exchange for roughly a quarter of the variance,
and it stays solvent when the edge estimate is wrong by a factor of two, which
it will be.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

D = Decimal


@dataclass(frozen=True)
class SizingResult:
    fraction: Decimal
    """Fraction of capital to commit, after all caps."""

    full_kelly: Decimal
    """What Kelly alone would have suggested, before scaling and caps."""

    binding_constraint: str
    """Which rule actually determined the size. Worth logging: a system whose
    sizes are always set by the hard cap is not really using Kelly, and one
    whose sizes are always set by Kelly has no hard cap worth having."""

    @property
    def is_capped(self) -> bool:
        return self.binding_constraint != "kelly"


def discrete_kelly(
    win_probability: Decimal,
    win_amount: Decimal,
    loss_amount: Decimal,
) -> Decimal:
    """Kelly fraction for a binary outcome.

    The prediction-market and sports-betting case: a known payoff if right, a
    known loss if wrong. `win_amount` and `loss_amount` are per unit staked.

    Returns 0 rather than a negative number when there is no edge. A negative
    Kelly means "take the other side", which is a different decision and
    should be made explicitly rather than by sign.
    """
    if not D("0") <= win_probability <= D("1"):
        raise ValueError("win_probability must be in [0, 1]")
    if win_amount <= 0 or loss_amount <= 0:
        raise ValueError("win and loss amounts must be positive")

    p = win_probability
    q = D("1") - p
    b = win_amount / loss_amount

    fraction = (p * b - q) / b
    return max(D("0"), fraction)


def continuous_kelly(
    expected_return: Decimal,
    variance: Decimal,
) -> Decimal:
    """Kelly fraction for a continuous return distribution: mu / sigma^2.

    Both arguments must be measured over the same period, and `expected_return`
    must already be net of costs -- sizing on a gross edge is how a strategy
    ends up levered into something that loses money after fees.
    """
    if variance <= 0:
        raise ValueError("variance must be positive")
    return max(D("0"), expected_return / variance)


def kelly_from_odds(
    fair_probability: Decimal,
    offered_odds: Decimal,
) -> Decimal:
    """Kelly stake given a fair probability and decimal odds on offer.

    Decimal odds of 2.5 return 2.5x the stake including it, so the profit is
    1.5x. This is the prediction-market form: our probability estimate against
    the market's price.
    """
    if not D("0") <= fair_probability <= D("1"):
        raise ValueError("fair_probability must be in [0, 1]")
    if offered_odds <= 1:
        raise ValueError("decimal odds must exceed 1")

    return discrete_kelly(fair_probability, offered_odds - D("1"), D("1"))


@dataclass(frozen=True)
class KellySizer:
    """Fractional Kelly with hard caps.

    The caps are not a refinement of Kelly, they override it. When an edge
    estimate is badly wrong -- and the failure mode of a research agent is
    producing confident wrong estimates at scale -- Kelly will happily
    recommend betting most of the portfolio. The cap is what makes that
    survivable.
    """

    fraction_of_kelly: Decimal = D("0.25")
    max_fraction: Decimal = D("0.05")
    """Hard ceiling on any single position, as a fraction of capital."""

    min_fraction: Decimal = D("0.002")
    """Below this a position is not worth the commission or the attention."""

    def __post_init__(self) -> None:
        if not D("0") < self.fraction_of_kelly <= D("1"):
            raise ValueError("fraction_of_kelly must be in (0, 1]")
        if not D("0") < self.max_fraction <= D("1"):
            raise ValueError("max_fraction must be in (0, 1]")
        if self.min_fraction < 0:
            raise ValueError("min_fraction must be non-negative")
        if self.min_fraction > self.max_fraction:
            raise ValueError("min_fraction cannot exceed max_fraction")

    def size(self, full_kelly: Decimal) -> SizingResult:
        if full_kelly <= 0:
            return SizingResult(D("0"), full_kelly, "no_edge")

        scaled = full_kelly * self.fraction_of_kelly

        if scaled > self.max_fraction:
            return SizingResult(self.max_fraction, full_kelly, "max_fraction")
        if scaled < self.min_fraction:
            return SizingResult(D("0"), full_kelly, "below_minimum")
        return SizingResult(scaled, full_kelly, "kelly")

    def size_discrete(
        self,
        win_probability: Decimal,
        win_amount: Decimal,
        loss_amount: Decimal,
    ) -> SizingResult:
        return self.size(
            discrete_kelly(win_probability, win_amount, loss_amount)
        )

    def size_continuous(
        self, expected_return: Decimal, variance: Decimal
    ) -> SizingResult:
        return self.size(continuous_kelly(expected_return, variance))

    def size_with_uncertainty(
        self,
        expected_return: Decimal,
        variance: Decimal,
        estimate_error: Decimal,
    ) -> SizingResult:
        """Kelly with the edge estimate shrunk toward zero.

        `estimate_error` is the standard error of the expected-return estimate.
        The edge is discounted by one standard error before sizing, so a signal
        measured over a short history is sized as though its weakest plausible
        value were the true one.

        This is deliberately crude. The point is not precision -- it is that a
        strategy with 20bp of edge measured over three months should not be
        sized like one with 20bp measured over ten years, and unadjusted Kelly
        cannot tell them apart.
        """
        if estimate_error < 0:
            raise ValueError("estimate_error must be non-negative")

        discounted = expected_return - estimate_error
        if discounted <= 0:
            return SizingResult(D("0"), D("0"), "edge_within_noise")

        return self.size(continuous_kelly(discounted, variance))


#: Default sizer for the satellite pillar. Quarter Kelly, capped at 5% of
#: capital in any one position -- matching the governor's position limit, so
#: the sizer and the governor agree rather than the sizer proposing sizes the
#: governor then refuses.
DEFAULT_SIZER = KellySizer(
    fraction_of_kelly=D("0.25"),
    max_fraction=D("0.05"),
    min_fraction=D("0.002"),
)
