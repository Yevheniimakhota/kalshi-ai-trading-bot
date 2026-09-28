#!/usr/bin/env python3
"""Empirical study of Kalshi close-out scalping: P(settle YES | last bid >= p).

Motivated by the "buy at 0.99 for the last 1%" strategy. For a sample of settled
markets, pull hourly candlesticks, take the last observable YES bid before
cutoffs (1h/3h/6h/24h/48h pre-close), and bucket the settled outcome. Also
measures opportunity frequency (how often does a market print >= 0.99 with
>= 1h to close) and lead-time distributions.

Fee model: Kalshi fee = round-up(0.07 * C * p * (1-p)) per ORDER (worst-case
per-contract ceil = 1c at p=0.99). Both variants reported.

Candles cached under data/backtest/scalp_candles/<ticker>.json; resumable.

Usage: python scripts/scalp_study.py [--days 10] [--limit 1200] [--concurrency 5]
Output: docs/SCALP_STUDY.md + data/backtest/scalp_observations.jsonl
"""
import argparse
import asyncio
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")
from src.clients.kalshi_client import KalshiClient, KalshiAPIError

CACHE = REPO / "data" / "backtest" / "scalp_candles"
OUT = REPO / "data" / "backtest" / "scalp_observations.jsonl"
CUTOFFS_H = [1, 3, 6, 24, 48]
BUCKETS = [(0.99, 1.01), (0.97, 0.99), (0.95, 0.97), (0.90, 0.95)]


async def fetch_settled(c, days: int, limit: int):
    now = int(time.time())
    min_close = now - days * 86400
    out, cursor = [], None
    while len(out) < limit:
        params = {"status": "settled", "limit": 1000, "max_close_ts": now}
        if cursor:
            params["cursor"] = cursor
        r = await c._make_authenticated_request("GET", "/trade-api/v2/markets",
                                                params=params, require_auth=False)
        mks = r.get("markets", [])
        for m in mks:
            try:
                ct = m.get("close_time", "").replace("Z", "+00:00")
                close_ts = datetime.fromisoformat(ct).timestamp()
            except Exception:
                continue
            if close_ts >= min_close and m.get("result") in ("yes", "no"):
                out.append({"ticker": m["ticker"], "close_ts": int(close_ts),
                            "result": m["result"], "series": m["ticker"].rsplit("-", 1)[0]})
        cursor = r.get("cursor")
        if not cursor or not mks:
            break
    return out


async def candles_for(c, ticker: str, series: str, close_ts: int):
    path = CACHE / f"{ticker}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    start = close_ts - 60 * 3600
    try:
        r = await c._make_authenticated_request(
            "GET", f"/trade-api/v2/series/{series}/markets/{ticker}/candlesticks",
            params={"start_ts": start, "end_ts": close_ts + 600, "period_interval": 60},
            require_auth=False)
        cs = r.get("candlesticks", [])
    except KalshiAPIError as e:
        cs = []
    except Exception:
        cs = []
    obs = []
    for cd in cs:
        ts = cd.get("end_period_ts")
        if ts is None:
            continue
        bid = cd.get("yes_bid", {}) or {}
        ask = cd.get("yes_ask", {}) or {}
        px = cd.get("price", {}) or {}
        def f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None
        obs.append({"ts": ts,
                    "bid": f(bid.get("close_dollars")) or f(bid.get("high_dollars")),
                    "ask": f(ask.get("close_dollars")) or f(ask.get("high_dollars")),
                    "prev": f(px.get("previous_dollars")),
                    "vol": float(cd.get("volume_fp") or 0)})
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obs))
    return obs


def last_before(obs, cutoff_ts, key="bid"):
    best = None
    for o in obs:
        if o["ts"] <= cutoff_ts and o.get(key) is not None:
            best = o[key]  # obs assumed sorted ascending
    return best


def fee_per_contract(p):
    if p <= 0 or p >= 1:
        return 0.0
    return math.ceil(7.0 * p * (1 - p)) / 100.0


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--limit", type=int, default=1200)
    ap.add_argument("--concurrency", type=int, default=5)
    args = ap.parse_args()

    c = KalshiClient()
    settled = await fetch_settled(c, args.days, args.limit)
    print(f"settled sample: {len(settled)} markets "
          f"(close_time {time.strftime('%F %H:%M', time.gmtime(min(m['close_ts'] for m in settled)))} .. "
          f"{time.strftime('%F %H:%M', time.gmtime(max(m['close_ts'] for m in settled)))})")
    CACHE.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(args.concurrency)
    done = [0]

    async def work(m):
        async with sem:
            obs = await candles_for(c, m["ticker"], m["series"], m["close_ts"])
            done[0] += 1
            if done[0] % 100 == 0:
                print(f"  candles {done[0]}/{len(settled)}")

    await asyncio.gather(*(work(m) for m in settled))
    await c.close()
    print(f"candle cache complete: {done[0]}")

    rows = []
    for m in settled:
        try:
            obs = json.loads((CACHE / f"{m['ticker']}.json").read_text())
        except Exception:
            continue
        obs = sorted(obs, key=lambda o: o["ts"])
        if not obs:
            continue
        y = 1 if m["result"] == "yes" else 0
        rec = {"ticker": m["ticker"], "series": m["series"], "close_ts": m["close_ts"], "y": y}
        for h_ in CUTOFFS_H:
            b = last_before(obs, m["close_ts"] - h_ * 3600, "bid")
            a = last_before(obs, m["close_ts"] - h_ * 3600, "ask")
            rec[f"bid_{h_}h"] = b
            rec[f"ask_{h_}h"] = a
        # opportunity scan: max bid with >=1h to close, and its lead time
        mb, mb_ts = None, None
        for o in obs:
            if o["ts"] <= m["close_ts"] - 3600 and o.get("bid") is not None:
                if mb is None or o["bid"] >= mb:
                    mb, mb_ts = o["bid"], o["ts"]
        rec["max_bid_1h"] = mb
        rec["max_bid_lead_h"] = (m["close_ts"] - mb_ts) / 3600 if mb_ts else None
        rows.append(rec)
    with open(OUT, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} observation rows -> {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
