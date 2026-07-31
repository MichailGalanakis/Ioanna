"""Gate 2, demonstrated.

Three strategies go through shadow mode. All three would look fine in a
backtest; only one earns live capital.

    python demo_shadow.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import numpy as np

from ioanna.research import (
    BINANCE_SPOT,
    Direction,
    Proposal,
    ShadowLedger,
)
from ioanna.validation import Trial, TrialRegistry, sharpe_stats

RULE = "=" * 74


def run_shadow(
    name: str,
    gross_edge_bps: float,
    noise_bps: float,
    n: int = 60,
    days: int = 120,
    seed: int = 0,
) -> ShadowLedger:
    """Four months of proposals, each recorded before its outcome is known."""
    ledger = ShadowLedger(BINANCE_SPOT)
    rng = np.random.default_rng(seed)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for i in range(n):
        opened = start + timedelta(days=i * days / n)
        pid = ledger.propose(
            Proposal(
                family=name,
                instrument="BTC/USDT",
                direction=Direction.LONG,
                reference_price=D("100000"),
                notional=D("10000"),
                expected_edge_bps=D(str(gross_edge_bps)),
                hypothesis=(
                    "Perpetual funding positive for fourteen sessions with "
                    "basis inside 0.3%; the carry should accrue over the week."
                ),
                counter_argument=(
                    "Funding flipped negative within two sessions three times "
                    "last year; the hedge would then cost more than it earns."
                ),
                invalidation="Funding negative for two consecutive sessions.",
                proposed_at=opened,
            )
        )
        move = rng.normal(gross_edge_bps, noise_bps)
        ledger.resolve(
            pid,
            D("100000") * (D(1) + D(str(round(move * 1e-4, 8)))),
            at=opened + timedelta(days=1),
        )
    return ledger


def main() -> None:
    print(f"\n{RULE}\n1. A REAL EDGE, FOUND WITHOUT SEARCHING\n{RULE}\n")
    with run_shadow("carry_v1", gross_edge_bps=86, noise_bps=120) as led:
        print(led.evaluate("carry_v1", n_trials=1, variance_across_trials=0.0)
              .summary())
    print("\n  A 70% hit rate and a net edge that clears costs three times")
    print("  over. One hypothesis, tested once, so there is no selection to")
    print("  deflate. This is what earning live capital looks like.")

    print(f"\n{RULE}\n2. THE SAME RESULT, FOUND BY TRYING 500 VARIANTS\n{RULE}\n")
    with run_shadow("carry_swept", gross_edge_bps=56, noise_bps=250) as led:
        narrow = led.evaluate("carry_swept", 1, 0.0)
        wide = led.evaluate("carry_swept", 500, 0.02)
        print(wide.summary())

    print(f"\n  Identical returns scored two ways:")
    print(f"    deflated Sharpe against   1 trial  : {narrow.deflated_sharpe:.3f}"
          f"  -> {'PASS' if narrow.passes else 'FAIL'}")
    print(f"    deflated Sharpe against 500 trials : {wide.deflated_sharpe:.3f}"
          f"  -> {'PASS' if wide.passes else 'FAIL'}")
    print("\n  Nothing about the strategy changed. Only the number of variants")
    print("  tried before settling on it, which the trial registry remembers")
    print("  whether or not anyone wants it to.")

    print(f"\n{RULE}\n3. A REAL SIGNAL THAT TRADING DESTROYS\n{RULE}\n")
    with run_shadow("scalper", gross_edge_bps=15, noise_bps=5) as led:
        report = led.evaluate("scalper", 1, 0.0)
        print(report.summary())

    print(f"\n  The signal is genuine -- 15bps gross, and it hits almost every")
    print(f"  time. It still loses money, because the round trip costs 26bps.")
    print(f"  This is the Alpha Arena failure exactly: four of six frontier")
    print(f"  models lost with PnL 'dominated by trading costs as agents")
    print(f"  over-traded and took quick, tiny gains that fees erased'.")
    print(f"\n  The fix is not a better signal. It is trading less.")

    print(f"\n{RULE}\n4. THE REGISTRY IS NOT OPTIONAL\n{RULE}\n")
    with run_shadow("unregistered", 86, 120) as led, TrialRegistry() as reg:
        try:
            led.evaluate_with_registry("unregistered", reg)
        except ValueError as exc:
            print(f"  evaluate_with_registry() -> refused:")
            print(f"    {exc}")

    print(f"\n{RULE}")
    print("Gate 2: a real edge passes, a searched-for one does not, and a")
    print("signal that cannot pay its own costs never reaches live capital.")
    print(f"{RULE}\n")


if __name__ == "__main__":
    main()
