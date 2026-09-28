"""Path + convergence drift + transfer model: pure-function tests."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aaa_pricer import (convergence_drift_c, fit_path_model, path_mcs,  # noqa: E402
                        sample_blend, transfer_fair_yes, fit_model,
                        CONV_INTERCEPT_C, CONV_SLOPE_PER_CENT)

DELTAS = [0.5, -0.6, -0.7, 0.3, -0.5, -0.6, 0.2, -1.0, -0.5, 0.4] * 5


def test_convergence_drift_regression():
    # documented regression: delta_next = 0.574 - 0.0298 * excess
    assert convergence_drift_c(None) is None
    assert convergence_drift_c(3.0) is None          # below apply threshold
    d = convergence_drift_c(46.7)
    assert abs(d - (CONV_INTERCEPT_C - CONV_SLOPE_PER_CENT * 46.7)) < 1e-9
    # more excess gap -> more negative drift
    assert convergence_drift_c(80.0) < convergence_drift_c(40.0) < 0
    # sanity at the 2026-09-28 live value (~57c): about -1.1c/day
    assert -1.4 < convergence_drift_c(56.6) < -0.9


def test_path_mc_gap_aware_and_deterministic():
    m = fit_path_model(DELTAS, excess_gap_cents=46.7)
    a = path_mcs(m, 4, seed=3)
    b = path_mcs(m, 4, seed=3)
    assert np.array_equal(a, b)
    emp = m["emp_drift_c"]
    # day-1 mean shifts by (drift(gap) - emp)
    d1 = convergence_drift_c(46.7)
    assert abs(a[:, 0].mean() - d1) < 0.5
    # later days converge slightly slower (decaying gap) -> day-4 daily mean
    # is LESS negative than day-1
    daily = np.diff(a, axis=1, prepend=np.zeros((a.shape[0], 1)))
    assert daily[:, 3].mean() > daily[:, 0].mean() - 0.01


def test_path_mc_small_gap_is_pure_empirical():
    m = fit_path_model(DELTAS, excess_gap_cents=3.0)
    a = path_mcs(m, 4, seed=3)
    assert abs(a[:, -1].mean() - 4 * m["emp_drift_c"]) < 0.5


def test_sample_blend_inverts_the_cdf():
    model = fit_model(list(np.random.default_rng(0).normal(0, 1, 400)),
                      current_streak=0)
    rng = np.random.default_rng(1)
    s = sample_blend(model, 20000, rng)
    # empirical median of samples ~ the CDF's median
    from aaa_pricer import forecast_cdf
    med = float(np.median(s))
    assert abs(forecast_cdf(model, med) - 0.5) < 0.02
    assert abs(s.mean() - float(np.mean(model["uncond"]))) < 0.15


def test_transfer_fair_yes_monotonic_in_strike():
    rng = np.random.default_rng(0)
    nat = rng.normal(0, 1.5, 300)
    state = 0.8 * nat + rng.normal(0, 0.8, 300)
    import numpy.polynomial as P
    beta, alpha = np.polyfit(nat, state, 1)
    resid = state - (alpha + beta * nat)
    tm = {"kind": "transfer", "alpha": float(alpha), "beta": float(beta),
          "resid": resid, "n_common": 300, "corr": 0.8}
    nm = fit_model(list(nat), current_streak=2)
    cur = 4.30
    f1 = transfer_fair_yes(tm, nm, cur, 4.31)
    f2 = transfer_fair_yes(tm, nm, cur, 4.35)
    f3 = transfer_fair_yes(tm, nm, cur, 4.25)
    # f2 sits ~3.5 sd out: MC draws may not resolve it above 0
    assert 0 <= f2 < 0.05 < f1 <= f3 < 1
    # median strike ~ anchor + alpha + beta*median_nat_delta
    med_strike = cur + (alpha + beta * float(np.median(nat))) / 100.0
    fm = transfer_fair_yes(tm, nm, cur, med_strike)
    assert 0.3 < fm < 0.7


def test_transfer_fair_yes_drift_shift_moves_fair():
    rng = np.random.default_rng(0)
    nat = rng.normal(0, 1.5, 300)
    state = 0.8 * nat + rng.normal(0, 0.8, 300)
    beta, alpha = np.polyfit(nat, state, 1)
    resid = state - (alpha + beta * nat)
    tm = {"kind": "transfer", "alpha": float(alpha), "beta": float(beta),
          "resid": resid, "n_common": 300, "corr": 0.8}
    nm = fit_model(list(nat), current_streak=2)
    base = transfer_fair_yes(tm, nm, 4.30, 4.30)
    lower = transfer_fair_yes(tm, nm, 4.30, 4.30, drift_shift=-2.0)
    assert lower < base - 0.3
