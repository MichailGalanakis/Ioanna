"""Unit tests for the validation maths."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ioanna.validation import (
    CombinatorialPurgedCV,
    Trial,
    TrialRegistry,
    annualize,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    min_track_record_length,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_stats,
)


# -- sharpe_stats -----------------------------------------------------------


def test_sharpe_of_known_series() -> None:
    r = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
    st = sharpe_stats(r)
    assert st.sharpe == pytest.approx(np.mean(r) / np.std(r, ddof=0))
    assert st.n_observations == 5


def test_normal_returns_have_kurtosis_near_three() -> None:
    """Kurtosis is non-excess, so a normal sample sits near 3, not near 0."""
    rng = np.random.default_rng(0)
    st = sharpe_stats(rng.normal(0, 0.01, 20000))
    assert st.kurtosis == pytest.approx(3.0, abs=0.15)
    assert st.skew == pytest.approx(0.0, abs=0.1)


def test_constant_returns_are_rejected() -> None:
    with pytest.raises(ValueError, match="zero variance"):
        sharpe_stats(np.full(50, 0.01))


def test_too_few_observations_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least 3"):
        sharpe_stats(np.array([0.01, 0.02]))


def test_annualize_scales_by_root_periods() -> None:
    assert annualize(0.1, 252) == pytest.approx(0.1 * math.sqrt(252))
    with pytest.raises(ValueError):
        annualize(0.1, 0)


# -- probabilistic Sharpe ---------------------------------------------------


def test_psr_rises_with_track_record_length() -> None:
    """The same Sharpe means more when observed for longer."""
    rng = np.random.default_rng(1)
    base = rng.normal(0.0005, 0.01, 5000)
    short = probabilistic_sharpe_ratio(sharpe_stats(base[:100]))
    long = probabilistic_sharpe_ratio(sharpe_stats(base))
    assert long > short


def test_psr_is_a_probability() -> None:
    rng = np.random.default_rng(2)
    for mu in (-0.001, 0.0, 0.001):
        p = probabilistic_sharpe_ratio(sharpe_stats(rng.normal(mu, 0.01, 500)))
        assert 0.0 <= p <= 1.0


def test_psr_penalises_negative_skew() -> None:
    """Small steady gains with rare large losses -- the shape of a strategy
    quietly selling tail risk -- should score below a symmetric one."""
    rng = np.random.default_rng(3)
    n = 2000
    symmetric = rng.normal(0.0005, 0.01, n)

    skewed = np.full(n, 0.0015)
    skewed[:: 50] = -0.06  # occasional large loss
    skewed = skewed + rng.normal(0, 0.001, n)

    st_sym, st_skew = sharpe_stats(symmetric), sharpe_stats(skewed)
    # Comparable raw Sharpe, but the skewed one is penalised.
    assert st_skew.skew < -1.0
    assert probabilistic_sharpe_ratio(st_skew) < probabilistic_sharpe_ratio(st_sym)


# -- expected maximum Sharpe ------------------------------------------------


def test_single_trial_has_no_selection_bias() -> None:
    assert expected_max_sharpe(1, 0.01) == 0.0


def test_expected_max_grows_with_trial_count() -> None:
    v = 0.001
    values = [expected_max_sharpe(n, v) for n in (2, 10, 100, 1000, 10000)]
    assert values == sorted(values)
    assert all(x > 0 for x in values)


def test_expected_max_grows_with_dispersion() -> None:
    assert expected_max_sharpe(100, 0.004) > expected_max_sharpe(100, 0.001)


def test_zero_dispersion_gives_zero_threshold() -> None:
    """If every variant scored identically, nothing was selected."""
    assert expected_max_sharpe(100, 0.0) == 0.0


@pytest.mark.parametrize("n,v", [(0, 0.01), (-1, 0.01), (10, -0.01)])
def test_expected_max_rejects_bad_arguments(n, v) -> None:
    with pytest.raises(ValueError):
        expected_max_sharpe(n, v)


# -- deflated Sharpe --------------------------------------------------------


def test_deflation_is_monotone_in_trial_count() -> None:
    """More variants searched, less credit for the winner."""
    rng = np.random.default_rng(4)
    st = sharpe_stats(rng.normal(0.001, 0.01, 1000))
    v = 0.001
    scores = [deflated_sharpe_ratio(st, n, v) for n in (1, 10, 100, 1000)]
    assert scores == sorted(scores, reverse=True)


def test_deflation_with_one_trial_equals_psr() -> None:
    rng = np.random.default_rng(5)
    st = sharpe_stats(rng.normal(0.001, 0.01, 500))
    assert deflated_sharpe_ratio(st, 1, 0.001) == pytest.approx(
        probabilistic_sharpe_ratio(st)
    )


# -- minimum track record length -------------------------------------------


def test_mtrl_is_infinite_when_sharpe_is_below_benchmark() -> None:
    rng = np.random.default_rng(6)
    st = sharpe_stats(rng.normal(-0.001, 0.01, 500))
    assert min_track_record_length(st) == math.inf


def test_mtrl_shrinks_as_sharpe_grows() -> None:
    rng = np.random.default_rng(7)
    weak = sharpe_stats(rng.normal(0.0002, 0.01, 2000))
    strong = sharpe_stats(rng.normal(0.003, 0.01, 2000))
    assert min_track_record_length(strong) < min_track_record_length(weak)


def test_mtrl_rejects_bad_confidence() -> None:
    rng = np.random.default_rng(8)
    st = sharpe_stats(rng.normal(0.001, 0.01, 500))
    with pytest.raises(ValueError):
        min_track_record_length(st, confidence=1.5)


# -- PBO --------------------------------------------------------------------


def test_pbo_requires_even_splits() -> None:
    rng = np.random.default_rng(9)
    with pytest.raises(ValueError, match="even"):
        probability_of_backtest_overfitting(rng.normal(size=(200, 5)), n_splits=7)


def test_pbo_requires_multiple_strategies() -> None:
    rng = np.random.default_rng(10)
    with pytest.raises(ValueError, match="at least 2 strategies"):
        probability_of_backtest_overfitting(rng.normal(size=(200, 1)))


def test_pbo_requires_enough_observations() -> None:
    rng = np.random.default_rng(11)
    with pytest.raises(ValueError, match="at least"):
        probability_of_backtest_overfitting(rng.normal(size=(4, 5)), n_splits=8)


def test_pbo_split_count_is_combinatorial() -> None:
    """S=8 choosing 4 gives C(8,4)=70 paths, not 8."""
    rng = np.random.default_rng(12)
    res = probability_of_backtest_overfitting(
        rng.normal(size=(400, 10)), n_splits=8
    )
    assert res.n_splits == 70


def test_pbo_is_a_probability() -> None:
    rng = np.random.default_rng(13)
    res = probability_of_backtest_overfitting(rng.normal(size=(400, 10)), n_splits=8)
    assert 0.0 <= res.pbo <= 1.0
    assert 0.0 <= res.median_oos_rank <= 1.0


# -- CPCV -------------------------------------------------------------------


def test_cpcv_generates_all_combinations() -> None:
    cv = CombinatorialPurgedCV(n_groups=6, n_test_groups=2)
    assert cv.n_splits() == 15
    assert len(list(cv.split(600))) == 15


def test_cpcv_train_and_test_never_overlap() -> None:
    cv = CombinatorialPurgedCV(n_groups=5, n_test_groups=2, embargo=0.02)
    label_end = np.arange(500) + 3
    for split in cv.split(500, label_end):
        assert set(split.train).isdisjoint(set(split.test))


def test_cpcv_purges_labels_spanning_the_boundary() -> None:
    """A training label that resolves inside the test window is leakage."""
    n, horizon = 400, 10
    label_end = np.minimum(np.arange(n) + horizon, n - 1)
    cv = CombinatorialPurgedCV(n_groups=4, n_test_groups=1, embargo=0.0)

    for split in cv.split(n, label_end):
        test_set = set(split.test.tolist())
        for i in split.train:
            spanned = set(range(int(i), int(label_end[i]) + 1))
            assert not (spanned & test_set), f"sample {i} leaks into test"


def test_cpcv_embargo_removes_samples_after_the_test_block() -> None:
    n = 400
    no_embargo = CombinatorialPurgedCV(4, 1, embargo=0.0)
    with_embargo = CombinatorialPurgedCV(4, 1, embargo=0.05)

    a = next(iter(no_embargo.split(n)))
    b = next(iter(with_embargo.split(n)))
    assert len(b.train) < len(a.train)
    assert b.n_purged > a.n_purged


def test_cpcv_without_label_end_still_separates() -> None:
    cv = CombinatorialPurgedCV(4, 1, embargo=0.0)
    for split in cv.split(200):
        assert set(split.train).isdisjoint(set(split.test))
        assert len(split.train) + len(split.test) == 200  # nothing to purge


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_groups": 1},
        {"n_groups": 4, "n_test_groups": 0},
        {"n_groups": 4, "n_test_groups": 4},
        {"n_groups": 4, "embargo": 1.0},
        {"n_groups": 4, "embargo": -0.1},
    ],
)
def test_cpcv_rejects_bad_configuration(kwargs) -> None:
    with pytest.raises(ValueError):
        CombinatorialPurgedCV(**kwargs)


def test_cpcv_rejects_labels_ending_before_their_observation() -> None:
    cv = CombinatorialPurgedCV(4, 1)
    with pytest.raises(ValueError, match="cannot precede"):
        list(cv.split(100, np.arange(100) - 5))


def test_cpcv_rejects_mismatched_label_length() -> None:
    cv = CombinatorialPurgedCV(4, 1)
    with pytest.raises(ValueError, match="one entry per sample"):
        list(cv.split(100, np.arange(50)))


# -- trial registry ---------------------------------------------------------


def _trial(family: str, seed: int, mu: float = 0.0) -> Trial:
    rng = np.random.default_rng(seed)
    return Trial(
        family=family,
        params={"lookback": seed, "threshold": 0.5},
        stats=sharpe_stats(rng.normal(mu, 0.01, 500)),
    )


def test_registry_counts_trials() -> None:
    with TrialRegistry() as reg:
        for i in range(10):
            reg.record(_trial("funding_arb", i))
        assert reg.n_trials("funding_arb") == 10
        assert reg.n_trials() == 10


def test_registry_scopes_counts_by_family() -> None:
    with TrialRegistry() as reg:
        for i in range(5):
            reg.record(_trial("funding_arb", i))
        for i in range(3):
            reg.record(_trial("momentum", i))
        assert reg.n_trials("funding_arb") == 5
        assert reg.n_trials("momentum") == 3
        assert reg.n_trials() == 8


def test_registry_deduplicates_identical_params() -> None:
    """Re-running a variant must not inflate the trial count."""
    with TrialRegistry() as reg:
        first = reg.record(_trial("funding_arb", 1))
        second = reg.record(_trial("funding_arb", 1))
        assert first == second
        assert reg.n_trials("funding_arb") == 1


def test_registry_reports_best_trial() -> None:
    with TrialRegistry() as reg:
        for i in range(8):
            reg.record(_trial("funding_arb", i))
        best = reg.best("funding_arb")
        assert best is not None
        assert best["sharpe"] == pytest.approx(max(reg.sharpes("funding_arb")))


def test_registry_best_is_none_when_empty() -> None:
    with TrialRegistry() as reg:
        assert reg.best("nothing") is None


def test_registry_variance_needs_two_trials() -> None:
    with TrialRegistry() as reg:
        reg.record(_trial("funding_arb", 1))
        assert reg.sharpe_variance("funding_arb") == 0.0


def test_registry_refuses_to_deflate_against_nothing() -> None:
    """Deflating with an empty registry would report the raw Sharpe."""
    with TrialRegistry() as reg:
        st = _trial("funding_arb", 1).stats
        with pytest.raises(ValueError, match="no trials recorded"):
            reg.deflated_sharpe(st, "never_searched")


def test_registry_deflation_tightens_as_search_widens() -> None:
    rng = np.random.default_rng(99)
    candidate = sharpe_stats(rng.normal(0.0015, 0.01, 1000))

    with TrialRegistry() as narrow, TrialRegistry() as wide:
        for i in range(5):
            narrow.record(_trial("f", i))
        for i in range(500):
            wide.record(_trial("f", i))
        assert wide.deflated_sharpe(candidate, "f") < narrow.deflated_sharpe(
            candidate, "f"
        )


def test_registry_persists_to_disk(tmp_path) -> None:
    path = tmp_path / "trials.db"
    with TrialRegistry(path) as reg:
        for i in range(4):
            reg.record(_trial("funding_arb", i))
    with TrialRegistry(path) as reopened:
        assert reopened.n_trials("funding_arb") == 4


def test_registry_has_no_delete_method() -> None:
    """Pruning the registry is how trial counts get understated."""
    assert not any(
        hasattr(TrialRegistry, name)
        for name in ("delete", "remove", "clear", "prune", "drop")
    )
