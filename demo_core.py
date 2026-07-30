"""The passive core, running.

Five years of monthly contributions with the two sleeves drifting apart,
showing what the system does each month and what it costs in tax.

    python demo_core.py
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal as D

import numpy as np

from ioanna.core import (
    ContributionSchedule,
    PassiveCore,
    RebalanceBands,
    Rebalancer,
    TargetAllocation,
    TaxLedger,
)
from ioanna.governor import Governor, Limits
from ioanna.journal import Journal

RULE = "=" * 74
IWDA, EIMI = "IWDA", "EIMI"
DEEP = {IWDA: D("100000000"), EIMI: D("100000000")}


def build(allow_sales_only: bool = False):
    allocation = TargetAllocation({IWDA: D("0.8"), EIMI: D("0.2")})
    limits = Limits(
        max_position_fraction=D("0.85"),
        max_pillar_fraction={"core": D("1.0")},
        max_trades_per_day=5,
        max_drawdown=D("0.15"),
        min_liquidity_multiple=D("10"),
        allowed_venues=frozenset({"ibkr"}),
        allowed_instruments=frozenset({IWDA, EIMI}),
    )
    return PassiveCore(
        allocation=allocation,
        schedule=ContributionSchedule(amount=D("500"), day_of_month=1),
        governor=Governor(limits),
        journal=Journal(),
        ledger=TaxLedger(),
        rebalancer=Rebalancer(allocation, RebalanceBands(), min_order=D("50")),
    )


def run(contribute: bool, months: int = 60, verbose: bool = False):
    """Simulate `months` of cycles. Returns the final state."""
    core = build()
    quantities = {IWDA: D("80"), EIMI: D("40")}   # 8000 / 2000 at 100 / 50
    prices = {IWDA: D("100"), EIMI: D("50")}
    last_contribution = date(2025, 12, 1)

    # Seed the tax ledger with the opening position. Without a cost basis on
    # record the first rebalancing sale has nothing to sell against -- which
    # is exactly the hole the ledger exists to prevent, so it fails loudly.
    opened = datetime(2025, 12, 1, tzinfo=timezone.utc)
    for name, qty in quantities.items():
        core.ledger.acquire(name, qty, prices[name], opened)

    rng = np.random.default_rng(11)
    sells = buys = 0

    for month in range(months):
        year, mo = 2026 + month // 12, month % 12 + 1
        now = datetime(year, mo, 1, tzinfo=timezone.utc)

        # Divergent monthly returns: developed outruns emerging.
        for name, mu, sd in ((IWDA, 0.008, 0.04), (EIMI, 0.003, 0.06)):
            r = D(str(round(float(rng.normal(mu, sd)), 6)))
            prices[name] = prices[name] * (1 + r)

        result = core.run_cycle(
            prices=prices,
            quantities=quantities,
            last_contribution=last_contribution if contribute else now.date(),
            now=now,
            liquidity=DEEP,
        )

        for intent in result.approved:
            qty = intent.order.quantity
            core.settle(intent, prices[intent.action.instrument], qty, at=now)
            signed = qty if intent.order.side.value == "buy" else -qty
            quantities[intent.action.instrument] += signed
            if signed > 0:
                buys += 1
            else:
                sells += 1

            if verbose and month < 3:
                pos = core.journal.get(intent.position_id)
                print(f"    {intent.order.side.value:<4} "
                      f"{intent.action.instrument} "
                      f"{float(intent.action.value):>8,.2f}  "
                      f"[{intent.action.trigger.value}]")

        if contribute and result.contribution:
            last_contribution = result.contribution.due_on

    total = sum(quantities[i] * prices[i] for i in quantities)
    return {
        "core": core,
        "buys": buys,
        "sells": sells,
        "total": total,
        "weight": quantities[IWDA] * prices[IWDA] / total,
        "quantities": quantities,
        "prices": prices,
    }


def main() -> None:
    print(f"\n{RULE}\n1. ONE CYCLE, IN DETAIL\n{RULE}")
    core = build()
    result = core.run_cycle(
        prices={IWDA: D("100"), EIMI: D("50")},
        quantities={IWDA: D("90"), EIMI: D("20")},   # 9000/1000 -- off target
        last_contribution=date(2026, 1, 1),
        now=datetime(2026, 2, 1, tzinfo=timezone.utc),
        liquidity=DEEP,
    )

    print(f"\n  Portfolio  : IWDA 9,000 (90%) / EIMI 1,000 (10%)")
    print(f"  Target     : 80% / 20%")
    print(f"  Contribution due: {float(result.contribution.amount):,.2f}\n")

    for intent in result.intents:
        verdict = "APPROVED" if intent.approved else "REFUSED"
        print(f"  {verdict}  {intent.order.side.value:<4} "
              f"{intent.action.instrument:<5} "
              f"{float(intent.action.value):>8,.2f}  "
              f"[{intent.action.trigger.value}]")

    intent = result.approved[0]
    hypothesis = core.journal.get(intent.position_id).hypothesis
    print(f"\n  Journalled before the order goes out:\n")
    print(f"    WHY   : {hypothesis.text}")
    print(f"\n    BUT   : {hypothesis.counter_argument}")
    print(f"\n    STOP  : {hypothesis.invalidation}")

    print(f"\n  Two triggers wanted EIMI this cycle -- the contribution and the")
    print(f"  band breach -- and they are merged into one order rather than two")
    print(f"  commissions. The sell is sequenced first because it funds the buy.")

    print(f"\n{RULE}\n2. FIVE YEARS, WITH AND WITHOUT CONTRIBUTIONS\n{RULE}\n")

    with_c = run(contribute=True)
    without = run(contribute=False)

    header = f"  {'':<22}{'buys':>6}{'sells':>7}{'tax owed':>12}{'IWDA wt':>10}"
    print(header)
    print(f"  {'-' * (len(header) - 2)}")
    for label, r in (("no contributions", without), ("500/mo", with_c)):
        tax = r["core"].ledger.tax_summary(2026)["estimated_tax"]
        realized = sum(
            r["core"].ledger.realized_gain(y) for y in range(2026, 2032)
        )
        print(f"  {label:<22}{r['buys']:>6}{r['sells']:>7}"
              f"{float(realized) * 0.15:>12,.2f}{float(r['weight']):>10.3f}")

    print(f"\n  Both paths held the target weight. The difference is the tax:")
    print(f"  selling to rebalance realises a gain taxed at 15%, while")
    print(f"  directing new money at whatever is underweight reaches the same")
    print(f"  allocation without a single taxable disposal.")

    print(f"\n{RULE}\n3. THE TAX RECORD\n{RULE}\n")
    core = without["core"]
    for year in (2026, 2027):
        s = core.ledger.tax_summary(year)
        if s["disposals"]:
            print(f"  {year}: {s['disposals']} disposals, "
                  f"net {float(s['net_gain']):>10,.2f}, "
                  f"tax {float(s['estimated_tax']):>8,.2f}")

    print(f"\n  Cost basis is recorded at fill time, per lot, FIFO. From")
    print(f"  1 Jan 2026 DAC8 reports crypto transactions to EU tax")
    print(f"  authorities automatically -- the data exists either way.")

    print(f"\n{RULE}\nPhase 1: contributions scheduled, drift corrected,")
    print(f"every order reviewed and journalled, cost basis tracked.\n{RULE}\n")


if __name__ == "__main__":
    main()
