"""Path model: convergence drift and multi-day MC sanity."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from aaa_pricer import fit_path_model, path_mcs  # noqa: E402


DELTAS = [0.5, -0.6, -0.7, 0.3, -0.5, -0.6, 0.2, -1.0, -0.5, 0.4] * 5


def test_drift_uses_convergence_only_when_gap_is_elevated():
    assert fit_path_model(DELTAS, None)["drift_c"] == fit_path_model(DELTAS, None)["emp_drift_c"]
    m = fit_path_model(DELTAS, excess_gap_cents=46.7)
    assert m["drift_c"] == -min(2.2, 0.03 * 46.7)  # convergence rate, negative
    # small gap -> no convergence override
    m2 = fit_path_model(DELTAS, excess_gap_cents=3.0)
    assert m2["drift_c"] == m2["emp_drift_c"]


def test_mc_deterministic_and_centered_on_drift():
    m = fit_path_model(DELTAS, excess_gap_cents=46.7)
    a = path_mcs(m, 4, seed=3)
    b = path_mcs(m, 4, seed=3)
    assert np.array_equal(a, b)
    # mean 4-day cumulative move ~= 4 * drift, within sampling noise
    assert abs(a[:, -1].mean() - 4 * m["drift_c"]) < 1.0
