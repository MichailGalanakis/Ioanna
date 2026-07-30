"""Execution cost model.

The most important file for Phase 2. Nof1's finding from Alpha Arena was that
"PnL was dominated by trading costs in early runs as agents over-traded and
took quick, tiny gains that fees erased" -- the models did not lose because
they predicted badly, they lost because they traded and the costs compounded.

A shadow-mode result computed without realistic costs is not a weak signal,
it is a fabricated one. So the useful direction to run this model is backwards:
given what a round trip costs, how much edge does a strategy need before it is
worth doing at all? `required_edge_bps` answers that, and it is the number
that should kill most strategy ideas before they are written.

Rates below are venue defaults as of 2026 and are arguments, not constants --
every one of them should be replaced with the fills actually observed once
live, which is what `realised_cost_bps` is for.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

D = Decimal

#: One basis point.
BPS = D("0.0001")


@dataclass(frozen=True)
class FeeSchedule:
    """Venue commissions.

    Two shapes exist in the wild and both are supported: proportional (crypto
    venues, quoted in bps) and flat-with-a-percentage-fallback (traditional
    brokers, e.g. IBKR's €3 per European stock trade, or 0.05% above roughly
    €6,000).
    """

    maker_bps: Decimal = D("0")
    taker_bps: Decimal = D("0")
    minimum: Decimal = D("0")
    """Floor per order.

    Traditional brokers quote a rate with a minimum rather than a flat fee --
    IBKR's European schedule is 0.05% with a €3 floor, which reads as "€3 per
    trade" only because most retail orders fall under the crossover. Modelling
    it as a genuine flat fee would understate the cost of large orders, which
    is the wrong direction to be wrong in.
    """

    def __post_init__(self) -> None:
        for name in ("maker_bps", "taker_bps", "minimum"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    def commission(self, notional: Decimal, maker: bool = False) -> Decimal:
        if notional <= 0:
            raise ValueError("notional must be positive")

        rate = self.maker_bps if maker else self.taker_bps
        return max(notional * rate * BPS, self.minimum)

    def crossover_notional(self, maker: bool = False) -> Decimal:
        """Order size at which the rate overtakes the minimum.

        Below this the commission is a fixed cost, so it falls as a share of
        the order -- which is what `MIN_ORDER` in the config is set against.
        """
        rate = self.maker_bps if maker else self.taker_bps
        if rate <= 0:
            return D("Infinity")
        return self.minimum / (rate * BPS)


@dataclass(frozen=True)
class CostModel:
    """Everything that stands between a signal and a realised return."""

    fees: FeeSchedule
    half_spread_bps: Decimal = D("1")
    """Cost of crossing to the mid. Paid on entry and again on exit."""

    slippage_bps: Decimal = D("2")
    """Expected fill degradation beyond the spread.

    Held constant here, which understates it for large orders. Once live fills
    exist this should become a function of order size against book depth --
    the `min_liquidity_multiple` limit in the governor exists precisely so
    that assumption stays roughly true.
    """

    borrow_bps_per_day: Decimal = D("0")
    """Financing on a short leg, if any."""

    def __post_init__(self) -> None:
        for name in ("half_spread_bps", "slippage_bps", "borrow_bps_per_day"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    # -- one side -----------------------------------------------------------

    def one_way_bps(self, maker: bool = False) -> Decimal:
        """Cost of a single fill, excluding the flat commission component."""
        rate = self.fees.maker_bps if maker else self.fees.taker_bps
        return rate + self.half_spread_bps + self.slippage_bps

    def one_way_cost(self, notional: Decimal, maker: bool = False) -> Decimal:
        commission = self.fees.commission(notional, maker)
        friction = notional * (self.half_spread_bps + self.slippage_bps) * BPS
        return commission + friction

    # -- round trip ---------------------------------------------------------

    def round_trip_cost(
        self,
        notional: Decimal,
        holding_days: Decimal = D("0"),
        maker: bool = False,
    ) -> Decimal:
        """Total cost of entering, holding and exiting a position."""
        if holding_days < 0:
            raise ValueError("holding_days must be non-negative")

        entry = self.one_way_cost(notional, maker)
        exit_ = self.one_way_cost(notional, maker)
        carry = notional * self.borrow_bps_per_day * BPS * holding_days
        return entry + exit_ + carry

    def round_trip_bps(
        self,
        notional: Decimal,
        holding_days: Decimal = D("0"),
        maker: bool = False,
    ) -> Decimal:
        return self.round_trip_cost(notional, holding_days, maker) / notional / BPS

    # -- the question that matters -----------------------------------------

    def required_edge_bps(
        self,
        notional: Decimal,
        holding_days: Decimal = D("0"),
        maker: bool = False,
        win_rate: Decimal = D("1"),
    ) -> Decimal:
        """Gross edge needed per trade to break even after costs.

        `win_rate` below 1 raises the bar: if only 55% of trades reach the
        target, the winners have to cover the costs of the losers too. Ignoring
        this is how a strategy with a "small positive edge" turns out to be
        reliably negative.
        """
        if not D("0") < win_rate <= D("1"):
            raise ValueError("win_rate must be in (0, 1]")

        return self.round_trip_bps(notional, holding_days, maker) / win_rate

    def breakeven_holding_days(
        self,
        notional: Decimal,
        daily_yield_bps: Decimal,
        maker: bool = False,
    ) -> Decimal:
        """Days a carry position must be held before it pays for itself.

        For funding-rate arbitrage this is the whole calculation. Collecting
        1bp a day against a 12bp round trip means twelve days before the trade
        is worth anything -- and a strategy that rotates venues weekly to chase
        the best rate never breaks even at all.
        """
        net_daily = daily_yield_bps - self.borrow_bps_per_day
        if net_daily <= 0:
            return D("Infinity")

        entry_exit = (
            self.one_way_cost(notional, maker) * 2 / notional / BPS
        )
        return entry_exit / net_daily

    # -- measuring reality --------------------------------------------------

    @staticmethod
    def realised_cost_bps(
        expected_price: Decimal,
        fill_price: Decimal,
        quantity: Decimal,
        commission: Decimal,
        side_is_buy: bool,
    ) -> Decimal:
        """Cost actually paid on a fill, in bps of notional.

        Compare against the model. Gate 3 requires realised slippage to land
        within 20% of the shadow-mode estimate; a persistent gap means the
        model is wrong and every backtest built on it was optimistic.
        """
        if expected_price <= 0 or fill_price <= 0 or quantity <= 0:
            raise ValueError("prices and quantity must be positive")

        notional = fill_price * quantity
        slip = (
            (fill_price - expected_price)
            if side_is_buy
            else (expected_price - fill_price)
        )
        return (slip * quantity + commission) / notional / BPS


# ---------------------------------------------------------------------------
# Venue presets
# ---------------------------------------------------------------------------

#: Interactive Brokers Ireland, Fixed plan, Western European stocks and ETFs:
#: 0.05% of notional with a €3 floor, so orders under €6,000 pay the floor.
#: ETFs on a major exchange are tight, so spread and slippage are small.
IBKR_EUROPE = CostModel(
    fees=FeeSchedule(taker_bps=D("5"), maker_bps=D("5"), minimum=D("3")),
    half_spread_bps=D("1"),
    slippage_bps=D("1"),
)

#: Binance spot, standard tier: 10bps both sides.
BINANCE_SPOT = CostModel(
    fees=FeeSchedule(maker_bps=D("10"), taker_bps=D("10")),
    half_spread_bps=D("1"),
    slippage_bps=D("2"),
)

#: Binance USD-M perpetual futures: 2bps maker, 5bps taker.
BINANCE_PERP = CostModel(
    fees=FeeSchedule(maker_bps=D("2"), taker_bps=D("5")),
    half_spread_bps=D("0.5"),
    slippage_bps=D("1.5"),
)


def contribution_frequency_cost(
    annual_amount: Decimal,
    orders_per_year: int,
    model: CostModel = IBKR_EUROPE,
    expected_return: Decimal = D("0.08"),
) -> dict[str, Decimal]:
    """Total cost of contributing `orders_per_year` times, as a fraction.

    Two costs pull in opposite directions. Contributing more often pays the
    broker's minimum commission more times; contributing less often leaves
    cash uninvested while it waits, at the opportunity cost of the expected
    return.

    Cash drag wins by a wide margin at retail contribution sizes -- waiting a
    month to save a €3 commission costs more in foregone return than the
    commission does -- which is why the schedule is monthly rather than
    quarterly. It stops being true only if the contribution is small enough
    that the commission floor dominates, and at that point the answer is a
    different broker rather than a different frequency.
    """
    if annual_amount <= 0:
        raise ValueError("annual_amount must be positive")
    if orders_per_year < 1:
        raise ValueError("orders_per_year must be at least 1")

    per_order = annual_amount / orders_per_year
    fees = model.one_way_cost(per_order) * orders_per_year
    fee_fraction = fees / annual_amount

    # On average, money waits half the interval before being invested.
    months_waiting = D(12) / orders_per_year / 2
    drag = expected_return * months_waiting / 12

    return {
        "orders_per_year": D(orders_per_year),
        "per_order": per_order,
        "fees": fees,
        "fee_fraction": fee_fraction,
        "cash_drag": drag,
        "total": fee_fraction + drag,
    }


def minimum_viable_contribution(
    model: CostModel = IBKR_EUROPE,
    max_fee_fraction: Decimal = D("0.005"),
) -> Decimal:
    """Smallest monthly contribution whose commission stays tolerable.

    Below this the broker's minimum commission dominates and the right answer
    is a venue with a free-ETF list rather than a lower contribution -- paying
    1% in commissions to save 0.22% in TER is a bad trade however good the
    fund is.
    """
    if not D("0") < max_fee_fraction < D("1"):
        raise ValueError("max_fee_fraction must be in (0, 1)")

    # Solve notional * max_fee_fraction >= one_way_cost(notional), stepping up
    # in €50 increments to land on a number worth quoting.
    amount = D("50")
    while amount < D("100000"):
        if model.one_way_cost(amount) / amount <= max_fee_fraction:
            return amount
        amount += D("50")
    return amount


def funding_arb_costs(
    spot: CostModel = BINANCE_SPOT, perp: CostModel = BINANCE_PERP
) -> CostModel:
    """Combined model for a delta-neutral spot-long / perp-short carry.

    Both legs are opened and both are closed, so the position pays two round
    trips, not one. Getting this wrong roughly halves the apparent cost of the
    strategy and makes a marginal trade look comfortable.
    """
    return CostModel(
        fees=FeeSchedule(
            maker_bps=spot.fees.maker_bps + perp.fees.maker_bps,
            taker_bps=spot.fees.taker_bps + perp.fees.taker_bps,
        ),
        half_spread_bps=spot.half_spread_bps + perp.half_spread_bps,
        slippage_bps=spot.slippage_bps + perp.slippage_bps,
    )
