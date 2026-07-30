"""Contribution scheduling.

Dollar-cost averaging is trivial when nothing goes wrong and fiddly when
something does. The cases that actually matter:

* **Month-end.** A schedule set to the 31st has to mean "the 31st, or the last
  day of the month if there is no 31st". Silently skipping February is the
  kind of bug that goes unnoticed for a year.
* **Downtime.** If the process was off for three months, three contributions
  are owed, not one. `due_between` returns every date in the window so a gap
  is caught up rather than quietly lost.
* **Catch-up limits.** Coming back after a long outage should not dump a
  year of contributions into the market in one order. `max_catch_up` caps how
  many are honoured at once.

The schedule says *when* and *how much*. It never decides *what* to buy --
that is the rebalancer's job, and keeping them separate is what lets a
contribution double as a rebalancing tool.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class ContributionSchedule:
    """A fixed amount, on a fixed day of the month."""

    amount: Decimal
    day_of_month: int = 1
    max_catch_up: int = 3

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("contribution amount must be positive")
        if not 1 <= self.day_of_month <= 31:
            raise ValueError("day_of_month must be in [1, 31]")
        if self.max_catch_up < 1:
            raise ValueError("max_catch_up must be at least 1")

    def contribution_date(self, year: int, month: int) -> date:
        """The scheduled date in a given month, clamped to month end."""
        last = calendar.monthrange(year, month)[1]
        return date(year, month, min(self.day_of_month, last))

    def due_between(self, start: date, end: date) -> list[date]:
        """Every contribution date in (start, end].

        Exclusive of `start` so passing the last contribution date does not
        re-issue it, inclusive of `end` so a contribution due today counts.
        """
        if end < start:
            raise ValueError("end must not precede start")

        out: list[date] = []
        year, month = start.year, start.month

        while True:
            due = self.contribution_date(year, month)
            if due > end:
                break
            if due > start:
                out.append(due)
            month += 1
            if month > 12:
                year, month = year + 1, 1

        return out

    def amount_due(self, last_contribution: date, now: date) -> Decimal:
        """Total owed since the last contribution, capped by `max_catch_up`.

        The cap is a risk control, not an accounting one: the skipped
        contributions are not owed later, they are skipped. Reporting them as
        deferred would invite a lump sum at exactly the wrong moment.
        """
        missed = self.due_between(last_contribution, now)
        return self.amount * min(len(missed), self.max_catch_up)

    def periods_missed(self, last_contribution: date, now: date) -> int:
        return len(self.due_between(last_contribution, now))


@dataclass(frozen=True)
class Contribution:
    """One scheduled deposit, ready to be handed to the rebalancer."""

    due_on: date
    amount: Decimal
    periods_covered: int
    periods_skipped: int = 0

    @property
    def is_catch_up(self) -> bool:
        return self.periods_covered > 1


def next_contribution(
    schedule: ContributionSchedule,
    last_contribution: date,
    now: date,
) -> Contribution | None:
    """What is owed right now, or None if nothing is due yet."""
    missed = schedule.due_between(last_contribution, now)
    if not missed:
        return None

    honoured = min(len(missed), schedule.max_catch_up)
    return Contribution(
        due_on=missed[-1],
        amount=schedule.amount * honoured,
        periods_covered=honoured,
        periods_skipped=len(missed) - honoured,
    )


def month_end(d: date) -> date:
    """Last day of the month containing `d`."""
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, months: int) -> date:
    """Shift by whole months, clamping to month end."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def business_day_before(d: date) -> date:
    """Nearest weekday at or before `d`.

    Markets are shut at weekends, so a schedule landing on a Sunday should
    place the order on the Friday rather than waiting until Monday and
    drifting later every month. Public holidays are not modelled -- the
    broker will reject and the order retries.
    """
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d
