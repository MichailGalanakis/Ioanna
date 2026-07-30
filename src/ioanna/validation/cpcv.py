"""Combinatorial Purged Cross-Validation.

López de Prado, "Advances in Financial Machine Learning" (2018), ch. 7 and 12.

Standard k-fold leaks in two ways on financial data. First, a label computed
over a window straddling the train/test boundary appears in both -- the model
is tested on information it was trained on. Second, serial correlation means
samples immediately after the test set still carry its information.

Purging removes the overlapping samples; embargo removes the ones just after.
The combinatorial part generates C(N, k) train/test paths instead of k, which
matters because a single walk-forward path gives one estimate of
out-of-sample performance and no idea of its variance. Comparative work finds
CPCV superior to k-fold, purged k-fold and walk-forward at resisting
overfitting.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterator

import numpy as np


@dataclass(frozen=True)
class Split:
    train: np.ndarray
    test: np.ndarray
    test_groups: tuple[int, ...]

    @property
    def n_purged(self) -> int:
        """Samples dropped from training by purge and embargo.

        Worth logging: if this is near zero the label spans are probably not
        being passed in, and the split is a plain k-fold wearing a costume.
        """
        return self._dropped

    _dropped: int = 0


class CombinatorialPurgedCV:
    """Generates purged, embargoed, combinatorial train/test splits.

    `label_end` is the crux. For each observation it gives the index at which
    that observation's label is finally known -- the exit bar of a trade, the
    end of a forward-return window. Leaving it at the default of `i` declares
    that every label resolves instantly, which is true for almost no realistic
    target.
    """

    def __init__(
        self,
        n_groups: int = 6,
        n_test_groups: int = 2,
        embargo: float = 0.01,
    ) -> None:
        if n_groups < 2:
            raise ValueError("n_groups must be at least 2")
        if not 1 <= n_test_groups < n_groups:
            raise ValueError("n_test_groups must be in [1, n_groups)")
        if not 0.0 <= embargo < 1.0:
            raise ValueError("embargo must be in [0, 1)")

        self.n_groups = n_groups
        self.n_test_groups = n_test_groups
        self.embargo = embargo

    def n_splits(self) -> int:
        from math import comb

        return comb(self.n_groups, self.n_test_groups)

    def split(
        self,
        n_samples: int,
        label_end: np.ndarray | None = None,
    ) -> Iterator[Split]:
        if n_samples < self.n_groups:
            raise ValueError(
                f"need at least {self.n_groups} samples for {self.n_groups} groups"
            )

        if label_end is None:
            label_end = np.arange(n_samples)
        else:
            label_end = np.asarray(label_end, dtype=int).ravel()
            if label_end.size != n_samples:
                raise ValueError("label_end must have one entry per sample")
            if np.any(label_end < np.arange(n_samples)):
                raise ValueError("label_end cannot precede the observation itself")

        groups = np.array_split(np.arange(n_samples), self.n_groups)
        embargo_len = int(n_samples * self.embargo)

        for test_groups in combinations(range(self.n_groups), self.n_test_groups):
            test = np.concatenate([groups[g] for g in test_groups])
            train = self._purge(n_samples, test, label_end, embargo_len)
            yield Split(
                train=train,
                test=np.sort(test),
                test_groups=test_groups,
                _dropped=n_samples - len(train) - len(test),
            )

    def _purge(
        self,
        n_samples: int,
        test: np.ndarray,
        label_end: np.ndarray,
        embargo_len: int,
    ) -> np.ndarray:
        keep = np.ones(n_samples, dtype=bool)
        keep[test] = False

        candidates = np.flatnonzero(keep)
        if candidates.size == 0:
            return candidates

        # Purge: drop any training sample whose label span [i, label_end[i]]
        # overlaps a test sample's span. Contiguous test runs are handled as
        # intervals so this stays linear in the number of runs rather than
        # quadratic in samples.
        for start, end in _contiguous_runs(np.sort(test)):
            test_span_end = int(label_end[start:end + 1].max())
            overlaps = (label_end[candidates] >= start) & (
                candidates <= test_span_end
            )
            keep[candidates[overlaps]] = False

            # Embargo: drop the samples immediately after the test block,
            # whose serial correlation with it survives purging.
            if embargo_len > 0:
                stop = min(n_samples, test_span_end + 1 + embargo_len)
                keep[test_span_end + 1:stop] = False

        return np.flatnonzero(keep)


def _contiguous_runs(sorted_idx: np.ndarray) -> list[tuple[int, int]]:
    """Collapse sorted indices into inclusive (start, end) runs."""
    if sorted_idx.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(sorted_idx) > 1)
    starts = np.concatenate([[0], breaks + 1])
    ends = np.concatenate([breaks, [sorted_idx.size - 1]])
    return [(int(sorted_idx[s]), int(sorted_idx[e])) for s, e in zip(starts, ends)]
