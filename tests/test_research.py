"""Cost model and position sizing tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ioanna.research import (
    BINANCE_PERP,
    BINANCE_SPOT,
    IBKR_EUROPE,
    CostModel,
    FeeSchedule,
    KellySizer,
    continuous_kelly,
    discrete_kelly,
    funding_arb_costs,
    kelly_from_odds,
)

D = Decimal


# ===========================================================================
# Fees
# ===========================================================================


def test_proportional_fee() -> None:
    fees = FeeSchedule(taker_bps=D("10"))
    assert fees.commission(D("10000")) == D("10")   # 10bps of 10k


def test_maker_and_taker_differ() -> None:
    fees = FeeSchedule(maker_bps=D("2"), taker_bps=D("5"))
    assert fees.commission(D("10000"), maker=True) == D("2")
    assert fees.commission(D("10000"), maker=False) == D("5")


def test_the_minimum_binds_on_small_orders() -> None:
    """IBKR: 0.05% with a €3 floor, so a €1,000 order pays the floor."""
    assert IBKR_EUROPE.fees.commission(D("1000")) == D("3")
    assert IBKR_EUROPE.fees.commission(D("5999")) == D("3")


def test_the_rate_takes_over_on_large_orders() -> None:
    """5bps of €10,000 is €5, which exceeds the €3 floor."""
    assert IBKR_EUROPE.fees.commission(D("10000")) == D("5")


def test_the_minimum_is_a_floor_never_a_cap() -> None:
    """Modelling the floor as a flat fee would understate large orders --
    the wrong direction to be wrong in."""
    fees = FeeSchedule(taker_bps=D("5"), minimum=D("3"))
    assert fees.commission(D("6001")) == D("3.0005")
    assert fees.commission(D("100000")) == D("50")


def test_crossover_notional_is_where_the_floor_stops_binding() -> None:
    """Below €6,000 the IBKR commission is effectively fixed, so it shrinks
    as a share of the order -- which is what MIN_ORDER is set against."""
    assert IBKR_EUROPE.fees.crossover_notional() == D("6000")


def test_zero_notional_is_refused() -> None:
    with pytest.raises(ValueError, match="notional must be positive"):
        FeeSchedule(taker_bps=D("10")).commission(D("0"))


@pytest.mark.parametrize(
    "kwargs",
    [{"maker_bps": D("-1")}, {"taker_bps": D("-1")}, {"minimum": D("-1")}],
)
def test_negative_fees_are_refused(kwargs) -> None:
    with pytest.raises(ValueError):
        FeeSchedule(**kwargs)


# ===========================================================================
# Cost model
# ===========================================================================


def test_one_way_cost_includes_spread_and_slippage() -> None:
    model = CostModel(
        fees=FeeSchedule(taker_bps=D("10")),
        half_spread_bps=D("1"),
        slippage_bps=D("2"),
    )
    # 10 + 1 + 2 = 13bps of 10,000 = 13
    assert model.one_way_cost(D("10000")) == D("13")


def test_round_trip_is_two_one_way_costs() -> None:
    model = CostModel(fees=FeeSchedule(taker_bps=D("10")))
    assert model.round_trip_cost(D("10000")) == model.one_way_cost(D("10000")) * 2


def test_holding_cost_accrues_with_time() -> None:
    model = CostModel(
        fees=FeeSchedule(taker_bps=D("5")), borrow_bps_per_day=D("1")
    )
    short = model.round_trip_cost(D("10000"), holding_days=D("1"))
    long = model.round_trip_cost(D("10000"), holding_days=D("30"))
    assert long - short == D("10000") * D("0.0001") * D("29")


def test_negative_holding_period_is_refused() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        BINANCE_SPOT.round_trip_cost(D("10000"), holding_days=D("-1"))


def test_maker_orders_cost_less_than_taker() -> None:
    assert BINANCE_PERP.round_trip_cost(
        D("10000"), maker=True
    ) < BINANCE_PERP.round_trip_cost(D("10000"), maker=False)


# ===========================================================================
# Required edge -- the number that kills strategies
# ===========================================================================


def test_required_edge_equals_round_trip_at_full_win_rate() -> None:
    assert BINANCE_SPOT.required_edge_bps(D("10000")) == BINANCE_SPOT.round_trip_bps(
        D("10000")
    )


def test_a_lower_win_rate_raises_the_bar() -> None:
    """Winners have to cover the losers' costs too."""
    at_full = BINANCE_SPOT.required_edge_bps(D("10000"), win_rate=D("1"))
    at_half = BINANCE_SPOT.required_edge_bps(D("10000"), win_rate=D("0.5"))
    assert at_half == at_full * 2


def test_a_scalping_strategy_needs_implausible_edge() -> None:
    """The Alpha Arena failure, quantified: a 55%-win-rate crypto strategy
    needs about 47bps per trade before it makes a cent."""
    required = BINANCE_SPOT.required_edge_bps(D("10000"), win_rate=D("0.55"))
    assert required > D("45")


@pytest.mark.parametrize("win_rate", [D("0"), D("-0.1"), D("1.5")])
def test_invalid_win_rate_is_refused(win_rate) -> None:
    with pytest.raises(ValueError, match="win_rate"):
        BINANCE_SPOT.required_edge_bps(D("10000"), win_rate=win_rate)


# ===========================================================================
# Carry breakeven -- the funding arbitrage calculation
# ===========================================================================


def test_breakeven_days_for_a_carry_trade() -> None:
    """A 26bps round trip collecting 2bps a day takes 13 days to break even."""
    model = CostModel(
        fees=FeeSchedule(taker_bps=D("10")),
        half_spread_bps=D("1"),
        slippage_bps=D("2"),
    )
    days = model.breakeven_holding_days(D("10000"), daily_yield_bps=D("2"))
    assert days == D("13")


def test_a_carry_that_does_not_cover_borrow_never_breaks_even() -> None:
    model = CostModel(
        fees=FeeSchedule(taker_bps=D("5")), borrow_bps_per_day=D("3")
    )
    assert model.breakeven_holding_days(
        D("10000"), daily_yield_bps=D("2")
    ) == D("Infinity")


def test_rotating_venues_weekly_destroys_a_thin_carry() -> None:
    """Funding arbitrage at realistic rates needs weeks, not days. A strategy
    that chases the best rate across venues every week pays the round trip
    more often than the carry can repay it."""
    model = funding_arb_costs()
    # 0.01% per 8h funding = 3bps/day, a normal rather than a spectacular rate.
    days = model.breakeven_holding_days(D("10000"), daily_yield_bps=D("3"))
    assert days > D("7")


def test_funding_arb_costs_charge_both_legs() -> None:
    """Two legs open and two close. Charging one round trip halves the true
    cost and makes a marginal trade look comfortable."""
    combined = funding_arb_costs()
    assert combined.fees.taker_bps == (
        BINANCE_SPOT.fees.taker_bps + BINANCE_PERP.fees.taker_bps
    )
    assert combined.round_trip_bps(D("10000")) > BINANCE_SPOT.round_trip_bps(
        D("10000")
    )


# ===========================================================================
# Realised cost
# ===========================================================================


def test_realised_cost_measures_adverse_fills() -> None:
    """Bought at 101 when 100 was expected: 100bps of slippage, plus fees."""
    cost = CostModel.realised_cost_bps(
        expected_price=D("100"),
        fill_price=D("101"),
        quantity=D("10"),
        commission=D("0"),
        side_is_buy=True,
    )
    assert cost == pytest.approx(D("99.0099"), abs=D("0.01"))


def test_a_favourable_fill_is_a_negative_cost() -> None:
    cost = CostModel.realised_cost_bps(
        expected_price=D("100"),
        fill_price=D("99"),
        quantity=D("10"),
        commission=D("0"),
        side_is_buy=True,
    )
    assert cost < 0


def test_sell_side_slippage_has_the_opposite_sign() -> None:
    """Selling below the expected price is the adverse direction."""
    cost = CostModel.realised_cost_bps(
        expected_price=D("100"),
        fill_price=D("99"),
        quantity=D("10"),
        commission=D("0"),
        side_is_buy=False,
    )
    assert cost > 0


# ===========================================================================
# Kelly
# ===========================================================================


def test_discrete_kelly_on_a_known_example() -> None:
    """60% chance to win 1:1. Kelly = 2*0.6 - 1 = 0.2."""
    assert discrete_kelly(D("0.6"), D("1"), D("1")) == D("0.2")


def test_kelly_is_zero_without_an_edge() -> None:
    assert discrete_kelly(D("0.5"), D("1"), D("1")) == D("0")


def test_kelly_is_zero_rather_than_negative() -> None:
    """A negative Kelly means "take the other side" -- a different decision,
    which should be made explicitly rather than by sign."""
    assert discrete_kelly(D("0.4"), D("1"), D("1")) == D("0")


def test_better_odds_raise_the_stake() -> None:
    assert discrete_kelly(D("0.6"), D("2"), D("1")) > discrete_kelly(
        D("0.6"), D("1"), D("1")
    )


def test_kelly_from_decimal_odds() -> None:
    """Fair probability 0.5 against odds of 3.0 is a large edge."""
    assert kelly_from_odds(D("0.5"), D("3")) == D("0.25")


def test_kelly_from_odds_at_fair_value_is_zero() -> None:
    assert kelly_from_odds(D("0.5"), D("2")) == D("0")


def test_continuous_kelly_is_mu_over_sigma_squared() -> None:
    assert continuous_kelly(D("0.02"), D("0.04")) == D("0.5")


@pytest.mark.parametrize(
    "args", [(D("-0.1"), D("1"), D("1")), (D("1.1"), D("1"), D("1"))]
)
def test_invalid_probability_is_refused(args) -> None:
    with pytest.raises(ValueError, match="probability"):
        discrete_kelly(*args)


def test_zero_variance_is_refused() -> None:
    with pytest.raises(ValueError, match="variance"):
        continuous_kelly(D("0.02"), D("0"))


# ===========================================================================
# Fractional Kelly and caps
# ===========================================================================


def test_quarter_kelly_scales_the_full_size() -> None:
    sizer = KellySizer(fraction_of_kelly=D("0.25"), max_fraction=D("1"))
    result = sizer.size(D("0.2"))
    assert result.fraction == D("0.05")
    assert result.full_kelly == D("0.2")
    assert result.binding_constraint == "kelly"


def test_the_hard_cap_overrides_kelly() -> None:
    """Kelly will happily recommend most of the portfolio on a confident but
    wrong estimate. The cap is what makes that survivable."""
    sizer = KellySizer(fraction_of_kelly=D("0.25"), max_fraction=D("0.05"))
    result = sizer.size(D("0.8"))   # quarter Kelly would be 20%
    assert result.fraction == D("0.05")
    assert result.binding_constraint == "max_fraction"
    assert result.is_capped


def test_tiny_edges_are_not_traded() -> None:
    sizer = KellySizer(min_fraction=D("0.002"))
    result = sizer.size(D("0.001"))
    assert result.fraction == D("0")
    assert result.binding_constraint == "below_minimum"


def test_no_edge_means_no_position() -> None:
    result = KellySizer().size(D("0"))
    assert result.fraction == D("0")
    assert result.binding_constraint == "no_edge"


def test_uncertainty_shrinks_the_size() -> None:
    """The same edge, measured less precisely, is sized smaller."""
    sizer = KellySizer(fraction_of_kelly=D("1"), max_fraction=D("1"))
    confident = sizer.size_with_uncertainty(D("0.02"), D("0.04"), D("0.001"))
    uncertain = sizer.size_with_uncertainty(D("0.02"), D("0.04"), D("0.015"))
    assert uncertain.fraction < confident.fraction


def test_an_edge_inside_the_noise_is_not_traded() -> None:
    sizer = KellySizer()
    result = sizer.size_with_uncertainty(D("0.01"), D("0.04"), D("0.02"))
    assert result.fraction == D("0")
    assert result.binding_constraint == "edge_within_noise"


def test_default_sizer_matches_the_governor_position_limit() -> None:
    """The sizer and the governor must agree, or the sizer spends its life
    proposing positions the governor then refuses."""
    from ioanna.research import DEFAULT_SIZER

    assert DEFAULT_SIZER.max_fraction == D("0.05")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fraction_of_kelly": D("0")},
        {"fraction_of_kelly": D("1.5")},
        {"max_fraction": D("0")},
        {"max_fraction": D("1.5")},
        {"min_fraction": D("-0.1")},
        {"min_fraction": D("0.5"), "max_fraction": D("0.05")},
    ],
)
def test_invalid_sizer_configuration_is_refused(kwargs) -> None:
    with pytest.raises(ValueError):
        KellySizer(**kwargs)
