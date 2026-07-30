"""Probabilistic and Deflated Sharpe Ratio.

Bailey & López de Prado, "The Deflated Sharpe Ratio: Correcting for Selection
Bias, Backtest Overfitting, and Non-Normality" (2014).

The problem being solved: if you try N strategy variants and keep the best
one, its Sharpe ratio is the maximum of N draws, not a sample of one. Even
with no skill at all that maximum is comfortably above zero, and it grows with
N. Reporting it as though a single strategy had been tested is the single most
common way a backtest lies.

All Sharpe ratios here are *per observation*, not annualized. Annualizing
before deflating would inflate the result -- see `annualize` for the one place
scaling is allowed, which is display.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

#: Euler-Mascheroni constant, from the expected-maximum expression in the paper.
EULER_MASCHERONI = 0.5772156649015329


@dataclass(frozen=True)
class SharpeStats:
    """Everything needed to deflate a Sharpe ratio, computed from returns."""

    sharpe: float  # per observation
    n_observations: int
    skew: float
    kurtosis: float  # non-excess: 3.0 for a normal distribution

    def annualized(self, periods_per_year: int) -> float:
        return annualize(self.sharpe, periods_per_year)


def annualize(sharpe: float, periods_per_year: int) -> float:
    """Scale a per-observation Sharpe to annual terms, for display only.

    Note this assumes independent returns. Serial correlation makes it
    optimistic -- inflation of over 65% has been documented -- so an
    annualized figure is a headline number, never an input to a decision.
    """
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    return sharpe * math.sqrt(periods_per_year)


def sharpe_stats(returns: np.ndarray, risk_free: float = 0.0) -> SharpeStats:
    """Observed Sharpe plus the higher moments the deflation needs.

    Uses the population standard deviation (ddof=0) to match the paper.
    """
    r = np.asarray(returns, dtype=float).ravel()
    if r.size < 3:
        raise ValueError("need at least 3 observations")

    excess = r - risk_free
    sd = float(np.std(excess, ddof=0))
    if sd == 0.0:
        raise ValueError("returns have zero variance; Sharpe is undefined")

    return SharpeStats(
        sharpe=float(np.mean(excess)) / sd,
        n_observations=int(r.size),
        skew=float(stats.skew(r, bias=True)),
        kurtosis=float(stats.kurtosis(r, fisher=False, bias=True)),
    )


def probabilistic_sharpe_ratio(stats_: SharpeStats, benchmark: float = 0.0) -> float:
    """P(true Sharpe > benchmark), given the observed Sharpe and its moments.

    The denominator is where non-normality enters: negative skew and fat tails
    both widen the estimator's standard error, which is the statistical form of
    the intuition that a strategy quietly selling tail risk deserves less
    credit than its track record suggests.
    """
    if stats_.n_observations < 2:
        raise ValueError("need at least 2 observations")

    sr = stats_.sharpe
    variance = 1.0 - stats_.skew * sr + ((stats_.kurtosis - 1.0) / 4.0) * sr**2

    # The expression can go negative for extreme moment combinations, at which
    # point the asymptotic approximation has broken down and there is no
    # meaningful probability to report.
    if variance <= 0:
        raise ValueError(
            "Sharpe estimator variance is non-positive; the approximation does "
            "not hold for these moments"
        )

    z = (sr - benchmark) * math.sqrt(stats_.n_observations - 1) / math.sqrt(variance)
    return float(stats.norm.cdf(z))


def expected_max_sharpe(n_trials: int, variance_across_trials: float) -> float:
    """Expected maximum Sharpe from `n_trials` skill-free variants.

    This is the benchmark a strategy has to beat to have shown anything. It
    rises with both the number of trials and how much the trials differ from
    each other, which is why the trial registry has to record every variant --
    including the ones abandoned halfway through.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be at least 1")
    if variance_across_trials < 0:
        raise ValueError("variance_across_trials must be non-negative")
    if n_trials == 1:
        # Nothing was selected, so there is no selection bias to correct.
        return 0.0

    sd = math.sqrt(variance_across_trials)
    gamma = EULER_MASCHERONI
    q1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
    q2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return float(sd * ((1.0 - gamma) * q1 + gamma * q2))


def deflated_sharpe_ratio(
    stats_: SharpeStats,
    n_trials: int,
    variance_across_trials: float,
) -> float:
    """P(true Sharpe > what `n_trials` of pure luck would have produced).

    Read it as a confidence level, not a performance figure. Above ~0.95 means
    the track record is hard to explain by selection alone; around 0.5 means
    the result is exactly what trying that many variants produces by chance,
    however impressive the raw number looks.
    """
    threshold = expected_max_sharpe(n_trials, variance_across_trials)
    return probabilistic_sharpe_ratio(stats_, benchmark=threshold)


def min_track_record_length(
    stats_: SharpeStats,
    benchmark: float = 0.0,
    confidence: float = 0.95,
) -> float:
    """Observations needed before the Sharpe could clear `benchmark`.

    Answers "is this track record simply too short to mean anything yet",
    which is usually the honest verdict on a promising three-month result.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if stats_.sharpe <= benchmark:
        return math.inf

    sr = stats_.sharpe
    variance = 1.0 - stats_.skew * sr + ((stats_.kurtosis - 1.0) / 4.0) * sr**2
    if variance <= 0:
        raise ValueError("Sharpe estimator variance is non-positive")

    z = stats.norm.ppf(confidence)
    return float(1.0 + variance * (z / (sr - benchmark)) ** 2)
