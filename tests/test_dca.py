"""Contribution scheduling tests.

Weighted toward the awkward cases: month ends, downtime, leap years. The happy
path is one test; the rest is where the bugs live.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from ioanna.core import (
    ContributionSchedule,
    add_months,
    business_day_before,
    month_end,
    next_contribution,
)

D = Decimal


@pytest.fixture
def schedule() -> ContributionSchedule:
    return ContributionSchedule(amount=D("500"), day_of_month=1, max_catch_up=3)


# -- construction -----------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"amount": D("0")},
        {"amount": D("-100")},
        {"day_of_month": 0},
        {"day_of_month": 32},
        {"max_catch_up": 0},
    ],
)
def test_invalid_schedules_are_refused(kwargs) -> None:
    params = {"amount": D("500"), "day_of_month": 1}
    params.update(kwargs)
    with pytest.raises(ValueError):
        ContributionSchedule(**params)


# -- month-end clamping -----------------------------------------------------


def test_day_31_clamps_to_month_end() -> None:
    """A schedule set to the 31st must not skip the months without one."""
    s = ContributionSchedule(amount=D("500"), day_of_month=31)
    assert s.contribution_date(2026, 1) == date(2026, 1, 31)
    assert s.contribution_date(2026, 2) == date(2026, 2, 28)
    assert s.contribution_date(2026, 4) == date(2026, 4, 30)


def test_day_31_in_a_leap_february() -> None:
    s = ContributionSchedule(amount=D("500"), day_of_month=31)
    assert s.contribution_date(2028, 2) == date(2028, 2, 29)


def test_every_month_gets_exactly_one_contribution_on_day_31() -> None:
    """The clamping must not cause a month to be skipped or doubled."""
    s = ContributionSchedule(amount=D("500"), day_of_month=31)
    due = s.due_between(date(2025, 12, 31), date(2026, 12, 31))
    assert len(due) == 12
    assert [d.month for d in due] == list(range(1, 13))


# -- due dates --------------------------------------------------------------


def test_nothing_is_due_before_the_first_date(schedule) -> None:
    assert schedule.due_between(date(2026, 1, 1), date(2026, 1, 31)) == []


def test_a_single_month_produces_a_single_date(schedule) -> None:
    assert schedule.due_between(date(2026, 1, 1), date(2026, 2, 1)) == [
        date(2026, 2, 1)
    ]


def test_start_is_exclusive_so_a_contribution_is_not_repeated(schedule) -> None:
    """Passing the last contribution date must not re-issue it."""
    assert date(2026, 3, 1) not in schedule.due_between(
        date(2026, 3, 1), date(2026, 3, 20)
    )


def test_end_is_inclusive_so_today_counts(schedule) -> None:
    assert schedule.due_between(date(2026, 2, 1), date(2026, 3, 1)) == [
        date(2026, 3, 1)
    ]


def test_due_dates_span_a_year_boundary(schedule) -> None:
    due = schedule.due_between(date(2026, 11, 1), date(2027, 2, 1))
    assert due == [date(2026, 12, 1), date(2027, 1, 1), date(2027, 2, 1)]


def test_end_before_start_is_refused(schedule) -> None:
    with pytest.raises(ValueError, match="must not precede"):
        schedule.due_between(date(2026, 6, 1), date(2026, 1, 1))


# -- catch-up ---------------------------------------------------------------


def test_downtime_owes_every_missed_period(schedule) -> None:
    """Three months off means three contributions owed, not one."""
    assert schedule.periods_missed(date(2026, 1, 1), date(2026, 4, 1)) == 3


def test_catch_up_is_capped(schedule) -> None:
    """Returning after a year must not dump 12 contributions at once."""
    assert schedule.periods_missed(date(2026, 1, 1), date(2027, 1, 1)) == 12
    assert schedule.amount_due(date(2026, 1, 1), date(2027, 1, 1)) == D("1500")


def test_amount_due_is_zero_when_nothing_is_owed(schedule) -> None:
    assert schedule.amount_due(date(2026, 2, 1), date(2026, 2, 20)) == D("0")


def test_next_contribution_is_none_when_nothing_is_due(schedule) -> None:
    assert next_contribution(schedule, date(2026, 2, 1), date(2026, 2, 15)) is None


def test_next_contribution_reports_a_normal_month(schedule) -> None:
    c = next_contribution(schedule, date(2026, 1, 1), date(2026, 2, 1))
    assert c is not None
    assert c.amount == D("500")
    assert c.periods_covered == 1
    assert not c.is_catch_up
    assert c.periods_skipped == 0


def test_next_contribution_reports_catch_up_and_what_was_dropped(schedule) -> None:
    """Skipped periods are reported, not silently deferred: they are not owed
    later, and showing them as pending would invite a lump sum later."""
    c = next_contribution(schedule, date(2026, 1, 1), date(2026, 7, 1))
    assert c is not None
    assert c.periods_covered == 3      # capped
    assert c.periods_skipped == 3      # 6 missed, 3 honoured
    assert c.amount == D("1500")
    assert c.is_catch_up


def test_catch_up_due_date_is_the_most_recent(schedule) -> None:
    c = next_contribution(schedule, date(2026, 1, 1), date(2026, 4, 1))
    assert c is not None and c.due_on == date(2026, 4, 1)


# -- date helpers -----------------------------------------------------------


def test_month_end() -> None:
    assert month_end(date(2026, 2, 10)) == date(2026, 2, 28)
    assert month_end(date(2028, 2, 10)) == date(2028, 2, 29)
    assert month_end(date(2026, 12, 1)) == date(2026, 12, 31)


def test_add_months_clamps_to_month_end() -> None:
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 15), 12) == date(2027, 1, 15)
    assert add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)


def test_add_months_backwards() -> None:
    assert add_months(date(2026, 1, 15), -1) == date(2025, 12, 15)
    assert add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)


def test_business_day_before_skips_the_weekend() -> None:
    # 2026-03-01 is a Sunday, 2026-02-28 a Saturday.
    assert business_day_before(date(2026, 3, 1)) == date(2026, 2, 27)
    assert business_day_before(date(2026, 2, 28)) == date(2026, 2, 27)


def test_business_day_before_leaves_weekdays_alone() -> None:
    assert business_day_before(date(2026, 3, 2)) == date(2026, 3, 2)
