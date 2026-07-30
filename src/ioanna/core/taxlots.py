"""Tax lot tracking, FIFO.

Cost basis has to be recorded as it happens. Reconstructing it years later
from broker statements is possible and miserable, and from a DEX it is often
not possible at all -- which matters more from 1 January 2026, when DAC8 began
reporting crypto transactions to EU tax authorities automatically. The
question is no longer whether the tax office has the data.

Design notes tied to the Greek framework (see research/06-regulatory-tax.md):

* Acquisition fees are added to cost basis and disposal fees are netted from
  proceeds, matching the "directly related expenses" deduction.
* FIFO. Greece does not offer the lot-selection choice that US investors have,
  so there is no method parameter here -- offering one would only invite
  reporting a basis the tax office will not accept.
* `disposal_report` groups realised gains by tax year, which is the shape the
  annual return wants.

Crypto-to-crypto is not a taxable event under the new framework, so a swap
should be recorded as `exchange` rather than as a disposal plus acquisition.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS lots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    instrument    TEXT NOT NULL,
    acquired_at   TEXT NOT NULL,
    quantity      TEXT NOT NULL,
    remaining     TEXT NOT NULL,
    cost_per_unit TEXT NOT NULL,
    fees          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lots_open
    ON lots (instrument, acquired_at, id);

CREATE TABLE IF NOT EXISTS disposals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id        INTEGER NOT NULL REFERENCES lots (id),
    instrument    TEXT NOT NULL,
    acquired_at   TEXT NOT NULL,
    disposed_at   TEXT NOT NULL,
    quantity      TEXT NOT NULL,
    cost_basis    TEXT NOT NULL,
    proceeds      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_disposals_when ON disposals (disposed_at);
"""


class InsufficientHoldingsError(ValueError):
    """Raised on an attempt to dispose of more than is held."""


@dataclass(frozen=True)
class Lot:
    id: int
    instrument: str
    acquired_at: datetime
    quantity: Decimal
    remaining: Decimal
    cost_per_unit: Decimal
    fees: Decimal

    @property
    def total_cost(self) -> Decimal:
        """Acquisition cost of the whole lot, fees included."""
        return self.quantity * self.cost_per_unit + self.fees

    @property
    def remaining_cost(self) -> Decimal:
        """Cost basis of the unsold part, with fees apportioned pro rata."""
        if self.quantity == 0:
            return Decimal(0)
        return self.total_cost * (self.remaining / self.quantity)

    @property
    def is_open(self) -> bool:
        return self.remaining > 0


@dataclass(frozen=True)
class Disposal:
    instrument: str
    quantity: Decimal
    acquired_at: datetime
    disposed_at: datetime
    cost_basis: Decimal
    proceeds: Decimal

    @property
    def gain(self) -> Decimal:
        return self.proceeds - self.cost_basis

    @property
    def holding_days(self) -> int:
        return (self.disposed_at - self.acquired_at).days


class TaxLedger:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> TaxLedger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- acquiring ----------------------------------------------------------

    def acquire(
        self,
        instrument: str,
        quantity: Decimal,
        price: Decimal,
        at: datetime | None = None,
        fees: Decimal = Decimal(0),
    ) -> int:
        if quantity <= 0:
            raise ValueError("acquisition quantity must be positive")
        if price < 0:
            raise ValueError("price must be non-negative")
        if fees < 0:
            raise ValueError("fees must be non-negative")

        ts = at or datetime.now(timezone.utc)
        cur = self._conn.execute(
            """
            INSERT INTO lots
                (instrument, acquired_at, quantity, remaining, cost_per_unit, fees)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                instrument,
                ts.isoformat(),
                str(quantity),
                str(quantity),
                str(price),
                str(fees),
            ),
        )
        self._conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    # -- disposing ----------------------------------------------------------

    def dispose(
        self,
        instrument: str,
        quantity: Decimal,
        price: Decimal,
        at: datetime | None = None,
        fees: Decimal = Decimal(0),
    ) -> tuple[Disposal, ...]:
        """Sell FIFO, returning one disposal per lot consumed.

        A sale spanning several lots produces several disposals, each with its
        own acquisition date -- which is what the tax report needs, and what a
        single blended-average number would destroy.
        """
        if quantity <= 0:
            raise ValueError("disposal quantity must be positive")
        if price < 0:
            raise ValueError("price must be non-negative")
        if fees < 0:
            raise ValueError("fees must be non-negative")

        held = self.quantity(instrument)
        if quantity > held:
            raise InsufficientHoldingsError(
                f"cannot dispose of {quantity} {instrument}: only {held} held"
            )

        ts = at or datetime.now(timezone.utc)
        gross_proceeds = quantity * price
        disposals: list[Disposal] = []
        outstanding = quantity

        with self._conn:
            for lot in self._open_lots(instrument):
                if outstanding <= 0:
                    break

                taken = min(lot.remaining, outstanding)
                unit_cost = lot.total_cost / lot.quantity
                cost_basis = unit_cost * taken

                # Disposal fees split across lots in proportion to the value
                # each contributes, so a multi-lot sale nets the same total.
                share = taken / quantity
                proceeds = gross_proceeds * share - fees * share

                self._conn.execute(
                    "UPDATE lots SET remaining = ? WHERE id = ?",
                    (str(lot.remaining - taken), lot.id),
                )
                self._conn.execute(
                    """
                    INSERT INTO disposals
                        (lot_id, instrument, acquired_at, disposed_at,
                         quantity, cost_basis, proceeds)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lot.id,
                        instrument,
                        lot.acquired_at.isoformat(),
                        ts.isoformat(),
                        str(taken),
                        str(cost_basis),
                        str(proceeds),
                    ),
                )

                disposals.append(
                    Disposal(
                        instrument=instrument,
                        quantity=taken,
                        acquired_at=lot.acquired_at,
                        disposed_at=ts,
                        cost_basis=cost_basis,
                        proceeds=proceeds,
                    )
                )
                outstanding -= taken

        return tuple(disposals)

    # -- reading ------------------------------------------------------------

    def _open_lots(self, instrument: str) -> list[Lot]:
        rows = self._conn.execute(
            """
            SELECT * FROM lots
            WHERE instrument = ? AND CAST(remaining AS REAL) > 0
            ORDER BY acquired_at, id
            """,
            (instrument,),
        ).fetchall()
        return [_to_lot(r) for r in rows]

    def open_lots(self, instrument: str | None = None) -> list[Lot]:
        if instrument is not None:
            return self._open_lots(instrument)
        rows = self._conn.execute(
            """
            SELECT * FROM lots WHERE CAST(remaining AS REAL) > 0
            ORDER BY instrument, acquired_at, id
            """
        ).fetchall()
        return [_to_lot(r) for r in rows]

    def quantity(self, instrument: str) -> Decimal:
        return sum(
            (lot.remaining for lot in self._open_lots(instrument)), Decimal(0)
        )

    def cost_basis(self, instrument: str) -> Decimal:
        """Total cost basis of what is still held."""
        return sum(
            (lot.remaining_cost for lot in self._open_lots(instrument)), Decimal(0)
        )

    def average_cost(self, instrument: str) -> Decimal:
        held = self.quantity(instrument)
        if held == 0:
            return Decimal(0)
        return self.cost_basis(instrument) / held

    def unrealized_gain(self, prices: dict[str, Decimal]) -> Decimal:
        """Paper gain at the given marks. Not taxable, and not income."""
        total = Decimal(0)
        for instrument, price in prices.items():
            held = self.quantity(instrument)
            if held > 0:
                total += held * price - self.cost_basis(instrument)
        return total

    # -- the annual return --------------------------------------------------

    def realized_gain(
        self, year: int | None = None, instrument: str | None = None
    ) -> Decimal:
        clauses, params = [], []
        if year is not None:
            clauses.append("disposed_at >= ? AND disposed_at < ?")
            params += [f"{year}-01-01", f"{year + 1}-01-01"]
        if instrument is not None:
            clauses.append("instrument = ?")
            params.append(instrument)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT cost_basis, proceeds FROM disposals {where}", params
        ).fetchall()

        return sum(
            (Decimal(r["proceeds"]) - Decimal(r["cost_basis"]) for r in rows),
            Decimal(0),
        )

    def disposal_report(self, year: int) -> list[Disposal]:
        """Every disposal in a tax year, oldest first."""
        rows = self._conn.execute(
            """
            SELECT * FROM disposals
            WHERE disposed_at >= ? AND disposed_at < ?
            ORDER BY disposed_at, id
            """,
            (f"{year}-01-01", f"{year + 1}-01-01"),
        ).fetchall()

        return [
            Disposal(
                instrument=r["instrument"],
                quantity=Decimal(r["quantity"]),
                acquired_at=datetime.fromisoformat(r["acquired_at"]),
                disposed_at=datetime.fromisoformat(r["disposed_at"]),
                cost_basis=Decimal(r["cost_basis"]),
                proceeds=Decimal(r["proceeds"]),
            )
            for r in rows
        ]

    def tax_summary(self, year: int, rate: Decimal = Decimal("0.15")) -> dict:
        """Gains, losses and estimated tax for a year.

        An estimate, not a filing. Loss offset rules, the crypto allowance and
        the treatment of funding income are all questions for an accountant --
        the value here is that the underlying numbers are complete and were
        recorded as the trades happened.
        """
        disposals = self.disposal_report(year)
        gains = sum((d.gain for d in disposals if d.gain > 0), Decimal(0))
        losses = sum((d.gain for d in disposals if d.gain < 0), Decimal(0))
        net = gains + losses

        return {
            "year": year,
            "disposals": len(disposals),
            "gross_gains": gains,
            "gross_losses": losses,
            "net_gain": net,
            "estimated_tax": max(Decimal(0), net) * rate,
            "rate": rate,
        }


def _to_lot(row: sqlite3.Row) -> Lot:
    return Lot(
        id=row["id"],
        instrument=row["instrument"],
        acquired_at=datetime.fromisoformat(row["acquired_at"]),
        quantity=Decimal(row["quantity"]),
        remaining=Decimal(row["remaining"]),
        cost_per_unit=Decimal(row["cost_per_unit"]),
        fees=Decimal(row["fees"]),
    )
