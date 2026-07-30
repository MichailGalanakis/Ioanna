"""Trial registry.

Every strategy variant ever evaluated, recorded before its result is known.

This is the least interesting file in the project and the one that decides
whether any of the rest means anything. The deflated Sharpe ratio needs the
number of trials that led to the candidate being chosen; supply a number that
is too small and it hands back false confidence with a rigorous-looking
decimal point on it.

The failure mode is not dishonesty, it is forgetting. Variants abandoned after
five minutes, parameter sweeps that were "just exploring", the version tried
before the data bug was fixed -- all of them narrowed the search, so all of
them count. Recording is therefore a side effect of evaluating, not a step
that can be skipped when in a hurry.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .sharpe import SharpeStats, deflated_sharpe_ratio

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategy_trials (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tried_at          TEXT    NOT NULL,
    family            TEXT    NOT NULL,
    params            TEXT    NOT NULL,
    params_hash       TEXT    NOT NULL,
    n_observations    INTEGER NOT NULL,
    sharpe            REAL    NOT NULL,
    skew              REAL    NOT NULL,
    kurtosis          REAL    NOT NULL,
    notes             TEXT,
    UNIQUE (family, params_hash)
);

CREATE INDEX IF NOT EXISTS idx_trials_family ON strategy_trials (family);
"""


@dataclass(frozen=True)
class Trial:
    """One evaluated variant.

    `family` groups variants that were searched over together. It defines the
    scope of the multiple-testing correction, so it should be drawn widely: if
    two "families" were explored in the same sitting with the intention of
    keeping whichever looked better, they are one family.
    """

    family: str
    params: dict[str, Any]
    stats: SharpeStats
    notes: str = ""
    tried_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def params_hash(self) -> str:
        """Stable hash of the parameters, so re-running a variant does not
        inflate the trial count."""
        import hashlib

        canonical = json.dumps(self.params, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class TrialRegistry:
    """Append-mostly store of strategy trials.

    There is deliberately no delete method. Pruning the registry is exactly
    the operation that produces an understated trial count, and it is far
    easier to resist when the code cannot do it.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> TrialRegistry:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writing ------------------------------------------------------------

    def record(self, trial: Trial) -> int:
        """Store a trial. Re-recording identical params is a no-op.

        Returns the row id, or the id of the existing row for a repeat.
        """
        cur = self._conn.execute(
            """
            INSERT INTO strategy_trials
                (tried_at, family, params, params_hash,
                 n_observations, sharpe, skew, kurtosis, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (family, params_hash) DO NOTHING
            """,
            (
                trial.tried_at.isoformat(),
                trial.family,
                json.dumps(trial.params, sort_keys=True, default=str),
                trial.params_hash,
                trial.stats.n_observations,
                trial.stats.sharpe,
                trial.stats.skew,
                trial.stats.kurtosis,
                trial.notes,
            ),
        )
        self._conn.commit()

        if cur.lastrowid:
            return cur.lastrowid
        existing = self._conn.execute(
            "SELECT id FROM strategy_trials WHERE family = ? AND params_hash = ?",
            (trial.family, trial.params_hash),
        ).fetchone()
        return int(existing["id"])

    # -- reading ------------------------------------------------------------

    def n_trials(self, family: str | None = None) -> int:
        if family is None:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM strategy_trials"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM strategy_trials WHERE family = ?",
                (family,),
            ).fetchone()
        return int(row["n"])

    def sharpes(self, family: str | None = None) -> np.ndarray:
        if family is None:
            rows = self._conn.execute(
                "SELECT sharpe FROM strategy_trials"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT sharpe FROM strategy_trials WHERE family = ?", (family,)
            ).fetchall()
        return np.array([r["sharpe"] for r in rows], dtype=float)

    def sharpe_variance(self, family: str | None = None) -> float:
        """Spread of Sharpe ratios across trials, feeding the deflation.

        A wider spread means a higher bar: variants that disagree strongly
        with each other produce a higher maximum by luck alone.
        """
        s = self.sharpes(family)
        if s.size < 2:
            return 0.0
        return float(np.var(s, ddof=1))

    def best(self, family: str | None = None) -> dict[str, Any] | None:
        if family is None:
            row = self._conn.execute(
                "SELECT * FROM strategy_trials ORDER BY sharpe DESC LIMIT 1"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM strategy_trials WHERE family = ? "
                "ORDER BY sharpe DESC LIMIT 1",
                (family,),
            ).fetchone()
        return dict(row) if row else None

    # -- the point of all this ----------------------------------------------

    def deflated_sharpe(self, stats: SharpeStats, family: str) -> float:
        """Deflate a candidate against everything tried in its family.

        The candidate should already be in the registry -- it was a trial too.
        """
        n = self.n_trials(family)
        if n == 0:
            raise ValueError(
                f"no trials recorded for family {family!r}; deflating against "
                "an empty registry would report the raw Sharpe as though "
                "nothing had been selected"
            )
        return deflated_sharpe_ratio(stats, n, self.sharpe_variance(family))
