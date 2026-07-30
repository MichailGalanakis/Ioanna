"""Tools for telling a real edge from a lucky search.

Gate 0 for this package: fed pure noise, every metric here must report
"nothing found". A validation module that certifies random data is worse than
no validation module, because it launders the search that produced it.
See tests/test_noise_gate.py.
"""

from .cpcv import CombinatorialPurgedCV, Split
from .pbo import PBOResult, probability_of_backtest_overfitting
from .registry import Trial, TrialRegistry
from .sharpe import (
    SharpeStats,
    annualize,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    min_track_record_length,
    probabilistic_sharpe_ratio,
    sharpe_stats,
)

__all__ = [
    "CombinatorialPurgedCV",
    "PBOResult",
    "SharpeStats",
    "Split",
    "Trial",
    "TrialRegistry",
    "annualize",
    "deflated_sharpe_ratio",
    "expected_max_sharpe",
    "min_track_record_length",
    "probabilistic_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "sharpe_stats",
]
