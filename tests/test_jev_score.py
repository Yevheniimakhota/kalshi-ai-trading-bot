"""jev_score: settled-result extraction and entry resolution."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from jev_score import extract_settled, parse_strike, resolve_entry  # noqa: E402


def test_extract_settled_keeps_yes_no_only():
    mks = [
        {"ticker": "KXRT-VER-90", "result": "yes", "strike": 90.0},
        {"ticker": "KXRT-VER-70", "result": "no", "strike": 70.0},
        {"ticker": "KXRT-VER-50", "result": "", "strike": 50.0},
    ]
    out = extract_settled(mks)
    assert out["KXRT-VER-90"]["result"] == "yes"
    assert out["KXRT-VER-70"]["result"] == "no"
    assert "KXRT-VER-50" not in out


def test_parse_strike_t_and_plain():
    assert parse_strike("KXDIESELD-26SEP27-T6.480") == 6.48
    assert parse_strike("KXRT-VER-90") == 90.0


def test_resolve_entry_exact_and_bracket():
    by_series = {"KXRT": {"KXRT-VER-70": {"result": "yes", "strike": 70.0},
                          "KXRT-VER-90": {"result": "no", "strike": 90.0}}}
    e = {"ticker": "KXRT-VER-70"}
    assert resolve_entry(e, by_series)["result"] == "yes"
    # exact ticker missing but bracket resolvable: entry strike <= lo -> yes
    e2 = {"ticker": "KXRT-VER-80"}
    res = resolve_entry(e2, by_series)
    assert res["result"] == "bracket" and res["lo"] == 70.0 and res["hi"] == 90.0
    # a strike OUTSIDE the settled bracket is still resolvable: 999 > realized
    # (70, 90] -> the entry's YES is false; scoring turns that into y=0
    res999 = resolve_entry({"ticker": "KXRT-VER-999"}, by_series)
    assert res999["result"] == "bracket" and res999["strike"] == 999.0
