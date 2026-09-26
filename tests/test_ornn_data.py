"""Ornn OCPI: month stats and strike break-even math."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import ornn_data  # noqa: E402


def _stub(monkeypatch, vals, days=30):
    data = [{"timestamp": f"2026-09-{i + 1:02d}T20:00:00.000Z", "index_value": v}
            for i, v in enumerate(vals)]
    monkeypatch.setattr(ornn_data, "load", lambda gpu: data)
    monkeypatch.setattr(ornn_data, "dt", ornn_data.dt)


def test_month_stats_counts_remaining_prints(monkeypatch):
    _stub(monkeypatch, [1.0] * 26, days=30)
    st = ornn_data.month_stats("A100 SXM4", "2026-09")
    assert st["n"] == 26
    assert st["days_in_month"] == 30
    assert st["remaining"] == 4
    assert st["mean_so_far"] == pytest.approx(1.0)
    assert st["last"] == 1.0


def test_strike_breakeven_matches_hand_math(monkeypatch):
    _stub(monkeypatch, [1.0142] * 26 + [0.95])
    st = ornn_data.month_stats("A100 SXM4", "2026-09")
    assert st["n"] == 27 and st["remaining"] == 3
    be = ornn_data.strike_breakeven(st, 1.00)
    mean27 = (26 * 1.0142 + 0.95) / 27
    need = (30 * 1.00 - 27 * mean27) / 3
    assert be["remaining_prints_must_avg_below"] == pytest.approx(need, abs=1e-3)
    # the remaining prints flat at the last print keep the mean above the strike
    assert be["verdict_if_flat_at_last"] == pytest.approx((27 * mean27 + 3 * 0.95) / 30, abs=1e-4)
    assert be["verdict_if_flat_at_last"] > 1.00


def test_full_month_no_remaining(monkeypatch):
    _stub(monkeypatch, [0.8] * 30, days=30)
    st = ornn_data.month_stats("A100 SXM4", "2026-09")
    assert st["remaining"] == 0
    be = ornn_data.strike_breakeven(st, 1.00)
    assert be["remaining_prints_must_avg_below"] != be["remaining_prints_must_avg_below"]  # nan
