#!/usr/bin/env python3
"""Wholesale futures series (HO=F, RB=F, CL=F) for the AAA print model.

The AAA retail prints lag wholesale futures by several days (verified: the
Sept-2026 diesel spike unwound at ~2c/day for weeks after ULSD peaked). The
retail-minus-wholesale gap relative to its trailing baseline measures the
pending retail decline. This module caches daily Yahoo Finance bars under
data/aaa/futures/ so the pricer can report convergence diagnostics instead of
pretending retail history alone is enough (the 2026-09-26 lesson).

Usage:
  python scripts/aaa_futures.py fetch --symbols HO=F RB=F
  python scripts/aaa_futures.py gap --symbol HO=F --retail diesel
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import httpx
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FUT_DIR = REPO / "data" / "aaa" / "futures"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0"}

SYMBOLS = {"HO=F": "heating_oil", "RB=F": "rbob", "CL=F": "wti"}


def fetch_symbol(symbol: str, range_days: int = 730) -> list[dict]:
    r = httpx.get(CHART_URL.format(symbol=symbol), params={
        "range": f"{range_days}d", "interval": "1d"}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res.get("timestamp") or []
    quote = res["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        close = quote["close"][i]
        if close is None:
            continue
        rows.append({"date": dt.datetime.fromtimestamp(t).date().isoformat(),
                     "close": round(float(close), 5)})
    return rows


def fetch(symbols: list[str]) -> None:
    FUT_DIR.mkdir(parents=True, exist_ok=True)
    for sym in symbols:
        rows = fetch_symbol(sym)
        name = SYMBOLS.get(sym, sym.replace("=", "").lower())
        path = FUT_DIR / f"{name}.csv"
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date", "close"])
            w.writeheader()
            w.writerows(rows)
        print(f"{sym}: {len(rows)} bars -> {path} (last {rows[-1] if rows else 'none'})")


def load(symbol: str) -> dict[str, float]:
    name = SYMBOLS.get(symbol, symbol.replace("=", "").lower())
    path = FUT_DIR / f"{name}.csv"
    if not path.exists():
        print(f"no cached futures for {symbol}; run fetch first", file=sys.stderr)
        return {}
    with open(path) as f:
        return {r["date"]: float(r["close"]) for r in csv.DictReader(f)}


def convergence(rows: dict[str, dict], symbol: str, retail_col: str = "diesel",
                baseline_days: int = 45, lag_days: int = 4) -> dict | None:
    """Excess retail gap and historical convergence stats. Read-only."""
    import aaa_data  # noqa
    fut = load(symbol)
    if not fut:
        return None
    series = aaa_data.build_print_series(rows, value_col=retail_col)
    if not series:
        return None
    last = series[-1]
    retail = last["value"]
    # latest futures close on/before the last print date + lag
    target = dt.date.fromisoformat(last["date"]) - dt.timedelta(days=lag_days)
    fut_close = None
    for k in range(10):
        d = (target - dt.timedelta(days=k)).isoformat()
        if d in fut:
            fut_close = fut[d]
            fut_date = d
            break
    if fut_close is None:
        return None
    gap = retail - fut_close
    # trailing baseline gap = median gap over the `baseline_days` days ending
    # 30 days before the latest print (excludes recent spike regimes)
    gaps = []
    for s in series:
        d = dt.date.fromisoformat(s["date"])
        if d > target - dt.timedelta(days=baseline_days):
            continue
        if d < target - dt.timedelta(days=baseline_days + 30):
            continue
        for k in range(5):
            f = fut.get((d - dt.timedelta(days=lag_days + k)).isoformat())
            if f:
                gaps.append(s["value"] - f)
                break
    baseline = sorted(gaps)[len(gaps) // 2] if gaps else None
    return {
        "retail": retail,
        "retail_date": last["date"],
        "fut_close": fut_close,
        "fut_date": fut_date,
        "symbol": symbol,
        "gap": round(gap, 4),
        "baseline_gap": round(baseline, 4) if baseline else None,
        "excess_gap_cents": round((gap - baseline) * 100, 1) if baseline else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("fetch")
    p1.add_argument("--symbols", nargs="+", default=list(SYMBOLS))
    p2 = sub.add_parser("gap")
    p2.add_argument("--symbol", default="HO=F")
    p2.add_argument("--retail", default="diesel", choices=["diesel", "regular"])
    args = ap.parse_args()
    if args.cmd == "fetch":
        fetch(args.symbols)
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import aaa_data
        rows = aaa_data.load_csv()
        out = convergence(rows, args.symbol, args.retail)
        print(out)


if __name__ == "__main__":
    main()
