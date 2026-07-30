"""Gate 0, demonstrated.

Runs the exact trap the validation module exists to catch: sweep 200 strategy
variants over data with no edge in it whatsoever, keep the best one, and see
what each metric says about it.

    python demo_gate0.py
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from ioanna.governor import (
    Governor,
    Limits,
    OrderRequest,
    PortfolioState,
    Side,
)
from ioanna.journal import Hypothesis, Journal, PostMortem
from ioanna.validation import (
    Trial,
    TrialRegistry,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_stats,
)

RULE = "=" * 72


def section(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def demo_validation() -> None:
    section("1. THE TRAP: 200 variants, zero edge, best one kept")

    rng = np.random.default_rng(1234)
    n_obs, n_variants = 1000, 200

    # Pure noise. Zero mean by construction -- there is nothing here to find.
    returns = rng.normal(0.0, 0.01, size=(n_obs, n_variants))

    with TrialRegistry() as registry:
        for i in range(n_variants):
            registry.record(
                Trial(
                    family="noise_sweep",
                    params={"variant": i},
                    stats=sharpe_stats(returns[:, i]),
                )
            )

        sharpes = returns.mean(axis=0) / returns.std(axis=0, ddof=0)
        winner = int(np.argmax(sharpes))
        best = sharpe_stats(returns[:, winner])

        print(f"\n  Variants tried            : {registry.n_trials('noise_sweep')}")
        print(f"  True edge in the data     : none (zero mean by construction)")
        print(f"\n  Winner: variant #{winner}")
        print(f"    Annualized Sharpe       : {best.annualized(252):>7.3f}"
              "   <- the number that gets quoted")
        print(f"    PSR vs zero             : {probabilistic_sharpe_ratio(best):>7.3f}"
              "   <- 'significant'!")
        print(f"    Deflated Sharpe         : "
              f"{registry.deflated_sharpe(best, 'noise_sweep'):>7.3f}"
              "   <- the honest answer")

        pbo = probability_of_backtest_overfitting(returns, n_splits=8)
        print(f"    PBO ({pbo.n_splits} CSCV paths)     : {pbo.pbo:>7.3f}"
              "   <- 0.5 means coin flip")

    print("\n  An annualized Sharpe of 1.4 and 99% 'confidence', from data with")
    print("  no signal in it. Deflation is what separates the two readings.")


def demo_real_edge() -> None:
    section("2. THE CONTROL: same machinery, one variant with real drift")

    rng = np.random.default_rng(7)
    returns = rng.normal(0.0, 0.01, size=(1000, 50))
    returns[:, 17] += 0.004  # a genuine, persistent edge

    sharpes = returns.mean(axis=0) / returns.std(axis=0, ddof=0)
    winner = int(np.argmax(sharpes))
    best = sharpe_stats(returns[:, winner])

    with TrialRegistry() as registry:
        for i in range(50):
            registry.record(
                Trial(family="real", params={"v": i}, stats=sharpe_stats(returns[:, i]))
            )
        dsr = registry.deflated_sharpe(best, "real")

    pbo = probability_of_backtest_overfitting(returns, n_splits=8)

    print(f"\n  Edge planted at variant   : 17")
    print(f"  Search selected           : {winner}")
    print(f"    Annualized Sharpe       : {best.annualized(252):>7.3f}")
    print(f"    Deflated Sharpe         : {dsr:>7.3f}   <- survives deflation")
    print(f"    PBO                     : {pbo.pbo:>7.3f}   <- near zero")
    print("\n  The gate is not merely strict: a real edge still gets through.")


def demo_governor() -> None:
    section("3. THE GOVERNOR: limits that no amount of conviction moves")

    limits = Limits(
        max_position_fraction=Decimal("0.05"),
        max_trades_per_day=5,
        max_drawdown=Decimal("0.15"),
        allowed_venues=frozenset({"binance"}),
        allowed_instruments=frozenset({"BTC/USDT"}),
    )
    governor = Governor(limits)
    state = PortfolioState(
        equity=Decimal("100000"),
        peak_equity=Decimal("100000"),
    )

    def order(**kw) -> OrderRequest:
        params = dict(
            instrument="BTC/USDT",
            venue="binance",
            side=Side.BUY,
            quantity=Decimal("0.01"),
            reference_price=Decimal("100000"),
            strategy_pillar="satellite",
            venue_liquidity=Decimal("1000000"),
        )
        params.update(kw)
        return OrderRequest(**params)

    cases = [
        ("a normal 1,000 order", order(), state),
        ("6,000 -- over the 5% cap", order(quantity=Decimal("0.06")), state),
        ("after 5 trades today", order(), PortfolioState(
            equity=Decimal("100000"), peak_equity=Decimal("100000"), trades_today=5)),
        ("at a 20% drawdown", order(), PortfolioState(
            equity=Decimal("80000"), peak_equity=Decimal("100000"))),
        ("exiting at that drawdown", order(reduce_only=True), PortfolioState(
            equity=Decimal("80000"), peak_equity=Decimal("100000"),
            positions={"BTC/USDT": Decimal("5000")})),
        ("an unlisted venue", order(venue="sketchy-dex"), state),
        ("a book too thin to fill", order(venue_liquidity=Decimal("500")), state),
    ]

    print()
    for label, o, s in cases:
        d = governor.review(o, s)
        mark = "APPROVED" if d.approved else "REFUSED "
        reason = "" if d.approved else f"  ({d.violations[0].reason.value})"
        print(f"  {mark}  {label:<28}{reason}")

    governor.engage_kill_switch()
    d = governor.review(order(), state)
    print(f"  {'REFUSED ' if not d.approved else 'APPROVED'}  "
          f"{'with the kill switch on':<28}  ({d.violations[0].reason.value})")


def demo_journal() -> None:
    section("4. THE JOURNAL: reasoning recorded before entry, frozen after")

    with Journal() as journal:
        pid = journal.open_position(
            instrument="BTC/USDT",
            venue="binance",
            side="buy",
            quantity=Decimal("0.05"),
            entry_price=Decimal("100000"),
            strategy_pillar="satellite",
            hypothesis=Hypothesis(
                text=(
                    "BTC perpetual funding positive for 14 consecutive sessions "
                    "with basis inside 0.3%; a delta-neutral carry should collect it."
                ),
                supporting_data={"funding_8h_bps": 12.4, "sessions": 14},
                counter_argument=(
                    "Funding flipped negative within two sessions three times "
                    "last year; the hedge would then cost more than it earns."
                ),
                invalidation="Funding negative for two consecutive sessions.",
                exit_plan="Unwind both legs together if invalidated or after 30 days.",
                expected_edge_bps=45.0,
            ),
        )
        print(f"\n  Position #{pid} opened, with its hypothesis on the record.")

        try:
            journal.revise_hypothesis(pid, "I always knew this would work")
        except Exception as exc:
            print(f"  Rewriting it after the fact -> refused:")
            print(f"    {type(exc).__name__}: {str(exc).splitlines()[0]}")

        # A trade that made money for a reason other than the stated one.
        journal.close_position(
            pid,
            PostMortem(
                exit_price=Decimal("101000"),
                realized_pnl=Decimal("50"),
                hypothesis_verified=False,
                what_actually_happened=(
                    "Funding turned negative on day 3. The position finished "
                    "up only because spot rallied while the hedge lagged."
                ),
                slippage_bps=3.2,
                lesson="Profitable, but not for the stated reason. Do not repeat.",
            ),
        )

        summary = journal.attribution_summary()
        print(f"\n  Closed profitably (+50), hypothesis NOT verified.")
        print(f"  Attribution: {summary}")
        print("\n  Booked as 'lucky', not 'skilled'. A P&L column alone would")
        print("  have recorded this as a win and invited a repeat.")


if __name__ == "__main__":
    demo_validation()
    demo_real_edge()
    demo_governor()
    demo_journal()
    print(f"\n{RULE}\nGate 0: noise is rejected, a real edge is not.\n{RULE}\n")
