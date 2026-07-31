"""Shadow mode tests.

Weighted toward the ways shadow mode can be faked: revising a proposal after
the outcome, quietly dropping the bad calls, or scoring without costs. Each of
those turns a three-month evaluation into a three-month self-congratulation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from ioanna.research import (
    BINANCE_SPOT,
    Direction,
    Proposal,
    Resolution,
    ShadowLedger,
)
from ioanna.validation import Trial, TrialRegistry, sharpe_stats

D = Decimal


def utc(y, m, d) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


@pytest.fixture
def ledger():
    with ShadowLedger(BINANCE_SPOT) as led:
        yield led


def make_proposal(**overrides) -> Proposal:
    params = {
        "family": "funding_arb",
        "instrument": "BTC/USDT",
        "direction": Direction.LONG,
        "reference_price": D("100000"),
        "notional": D("10000"),
        "expected_edge_bps": D("60"),
        "hypothesis": (
            "Perpetual funding has been positive for fourteen sessions while "
            "basis stays inside 0.3%, so the carry should accrue."
        ),
        "counter_argument": (
            "Funding flipped negative within two sessions three times in the "
            "past year, and the hedge would then cost more than it earns."
        ),
        "invalidation": "Funding negative for two consecutive sessions.",
        "proposed_at": utc(2026, 1, 1),
    }
    params.update(overrides)
    return Proposal(**params)


# ===========================================================================
# Proposing
# ===========================================================================


def test_a_proposal_round_trips(ledger) -> None:
    pid = ledger.propose(make_proposal())
    assert pid > 0
    assert len(ledger.open_proposals("funding_arb")) == 1


@pytest.mark.parametrize(
    "field", ["hypothesis", "counter_argument", "invalidation"]
)
def test_a_proposal_needs_the_same_reasoning_as_a_live_position(
    ledger, field
) -> None:
    """A shadow proposal is standing in for a real one. Accepting a thinner
    record here would make the three months prove less than it appears to."""
    with pytest.raises(ValueError, match="incomplete proposal"):
        ledger.propose(make_proposal(**{field: "n/a"}))


@pytest.mark.parametrize(
    "kwargs", [{"reference_price": D("0")}, {"notional": D("-1")}]
)
def test_malformed_proposals_are_refused(kwargs) -> None:
    with pytest.raises(ValueError):
        make_proposal(**kwargs)


def test_a_proposal_cannot_be_revised(ledger) -> None:
    """The whole point: a prediction that can be edited afterwards is not a
    prediction."""
    import sqlite3

    pid = ledger.propose(make_proposal())
    with pytest.raises(sqlite3.DatabaseError, match="cannot be revised"):
        ledger._conn.execute(
            "UPDATE proposals SET expected_edge_bps = ? WHERE id = ?",
            ("999", pid),
        )


def test_the_ledger_has_no_delete(ledger) -> None:
    """Shadow mode is trivial to fake by forgetting the bad calls."""
    assert not any(
        hasattr(ShadowLedger, name)
        for name in ("delete", "remove", "withdraw", "cancel", "prune")
    )


# ===========================================================================
# Resolving
# ===========================================================================


def test_a_winning_long_is_scored_net_of_costs(ledger) -> None:
    """+1% gross on a 10k position, less the Binance spot round trip."""
    pid = ledger.propose(make_proposal())
    outcome = ledger.resolve(pid, D("101000"), at=utc(2026, 1, 8))

    assert outcome.gross_bps == pytest.approx(D("100"), abs=D("0.01"))
    assert outcome.cost_bps == BINANCE_SPOT.round_trip_bps(D("10000"), D("7"))
    assert outcome.net_bps < outcome.gross_bps
    assert outcome.profitable


def test_a_short_profits_when_the_price_falls(ledger) -> None:
    pid = ledger.propose(make_proposal(direction=Direction.SHORT))
    outcome = ledger.resolve(pid, D("99000"), at=utc(2026, 1, 8))
    assert outcome.gross_bps > 0


def test_a_short_loses_when_the_price_rises(ledger) -> None:
    pid = ledger.propose(make_proposal(direction=Direction.SHORT))
    outcome = ledger.resolve(pid, D("101000"), at=utc(2026, 1, 8))
    assert outcome.gross_bps < 0


def test_costs_can_eat_a_correct_call(ledger) -> None:
    """The Alpha Arena signature, flagged separately: right about direction,
    wrong about whether it was worth trading."""
    pid = ledger.propose(make_proposal())
    outcome = ledger.resolve(pid, D("100100"), at=utc(2026, 1, 2))  # +10bps

    assert outcome.gross_bps > 0
    assert not outcome.profitable
    assert outcome.costs_ate_the_edge


def test_a_genuine_winner_is_not_flagged_as_cost_eaten(ledger) -> None:
    pid = ledger.propose(make_proposal())
    outcome = ledger.resolve(pid, D("105000"), at=utc(2026, 1, 8))
    assert not outcome.costs_ate_the_edge


def test_holding_longer_costs_more_when_carry_applies() -> None:
    from ioanna.research import CostModel, FeeSchedule

    model = CostModel(
        fees=FeeSchedule(taker_bps=D("10")), borrow_bps_per_day=D("2")
    )
    with ShadowLedger(model) as led:
        short = led.resolve(
            led.propose(make_proposal()), D("101000"), at=utc(2026, 1, 2)
        )
        long = led.resolve(
            led.propose(make_proposal()), D("101000"), at=utc(2026, 2, 1)
        )
    assert long.cost_bps > short.cost_bps


def test_a_proposal_resolves_only_once(ledger) -> None:
    pid = ledger.propose(make_proposal())
    ledger.resolve(pid, D("101000"), at=utc(2026, 1, 8))
    with pytest.raises(ValueError, match="already resolved"):
        ledger.resolve(pid, D("110000"), at=utc(2026, 1, 9))


def test_resolving_an_unknown_proposal_raises(ledger) -> None:
    with pytest.raises(KeyError):
        ledger.resolve(999, D("101000"))


def test_a_zero_exit_price_is_refused(ledger) -> None:
    pid = ledger.propose(make_proposal())
    with pytest.raises(ValueError, match="exit price"):
        ledger.resolve(pid, D("0"))


def test_resolved_proposals_leave_the_open_list(ledger) -> None:
    pid = ledger.propose(make_proposal())
    ledger.resolve(pid, D("101000"), at=utc(2026, 1, 8))
    assert ledger.open_proposals("funding_arb") == []


# ===========================================================================
# Gate 2
# ===========================================================================


def populate(
    ledger: ShadowLedger,
    n: int,
    edge_bps: float,
    noise_bps: float = 50.0,
    days: int = 120,
    seed: int = 0,
) -> None:
    """Fill a ledger with `n` proposals whose gross moves average `edge_bps`."""
    rng = np.random.default_rng(seed)
    start = utc(2026, 1, 1)
    for i in range(n):
        opened = start + timedelta(days=i * days / n)
        pid = ledger.propose(
            make_proposal(proposed_at=opened, notional=D("10000"))
        )
        move = rng.normal(edge_bps, noise_bps)
        exit_price = D("100000") * (D(1) + D(str(round(move * 1e-4, 8))))
        ledger.resolve(
            pid, exit_price, at=opened + timedelta(days=1), maker=False
        )


def test_gate2_fails_an_empty_family(ledger) -> None:
    report = ledger.evaluate("funding_arb", n_trials=1, variance_across_trials=0.0)
    assert not report.passes
    assert "no resolved proposals" in report.blockers[0]


def test_gate2_fails_a_short_track_record(ledger) -> None:
    populate(ledger, n=40, edge_bps=86.0, noise_bps=120.0, days=30)
    report = ledger.evaluate("funding_arb", n_trials=1, variance_across_trials=0.0)
    assert not report.passes
    assert any("days observed" in b for b in report.blockers)


def test_gate2_fails_too_few_proposals(ledger) -> None:
    populate(ledger, n=10, edge_bps=86.0, noise_bps=120.0, days=120)
    report = ledger.evaluate("funding_arb", n_trials=1, variance_across_trials=0.0)
    assert not report.passes
    assert any("resolved proposals" in b for b in report.blockers)


def test_gate2_fails_when_costs_consume_the_edge(ledger) -> None:
    """A real but thin signal: positive gross, negative net."""
    populate(ledger, n=60, edge_bps=15.0, noise_bps=5.0, days=120)
    report = ledger.evaluate("funding_arb", n_trials=1, variance_across_trials=0.0)

    assert report.mean_gross_bps > 0
    assert report.mean_net_bps < 0
    assert not report.passes
    assert any("costs consumed it" in b for b in report.blockers)
    assert report.cost_ratio > 1


def test_gate2_fails_a_strategy_with_no_edge(ledger) -> None:
    populate(ledger, n=60, edge_bps=0.0, noise_bps=100.0, days=120)
    report = ledger.evaluate("funding_arb", n_trials=1, variance_across_trials=0.0)
    assert not report.passes


def test_gate2_passes_a_genuinely_strong_strategy(ledger) -> None:
    """A real edge over four months and sixty trades.

    86bps gross less the 26bps Binance round trip leaves 60bps net against
    120bps of noise -- a per-trade Sharpe of 0.5, which is strong but not
    fantastical.
    """
    populate(ledger, n=60, edge_bps=86.0, noise_bps=120.0, days=120)
    report = ledger.evaluate("funding_arb", n_trials=1, variance_across_trials=0.0)

    assert report.mean_net_bps > 0
    assert report.deflated_sharpe > 0.5
    assert report.passes, report.blockers


def test_a_wide_search_deflates_the_same_result_away(ledger) -> None:
    """Identical returns, but found by trying 500 variants instead of one.

    56bps gross leaves 30bps net against 250bps of noise. On its own that
    scores a deflated Sharpe around 0.95; against 500 trials it collapses to
    roughly 0.05, because a search that wide produces a result this good by
    luck alone.
    """
    populate(ledger, n=60, edge_bps=56.0, noise_bps=250.0, days=120, seed=0)

    narrow = ledger.evaluate("funding_arb", 1, 0.0)
    wide = ledger.evaluate("funding_arb", 500, 0.02)

    assert narrow.passes, narrow.blockers
    assert wide.deflated_sharpe < narrow.deflated_sharpe
    assert not wide.passes


def test_the_report_separates_gross_from_net(ledger) -> None:
    populate(ledger, n=60, edge_bps=86.0, noise_bps=120.0, days=120)
    report = ledger.evaluate("funding_arb", 1, 0.0)

    assert report.mean_gross_bps > report.mean_net_bps
    assert report.mean_cost_bps == pytest.approx(
        report.mean_gross_bps - report.mean_net_bps, abs=0.01
    )


def test_the_summary_names_the_verdict(ledger) -> None:
    populate(ledger, n=60, edge_bps=56.0, noise_bps=250.0, days=120, seed=0)
    assert "PASS" in ledger.evaluate("funding_arb", 1, 0.0).summary()
    assert "FAIL" in ledger.evaluate("funding_arb", 500, 0.02).summary()


# ===========================================================================
# Registry integration
# ===========================================================================


def test_evaluating_without_a_registry_entry_is_refused(ledger) -> None:
    """Deflating against N=0 would report a raw Sharpe as though nothing had
    been selected -- the exact failure the registry exists to prevent."""
    populate(ledger, n=60, edge_bps=86.0, noise_bps=120.0, days=120)
    with TrialRegistry() as registry:
        with pytest.raises(ValueError, match="no trials recorded"):
            ledger.evaluate_with_registry("funding_arb", registry)


def test_the_registry_supplies_the_trial_count(ledger) -> None:
    populate(ledger, n=60, edge_bps=86.0, noise_bps=120.0, days=120)

    rng = np.random.default_rng(3)
    with TrialRegistry() as registry:
        for i in range(200):
            registry.record(
                Trial(
                    family="funding_arb",
                    params={"variant": i},
                    stats=sharpe_stats(rng.normal(0, 0.01, 300)),
                )
            )
        report = ledger.evaluate_with_registry("funding_arb", registry)

    assert report.n_trials == 200
