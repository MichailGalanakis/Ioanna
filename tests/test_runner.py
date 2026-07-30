"""Integration tests for the passive core.

Gate 1 asks for a month of autonomous running with no wrong orders. These
tests are the standing part of that check: every order reviewed, every
approved order journalled, nothing reaching the ledger that the governor
refused.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ioanna.core import (
    ActionKind,
    ContributionSchedule,
    PassiveCore,
    RebalanceBands,
    Rebalancer,
    TargetAllocation,
    TaxLedger,
    Trigger,
)
from ioanna.governor import Governor, Limits, Rejection
from ioanna.journal import Journal

D = Decimal

IWDA, EIMI = "IWDA", "EIMI"
PRICES = {IWDA: D("100"), EIMI: D("50")}
DEEP = {IWDA: D("100000000"), EIMI: D("100000000")}


@pytest.fixture
def limits() -> Limits:
    return Limits(
        max_position_fraction=D("0.85"),   # core runs concentrated by design
        max_pillar_fraction={"core": D("1.0")},
        max_trades_per_day=5,
        max_drawdown=D("0.15"),
        min_liquidity_multiple=D("10"),
        allowed_venues=frozenset({"ibkr"}),
        allowed_instruments=frozenset({IWDA, EIMI}),
    )


@pytest.fixture
def core(limits: Limits):
    allocation = TargetAllocation({IWDA: D("0.8"), EIMI: D("0.2")})
    with Journal() as journal, TaxLedger() as ledger:
        yield PassiveCore(
            allocation=allocation,
            schedule=ContributionSchedule(amount=D("1000"), day_of_month=1),
            governor=Governor(limits),
            journal=journal,
            ledger=ledger,
            rebalancer=Rebalancer(allocation, RebalanceBands(), min_order=D("50")),
        )


def utc(y, m, d) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


# -- a normal cycle ---------------------------------------------------------


def test_contribution_cycle_produces_approved_orders(core) -> None:
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},   # 8000 / 2000, on target
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity=DEEP,
    )

    assert result.contribution is not None
    assert result.contribution.amount == D("1000")
    assert len(result.approved) == 2
    assert not result.refused
    assert all(i.action.trigger is Trigger.CONTRIBUTION for i in result.intents)


def test_nothing_due_means_nothing_happens(core) -> None:
    """Mid-month, on target: the correct number of orders is zero."""
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 2, 1),
        now=utc(2026, 2, 15),
        liquidity=DEEP,
    )
    assert result.did_nothing
    assert result.contribution is None


def test_order_quantities_follow_from_value_and_price(core) -> None:
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity=DEEP,
    )
    by_instrument = {i.action.instrument: i for i in result.intents}
    # 1000 contribution on an 11000 portfolio: 800 to IWDA at 100 = 8 shares.
    assert by_instrument[IWDA].order.quantity == D("8")
    assert by_instrument[EIMI].order.quantity == D("4")   # 200 at 50


# -- the governor is not optional ------------------------------------------


def test_every_order_is_reviewed(core) -> None:
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity=DEEP,
    )
    assert all(i.decision is not None for i in result.intents)


def test_refused_orders_are_kept_not_dropped(core) -> None:
    """A cycle with a refusal must look different from a quiet cycle."""
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity={IWDA: D("1"), EIMI: D("1")},   # unfillable book
    )
    assert result.refused
    assert all(
        Rejection.INSUFFICIENT_LIQUIDITY in i.decision.reasons
        for i in result.refused
    )


def test_kill_switch_stops_buying(core) -> None:
    core.governor.engage_kill_switch()
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity=DEEP,
    )
    assert not result.approved
    assert all(Rejection.KILL_SWITCH in i.decision.reasons for i in result.refused)


def test_trade_budget_limits_a_busy_cycle(core) -> None:
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        trades_today=5,
        liquidity=DEEP,
    )
    assert not result.approved
    assert all(
        Rejection.TRADE_BUDGET_EXHAUSTED in i.decision.reasons
        for i in result.refused
    )


def test_rebalancing_sales_survive_a_drawdown_halt(core) -> None:
    """Core sells are reduce-only, so a halt must not block the correction
    that would bring the portfolio back to target."""
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("180"), EIMI: D("20")},   # 18000/1000, far off
        last_contribution=date(2026, 2, 1),
        now=utc(2026, 2, 15),
        peak_equity=D("30000"),                       # deep drawdown
        liquidity=DEEP,
    )
    sells = [i for i in result.intents if i.order.side.value == "sell"]
    assert sells
    assert all(i.approved for i in sells)


# -- journalling ------------------------------------------------------------


def test_approved_orders_are_journalled_before_execution(core) -> None:
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity=DEEP,
    )
    for intent in result.approved:
        assert intent.position_id is not None
        assert core.journal.get(intent.position_id) is not None


def test_refused_orders_are_not_journalled(core) -> None:
    """The journal records positions, not rejected proposals."""
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity={IWDA: D("1"), EIMI: D("1")},
    )
    assert result.refused
    assert all(i.position_id is None for i in result.refused)
    assert core.journal.open_positions() == []


def test_hypothesis_records_the_actual_drift_numbers(core) -> None:
    """"Why did we buy in February" has to be answerable from the record."""
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("90"), EIMI: D("20")},   # 9000/1000, off target
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity=DEEP,
    )
    eimi = next(i for i in result.approved if i.action.instrument == EIMI)
    position = core.journal.get(eimi.position_id)

    data = position.hypothesis.supporting_data
    assert data["trigger"] in {t.value for t in Trigger}
    assert data["target_weight"] == "0.2"
    assert "value_gap" in data and "band_threshold" in data
    assert len(position.hypothesis.counter_argument) >= 20


def test_a_rebalancing_sale_states_the_tax_cost(core) -> None:
    """The counter argument for a sale must name the gain being realised."""
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("180"), EIMI: D("20")},
        last_contribution=date(2026, 2, 1),
        now=utc(2026, 2, 15),
        liquidity=DEEP,
    )
    sells = [i for i in result.approved if i.order.side.value == "sell"]
    assert sells
    counter = core.journal.get(sells[0].position_id).hypothesis.counter_argument
    assert "15%" in counter


# -- settlement -------------------------------------------------------------


def test_settling_a_buy_records_cost_basis(core) -> None:
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity=DEEP,
    )
    intent = next(i for i in result.approved if i.action.instrument == IWDA)
    core.settle(intent, fill_price=D("101"), fill_quantity=D("8"),
                at=utc(2026, 2, 1), fees=D("1"))

    assert core.ledger.quantity(IWDA) == D("8")
    assert core.ledger.cost_basis(IWDA) == D("809")   # 8 * 101 + 1


def test_a_refused_order_cannot_be_settled(core) -> None:
    """Nothing the governor blocked may reach the tax ledger."""
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity={IWDA: D("1"), EIMI: D("1")},
    )
    with pytest.raises(ValueError, match="refused"):
        core.settle(result.refused[0], D("100"), D("8"))


def test_settlement_uses_the_fill_price_not_the_reference(core) -> None:
    """Slippage has to land in the cost basis or the tax record is wrong."""
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity=DEEP,
    )
    intent = next(i for i in result.approved if i.action.instrument == IWDA)
    core.settle(intent, fill_price=D("103.5"), fill_quantity=D("8"),
                at=utc(2026, 2, 1))
    assert core.ledger.average_cost(IWDA) == D("103.5")


# -- input validation -------------------------------------------------------


def test_a_missing_price_is_refused(core) -> None:
    with pytest.raises(ValueError, match="no price"):
        core.run_cycle(
            prices={IWDA: D("100")},
            quantities={IWDA: D("80"), EIMI: D("40")},
            last_contribution=date(2026, 1, 1),
            now=utc(2026, 2, 1),
        )


def test_an_empty_start_with_nothing_due_is_refused(core) -> None:
    with pytest.raises(ValueError, match="no holdings and no contribution"):
        core.run_cycle(
            prices=PRICES,
            quantities={},
            last_contribution=date(2026, 2, 1),
            now=utc(2026, 2, 15),
        )


# -- Gate 1: a month of autonomous operation -------------------------------


def test_a_year_of_cycles_runs_clean(core) -> None:
    """Twelve monthly contributions with prices moving underneath.

    Checks the properties Gate 1 cares about: every order reviewed, nothing
    unapproved settled, the tax ledger agreeing with what was filled, and the
    allocation still near target at the end.
    """
    quantities = {IWDA: D("80"), EIMI: D("40")}
    prices = dict(PRICES)
    last_contribution = date(2025, 12, 1)

    settled = {IWDA: D("0"), EIMI: D("0")}
    orders = 0

    for month in range(1, 13):
        now = utc(2026, month, 1)
        # IWDA outruns EIMI, so the allocation drifts and eventually breaches.
        prices[IWDA] *= D("1.015")
        prices[EIMI] *= D("1.002")

        result = core.run_cycle(
            prices=prices,
            quantities=quantities,
            last_contribution=last_contribution,
            now=now,
            liquidity=DEEP,
        )

        for intent in result.intents:
            assert intent.decision is not None          # reviewed, always
            if not intent.approved:
                continue

            orders += 1
            qty = intent.order.quantity
            core.settle(intent, prices[intent.action.instrument], qty, at=now)

            signed = qty if intent.order.side.value == "buy" else -qty
            quantities[intent.action.instrument] += signed
            settled[intent.action.instrument] += signed

        if result.contribution:
            last_contribution = result.contribution.due_on

    assert orders >= 12

    # The ledger and the portfolio must not have diverged.
    for instrument in (IWDA, EIMI):
        assert core.ledger.quantity(instrument) == settled[instrument]

    # Every filled order left a record behind.
    assert len(core.journal.open_positions()) == orders

    # And the allocation held despite a year of divergent returns.
    total = sum(quantities[i] * prices[i] for i in quantities)
    iwda_weight = quantities[IWDA] * prices[IWDA] / total
    assert D("0.75") <= iwda_weight <= D("0.85")


def test_a_year_of_contributions_realises_no_gains(core) -> None:
    """The tax claim, end to end: contribution-first rebalancing through a
    year of drift should not trigger a single taxable disposal."""
    quantities = {IWDA: D("80"), EIMI: D("40")}
    prices = dict(PRICES)
    last_contribution = date(2025, 12, 1)

    for month in range(1, 13):
        now = utc(2026, month, 1)
        prices[IWDA] *= D("1.015")
        prices[EIMI] *= D("1.002")

        result = core.run_cycle(
            prices=prices, quantities=quantities,
            last_contribution=last_contribution, now=now, liquidity=DEEP,
        )
        for intent in result.approved:
            core.settle(intent, prices[intent.action.instrument],
                        intent.order.quantity, at=now)
            signed = (
                intent.order.quantity
                if intent.order.side.value == "buy"
                else -intent.order.quantity
            )
            quantities[intent.action.instrument] += signed

        if result.contribution:
            last_contribution = result.contribution.due_on

    assert core.ledger.realized_gain(2026) == D("0")
    assert core.ledger.tax_summary(2026)["estimated_tax"] == D("0")


# ===========================================================================
# Whole shares and cash carry-over
# ===========================================================================


@pytest.fixture
def whole_share_core():
    """A single-fund core in an instrument that trades in whole shares.

    IBKR requires $5m average daily volume and $5bn market cap before
    fractional trading is enabled on European ETFs, and many UCITS funds do
    not clear it. Whole shares are the assumption until a venue says
    otherwise.
    """
    allocation = TargetAllocation({"VWCE": D("1")})
    limits = Limits(
        max_position_fraction=D("1.0"),
        max_pillar_fraction={"core": D("1.0")},
        max_trades_per_day=2,
        max_drawdown=D("0.35"),
        min_liquidity_multiple=D("10"),
        allowed_venues=frozenset({"ibkr"}),
        allowed_instruments=frozenset({"VWCE"}),
    )
    with Journal() as journal, TaxLedger() as ledger:
        yield PassiveCore(
            allocation=allocation,
            schedule=ContributionSchedule(amount=D("500"), day_of_month=1),
            governor=Governor(limits),
            journal=journal,
            ledger=ledger,
            rebalancer=Rebalancer(allocation, RebalanceBands(), min_order=D("100")),
            lot_sizes={"VWCE": D("1")},
        )


def test_order_is_rounded_down_to_whole_shares(whole_share_core) -> None:
    """€500 into a €137 fund is 3 shares, not 3.649."""
    result = whole_share_core.run_cycle(
        prices={"VWCE": D("137")},
        quantities={"VWCE": D("10")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity={"VWCE": D("100000000")},
    )
    assert len(result.approved) == 1
    assert result.approved[0].order.quantity == D("3")


def test_rounding_is_never_up(whole_share_core) -> None:
    """Rounding a buy up spends money that was not contributed."""
    result = whole_share_core.run_cycle(
        prices={"VWCE": D("137")},
        quantities={"VWCE": D("10")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity={"VWCE": D("100000000")},
    )
    spent = result.approved[0].order.quantity * D("137")
    assert spent <= D("500")


def test_the_remainder_is_carried_not_dropped(whole_share_core) -> None:
    """3 shares at 137 is 411, leaving 89 to carry."""
    result = whole_share_core.run_cycle(
        prices={"VWCE": D("137")},
        quantities={"VWCE": D("10")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity={"VWCE": D("100000000")},
    )
    assert result.cash_carried == D("89")


def test_carried_cash_is_spendable_next_cycle(whole_share_core) -> None:
    """500 + 89 carried = 589, which buys 4 shares at 137 rather than 3."""
    result = whole_share_core.run_cycle(
        prices={"VWCE": D("137")},
        quantities={"VWCE": D("13")},
        last_contribution=date(2026, 2, 1),
        now=utc(2026, 3, 1),
        liquidity={"VWCE": D("100000000")},
        carried_cash=D("89"),
    )
    assert result.approved[0].order.quantity == D("4")


def test_an_order_below_one_lot_produces_nothing(whole_share_core) -> None:
    """A contribution smaller than a single share cannot be executed."""
    core = whole_share_core
    core.schedule = ContributionSchedule(amount=D("120"), day_of_month=1)
    result = core.run_cycle(
        prices={"VWCE": D("137")},
        quantities={"VWCE": D("10")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity={"VWCE": D("100000000")},
    )
    assert not result.intents
    assert result.cash_carried == D("120")


def test_carry_accumulates_until_it_buys_a_share(whole_share_core) -> None:
    """Two cycles of 120 cannot buy a 137 share; three can."""
    core = whole_share_core
    core.schedule = ContributionSchedule(amount=D("120"), day_of_month=1)

    carried = D("0")
    bought = D("0")
    for month in range(2, 6):
        result = core.run_cycle(
            prices={"VWCE": D("137")},
            quantities={"VWCE": D("10") + bought},
            last_contribution=date(2026, month - 1, 1),
            now=utc(2026, month, 1),
            liquidity={"VWCE": D("100000000")},
            carried_cash=carried,
        )
        carried = result.cash_carried
        for intent in result.approved:
            bought += intent.order.quantity

    # Four contributions of 120 = 480, which buys three shares at 137 (411).
    assert bought == D("3")
    assert carried == D("69")


def test_no_contribution_is_lost_over_a_year(whole_share_core) -> None:
    """Everything contributed is either invested or still carried."""
    core = whole_share_core
    price = D("137")
    carried = D("0")
    held = D("10")
    contributed = D("0")

    for month in range(1, 13):
        result = core.run_cycle(
            prices={"VWCE": price},
            quantities={"VWCE": held},
            last_contribution=date(2025 if month == 1 else 2026,
                                   12 if month == 1 else month - 1, 1),
            now=utc(2026, month, 1),
            liquidity={"VWCE": D("100000000")},
            carried_cash=carried,
        )
        if result.contribution:
            contributed += result.contribution.amount
        carried = result.cash_carried
        for intent in result.approved:
            held += intent.order.quantity

    invested = (held - D("10")) * price
    assert invested + carried == contributed


def test_fractional_instruments_are_not_rounded(core) -> None:
    """With no lot size configured, fractional quantities pass through."""
    result = core.run_cycle(
        prices=PRICES,
        quantities={IWDA: D("80"), EIMI: D("40")},
        last_contribution=date(2026, 1, 1),
        now=utc(2026, 2, 1),
        liquidity=DEEP,
    )
    assert result.cash_carried == D("0")


def test_negative_carried_cash_is_refused(whole_share_core) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        whole_share_core.run_cycle(
            prices={"VWCE": D("137")},
            quantities={"VWCE": D("10")},
            last_contribution=date(2026, 1, 1),
            now=utc(2026, 2, 1),
            carried_cash=D("-1"),
        )
