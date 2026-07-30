"""Config tests.

The live decisions, checked against each other. Individually valid settings
that contradict one another are the failure mode here -- nothing complains
when a limit is loosened for a test and left that way.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ioanna import config
from ioanna.research.costs import (
    IBKR_EUROPE,
    contribution_frequency_cost,
    minimum_viable_contribution,
)

D = Decimal


def test_the_shipped_config_is_self_consistent() -> None:
    assert config.validate() == []


def test_the_allocated_fund_is_whitelisted() -> None:
    for symbol in config.CORE_ALLOCATION.instruments:
        assert symbol in config.LIVE_LIMITS.allowed_instruments
        assert symbol in config.INSTRUMENTS


def test_unproven_pillars_are_unfunded() -> None:
    """Satellite and exploratory stay at zero until their gates are passed."""
    assert config.LIVE_LIMITS.max_pillar_fraction["satellite"] == D("0")
    assert config.LIVE_LIMITS.max_pillar_fraction["exploratory"] == D("0")


def test_the_core_pillar_can_actually_trade() -> None:
    assert config.LIVE_LIMITS.max_pillar_fraction["core"] > 0


def test_the_fund_is_accumulating_and_irish() -> None:
    """Both are load-bearing: Irish domicile halves US dividend withholding,
    and accumulating avoids a 5% Greek dividend tax event every quarter."""
    assert config.VWCE.isin.startswith("IE")
    assert "Acc" in config.VWCE.description


def test_whole_shares_are_assumed_until_confirmed() -> None:
    """IBKR gates fractional trading on $5m daily volume and $5bn market cap
    for European ETFs. Assuming fractional would produce unfillable orders."""
    assert config.VWCE.lot_size == D("1")
    assert not config.VWCE.is_fractional


def test_the_contribution_clears_the_commission_floor() -> None:
    assert config.CONTRIBUTION_AMOUNT >= minimum_viable_contribution()


def test_the_contribution_costs_under_half_a_percent() -> None:
    cost = (
        IBKR_EUROPE.one_way_cost(config.CONTRIBUTION_AMOUNT)
        / config.CONTRIBUTION_AMOUNT
    )
    assert cost <= D("0.005")


def test_monthly_beats_every_other_frequency() -> None:
    """Cash drag dominates the commission floor at retail sizes, which is why
    the schedule is monthly rather than quarterly."""
    annual = config.CONTRIBUTION_AMOUNT * 12
    costs = {
        n: contribution_frequency_cost(annual, n)["total"]
        for n in (1, 2, 4, 6, 12)
    }
    assert min(costs, key=lambda n: costs[n]) == 12


def test_a_contribution_below_min_order_would_stall_forever() -> None:
    """Guarded by validate(), because the failure is silent: every cycle
    rounds to nothing and carries forward, and the portfolio never grows."""
    assert config.CONTRIBUTION_AMOUNT >= config.MIN_ORDER


def test_the_drawdown_limit_survives_an_ordinary_bear_market() -> None:
    """Global equities fell 34% in March 2020. A 15% halt would liquidate a
    passive core at the bottom and call it risk management."""
    assert config.LIVE_LIMITS.max_drawdown > D("0.34")


def test_the_trade_budget_is_tight() -> None:
    """One contribution and at most one rebalance a day. The Alpha Arena
    failure mode was overtrading."""
    assert config.LIVE_LIMITS.max_trades_per_day <= 2


# -- validate() catches what it claims to ----------------------------------


def test_validate_flags_a_contribution_below_min_order(monkeypatch) -> None:
    monkeypatch.setattr(config, "CONTRIBUTION_AMOUNT", D("100"))
    monkeypatch.setattr(config, "MIN_ORDER", D("650"))
    problems = config.validate()
    assert any("below MIN_ORDER" in p for p in problems)


def test_validate_flags_an_uneconomic_contribution(monkeypatch) -> None:
    monkeypatch.setattr(config, "CONTRIBUTION_AMOUNT", D("100"))
    monkeypatch.setattr(config, "MIN_ORDER", D("50"))
    problems = config.validate()
    assert any("commission" in p for p in problems)


def test_validate_flags_an_unwhitelisted_fund(monkeypatch) -> None:
    from ioanna.core import TargetAllocation

    monkeypatch.setattr(
        config, "CORE_ALLOCATION", TargetAllocation({"NOPE": D("1")})
    )
    problems = config.validate()
    assert any("not whitelisted" in p for p in problems)


def test_validate_flags_a_useless_concentration_limit(monkeypatch) -> None:
    """100% position limit is only safe while the whitelist has one entry."""
    from ioanna.governor import Limits

    monkeypatch.setattr(
        config,
        "LIVE_LIMITS",
        Limits(
            max_position_fraction=D("1.0"),
            max_pillar_fraction={"core": D("1.0")},
            allowed_venues=frozenset({config.VENUE}),
            allowed_instruments=frozenset({"VWCE", "IWDA"}),
        ),
    )
    problems = config.validate()
    assert any("doing no work" in p for p in problems)


def test_validate_flags_an_unfunded_core(monkeypatch) -> None:
    from ioanna.governor import Limits

    monkeypatch.setattr(
        config,
        "LIVE_LIMITS",
        Limits(
            max_pillar_fraction={"core": D("0")},
            allowed_venues=frozenset({config.VENUE}),
            allowed_instruments=frozenset({"VWCE"}),
        ),
    )
    problems = config.validate()
    assert any("no budget" in p for p in problems)
