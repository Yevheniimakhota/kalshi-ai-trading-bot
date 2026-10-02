#!/usr/bin/env python3
"""Ornn Compute Price Index (OCPI) data layer.

The Kalshi KXA100MS family ("Will the monthly average compute price of NVIDIA's
A100 be above $X in MONTH?") resolves on the arithmetic mean of hourly values
reported by Ornn. Ornn publishes a free public daily series (OCPI settles once
per trading day at 4:00 PM ET; data.ornn.com, no auth):

    https://data.ornn.com/api/public-index/gpu/{GPU}/index-history  (3 months)
    https://data.ornn.com/api/public-index/daily-index/all          (latest day)

Because each day contributes the same 24 hours, the month's hourly mean equals
the mean of that month's daily prints — so the daily series is exactly what the
pricing math needs:

    mean(MONTH) = (n_so_far * mean_so_far + n_remaining * avg_future) / days
    => the strike loses only if the remaining prints average below
       (days * strike - n_so_far * mean_so_far) / n_remaining.

Free data is the latest 3 months; the KXA100MS markets are monthly, so the
in-month prints are always inside the window. Rebuild/refresh with `fetch`.

Usage:
  python scripts/ornn_data.py fetch              # cache all GPU histories
  python scripts/ornn_data.py strike --gpu "A100 SXM4" --month 2026-09 --strike 1.00
"""
from __future__ import annotations

import argparse
import datetime as dt
import httpx
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ORNN_DIR = REPO / "data" / "ornn"
HIST_URL = "https://data.ornn.com/api/public-index/gpu/{gpu}/index-history"
ALL_URL = "https://data.ornn.com/api/public-index/daily-index/all"
GPU_TYPES_URL = "https://data.ornn.com/api/public-index/gpu-types-free"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def gpu_types() -> list[str]:
    r = httpx.get(GPU_TYPES_URL, timeout=30, headers=HEADERS)
    r.raise_for_status()
    return [d["gpu_name"] for d in r.json()["data"]]


def fetch_history(gpu: str) -> list[dict]:
    r = httpx.get(HIST_URL.format(gpu=httpx.QueryParams({"gpu": gpu})["gpu"]),
                  timeout=30, headers=HEADERS)
    r.raise_for_status()
    return r.json()["data"]


def fetch(gpus: list[str] | None = None) -> None:
    ORNN_DIR.mkdir(parents=True, exist_ok=True)
    for gpu in (gpus or gpu_types()):
        data = fetch_history(gpu)
        slug = gpu.lower().replace(" ", "-")
        path = ORNN_DIR / f"{slug}.json"
        path.write_text(json.dumps({"gpu": gpu, "fetched": dt.datetime.now(dt.UTC).isoformat(),
                                    "data": data}, indent=1))
        if data:
            print(f"{gpu}: {len(data)} daily prints "
                  f"({data[0]['timestamp'][:10]} -> {data[-1]['timestamp'][:10]}) -> {path}")


def load(gpu: str) -> list[dict]:
    slug = gpu.lower().replace(" ", "-")
    path = ORNN_DIR / f"{slug}.json"
    if not path.exists():
        fetch([gpu])
    return json.loads(path.read_text())["data"]


def month_stats(gpu: str, month: str) -> dict | None:
    """n_so_far, mean_so_far, last print and the break-even average for a strike."""
    rows = [d for d in load(gpu) if d["timestamp"][:7] == month]
    if not rows:
        return None
    vals = [d["index_value"] for d in rows]
    year, m = int(month[:4]), int(month[5:7])
    days = (dt.date(year + (m == 12), (m % 12) + 1, 1) - dt.date(year, m, 1)).days
    n = len(vals)
    return {"gpu": gpu, "month": month, "n": n, "days_in_month": days,
            "mean_so_far": sum(vals) / n, "last": vals[-1],
            "last_date": rows[-1]["timestamp"][:10],
            "remaining": days - n,
            "values": vals}


def strike_breakeven(stats: dict, strike: float) -> dict:
    n, msf, rem = stats["n"], stats["mean_so_far"], stats["remaining"]
    need = (stats["days_in_month"] * strike - n * msf) / rem if rem > 0 else float("nan")
    return {"strike": strike,
            "remaining_prints_must_avg_below": round(need, 4),
            "last_print": stats["last"],
            "downside_from_last_pct": round((stats["last"] - need) / stats["last"] * 100, 2),
            "verdict_if_flat_at_last": round((n * msf + rem * stats["last"]) / stats["days_in_month"], 4)}


GPUS = ["A100 SXM4", "H100 SXM", "H200", "B200", "RTX 5090"]
GPU_SERIES = {"A100 SXM4": "KXA100MS", "H100 SXM": "KXH100MS",
              "H200": "KXH200MS", "B200": "KXB200MS"}
MONTH_DAYS = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30,
              10: 31, 11: 30, 12: 31}


def mc_month_mean(data: list[dict], month: str, recency: int = 30,
                  n_sims: int = 20000, seed: int = 7) -> dict | None:
    """Random-walk MC of the month's final mean from the recent change regime.

    ``data`` = dated rows ({"timestamp", "index_value"}). Valid for near months
    (a handful of remaining prints); the recent drift overextrapolates badly at
    2-3 month horizons, so treat far months as junk. Tested.
    """
    import numpy as np
    rng = np.random.default_rng(seed)
    all_vals = [d["index_value"] for d in data]
    chg = np.diff(np.asarray(all_vals, dtype=float))[-recency:]
    rows = [d["index_value"] for d in data if d["timestamp"][:7] == month]
    year, m = int(month[:4]), int(month[5:7])
    days = MONTH_DAYS[m] + (1 if m == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 0)
    n = len(rows)
    msf = sum(rows) / n if rows else 0.0
    last = all_vals[-1]
    rem = max(days - n, 0)
    if rem == 0 or len(chg) == 0:
        return None
    samp = rng.choice(chg, size=(n_sims, rem))
    future = last + np.cumsum(samp, axis=1)
    means = (n * msf + future.sum(axis=1)) / days
    return {"means": means, "n": n, "days": days, "msf": msf, "last": last, "rem": rem}


def cmd_ladder(month: str | None = None) -> None:
    """Price the near-month OCPI strike ladders vs live books (snapshot only)."""
    import asyncio
    import datetime as dt
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    from src.clients.kalshi_client import KalshiClient
    from aaa_pricer import fetch_book, parse_strike, taker_fee_per_contract

    now = dt.datetime.now()
    month = month or f"{now.year}-{now.month:02d}"
    tag = f"{now.year % 100:02d}{['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][now.month-1]}"
    rows = []
    async def run():
        c = KalshiClient()
        for gpu in GPUS:
            series = GPU_SERIES.get(gpu)
            if not series:
                continue
            data = load(gpu)
            mc = mc_month_mean(data, month)
            if mc is None or mc["rem"] <= 0:
                continue
            r = await c.get_markets(series_ticker=series, status="open", limit=200)
            mks = r.get("markets", r) if isinstance(r, dict) else r
            for m in mks:
                parts = m["ticker"].split("-")
                if parts[1] != tag:
                    continue
                strike = parse_strike(m["ticker"])
                if strike is None:
                    continue
                p_yes = float((mc["means"] > strike).mean())
                book = await fetch_book(c, m["ticker"])
                cy = min(book["yes_ask"] + taker_fee_per_contract(book["yes_ask"]), 1.0)
                cn = min((1 - book["yes_bid"]) + taker_fee_per_contract(1 - book["yes_bid"]), 1.0)
                rows.append({"gpu": gpu, "ticker": m["ticker"], "strike": strike,
                             "model_p_yes": round(p_yes, 4), **book,
                             "buy_yes_edge": round(p_yes - cy, 4),
                             "buy_no_edge": round((1 - p_yes) - cn, 4)})
        await c.close()
    asyncio.run(run())
    rows.sort(key=lambda r: -abs(max(r["buy_yes_edge"], r["buy_no_edge"])))
    print(f"{'gpu':10s} {'strike':>6s} {'modelP':>7s} {'bid':>5s} {'ask':>5s} {'edgeY':>7s} {'edgeN':>7s}")
    for r in rows[:15]:
        print(f"{r['gpu']:10s} {r['strike']:6.2f} {r['model_p_yes']:7.3f} {r['yes_bid']:5.2f} "
              f"{r['yes_ask']:5.2f} {r['buy_yes_edge']:+7.3f} {r['buy_no_edge']:+7.3f}")
    out = REPO / "data" / "ornn" / "ladder_pricings"
    out.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.UTC).isoformat()
    (out / f"{ts.replace(':', '').replace('-', '')}.json").write_text(
        json.dumps({"ts": ts, "month": month, "rows": rows}, indent=1))
    print(f"snapshot -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    sub.add_parser("ladder")
    p = sub.add_parser("strike")
    p.add_argument("--gpu", default="A100 SXM4")
    p.add_argument("--month", required=True, help="e.g. 2026-09")
    p.add_argument("--strike", type=float, required=True)
    p3 = ap.parse_args()
    args = p3
    if args.cmd == "fetch":
        fetch()
    elif args.cmd == "ladder":
        cmd_ladder()
    else:
        st = month_stats(args.gpu, args.month)
        if not st:
            print("no prints for that month", file=sys.stderr)
            return
        out = {k: v for k, v in st.items() if k != "values"}
        out.update(strike_breakeven(st, args.strike))
        print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
