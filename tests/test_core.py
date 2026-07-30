"""Passive core tests: allocation, rebalancing, tax lots."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ioanna.core import (
    ActionKind,
    InsufficientHoldingsError,
    RebalanceBands,
    Rebalancer,
    TargetAllocation,
    TaxLedger,
    Trigger,
)

D = Decimal


def utc(y, m, d) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


@pytest.fixture
def allocation() -> TargetAllocation:
    """80/20 developed/emerging, the usual IWDA+EIMI shape."""
    return TargetAllocation({"IWDA": D("0.8"), "EIMI": D("0.2")})


@pytest.fixture
def rebalancer(allocation: TargetAllocation) -> Rebalancer:
    return Rebalancer(allocation, RebalanceBands(), min_order=D("50"))


# ===========================================================================
# Allocation
# ===========================================================================


def test_weights_must_sum_to_exactly_one() -> None:
    with pytest.raises(ValueError, match="sum to exactly 1"):
        TargetAllocation({"IWDA": D("0.8"), "EIMI": D("0.19")})


def test_near_miss_weights_are_still_refused() -> None:
    """0.999 would leave 0.1% permanently unallocated, silently."""
    with pytest.raises(ValueError, match="sum to exactly 1"):
        TargetAllocation({"IWDA": D("0.799"), "EIMI": D("0.2")})


def test_single_instrument_allocation_is_valid() -> None:
    alloc = TargetAllocation({"VWCE": D("1")})
    assert alloc.instruments == {"VWCE"}


@pytest.mark.parametrize(
    "weights",
    [
        {},
        {"IWDA": D("-0.1"), "EIMI": D("1.1")},
        {"IWDA": D("1.5"), "EIMI": D("-0.5")},
    ],
)
def test_invalid_weights_are_refused(weights) -> None:
    with pytest.raises(ValueError):
        TargetAllocation(weights)


def test_drift_on_a_balanced_portfolio_is_zero(allocation) -> None:
    drifts = allocation.drifts({"IWDA": D("8000"), "EIMI": D("2000")})
    assert drifts["IWDA"].absolute == 0
    assert drifts["EIMI"].absolute == 0
    assert drifts["IWDA"].value_gap == 0


def test_drift_measures_both_absolute_and_relative(allocation) -> None:
    """9000/1000 on an 80/20 target: IWDA 90%, EIMI 10%."""
    drifts = allocation.drifts({"IWDA": D("9000"), "EIMI": D("1000")})

    assert drifts["IWDA"].current_weight == D("0.9")
    assert drifts["IWDA"].absolute == D("0.1")  # 10 points over
    assert drifts["EIMI"].absolute == D("-0.1")
    # EIMI is half its target weight: -0.1 / 0.2 = -50% relative
    assert drifts["EIMI"].relative == D("-0.5")


def test_value_gap_points_toward_target(allocation) -> None:
    drifts = allocation.drifts({"IWDA": D("9000"), "EIMI": D("1000")})
    assert drifts["IWDA"].value_gap == D("-1000")  # sell 1000
    assert drifts["EIMI"].value_gap == D("1000")   # buy 1000


def test_untargeted_holdings_appear_with_zero_target(allocation) -> None:
    """Something held but not wanted must not hide by being absent."""
    drifts = allocation.drifts(
        {"IWDA": D("8000"), "EIMI": D("2000"), "DOGE": D("500")}
    )
    assert drifts["DOGE"].target_weight == 0
    assert drifts["DOGE"].relative == D("Infinity")


def test_empty_portfolio_is_refused(allocation) -> None:
    with pytest.raises(ValueError, match="no value"):
        allocation.drifts({"IWDA": D("0")})


def test_negative_holdings_are_refused(allocation) -> None:
    with pytest.raises(ValueError, match="negative holding"):
        allocation.drifts({"IWDA": D("-100"), "EIMI": D("200")})


# ===========================================================================
# Bands
# ===========================================================================


def test_large_sleeve_uses_the_absolute_band() -> None:
    """80% target: 25% relative = 20 points, so the 5-point band binds."""
    assert RebalanceBands().threshold_for(D("0.8")) == D("0.05")


def test_small_sleeve_uses_the_relative_band() -> None:
    """5% target: 25% relative = 1.25 points, tighter than the 5-point band.

    Without this leg a 5% sleeve could reach 10% -- double its target --
    before an absolute band noticed.
    """
    assert RebalanceBands().threshold_for(D("0.05")) == D("0.0125")


def test_zero_target_tolerates_nothing() -> None:
    assert RebalanceBands().threshold_for(D("0")) == 0


@pytest.mark.parametrize(
    "kwargs",
    [{"absolute": D("0")}, {"absolute": D("1.5")}, {"relative": D("0")}],
)
def test_invalid_bands_are_refused(kwargs) -> None:
    with pytest.raises(ValueError):
        RebalanceBands(**kwargs)


# ===========================================================================
# Rebalancing
# ===========================================================================


def test_balanced_portfolio_with_no_contribution_does_nothing(rebalancer) -> None:
    plan = rebalancer.plan({"IWDA": D("8000"), "EIMI": D("2000")})
    assert plan.is_empty
    assert not plan.breaches


def test_small_drift_inside_the_bands_does_nothing(rebalancer) -> None:
    """82/18 is 2 points out -- inside the 5-point band for IWDA and inside
    EIMI's 5-point relative band (0.2 * 0.25 = 0.05)."""
    plan = rebalancer.plan({"IWDA": D("8200"), "EIMI": D("1800")})
    assert plan.is_empty


def test_breach_triggers_a_correction(rebalancer) -> None:
    """90/10: IWDA is 10 points over, EIMI 10 points under."""
    plan = rebalancer.plan({"IWDA": D("9000"), "EIMI": D("1000")})

    assert plan.breaches == {"IWDA", "EIMI"}
    by_instrument = {a.instrument: a for a in plan.actions}
    assert by_instrument["IWDA"].kind is ActionKind.SELL
    assert by_instrument["IWDA"].value == D("1000")
    assert by_instrument["EIMI"].kind is ActionKind.BUY
    assert plan.requires_sales


def test_contribution_goes_to_the_underweight_holding(rebalancer) -> None:
    """The tax-free correction: new money, no sales."""
    plan = rebalancer.plan(
        {"IWDA": D("9000"), "EIMI": D("1000")}, contribution=D("1000")
    )

    buys = [a for a in plan.actions if a.trigger is Trigger.CONTRIBUTION]
    assert len(buys) == 1
    assert buys[0].instrument == "EIMI"
    assert buys[0].kind is ActionKind.BUY


def test_a_sufficient_contribution_avoids_sales_entirely(rebalancer) -> None:
    """9000/1000 needs EIMI at 20%. A 2500 contribution gets there without
    selling anything, which is the whole point of contribution-first."""
    plan = rebalancer.plan(
        {"IWDA": D("9000"), "EIMI": D("1000")}, contribution=D("2500")
    )
    assert not plan.requires_sales
    assert plan.breaches == frozenset()


def test_contribution_targets_the_post_contribution_portfolio(rebalancer) -> None:
    """Aiming at pre-contribution targets would systematically undershoot."""
    plan = rebalancer.plan({"IWDA": D("8000"), "EIMI": D("2000")},
                           contribution=D("1000"))
    # Post-contribution total is 11000, so targets are 8800 / 2200.
    buys = {a.instrument: a.value for a in plan.actions}
    assert buys["IWDA"] == D("800")
    assert buys["EIMI"] == D("200")


def test_contribution_is_fully_deployed(rebalancer) -> None:
    plan = rebalancer.plan({"IWDA": D("8000"), "EIMI": D("2000")},
                           contribution=D("1000"))
    assert plan.contribution_deployed == D("1000")
    assert plan.cash_remaining == D("0")


def test_partial_contribution_splits_proportionally_to_gaps(rebalancer) -> None:
    """When the contribution cannot close every gap, every underweight
    holding should move toward target at the same rate."""
    plan = rebalancer.plan({"IWDA": D("5000"), "EIMI": D("500")},
                           contribution=D("1000"))
    buys = {a.instrument: a.value for a in plan.actions
            if a.trigger is Trigger.CONTRIBUTION}
    assert set(buys) == {"IWDA", "EIMI"}
    assert sum(buys.values()) == D("1000")


def test_allow_sales_false_never_realises_a_gain(rebalancer) -> None:
    """Contribution-only mode, for when a tax year should stay clean."""
    plan = rebalancer.plan(
        {"IWDA": D("9000"), "EIMI": D("1000")},
        contribution=D("100"),
        allow_sales=False,
    )
    assert not plan.requires_sales
    assert all(a.kind is ActionKind.BUY for a in plan.actions)


def test_untargeted_holding_is_sold_in_full(rebalancer) -> None:
    plan = rebalancer.plan(
        {"IWDA": D("8000"), "EIMI": D("2000"), "DOGE": D("500")}
    )
    doge = [a for a in plan.actions if a.instrument == "DOGE"]
    assert len(doge) == 1
    assert doge[0].kind is ActionKind.SELL
    assert doge[0].value == D("500")
    assert doge[0].trigger is Trigger.UNTARGETED


def test_dust_corrections_are_suppressed(allocation) -> None:
    """A tiny correction costs a commission and achieves nothing."""
    rb = Rebalancer(allocation, RebalanceBands(), min_order=D("50"))
    plan = rb.plan({"IWDA": D("8000"), "EIMI": D("2000")}, contribution=D("10"))
    assert plan.is_empty
    assert plan.cash_remaining == D("10")


def test_negative_contribution_is_refused(rebalancer) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        rebalancer.plan({"IWDA": D("8000")}, contribution=D("-100"))


def test_nothing_to_allocate_is_refused(rebalancer) -> None:
    with pytest.raises(ValueError, match="nothing to allocate"):
        rebalancer.plan({}, contribution=D("0"))


def test_first_contribution_into_an_empty_portfolio(rebalancer) -> None:
    """Opening position: no holdings, one contribution, target weights."""
    plan = rebalancer.plan({}, contribution=D("10000"))
    buys = {a.instrument: a.value for a in plan.actions}
    assert buys == {"IWDA": D("8000"), "EIMI": D("2000")}


def test_plan_turnover_sums_the_actions(rebalancer) -> None:
    plan = rebalancer.plan({"IWDA": D("9000"), "EIMI": D("1000")})
    assert plan.turnover == sum(a.value for a in plan.actions)


def test_repeated_planning_is_stable(rebalancer) -> None:
    """Planning twice on the same inputs must not drift."""
    holdings = {"IWDA": D("9000"), "EIMI": D("1000")}
    first = rebalancer.plan(holdings)
    second = rebalancer.plan(holdings)
    assert first.actions == second.actions


def test_applying_the_plan_lands_inside_the_bands(rebalancer) -> None:
    """The plan must actually fix what it flagged."""
    holdings = {"IWDA": D("9000"), "EIMI": D("1000")}
    plan = rebalancer.plan(holdings)

    after = dict(holdings)
    for action in plan.actions:
        delta = action.value if action.kind is ActionKind.BUY else -action.value
        after[action.instrument] = after.get(action.instrument, D(0)) + delta

    assert rebalancer.plan(after).is_empty


# ===========================================================================
# Tax lots
# ===========================================================================


@pytest.fixture
def ledger() -> TaxLedger:
    with TaxLedger() as t:
        yield t


def test_acquisition_records_cost_including_fees(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("90"), utc(2026, 1, 15), fees=D("5"))
    assert ledger.quantity("IWDA") == D("100")
    assert ledger.cost_basis("IWDA") == D("9005")


def test_average_cost_reflects_fees(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("90"), utc(2026, 1, 15), fees=D("10"))
    assert ledger.average_cost("IWDA") == D("90.1")


def test_disposal_is_fifo(ledger) -> None:
    """Oldest lot goes first, and the gain is measured against its cost."""
    ledger.acquire("IWDA", D("100"), D("80"), utc(2026, 1, 15))
    ledger.acquire("IWDA", D("100"), D("100"), utc(2026, 6, 15))

    disposals = ledger.dispose("IWDA", D("100"), D("120"), utc(2026, 12, 1))

    assert len(disposals) == 1
    assert disposals[0].acquired_at == utc(2026, 1, 15)
    assert disposals[0].cost_basis == D("8000")
    assert disposals[0].gain == D("4000")
    assert ledger.quantity("IWDA") == D("100")


def test_disposal_spanning_lots_produces_one_record_each(ledger) -> None:
    """A blended average would lose the acquisition dates the return needs."""
    ledger.acquire("IWDA", D("100"), D("80"), utc(2026, 1, 15))
    ledger.acquire("IWDA", D("100"), D("100"), utc(2026, 6, 15))

    disposals = ledger.dispose("IWDA", D("150"), D("120"), utc(2026, 12, 1))

    assert len(disposals) == 2
    assert disposals[0].quantity == D("100")
    assert disposals[1].quantity == D("50")
    assert disposals[0].acquired_at != disposals[1].acquired_at
    assert ledger.quantity("IWDA") == D("50")


def test_partial_lot_disposal_leaves_the_remainder(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("90"), utc(2026, 1, 15), fees=D("10"))
    ledger.dispose("IWDA", D("40"), D("100"), utc(2026, 6, 1))

    assert ledger.quantity("IWDA") == D("60")
    # 60% of a 9010 basis stays with the open remainder.
    assert ledger.cost_basis("IWDA") == D("5406")


def test_disposal_fees_reduce_proceeds(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("90"), utc(2026, 1, 15))
    disposals = ledger.dispose("IWDA", D("100"), D("100"), utc(2026, 6, 1),
                               fees=D("20"))
    assert disposals[0].proceeds == D("9980")
    assert disposals[0].gain == D("980")


def test_fees_split_across_lots_net_to_the_same_total(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("80"), utc(2026, 1, 15))
    ledger.acquire("IWDA", D("100"), D("100"), utc(2026, 6, 15))

    disposals = ledger.dispose("IWDA", D("200"), D("120"), utc(2026, 12, 1),
                               fees=D("30"))
    total_proceeds = sum(d.proceeds for d in disposals)
    assert total_proceeds == D("200") * D("120") - D("30")


def test_overselling_is_refused(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("90"), utc(2026, 1, 15))
    with pytest.raises(InsufficientHoldingsError, match="only 100 held"):
        ledger.dispose("IWDA", D("101"), D("100"), utc(2026, 6, 1))


def test_failed_disposal_changes_nothing(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("90"), utc(2026, 1, 15))
    with pytest.raises(InsufficientHoldingsError):
        ledger.dispose("IWDA", D("500"), D("100"), utc(2026, 6, 1))

    assert ledger.quantity("IWDA") == D("100")
    assert ledger.realized_gain() == D("0")


def test_selling_an_unheld_instrument_is_refused(ledger) -> None:
    with pytest.raises(InsufficientHoldingsError):
        ledger.dispose("EIMI", D("1"), D("100"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"quantity": D("0")},
        {"quantity": D("-1")},
        {"price": D("-1")},
        {"fees": D("-1")},
    ],
)
def test_invalid_acquisitions_are_refused(ledger, kwargs) -> None:
    params = {"instrument": "IWDA", "quantity": D("10"), "price": D("90")}
    params.update(kwargs)
    with pytest.raises(ValueError):
        ledger.acquire(**params)


def test_realized_gain_is_scoped_by_year(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("80"), utc(2025, 1, 15))
    ledger.dispose("IWDA", D("50"), D("100"), utc(2025, 6, 1))
    ledger.dispose("IWDA", D("50"), D("120"), utc(2026, 6, 1))

    assert ledger.realized_gain(2025) == D("1000")
    assert ledger.realized_gain(2026) == D("2000")
    assert ledger.realized_gain() == D("3000")


def test_realized_gain_is_scoped_by_instrument(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("80"), utc(2026, 1, 15))
    ledger.acquire("EIMI", D("100"), D("30"), utc(2026, 1, 15))
    ledger.dispose("IWDA", D("100"), D("100"), utc(2026, 6, 1))
    ledger.dispose("EIMI", D("100"), D("25"), utc(2026, 6, 1))

    assert ledger.realized_gain(instrument="IWDA") == D("2000")
    assert ledger.realized_gain(instrument="EIMI") == D("-500")


def test_unrealized_gain_marks_open_lots(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("80"), utc(2026, 1, 15))
    assert ledger.unrealized_gain({"IWDA": D("100")}) == D("2000")


def test_unrealized_ignores_fully_sold_positions(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("80"), utc(2026, 1, 15))
    ledger.dispose("IWDA", D("100"), D("100"), utc(2026, 6, 1))
    assert ledger.unrealized_gain({"IWDA": D("500")}) == D("0")


def test_tax_summary_separates_gains_from_losses(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("80"), utc(2026, 1, 15))
    ledger.acquire("EIMI", D("100"), D("30"), utc(2026, 1, 15))
    ledger.dispose("IWDA", D("100"), D("100"), utc(2026, 6, 1))   # +2000
    ledger.dispose("EIMI", D("100"), D("25"), utc(2026, 7, 1))    # -500

    summary = ledger.tax_summary(2026)
    assert summary["gross_gains"] == D("2000")
    assert summary["gross_losses"] == D("-500")
    assert summary["net_gain"] == D("1500")
    assert summary["estimated_tax"] == D("225")  # 15%


def test_tax_summary_of_a_losing_year_owes_nothing(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("100"), utc(2026, 1, 15))
    ledger.dispose("IWDA", D("100"), D("80"), utc(2026, 6, 1))

    summary = ledger.tax_summary(2026)
    assert summary["net_gain"] == D("-2000")
    assert summary["estimated_tax"] == D("0")


def test_disposal_report_is_chronological(ledger) -> None:
    ledger.acquire("IWDA", D("300"), D("80"), utc(2026, 1, 15))
    for month in (3, 6, 9):
        ledger.dispose("IWDA", D("100"), D("100"), utc(2026, month, 1))

    report = ledger.disposal_report(2026)
    assert len(report) == 3
    assert [d.disposed_at for d in report] == sorted(d.disposed_at for d in report)


def test_holding_period_is_recorded(ledger) -> None:
    ledger.acquire("IWDA", D("100"), D("80"), utc(2025, 1, 1))
    disposals = ledger.dispose("IWDA", D("100"), D("100"), utc(2026, 1, 1))
    assert disposals[0].holding_days == 365


def test_ledger_persists(tmp_path) -> None:
    path = tmp_path / "lots.db"
    with TaxLedger(path) as t:
        t.acquire("IWDA", D("100"), D("90"), utc(2026, 1, 15), fees=D("5"))
        t.dispose("IWDA", D("40"), D("100"), utc(2026, 6, 1))

    with TaxLedger(path) as reopened:
        assert reopened.quantity("IWDA") == D("60")
        assert reopened.realized_gain(2026) == D("400") - D("2")


def test_fractional_quantities_survive(ledger) -> None:
    """Fractional ETF shares and crypto amounts must not go through float."""
    ledger.acquire("BTC", D("0.00123456"), D("100000"), utc(2026, 1, 15))
    ledger.dispose("BTC", D("0.00023456"), D("110000"), utc(2026, 6, 1))
    assert ledger.quantity("BTC") == D("0.001")


# ===========================================================================
# Order merging and sequencing
# ===========================================================================


def test_two_triggers_on_one_instrument_become_one_order(rebalancer) -> None:
    """A contribution and a band breach can both call for buying the same
    fund. Sending two orders pays two commissions for one position change."""
    plan = rebalancer.plan(
        {"IWDA": D("9000"), "EIMI": D("1000")}, contribution=D("500")
    )
    eimi = [a for a in plan.actions if a.instrument == "EIMI"]
    assert len(eimi) == 1
    assert eimi[0].is_merged
    assert eimi[0].value == D("1100")   # 500 contribution + 600 breach


def test_merged_order_keeps_its_components_for_the_record(rebalancer) -> None:
    plan = rebalancer.plan(
        {"IWDA": D("9000"), "EIMI": D("1000")}, contribution=D("500")
    )
    eimi = next(a for a in plan.actions if a.instrument == "EIMI")
    triggers = {t for t, _ in eimi.components}
    assert triggers == {Trigger.CONTRIBUTION, Trigger.BAND_BREACH}


def test_a_plan_never_holds_both_sides_of_one_instrument(rebalancer) -> None:
    """Netting keeps a plan from looking like a wash trade."""
    plan = rebalancer.plan(
        {"IWDA": D("9000"), "EIMI": D("1000")}, contribution=D("500")
    )
    per_instrument = {}
    for action in plan.actions:
        assert action.instrument not in per_instrument
        per_instrument[action.instrument] = action.kind


def test_sells_are_sequenced_before_buys(rebalancer) -> None:
    """A rebalance funds its buys from its sells. Buying first asks the
    broker for cash that has not been raised yet."""
    plan = rebalancer.plan(
        {"IWDA": D("9000"), "EIMI": D("1000")}, contribution=D("500")
    )
    kinds = [a.kind for a in plan.actions]
    assert kinds == sorted(kinds, key=lambda k: k is ActionKind.BUY)
    assert kinds[0] is ActionKind.SELL


def test_cancelling_legs_produce_no_order(allocation) -> None:
    """If the contribution and the breach point opposite ways and net out
    below min_order, there is nothing worth sending."""
    rb = Rebalancer(allocation, RebalanceBands(), min_order=D("50"))
    plan = rb.plan({"IWDA": D("8000"), "EIMI": D("2000")}, contribution=D("30"))
    assert plan.is_empty


def test_merged_plan_still_lands_on_target(rebalancer) -> None:
    holdings = {"IWDA": D("9000"), "EIMI": D("1000")}
    plan = rebalancer.plan(holdings, contribution=D("500"))

    after = dict(holdings)
    for action in plan.actions:
        delta = action.value if action.kind is ActionKind.BUY else -action.value
        after[action.instrument] += delta

    total = sum(after.values())
    assert after["IWDA"] / total == D("0.8")
    assert after["EIMI"] / total == D("0.2")
