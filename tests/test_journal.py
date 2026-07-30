"""Journal tests.

The interesting ones are the refusals: a journal that accepts a position with
no counter argument, or lets a hypothesis be edited after the fact, provides
the appearance of a research process without the substance.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ioanna.journal import (
    Hypothesis,
    ImmutableRecordError,
    Journal,
    PostMortem,
)


@pytest.fixture
def journal() -> Journal:
    with Journal() as j:
        yield j


def make_hypothesis(**overrides) -> Hypothesis:
    params = {
        "text": (
            "BTC perpetual funding has been positive for 14 consecutive "
            "sessions while spot basis stays within 0.3%, so a delta-neutral "
            "long spot / short perp carry should collect funding."
        ),
        "supporting_data": {
            "funding_8h_mean_bps": 12.4,
            "sessions_positive": 14,
            "basis_pct": 0.28,
        },
        "counter_argument": (
            "Funding has flipped negative within two sessions three times in "
            "the past year, and the borrow leg would then cost more than the "
            "carry collects."
        ),
        "invalidation": "Funding negative for two consecutive sessions.",
        "exit_plan": "Unwind both legs together if invalidated or after 30 days.",
        "expected_edge_bps": 45.0,
        "risk_assessment": {"max_loss_pct": 2.1, "liquidation_buffer_pct": 40},
    }
    params.update(overrides)
    return Hypothesis(**params)


def open_one(journal: Journal, **overrides) -> int:
    params = {
        "instrument": "BTC/USDT",
        "venue": "binance",
        "side": "buy",
        "quantity": Decimal("0.05"),
        "entry_price": Decimal("100000"),
        "strategy_pillar": "satellite",
        "hypothesis": make_hypothesis(),
    }
    params.update(overrides)
    return journal.open_position(**params)


def make_post_mortem(**overrides) -> PostMortem:
    params = {
        "exit_price": Decimal("101000"),
        "realized_pnl": Decimal("50"),
        "hypothesis_verified": True,
        "what_actually_happened": (
            "Funding stayed positive for the full holding period and the "
            "carry accrued close to the projected rate."
        ),
        "slippage_bps": 3.2,
        "lesson": "Basis stability was a better entry filter than funding level.",
    }
    params.update(overrides)
    return PostMortem(**params)


# -- opening ----------------------------------------------------------------


def test_position_round_trips(journal: Journal) -> None:
    pid = open_one(journal)
    pos = journal.get(pid)

    assert pos is not None
    assert pos.instrument == "BTC/USDT"
    assert pos.quantity == Decimal("0.05")
    assert pos.is_open
    assert pos.hypothesis.expected_edge_bps == 45.0
    assert pos.hypothesis.supporting_data["sessions_positive"] == 14


def test_decimals_survive_the_round_trip(journal: Journal) -> None:
    """Money must not go through float. 0.1 + 0.2 problems are not acceptable
    in a position size."""
    pid = open_one(journal, quantity=Decimal("0.000000012345678"))
    pos = journal.get(pid)
    assert pos is not None
    assert pos.quantity == Decimal("0.000000012345678")


def test_missing_position_is_none(journal: Journal) -> None:
    assert journal.get(999) is None


def test_open_positions_lists_only_open_ones(journal: Journal) -> None:
    a, b = open_one(journal), open_one(journal)
    journal.close_position(a, make_post_mortem())

    open_ids = [p.id for p in journal.open_positions()]
    assert open_ids == [b]


# -- the required fields ----------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["text", "counter_argument", "invalidation", "exit_plan"],
)
def test_empty_reasoning_fields_are_refused(journal: Journal, field: str) -> None:
    with pytest.raises(ValueError, match="incomplete pre-trade record"):
        open_one(journal, hypothesis=make_hypothesis(**{field: ""}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "looks good"),
        ("counter_argument", "none"),
        ("counter_argument", "n/a"),
        ("invalidation", "TBD"),
        ("exit_plan", "?"),
    ],
)
def test_token_reasoning_is_refused(journal: Journal, field, value) -> None:
    """"none" is not a counter argument. Accepting it once makes the devil's
    advocate step optional forever."""
    with pytest.raises(ValueError, match="incomplete pre-trade record"):
        open_one(journal, hypothesis=make_hypothesis(**{field: value}))


def test_whitespace_does_not_satisfy_the_length_check(journal: Journal) -> None:
    with pytest.raises(ValueError, match="incomplete pre-trade record"):
        open_one(journal, hypothesis=make_hypothesis(counter_argument=" " * 50))


def test_invalid_side_is_refused(journal: Journal) -> None:
    with pytest.raises(ValueError):
        open_one(journal, side="maybe")


# -- immutability -----------------------------------------------------------


def test_revise_hypothesis_always_raises(journal: Journal) -> None:
    pid = open_one(journal)
    with pytest.raises(ImmutableRecordError):
        journal.revise_hypothesis(pid, "actually I meant something else")


def test_hypothesis_is_unchanged_after_a_revision_attempt(journal: Journal) -> None:
    pid = open_one(journal)
    original = journal.get(pid).hypothesis.text

    with pytest.raises(ImmutableRecordError):
        journal.revise_hypothesis(pid, "rewritten after the fact")

    assert journal.get(pid).hypothesis.text == original


@pytest.mark.parametrize(
    "column",
    [
        "hypothesis",
        "supporting_data",
        "counter_argument",
        "invalidation",
        "exit_plan",
        "entry_price",
        "quantity",
        "strategy_pillar",
        "opened_at",
    ],
)
def test_raw_sql_cannot_edit_the_pre_trade_record(
    journal: Journal, column: str
) -> None:
    """The trigger is the real defence -- going around the Python API must
    fail too, since that is what someone determined would actually do."""
    pid = open_one(journal)
    import sqlite3

    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        journal._conn.execute(
            f"UPDATE positions SET {column} = ? WHERE id = ?", ("tampered", pid)
        )


def test_closing_is_still_permitted(journal: Journal) -> None:
    """Immutability must not extend to the one field that has to change."""
    pid = open_one(journal)
    journal.close_position(pid, make_post_mortem())
    assert not journal.get(pid).is_open


# -- closing ----------------------------------------------------------------


def test_post_mortem_is_recorded(journal: Journal) -> None:
    pid = open_one(journal)
    journal.close_position(pid, make_post_mortem())

    pm = journal.post_mortem(pid)
    assert pm is not None
    assert pm["hypothesis_verified"] == 1
    assert pm["slippage_bps"] == 3.2


def test_a_position_closes_only_once(journal: Journal) -> None:
    pid = open_one(journal)
    journal.close_position(pid, make_post_mortem())
    with pytest.raises(ValueError, match="already closed"):
        journal.close_position(pid, make_post_mortem())


def test_closing_an_unknown_position_raises(journal: Journal) -> None:
    with pytest.raises(KeyError):
        journal.close_position(999, make_post_mortem())


def test_post_mortem_requires_a_real_account(journal: Journal) -> None:
    pid = open_one(journal)
    with pytest.raises(ValueError, match="incomplete post mortem"):
        journal.close_position(
            pid, make_post_mortem(what_actually_happened="closed")
        )


def test_failed_close_leaves_the_position_open(journal: Journal) -> None:
    """The close and the post mortem are one transaction: a position must
    never end up closed with no explanation attached."""
    pid = open_one(journal)
    with pytest.raises(ValueError):
        journal.close_position(pid, make_post_mortem(what_actually_happened="x"))

    assert journal.get(pid).is_open
    assert journal.post_mortem(pid) is None


def test_closed_at_is_consistent_across_both_tables(journal: Journal) -> None:
    pid = open_one(journal)
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    journal.close_position(pid, make_post_mortem(), closed_at=ts)

    assert journal.get(pid).closed_at == ts
    assert journal.post_mortem(pid)["closed_at"] == ts.isoformat()


# -- attribution ------------------------------------------------------------


def test_attribution_separates_skill_from_luck(journal: Journal) -> None:
    """Four outcomes, and the two off-diagonal ones are the point."""
    cases = [
        (True, Decimal("100")),    # skilled: right, and paid
        (True, Decimal("100")),
        (False, Decimal("80")),    # lucky: wrong, but paid anyway
        (True, Decimal("-50")),    # unlucky: right, but lost
        (False, Decimal("-70")),   # wrong: wrong, and lost
        (False, Decimal("-30")),
    ]
    for verified, pnl in cases:
        pid = open_one(journal)
        journal.close_position(
            pid,
            make_post_mortem(hypothesis_verified=verified, realized_pnl=pnl),
        )

    assert journal.attribution_summary() == {
        "skilled": 2,
        "lucky": 1,
        "unlucky": 1,
        "wrong": 2,
    }


def test_attribution_can_be_scoped_to_a_pillar(journal: Journal) -> None:
    for pillar, verified in [
        ("satellite", True),
        ("satellite", True),
        ("exploratory", False),
    ]:
        pid = open_one(journal, strategy_pillar=pillar)
        journal.close_position(
            pid,
            make_post_mortem(
                hypothesis_verified=verified, realized_pnl=Decimal("10")
            ),
        )

    assert journal.attribution_summary("satellite")["skilled"] == 2
    assert journal.attribution_summary("exploratory")["lucky"] == 1


def test_attribution_of_an_empty_journal_is_all_zeros(journal: Journal) -> None:
    assert journal.attribution_summary() == {
        "skilled": 0,
        "lucky": 0,
        "unlucky": 0,
        "wrong": 0,
    }


def test_open_positions_are_excluded_from_attribution(journal: Journal) -> None:
    open_one(journal)
    assert sum(journal.attribution_summary().values()) == 0


# -- persistence ------------------------------------------------------------


def test_journal_persists_and_stays_immutable_after_reopen(tmp_path) -> None:
    path = tmp_path / "journal.db"
    with Journal(path) as j:
        pid = open_one(j)
        original = j.get(pid).hypothesis.text

    with Journal(path) as reopened:
        assert reopened.get(pid).hypothesis.text == original
        with pytest.raises(ImmutableRecordError):
            reopened.revise_hypothesis(pid, "changed my mind")


def test_positions_keep_their_order(tmp_path) -> None:
    path = tmp_path / "journal.db"
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with Journal(path) as j:
        for i in range(5):
            j.open_position(
                instrument="BTC/USDT",
                venue="binance",
                side="buy",
                quantity=Decimal("0.01"),
                entry_price=Decimal("100000"),
                strategy_pillar="satellite",
                hypothesis=make_hypothesis(),
                opened_at=base + timedelta(days=i),
            )
    with Journal(path) as j:
        opened = [p.opened_at for p in j.open_positions()]
        assert opened == sorted(opened)
