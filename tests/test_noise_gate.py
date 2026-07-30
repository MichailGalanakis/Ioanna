"""Gate 0: the validation module must find nothing in pure noise.

Everything downstream rests on this. If these metrics certify random data,
then the first time a backtest looks good we will have no way to tell whether
we found an edge or found the tool's blind spot -- and we will believe the
backtest, because by then real money will be waiting on it.

The tests below are written the way the gate is stated in
research/05-roadmap.md: feed known-worthless data, require the honest verdict.
Seeds are fixed so a failure means the maths changed, not that the dice moved.
"""

from __future__ import annotations

import numpy as np
import pytest

from ioanna.validation import (
    Trial,
    TrialRegistry,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_stats,
)

N_OBS = 1000
N_STRATEGIES = 100
DAILY_VOL = 0.01
TRADING_DAYS = 252


def noise_matrix(seed: int, n_obs=N_OBS, n_strategies=N_STRATEGIES) -> np.ndarray:
    """Skill-free strategies: zero mean, no edge, nothing to find."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, DAILY_VOL, size=(n_obs, n_strategies))


def best_of(matrix: np.ndarray) -> tuple[int, float]:
    sharpes = matrix.mean(axis=0) / matrix.std(axis=0, ddof=0)
    return int(np.argmax(sharpes)), float(np.var(sharpes, ddof=1))


# -- the headline result ----------------------------------------------------


def test_best_of_pure_noise_looks_impressive_raw() -> None:
    """Establishes the danger the rest of the gate exists to catch.

    Picking the best of 100 worthless strategies produces an annualized Sharpe
    above 1.0 -- a number most people would deploy capital against.
    """
    m = noise_matrix(42)
    winner, _ = best_of(m)
    st = sharpe_stats(m[:, winner])
    assert st.annualized(TRADING_DAYS) > 1.0


def test_raw_confidence_is_dangerously_high_on_noise() -> None:
    """PSR against a zero benchmark is ~0.99 for the same worthless strategy.

    This is why PSR alone is not the gate: it answers "is this better than
    nothing", which is the wrong question once you have gone looking.
    """
    m = noise_matrix(42)
    winner, _ = best_of(m)
    assert probabilistic_sharpe_ratio(sharpe_stats(m[:, winner])) > 0.95


def test_deflated_sharpe_rejects_the_same_strategy() -> None:
    """The whole point: same returns, correct question, honest answer."""
    m = noise_matrix(42)
    winner, variance = best_of(m)
    dsr = deflated_sharpe_ratio(sharpe_stats(m[:, winner]), N_STRATEGIES, variance)
    assert dsr < 0.95, f"DSR {dsr:.3f} would have passed noise as a real edge"


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 123, 999, 31337])
def test_deflation_holds_across_seeds(seed: int) -> None:
    """Not a fluke of one draw. No seed may sneak noise past the threshold."""
    m = noise_matrix(seed)
    winner, variance = best_of(m)
    dsr = deflated_sharpe_ratio(sharpe_stats(m[:, winner]), N_STRATEGIES, variance)
    assert dsr < 0.95, f"seed {seed}: DSR {dsr:.3f}"


@pytest.mark.parametrize("n_strategies", [10, 50, 100, 500])
def test_deflation_holds_across_search_widths(n_strategies: int) -> None:
    """Whether we tried 10 variants or 500, noise stays noise."""
    m = noise_matrix(2024, n_strategies=n_strategies)
    winner, variance = best_of(m)
    dsr = deflated_sharpe_ratio(sharpe_stats(m[:, winner]), n_strategies, variance)
    assert dsr < 0.95, f"N={n_strategies}: DSR {dsr:.3f}"


# -- PBO on noise -----------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 42, 999, 31337])
def test_pbo_never_certifies_noise_as_clean(seed: int) -> None:
    """The asymmetric half of the PBO gate, and the half that matters.

    A high PBO on noise is the correct answer -- it says "this selection was
    overfitted", which is true. A *low* PBO on noise would be the dangerous
    failure: the estimator claiming the choice generalised when there was
    nothing to generalise. Only the floor is a real assertion here.
    """
    res = probability_of_backtest_overfitting(noise_matrix(seed), n_splits=8)
    assert res.pbo > 0.15, f"seed {seed}: PBO {res.pbo:.3f} passed noise as clean"


def test_pbo_on_noise_averages_near_one_half() -> None:
    """Centred on the coin-flip baseline, measured across seeds.

    A single PBO run is noisy -- the C(8,4)=70 paths overlap heavily, so the
    effective sample size is far below 70 and individual runs range roughly
    0.2 to 0.85 on identical inputs. That is a property of the estimator, not
    of the data, and it is the reason a live PBO reading should be treated as
    a band rather than a number.
    """
    values = np.array(
        [
            probability_of_backtest_overfitting(noise_matrix(s), n_splits=8).pbo
            for s in range(30)
        ]
    )
    assert 0.35 <= values.mean() <= 0.65, f"mean PBO on noise {values.mean():.3f}"


def test_pbo_median_rank_on_noise_is_near_one_half() -> None:
    res = probability_of_backtest_overfitting(noise_matrix(42), n_splits=8)
    assert 0.35 <= res.median_oos_rank <= 0.65


# -- the other direction: a real edge must still be found ------------------

def test_a_genuine_edge_is_not_deflated_away() -> None:
    """The gate must not be so strict that nothing ever passes.

    A strategy with real, persistent drift should survive deflation against
    the same 50-variant search that flattens noise.
    """
    rng = np.random.default_rng(7)
    m = rng.normal(0.0, DAILY_VOL, size=(N_OBS, 50))
    m[:, 17] += 0.004  # unambiguous edge

    winner, variance = best_of(m)
    assert winner == 17, "the search should find the strategy with real drift"

    dsr = deflated_sharpe_ratio(sharpe_stats(m[:, winner]), 50, variance)
    assert dsr > 0.95, f"real edge was deflated away: DSR {dsr:.3f}"


def test_pbo_falls_when_the_edge_is_real() -> None:
    rng = np.random.default_rng(7)
    m = rng.normal(0.0, DAILY_VOL, size=(N_OBS, 50))
    m[:, 17] += 0.004

    res = probability_of_backtest_overfitting(m, n_splits=8)
    assert res.pbo < 0.1, f"PBO {res.pbo:.3f} should be near zero for a real edge"
    assert res.median_oos_rank > 0.9


# -- the registry closes the loop ------------------------------------------


def test_registry_deflation_catches_a_realistic_search() -> None:
    """End to end, the way it will actually be used.

    Sweep 200 variants over worthless data, record every one, keep the best,
    and ask the registry what it is worth. The answer must be "nothing" --
    and it must come out without anyone having to remember that 200 variants
    were tried, because the registry counted them.
    """
    m = noise_matrix(1234, n_strategies=200)

    with TrialRegistry() as reg:
        for i in range(m.shape[1]):
            reg.record(
                Trial(
                    family="noise_sweep",
                    params={"variant": i},
                    stats=sharpe_stats(m[:, i]),
                )
            )

        assert reg.n_trials("noise_sweep") == 200

        best = reg.best("noise_sweep")
        assert best is not None
        winner = int(np.argmax(m.mean(axis=0) / m.std(axis=0, ddof=0)))
        candidate = sharpe_stats(m[:, winner])

        # Raw, this is the number that would get quoted in a status update.
        assert candidate.annualized(TRADING_DAYS) > 1.0

        # Deflated against the search that produced it, it is worth nothing.
        dsr = reg.deflated_sharpe(candidate, "noise_sweep")
        assert dsr < 0.95, f"registry-deflated DSR {dsr:.3f} passed a noise sweep"
