"""Governor tests.

Gate 0 requires that the governor correctly refuses every limit breach. These
tests are that gate, so they lean towards checking the specific rejection
reason rather than just `approved is False` -- an order refused for the wrong
reason is a bug that would otherwise hide.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ioanna.governor import (
    Governor,
    Limits,
    OrderRequest,
    PortfolioState,
    Rejection,
    Side,
)

VENUE = "binance"
INSTRUMENT = "BTC/USDT"


@pytest.fixture
def limits() -> Limits:
    return Limits(
        max_position_fraction=Decimal("0.05"),
        max_pillar_fraction={
            "core": Decimal("0.70"),
            "satellite": Decimal("0.25"),
            "exploratory": Decimal("0.05"),
        },
        max_trades_per_day=5,
        max_drawdown=Decimal("0.15"),
        min_liquidity_multiple=Decimal("10"),
        max_state_age_seconds=60.0,
        allowed_venues=frozenset({VENUE}),
        allowed_instruments=frozenset({INSTRUMENT}),
    )


@pytest.fixture
def governor(limits: Limits) -> Governor:
    return Governor(limits)


def make_order(**overrides) -> OrderRequest:
    """A well-formed order that passes every check, unless overridden."""
    params = {
        "instrument": INSTRUMENT,
        "venue": VENUE,
        "side": Side.BUY,
        "quantity": Decimal("0.01"),
        "reference_price": Decimal("100000"),  # notional = 1000
        "strategy_pillar": "satellite",
        "reduce_only": False,
        "venue_liquidity": Decimal("1000000"),
    }
    params.update(overrides)
    return OrderRequest(**params)


def make_state(**overrides) -> PortfolioState:
    params = {
        "equity": Decimal("100000"),
        "peak_equity": Decimal("100000"),
        "positions": {},
        "pillar_exposure": {},
        "trades_today": 0,
        "age_seconds": 0.0,
    }
    params.update(overrides)
    return PortfolioState(**params)


# -- the happy path ---------------------------------------------------------


def test_clean_order_is_approved(governor: Governor) -> None:
    decision = governor.review(make_order(), make_state())
    assert decision.approved, decision.violations
    assert decision.violations == ()
    assert bool(decision) is True


# -- whitelists -------------------------------------------------------------


def test_unknown_venue_is_refused(governor: Governor) -> None:
    decision = governor.review(make_order(venue="sketchy-dex"), make_state())
    assert not decision.approved
    assert Rejection.VENUE_NOT_ALLOWED in decision.reasons


def test_unknown_instrument_is_refused(governor: Governor) -> None:
    decision = governor.review(make_order(instrument="DOGE/USDT"), make_state())
    assert not decision.approved
    assert Rejection.INSTRUMENT_NOT_ALLOWED in decision.reasons


def test_unknown_pillar_is_refused(governor: Governor) -> None:
    """A pillar with no configured limit must not default to unlimited."""
    decision = governor.review(make_order(strategy_pillar="moonshot"), make_state())
    assert not decision.approved
    assert Rejection.PILLAR_NOT_ALLOWED in decision.reasons


def test_empty_whitelist_blocks_everything() -> None:
    """The default limits ship with empty whitelists, so nothing is tradeable."""
    governor = Governor(Limits())
    decision = governor.review(make_order(), make_state())
    assert not decision.approved
    assert Rejection.VENUE_NOT_ALLOWED in decision.reasons
    assert Rejection.INSTRUMENT_NOT_ALLOWED in decision.reasons


# -- position sizing --------------------------------------------------------


def test_position_at_the_cap_is_allowed(governor: Governor) -> None:
    """Cap is 5% of 100k = 5000. An order landing exactly there is fine."""
    order = make_order(quantity=Decimal("0.05"))  # notional 5000
    decision = governor.review(order, make_state())
    assert decision.approved, decision.violations


def test_position_one_unit_over_the_cap_is_refused(governor: Governor) -> None:
    order = make_order(quantity=Decimal("0.050001"))
    decision = governor.review(order, make_state())
    assert not decision.approved
    assert Rejection.POSITION_TOO_LARGE in decision.reasons


def test_position_limit_counts_existing_exposure(governor: Governor) -> None:
    """4500 held + 1000 new = 5500, over the 5000 cap."""
    state = make_state(positions={INSTRUMENT: Decimal("4500")})
    decision = governor.review(make_order(), state)
    assert not decision.approved
    assert Rejection.POSITION_TOO_LARGE in decision.reasons


def test_reduce_only_shrinks_rather_than_grows(governor: Governor) -> None:
    """An exit from an oversized position must not be read as new exposure."""
    state = make_state(positions={INSTRUMENT: Decimal("4900")})
    decision = governor.review(make_order(reduce_only=True), state)
    assert decision.approved, decision.violations


def test_oversized_exit_does_not_flip_to_positive_exposure(
    governor: Governor,
) -> None:
    """Closing more than we hold floors at zero instead of wrapping negative."""
    state = make_state(positions={INSTRUMENT: Decimal("100")})
    order = make_order(reduce_only=True, quantity=Decimal("0.05"))
    decision = governor.review(order, state)
    assert decision.approved, decision.violations


# -- pillar exposure --------------------------------------------------------


def test_pillar_exposure_cap_is_enforced(governor: Governor) -> None:
    """Satellite cap is 25% of 100k = 25000."""
    state = make_state(
        pillar_exposure={"satellite": Decimal("24500")},
        positions={},
    )
    decision = governor.review(make_order(), state)
    assert not decision.approved
    assert Rejection.PILLAR_EXPOSURE_EXCEEDED in decision.reasons


def test_exploratory_pillar_has_the_tightest_cap(governor: Governor) -> None:
    """5% of equity, matching the allocation in the architecture doc."""
    state = make_state(pillar_exposure={"exploratory": Decimal("4500")})
    decision = governor.review(make_order(strategy_pillar="exploratory"), state)
    assert not decision.approved
    assert Rejection.PILLAR_EXPOSURE_EXCEEDED in decision.reasons


def test_pillars_are_accounted_separately(governor: Governor) -> None:
    """A full core book must not constrain a satellite order."""
    state = make_state(pillar_exposure={"core": Decimal("69000")})
    decision = governor.review(make_order(strategy_pillar="satellite"), state)
    assert decision.approved, decision.violations


# -- trade budget -----------------------------------------------------------


def test_trade_budget_is_enforced(governor: Governor) -> None:
    decision = governor.review(make_order(), make_state(trades_today=5))
    assert not decision.approved
    assert Rejection.TRADE_BUDGET_EXHAUSTED in decision.reasons


def test_last_trade_of_the_budget_is_allowed(governor: Governor) -> None:
    decision = governor.review(make_order(), make_state(trades_today=4))
    assert decision.approved, decision.violations


def test_exits_do_not_consume_the_trade_budget(governor: Governor) -> None:
    """The budget is a cost control. It must never block an exit."""
    state = make_state(trades_today=99, positions={INSTRUMENT: Decimal("2000")})
    decision = governor.review(make_order(reduce_only=True), state)
    assert decision.approved, decision.violations


# -- drawdown halt ----------------------------------------------------------


def test_drawdown_at_the_limit_halts_new_risk(governor: Governor) -> None:
    state = make_state(equity=Decimal("85000"), peak_equity=Decimal("100000"))
    decision = governor.review(make_order(), state)
    assert not decision.approved
    assert Rejection.DRAWDOWN_HALT in decision.reasons


def test_drawdown_just_inside_the_limit_still_trades(governor: Governor) -> None:
    state = make_state(equity=Decimal("85001"), peak_equity=Decimal("100000"))
    decision = governor.review(make_order(), state)
    assert decision.approved, decision.violations


def test_drawdown_halt_still_permits_exits(governor: Governor) -> None:
    """Otherwise a halt would trap us in the position that caused it."""
    state = make_state(
        equity=Decimal("70000"),
        peak_equity=Decimal("100000"),
        positions={INSTRUMENT: Decimal("2000")},
    )
    decision = governor.review(make_order(reduce_only=True), state)
    assert decision.approved, decision.violations


def test_drawdown_uses_peak_not_starting_equity(governor: Governor) -> None:
    """Up 50% then down 15% off the peak is still a halt."""
    state = make_state(equity=Decimal("127500"), peak_equity=Decimal("150000"))
    decision = governor.review(make_order(), state)
    assert not decision.approved
    assert Rejection.DRAWDOWN_HALT in decision.reasons


# -- kill switch ------------------------------------------------------------


def test_kill_switch_blocks_new_risk(governor: Governor) -> None:
    governor.engage_kill_switch()
    decision = governor.review(make_order(), make_state())
    assert not decision.approved
    assert Rejection.KILL_SWITCH in decision.reasons


def test_kill_switch_permits_liquidation(governor: Governor) -> None:
    governor.engage_kill_switch()
    state = make_state(positions={INSTRUMENT: Decimal("2000")})
    decision = governor.review(make_order(reduce_only=True), state)
    assert decision.approved, decision.violations


def test_kill_switch_release_is_explicit(governor: Governor) -> None:
    governor.engage_kill_switch()
    assert governor.kill_switch_engaged
    governor.release_kill_switch()
    assert not governor.kill_switch_engaged
    assert governor.review(make_order(), make_state()).approved


def test_reduce_only_exemption_does_not_bypass_other_limits(
    governor: Governor,
) -> None:
    """The halt exemption is for halts only -- whitelists still apply."""
    governor.engage_kill_switch()
    decision = governor.review(
        make_order(reduce_only=True, venue="sketchy-dex"), make_state()
    )
    assert not decision.approved
    assert Rejection.VENUE_NOT_ALLOWED in decision.reasons


# -- liquidity --------------------------------------------------------------


def test_thin_book_is_refused(governor: Governor) -> None:
    """Notional 1000 needs 10x depth. 9999 is not enough."""
    decision = governor.review(
        make_order(venue_liquidity=Decimal("9999")), make_state()
    )
    assert not decision.approved
    assert Rejection.INSUFFICIENT_LIQUIDITY in decision.reasons


def test_unmeasured_liquidity_is_refused_not_assumed(governor: Governor) -> None:
    """Fail closed: an unknown book is treated as an empty one."""
    decision = governor.review(make_order(venue_liquidity=None), make_state())
    assert not decision.approved
    assert Rejection.INSUFFICIENT_LIQUIDITY in decision.reasons


# -- malformed orders and state --------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", Decimal("0")),
        ("quantity", Decimal("-1")),
        ("reference_price", Decimal("0")),
        ("reference_price", Decimal("-100")),
        ("instrument", ""),
        ("venue", ""),
    ],
)
def test_malformed_orders_are_refused(governor: Governor, field, value) -> None:
    decision = governor.review(make_order(**{field: value}), make_state())
    assert not decision.approved
    assert Rejection.INVALID_ORDER in decision.reasons


def test_stale_state_is_refused(governor: Governor) -> None:
    """Limit checks against an old snapshot are checks against fiction."""
    decision = governor.review(make_order(), make_state(age_seconds=61.0))
    assert not decision.approved
    assert Rejection.STALE_STATE in decision.reasons


def test_fresh_state_passes(governor: Governor) -> None:
    decision = governor.review(make_order(), make_state(age_seconds=59.9))
    assert decision.approved, decision.violations


def test_zero_equity_is_refused(governor: Governor) -> None:
    decision = governor.review(make_order(), make_state(equity=Decimal("0")))
    assert not decision.approved
    assert Rejection.INVALID_ORDER in decision.reasons


# -- behaviour of the check set as a whole ---------------------------------


def test_all_violations_are_reported_not_just_the_first(governor: Governor) -> None:
    order = make_order(
        venue="sketchy-dex",
        instrument="DOGE/USDT",
        strategy_pillar="moonshot",
        venue_liquidity=Decimal("1"),
    )
    decision = governor.review(order, make_state(trades_today=10))
    reasons = set(decision.reasons)
    assert {
        Rejection.VENUE_NOT_ALLOWED,
        Rejection.INSTRUMENT_NOT_ALLOWED,
        Rejection.PILLAR_NOT_ALLOWED,
        Rejection.INSUFFICIENT_LIQUIDITY,
        Rejection.TRADE_BUDGET_EXHAUSTED,
    } <= reasons


def test_review_is_deterministic(governor: Governor) -> None:
    """Same inputs, same answer -- no clock, no randomness, no I/O."""
    order, state = make_order(), make_state()
    first = governor.review(order, state)
    for _ in range(50):
        assert governor.review(order, state) == first


def test_review_does_not_mutate_its_inputs(governor: Governor) -> None:
    state = make_state(
        positions={INSTRUMENT: Decimal("1000")},
        pillar_exposure={"satellite": Decimal("1000")},
        trades_today=2,
    )
    governor.review(make_order(), state)
    assert state.positions == {INSTRUMENT: Decimal("1000")}
    assert state.pillar_exposure == {"satellite": Decimal("1000")}
    assert state.trades_today == 2


# -- limit validation -------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_position_fraction": Decimal("0")},
        {"max_position_fraction": Decimal("1.5")},
        {"max_drawdown": Decimal("0")},
        {"max_drawdown": Decimal("1")},
        {"max_trades_per_day": -1},
        {"min_liquidity_multiple": Decimal("-1")},
        {"max_pillar_fraction": {"core": Decimal("1.5")}},
    ],
)
def test_nonsensical_limits_are_rejected_at_construction(kwargs) -> None:
    with pytest.raises(ValueError):
        Limits(**kwargs)
