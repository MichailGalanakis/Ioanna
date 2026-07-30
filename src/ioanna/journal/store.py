"""The journal.

Every position carries the reasoning that produced it, written down before
entry and frozen afterwards. This is the "back up the investment decisions"
requirement, and the freezing is the part that gives it value: a record that
can be revised after the outcome is known documents nothing except hindsight.

After six months the useful question is not "did we make money" -- that is one
number and mostly noise at this sample size. It is "how often was the stated
hypothesis actually the reason it worked", which the `attribution_summary`
below answers, and which needs the hypothesis to have been immutable to mean
anything.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class ImmutableRecordError(RuntimeError):
    """Raised on any attempt to revise a pre-trade record."""


@dataclass(frozen=True)
class Hypothesis:
    """The case for a trade, made before it is placed.

    Every field is required. The minimum lengths enforced by the schema are
    low, but they exist: a counter argument reading "none" is not a counter
    argument, and the moment one is accepted the devil's advocate step has
    quietly become optional.
    """

    text: str
    supporting_data: dict[str, Any]
    counter_argument: str
    invalidation: str
    exit_plan: str
    expected_edge_bps: float | None = None
    risk_assessment: dict[str, Any] | None = None


@dataclass(frozen=True)
class PostMortem:
    exit_price: Decimal
    realized_pnl: Decimal
    hypothesis_verified: bool
    what_actually_happened: str
    slippage_bps: float | None = None
    lesson: str = ""
    attribution: dict[str, Any] | None = None


@dataclass(frozen=True)
class Position:
    id: int
    opened_at: datetime
    instrument: str
    venue: str
    side: str
    quantity: Decimal
    entry_price: Decimal
    strategy_pillar: str
    hypothesis: Hypothesis
    closed_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


class Journal:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_PATH.read_text())
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- opening ------------------------------------------------------------

    def open_position(
        self,
        *,
        instrument: str,
        venue: str,
        side: str,
        quantity: Decimal,
        entry_price: Decimal,
        strategy_pillar: str,
        hypothesis: Hypothesis,
        opened_at: datetime | None = None,
    ) -> int:
        """Record a position and its reasoning. Returns the position id.

        Called by the execution layer *after* the governor approves and
        *before* the order goes out, so an order that fills always has a
        record and a record without a fill is a reconciliation problem rather
        than a missing rationale.
        """
        ts = opened_at or datetime.now(timezone.utc)
        try:
            cur = self._conn.execute(
                """
                INSERT INTO positions (
                    opened_at, instrument, venue, side, quantity, entry_price,
                    strategy_pillar, hypothesis, supporting_data,
                    counter_argument, invalidation, exit_plan,
                    expected_edge_bps, risk_assessment
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts.isoformat(),
                    instrument,
                    venue,
                    side,
                    str(quantity),
                    str(entry_price),
                    strategy_pillar,
                    hypothesis.text,
                    json.dumps(hypothesis.supporting_data, default=str),
                    hypothesis.counter_argument,
                    hypothesis.invalidation,
                    hypothesis.exit_plan,
                    hypothesis.expected_edge_bps,
                    json.dumps(hypothesis.risk_assessment, default=str)
                    if hypothesis.risk_assessment is not None
                    else None,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"incomplete pre-trade record: {exc}. Every position needs a "
                "hypothesis, a counter argument, an invalidation condition "
                "and an exit plan."
            ) from exc

        self._conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    # -- closing ------------------------------------------------------------

    def close_position(
        self,
        position_id: int,
        post_mortem: PostMortem,
        closed_at: datetime | None = None,
    ) -> None:
        ts = closed_at or datetime.now(timezone.utc)

        row = self._conn.execute(
            "SELECT closed_at FROM positions WHERE id = ?", (position_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no position {position_id}")

        try:
            with self._conn:
                self._conn.execute(
                    "UPDATE positions SET closed_at = ? WHERE id = ?",
                    (ts.isoformat(), position_id),
                )
                self._conn.execute(
                    """
                    INSERT INTO post_mortems (
                        position_id, closed_at, exit_price, realized_pnl,
                        slippage_bps, hypothesis_verified,
                        what_actually_happened, lesson, attribution
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        position_id,
                        ts.isoformat(),
                        str(post_mortem.exit_price),
                        str(post_mortem.realized_pnl),
                        post_mortem.slippage_bps,
                        int(post_mortem.hypothesis_verified),
                        post_mortem.what_actually_happened,
                        post_mortem.lesson,
                        json.dumps(post_mortem.attribution, default=str)
                        if post_mortem.attribution is not None
                        else None,
                    ),
                )
        except sqlite3.DatabaseError as exc:
            if "already closed" in str(exc) or "UNIQUE" in str(exc):
                raise ValueError(f"position {position_id} is already closed") from exc
            raise ValueError(f"incomplete post mortem: {exc}") from exc

    # -- the guard rail -----------------------------------------------------

    def revise_hypothesis(self, position_id: int, new_text: str) -> None:
        """Exists only to fail, loudly and by name.

        Somebody will eventually want this method -- usually while a position
        is going against them and the original reasoning has started to look
        embarrassing. Better that it exists and refuses than that its absence
        sends them to raw SQL.
        """
        try:
            self._conn.execute(
                "UPDATE positions SET hypothesis = ? WHERE id = ?",
                (new_text, position_id),
            )
        except sqlite3.DatabaseError as exc:
            # RAISE(ABORT) surfaces as IntegrityError, but catch the shared
            # base class so the guard does not depend on which one.
            raise ImmutableRecordError(str(exc)) from exc
        raise ImmutableRecordError(
            "the pre-trade record is immutable; record what happened in the "
            "post mortem instead"
        )

    # -- reading ------------------------------------------------------------

    def get(self, position_id: int) -> Position | None:
        row = self._conn.execute(
            "SELECT * FROM positions WHERE id = ?", (position_id,)
        ).fetchone()
        return _to_position(row) if row else None

    def open_positions(self) -> list[Position]:
        rows = self._conn.execute(
            "SELECT * FROM positions WHERE closed_at IS NULL ORDER BY id"
        ).fetchall()
        return [_to_position(r) for r in rows]

    def post_mortem(self, position_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM post_mortems WHERE position_id = ?", (position_id,)
        ).fetchone()
        return dict(row) if row else None

    # -- the question the journal exists to answer -------------------------

    def attribution_summary(self, pillar: str | None = None) -> dict[str, int]:
        """Cross-tabulate "was the hypothesis right" against "did we profit".

        The off-diagonal cells are the interesting ones. `lucky` -- profitable
        despite the reasoning being wrong -- is the count that matters most,
        because those trades feel like successes and teach the wrong lesson.
        A strategy whose profits are mostly `lucky` has no demonstrated edge
        however good the equity curve looks.
        """
        clause = "WHERE p.strategy_pillar = ?" if pillar else ""
        params = (pillar,) if pillar else ()

        rows = self._conn.execute(
            f"""
            SELECT pm.hypothesis_verified AS verified,
                   CAST(pm.realized_pnl AS REAL) > 0 AS profitable,
                   COUNT(*) AS n
            FROM post_mortems pm
            JOIN positions p ON p.id = pm.position_id
            {clause}
            GROUP BY verified, profitable
            """,
            params,
        ).fetchall()

        out = {"skilled": 0, "lucky": 0, "unlucky": 0, "wrong": 0}
        for r in rows:
            verified, profitable, n = bool(r["verified"]), bool(r["profitable"]), r["n"]
            if verified and profitable:
                out["skilled"] += n
            elif not verified and profitable:
                out["lucky"] += n
            elif verified and not profitable:
                out["unlucky"] += n
            else:
                out["wrong"] += n
        return out


def _to_position(row: sqlite3.Row) -> Position:
    return Position(
        id=row["id"],
        opened_at=datetime.fromisoformat(row["opened_at"]),
        instrument=row["instrument"],
        venue=row["venue"],
        side=row["side"],
        quantity=Decimal(row["quantity"]),
        entry_price=Decimal(row["entry_price"]),
        strategy_pillar=row["strategy_pillar"],
        hypothesis=Hypothesis(
            text=row["hypothesis"],
            supporting_data=json.loads(row["supporting_data"]),
            counter_argument=row["counter_argument"],
            invalidation=row["invalidation"],
            exit_plan=row["exit_plan"],
            expected_edge_bps=row["expected_edge_bps"],
            risk_assessment=json.loads(row["risk_assessment"])
            if row["risk_assessment"]
            else None,
        ),
        closed_at=datetime.fromisoformat(row["closed_at"])
        if row["closed_at"]
        else None,
    )
