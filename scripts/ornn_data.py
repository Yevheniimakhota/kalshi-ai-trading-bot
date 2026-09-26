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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    p = sub.add_parser("strike")
    p.add_argument("--gpu", default="A100 SXM4")
    p.add_argument("--month", required=True, help="e.g. 2026-09")
    p.add_argument("--strike", type=float, required=True)
    args = ap.parse_args()
    if args.cmd == "fetch":
        fetch()
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
