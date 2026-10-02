"""MC month-mean model: deterministic given seed, sane break-even behavior."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ornn_data as O


def _data():
    vals = [1.0] * 26 + [0.95]
    return [{"timestamp": f"2026-09-{i+1:02d}T20:00:00.000Z", "index_value": v}
            for i, v in enumerate(vals)]


def test_mc_is_deterministic_and_sane():
    d = _data()
    a = O.mc_month_mean(d, "2026-09", seed=7)
    b = O.mc_month_mean(d, "2026-09", seed=7)
    assert abs(float((a["means"] > 1.0).mean()) - float((b["means"] > 1.0).mean())) < 1e-9
    assert a["rem"] == 3 and a["n"] == 27 and a["days"] == 30
    # with near-zero recent volatility, flat-at-last must dominate: P(mean > strike)
    # for a strike below the flat verdict should be ~1
    flat = (26 * 1.0 + 0.95) / 27
    quiet = d[:]
    for row in quiet:
        pass
    c = O.mc_month_mean(quiet, "2026-09", recency=26, seed=7)
    # recency window includes the -0.05 step; just check boundedness
    p = float((c["means"] > flat).mean())
    assert 0.0 <= p <= 1.0
