"""Probability of Backtest Overfitting, via Combinatorially Symmetric CV.

Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest
Overfitting" (2015).

The question it answers is narrower and more useful than "is this strategy
good": *if I pick the best variant in-sample, how often does it land in the
bottom half out-of-sample?* A skill-free selection process scores 0.5. Above
that means the selection is worse than a coin flip -- overfitted strategies
systematically underperform rather than merely reverting to average, which is
why a high PBO is a reason to discard the whole search, not to retune it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations

import numpy as np


@dataclass(frozen=True)
class PBOResult:
    pbo: float
    """Fraction of splits where the in-sample winner was below the
    out-of-sample median. 0.5 is the skill-free baseline."""

    logits: np.ndarray
    """Per-split logit of the winner's out-of-sample rank. Its distribution
    is more informative than the headline number: a tight cluster just below
    zero is a different failure from a bimodal spread."""

    n_splits: int
    median_oos_rank: float
    """Median relative rank of the in-sample winner, in (0, 1). 0.5 is
    skill-free, above 0.5 indicates the selection carried real information."""

    @property
    def is_overfit(self) -> bool:
        """Whether the selection process performed no better than chance."""
        return self.pbo >= 0.5


def _sharpe(block: np.ndarray) -> np.ndarray:
    """Per-observation Sharpe down each column, with zero-variance columns
    scored as zero rather than as infinite skill."""
    mean = block.mean(axis=0)
    sd = block.std(axis=0, ddof=0)
    return np.divide(mean, sd, out=np.zeros_like(mean), where=sd > 0)


def probability_of_backtest_overfitting(
    returns: np.ndarray,
    n_splits: int = 16,
    performance=_sharpe,
) -> PBOResult:
    """Run CSCV over a (T observations x N strategies) return matrix.

    `n_splits` must be even: the method works by splitting the timeline into S
    equal blocks and forming every way of choosing S/2 of them as training,
    with the complement as testing. That symmetry is what makes the result
    unbiased. S=16 gives 12870 combinations, which is the usual choice.
    """
    m = np.asarray(returns, dtype=float)
    if m.ndim != 2:
        raise ValueError("returns must be a 2-D (observations x strategies) matrix")
    if n_splits < 2 or n_splits % 2 != 0:
        raise ValueError("n_splits must be an even number >= 2")

    n_obs, n_strategies = m.shape
    if n_strategies < 2:
        raise ValueError("need at least 2 strategies to rank")
    if n_obs < n_splits:
        raise ValueError(
            f"need at least {n_splits} observations for {n_splits} splits"
        )

    # Trailing observations that do not divide evenly are dropped, so every
    # block carries the same weight.
    block_len = n_obs // n_splits
    usable = block_len * n_splits
    blocks = np.split(m[:usable], n_splits, axis=0)

    half = n_splits // 2
    logits = []

    for train_idx in combinations(range(n_splits), half):
        test_idx = tuple(i for i in range(n_splits) if i not in train_idx)

        train = np.concatenate([blocks[i] for i in train_idx], axis=0)
        test = np.concatenate([blocks[i] for i in test_idx], axis=0)

        winner = int(np.argmax(performance(train)))
        oos = performance(test)

        # Relative rank of the winner out-of-sample, in (0, 1). Dividing by
        # N+1 keeps the value off the endpoints so the logit stays finite.
        rank = float(np.sum(oos <= oos[winner]))
        omega = rank / (n_strategies + 1)
        logits.append(math.log(omega / (1.0 - omega)))

    arr = np.asarray(logits, dtype=float)
    return PBOResult(
        pbo=float(np.mean(arr < 0)),
        logits=arr,
        n_splits=len(arr),
        median_oos_rank=float(np.median(1.0 / (1.0 + np.exp(-arr)))),
    )
