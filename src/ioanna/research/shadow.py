"""Shadow mode: propose, record, resolve, judge.

Phase 2 runs the research layer for three months with nothing executing. The
point is not to see whether the ideas *look* good -- backtests always look
good, which is what `validation/` exists to remember. The point is to collect
an out-of-sample record that was written down before the outcome was known,
and then apply the same deflation to it that would flatten a lucky search.

Three properties make the record worth anything, and all three are enforced
here rather than left to discipline:

* **Proposals are immutable.** Expected edge is fixed at proposal time. A
  record that can be revised after the fact measures nothing.
* **Every proposal counts.** There is no way to withdraw one. Shadow mode is
  trivial to fake by quietly forgetting the bad calls, so the ledger has no
  delete and `evaluate` refuses to score a subset.
* **Costs always apply.** There is no gross mode. Nof1 found that LLM traders
  lost to fees rather than to bad predictions; a shadow result that ignores
  costs would reproduce exactly that mistake with none of the evidence.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from ..validation.sharpe import SharpeStats, deflated_sharpe_ratio, sharpe_stats
from .costs import BPS, CostModel

D = Decimal

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    proposed_at       TEXT    NOT NULL,
    family            TEXT    NOT NULL,
    instrument        TEXT    NOT NULL,
    direction         TEXT    NOT NULL CHECK (direction IN ('long', 'short')),
    reference_price   TEXT    NOT NULL,
    notional          TEXT    NOT NULL,
    expected_edge_bps TEXT    NOT NULL,
    hypothesis        TEXT    NOT NULL CHECK (length(trim(hypothesis)) >= 20),
    counter_argument  TEXT    NOT NULL CHECK
                              (length(trim(counter_argument)) >= 20),
    invalidation      TEXT    NOT NULL CHECK (length(trim(invalidation)) >= 10),
    supporting_data   TEXT,

    resolved_at       TEXT,
    exit_price        TEXT,
    gross_bps         TEXT,
    cost_bps          TEXT,
    net_bps           TEXT,
    resolution        TEXT
);

CREATE INDEX IF NOT EXISTS idx_proposals_family ON proposals (family);
CREATE INDEX IF NOT EXISTS idx_proposals_open
    ON proposals (resolved_at) WHERE resolved_at IS NULL;

-- Same reasoning as the journal: a proposal is a prediction, and a prediction
-- that can be edited after the result is in is not a prediction.
CREATE TRIGGER IF NOT EXISTS proposals_are_immutable
BEFORE UPDATE OF
    proposed_at, family, instrument, direction, reference_price, notional,
    expected_edge_bps, hypothesis, counter_argument, invalidation,
    supporting_data
ON proposals
BEGIN
    SELECT RAISE(ABORT, 'a shadow proposal cannot be revised after the fact');
END;

CREATE TRIGGER IF NOT EXISTS proposals_resolve_once
BEFORE UPDATE OF resolved_at ON proposals
WHEN OLD.resolved_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'proposal is already resolved');
END;
"""


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class Resolution(str, Enum):
    TARGET = "target_reached"
    INVALIDATED = "hypothesis_invalidated"
    EXPIRED = "horizon_expired"


@dataclass(frozen=True)
class Proposal:
    """A trade the system would have made, recorded before the outcome."""

    family: str
    instrument: str
    direction: Direction
    reference_price: Decimal
    notional: Decimal
    expected_edge_bps: Decimal
    hypothesis: str
    counter_argument: str
    invalidation: str
    supporting_data: dict[str, Any] = field(default_factory=dict)
    proposed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if self.reference_price <= 0:
            raise ValueError("reference price must be positive")
        if self.notional <= 0:
            raise ValueError("notional must be positive")


@dataclass(frozen=True)
class Outcome:
    proposal_id: int
    resolved_at: datetime
    exit_price: Decimal
    gross_bps: Decimal
    cost_bps: Decimal
    net_bps: Decimal
    resolution: Resolution

    @property
    def profitable(self) -> bool:
        return self.net_bps > 0

    @property
    def costs_ate_the_edge(self) -> bool:
        """Right about direction, wrong about whether it was worth trading.

        The Alpha Arena signature. Counting these separately matters because
        the fix is different: a strategy losing on direction needs a better
        signal, one losing on costs needs to trade less.
        """
        return self.gross_bps > 0 and self.net_bps <= 0


@dataclass(frozen=True)
class Gate2Report:
    """Whether a strategy family has earned live capital."""

    family: str
    n_proposals: int
    n_resolved: int
    days_observed: int

    hit_rate: float
    mean_gross_bps: float
    mean_cost_bps: float
    mean_net_bps: float
    cost_ratio: float
    """Costs as a fraction of gross edge. Above 1 means the signal was real
    and the trading destroyed it anyway."""

    net_sharpe_annualised: float
    deflated_sharpe: float
    n_trials: int
    blockers: tuple[str, ...]

    @property
    def passes(self) -> bool:
        return not self.blockers

    def summary(self) -> str:
        verdict = "PASS" if self.passes else "FAIL"
        lines = [
            f"Gate 2 [{verdict}] {self.family}",
            f"  observed        : {self.days_observed} days, "
            f"{self.n_resolved}/{self.n_proposals} resolved",
            f"  hit rate        : {self.hit_rate:.1%}",
            f"  gross edge      : {self.mean_gross_bps:+.1f} bps/trade",
            f"  costs           : {self.mean_cost_bps:.1f} bps/trade "
            f"({self.cost_ratio:.0%} of gross)",
            f"  net edge        : {self.mean_net_bps:+.1f} bps/trade",
            f"  net Sharpe      : {self.net_sharpe_annualised:.2f} annualised",
            f"  deflated Sharpe : {self.deflated_sharpe:.3f} "
            f"(N={self.n_trials})",
        ]
        for blocker in self.blockers:
            lines.append(f"  BLOCKER: {blocker}")
        return "\n".join(lines)


class ShadowLedger:
    """Records what the system would have done, and what it would have cost."""

    def __init__(
        self,
        cost_model: CostModel,
        path: str | Path = ":memory:",
    ) -> None:
        self.costs = cost_model
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> ShadowLedger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- proposing ----------------------------------------------------------

    def propose(self, proposal: Proposal) -> int:
        try:
            cur = self._conn.execute(
                """
                INSERT INTO proposals (
                    proposed_at, family, instrument, direction,
                    reference_price, notional, expected_edge_bps,
                    hypothesis, counter_argument, invalidation, supporting_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.proposed_at.isoformat(),
                    proposal.family,
                    proposal.instrument,
                    proposal.direction.value,
                    str(proposal.reference_price),
                    str(proposal.notional),
                    str(proposal.expected_edge_bps),
                    proposal.hypothesis,
                    proposal.counter_argument,
                    proposal.invalidation,
                    json.dumps(proposal.supporting_data, default=str),
                ),
            )
        except sqlite3.DatabaseError as exc:
            raise ValueError(
                f"incomplete proposal: {exc}. A shadow proposal needs the same "
                "hypothesis, counter argument and invalidation condition as a "
                "live position -- it is standing in for one."
            ) from exc

        self._conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    # -- resolving ----------------------------------------------------------

    def resolve(
        self,
        proposal_id: int,
        exit_price: Decimal,
        resolution: Resolution = Resolution.TARGET,
        at: datetime | None = None,
        maker: bool = False,
    ) -> Outcome:
        """Close a proposal at a price and charge it the full round trip."""
        row = self._conn.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no proposal {proposal_id}")
        if row["resolved_at"] is not None:
            raise ValueError(f"proposal {proposal_id} is already resolved")
        if exit_price <= 0:
            raise ValueError("exit price must be positive")

        ts = at or datetime.now(timezone.utc)
        entry = Decimal(row["reference_price"])
        notional = Decimal(row["notional"])
        proposed_at = datetime.fromisoformat(row["proposed_at"])

        move = (exit_price - entry) / entry
        if row["direction"] == Direction.SHORT.value:
            move = -move
        gross_bps = move / BPS

        holding_days = D(str(max(0.0, (ts - proposed_at).total_seconds() / 86400)))
        cost_bps = self.costs.round_trip_bps(notional, holding_days, maker)
        net_bps = gross_bps - cost_bps

        with self._conn:
            self._conn.execute(
                """
                UPDATE proposals
                SET resolved_at = ?, exit_price = ?, gross_bps = ?,
                    cost_bps = ?, net_bps = ?, resolution = ?
                WHERE id = ?
                """,
                (
                    ts.isoformat(),
                    str(exit_price),
                    str(gross_bps),
                    str(cost_bps),
                    str(net_bps),
                    resolution.value,
                    proposal_id,
                ),
            )

        return Outcome(
            proposal_id=proposal_id,
            resolved_at=ts,
            exit_price=exit_price,
            gross_bps=gross_bps,
            cost_bps=cost_bps,
            net_bps=net_bps,
            resolution=resolution,
        )

    # -- reading ------------------------------------------------------------

    def open_proposals(self, family: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM proposals WHERE resolved_at IS NULL"
        params: tuple = ()
        if family:
            sql += " AND family = ?"
            params = (family,)
        return [dict(r) for r in self._conn.execute(sql + " ORDER BY id", params)]

    def net_returns(self, family: str) -> np.ndarray:
        """Net per-trade returns, as fractions. Every resolved proposal."""
        rows = self._conn.execute(
            "SELECT net_bps FROM proposals "
            "WHERE family = ? AND resolved_at IS NOT NULL ORDER BY id",
            (family,),
        ).fetchall()
        return np.array([float(r["net_bps"]) * 1e-4 for r in rows])

    def gross_returns(self, family: str) -> np.ndarray:
        rows = self._conn.execute(
            "SELECT gross_bps FROM proposals "
            "WHERE family = ? AND resolved_at IS NOT NULL ORDER BY id",
            (family,),
        ).fetchall()
        return np.array([float(r["gross_bps"]) * 1e-4 for r in rows])

    def observation_days(self, family: str) -> int:
        row = self._conn.execute(
            "SELECT MIN(proposed_at) AS first, MAX(COALESCE(resolved_at, "
            "proposed_at)) AS last FROM proposals WHERE family = ?",
            (family,),
        ).fetchone()
        if not row or not row["first"]:
            return 0
        first = datetime.fromisoformat(row["first"])
        last = datetime.fromisoformat(row["last"])
        return (last - first).days

    # -- the verdict --------------------------------------------------------

    def evaluate(
        self,
        family: str,
        n_trials: int,
        variance_across_trials: float,
        min_days: int = 90,
        min_proposals: int = 30,
        min_deflated_sharpe: float = 0.5,
    ) -> Gate2Report:
        """Score a family against the Gate 2 criteria.

        `n_trials` and `variance_across_trials` come from the trial registry.
        They are required rather than optional: deflating against an unknown
        number of trials is the failure the registry exists to prevent, and
        defaulting them to 1 would quietly report a raw Sharpe.
        """
        net = self.net_returns(family)
        gross = self.gross_returns(family)

        total = self._conn.execute(
            "SELECT COUNT(*) AS n FROM proposals WHERE family = ?", (family,)
        ).fetchone()["n"]
        days = self.observation_days(family)
        blockers: list[str] = []

        if net.size == 0:
            return Gate2Report(
                family=family,
                n_proposals=total,
                n_resolved=0,
                days_observed=days,
                hit_rate=0.0,
                mean_gross_bps=0.0,
                mean_cost_bps=0.0,
                mean_net_bps=0.0,
                cost_ratio=0.0,
                net_sharpe_annualised=0.0,
                deflated_sharpe=0.0,
                n_trials=n_trials,
                blockers=("no resolved proposals",),
            )

        mean_gross = float(gross.mean()) * 1e4
        mean_net = float(net.mean()) * 1e4
        mean_cost = mean_gross - mean_net
        cost_ratio = mean_cost / abs(mean_gross) if mean_gross else float("inf")

        # Per-trade Sharpe, annualised by the observed trade frequency. Using
        # a fixed 252 would overstate a strategy that trades ten times a year
        # and understate one that trades daily.
        deflated = 0.0
        annualised = 0.0
        try:
            stats: SharpeStats = sharpe_stats(net)
            trades_per_year = (
                net.size * 365.0 / days if days > 0 else float(net.size)
            )
            annualised = stats.sharpe * np.sqrt(max(trades_per_year, 1.0))
            deflated = deflated_sharpe_ratio(
                stats, n_trials, variance_across_trials
            )
        except ValueError as exc:
            blockers.append(f"cannot score returns: {exc}")

        if days < min_days:
            blockers.append(
                f"only {days} days observed, Gate 2 needs {min_days}"
            )
        if net.size < min_proposals:
            blockers.append(
                f"only {net.size} resolved proposals, need {min_proposals} "
                "for the statistics to mean anything"
            )
        if mean_net <= 0:
            blockers.append(
                f"net edge is {mean_net:+.1f} bps/trade after costs"
            )
        if deflated < min_deflated_sharpe:
            blockers.append(
                f"deflated Sharpe {deflated:.3f} below {min_deflated_sharpe} "
                f"against {n_trials} trials"
            )
        if mean_gross > 0 and mean_net <= 0:
            blockers.append(
                "the signal was real but trading costs consumed it -- trade "
                "less, not differently"
            )

        return Gate2Report(
            family=family,
            n_proposals=total,
            n_resolved=int(net.size),
            days_observed=days,
            hit_rate=float((net > 0).mean()),
            mean_gross_bps=mean_gross,
            mean_cost_bps=mean_cost,
            mean_net_bps=mean_net,
            cost_ratio=cost_ratio,
            net_sharpe_annualised=float(annualised),
            deflated_sharpe=float(deflated),
            n_trials=n_trials,
            blockers=tuple(blockers),
        )

    def evaluate_with_registry(
        self, family: str, registry, **kwargs
    ) -> Gate2Report:
        """Score against a `TrialRegistry`, which knows the real trial count."""
        n = registry.n_trials(family)
        if n == 0:
            raise ValueError(
                f"no trials recorded for {family!r}; the deflation would run "
                "on N=0 and report a raw Sharpe as though nothing had been "
                "selected"
            )
        return self.evaluate(family, n, registry.sharpe_variance(family), **kwargs)
