#!/usr/bin/env python3
"""Analysis of the Becker Kalshi trade dataset (72M trades, 2023-2025-11).

Three passes over the trade shard files (single scan each, bounded memory):

A. Taker P&L by price bucket x side (validates the longshot bias + optimism tax
   on our copy of the data).
B. Close-out backtest: for every settled market, the LAST trade at least 1h and
   3h before close; bucket by price; win rate. Plus: trades AT >=0.98 in the
   final hour - win rate by taker side (the adverse-selection measurement at
   exchange scale).
C. Gas/diesel ladder dynamics: for KXDIESELD/KXAAAGASD/KXDIESELW/KXDIESELMON/
   KXAAAGASM* tickers, the time from the trade stream crossing 0.95 to close,
   and taker P&L in the final 6h.

Output: data/external/analysis_results.json + docs/KALSHI_DATASET_FINDINGS.md
"""
import glob
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
TRADES = sorted(glob.glob(str(REPO / "data/external/data/kalshi/trades/*.parquet")))
MARKETS = sorted(glob.glob(str(REPO / "data/external/data/kalshi/markets/*.parquet")))
OUT_JSON = REPO / "data/external/analysis_results.json"

# ---------- pass 0: markets ----------
print("loading markets...")
result_by_ticker = {}
close_by_ticker = {}
title_by_ticker = {}
for f in MARKETS:
    t = pq.read_table(f, columns=["ticker", "status", "result", "close_time", "title", "volume"])
    df = t.to_pandas()
    df = df[(df["status"].isin(["finalized", "settled", "closed"])) &
            (df["result"].isin(["yes", "no"]))]
    for _, r in df.iterrows():
        result_by_ticker[r["ticker"]] = 1 if r["result"] == "yes" else 0
        try:
            close_by_ticker[r["ticker"]] = r["close_time"].to_pydatetime()
        except Exception:
            continue
        if r["volume"] and r["volume"] >= 100:
            title_by_ticker[r["ticker"]] = r["title"]
print(f"settled markets with result: {len(result_by_ticker)}")

BUCKETS = [(0.01, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.35), (0.35, 0.65),
           (0.65, 0.80), (0.80, 0.90), (0.90, 0.95), (0.95, 0.97), (0.97, 0.99), (0.99, 1.0)]

def bucket_of(p):
    for lo, hi in BUCKETS:
        if lo <= p < hi:
            return f"[{lo},{hi})"
    return None

# A: taker pnl by bucket x side ; B accumulators
agg = defaultdict(lambda: [0, 0, 0])   # (bucket, side) -> [n, win_exposure, risked]
# close-out: last trade <= close-1h and close-3h per ticker (settled only)
co1 = {}
co3 = {}
# final-hour trades at >=0.98
fh = defaultdict(lambda: [0, 0, 0])   # side -> [n, wins, notional]
# C: fuel tickers
fuel_trades = defaultdict(list)
FUEL_PREFIX = ("KXDIESELD", "KXDIESELW", "KXDIESELMON", "KXAAAGASD", "KXAAAGASM")

def process_file(f):
    t = pq.read_table(f, columns=["ticker", "count", "yes_price", "taker_side", "created_time"])
    df = t.to_pandas()
    for tk, cnt, yp, side, ts in zip(df["ticker"], df["count"], df["yes_price"],
                                     df["taker_side"], df["created_time"]):
        res = result_by_ticker.get(tk)
        if tk.startswith(FUEL_PREFIX) and len(fuel_trades[tk]) < 20000:
            try:
                fuel_trades[tk].append((ts.to_pydatetime(), yp, cnt, side))
            except Exception:
                pass
        if res is None:
            continue
        p = yp / 100.0
        win = res
        taker_win = win if side == "yes" else 1 - win
        cnt = int(cnt)
        cost = p if side == "yes" else 1.0 - p   # what the taker risked per contract
        b = bucket_of(p)
        if b:
            a = agg[(b, side)]
            a[0] += cnt
            a[1] += cnt * taker_win
            a[2] += cnt * cost
        ct = close_by_ticker.get(tk)
        if ct is not None:
            try:
                tts = ts.to_pydatetime()
            except Exception:
                continue
            lead1 = (ct - tts).total_seconds()
            if lead1 >= 3600:
                cur = co1.get(tk)
                if cur is None or tts > cur[0]:
                    co1[tk] = (tts, p, side)
            if lead1 >= 3 * 3600:
                cur = co3.get(tk)
                if cur is None or tts > cur[0]:
                    co3[tk] = (tts, p, side)
            if lead1 < 3600 and p >= 0.98:
                a = fh[side]
                a[0] += cnt
                a[1] += cnt * taker_win
                a[2] += cnt * p

for i, f in enumerate(TRADES):
    process_file(f)
    if (i + 1) % 500 == 0:
        print(f"  trades {i+1}/{len(TRADES)} files")

results = {"n_settled": len(result_by_ticker)}

# A: taker edge per bucket per side
cal = {}
for (b, side), (n, wins, risked) in sorted(agg.items()):
    cal[f"{b}|{side}"] = {"contracts": n,
                          "win_rate": round(wins / n, 5) if n else None,
                          "avg_price": round(risked / n, 4) if n else None,
                          "taker_ev_per_contract": round((wins - risked) / n, 5) if n else None}
results["taker_by_bucket_side"] = cal

# B: close-out buckets
def closeout_stats(co, label):
    stats = defaultdict(lambda: [0, 0])
    for tk, (_, p, side) in co.items():
        b = bucket_of(p)
        if b:
            stats[b][0] += 1
            stats[b][1] += result_by_ticker[tk]
    out = {}
    for b, (n, w) in sorted(stats.items()):
        if n >= 30:
            out[b] = {"n": n, "win_rate": round(w / n, 4)}
    results[label] = out

closeout_stats(co1, "closeout_last_before_1h")
closeout_stats(co3, "closeout_last_before_3h")
results["final_hour_ge098"] = {
    side: {"contracts": n, "win_rate": round(w / n, 4) if n else None,
           "avg_price": round(r / n, 4) if n else None,
           "taker_ev_per_contract": round((w - r) / n, 4) if n else None}
    for side, (n, w, r) in fh.items()}

# C: fuel ladder dynamics
fuel_stats = {}
for tk, trades in fuel_trades.items():
    if len(trades) < 20:
        continue
    trades.sort()
    ct = close_by_ticker.get(tk)
    res = result_by_ticker.get(tk)
    crossing = None
    for ts, p, cnt, side in trades:
        if p >= 0.95:
            crossing = ts
            break
    if crossing and ct:
        fuel_stats[tk] = {"cross_lead_h": round((ct - crossing).total_seconds() / 3600, 2),
                          "settled": res}
results["fuel_crossing"] = {"n": len(fuel_stats),
                            "median_cross_lead_h": sorted(v["cross_lead_h"] for v in fuel_stats.values())[len(fuel_stats)//2] if fuel_stats else None,
                            "pct_crossed_1h_before": round(sum(1 for v in fuel_stats.values() if v["cross_lead_h"] >= 1) / len(fuel_stats), 3) if fuel_stats else None,
                            "examples": dict(list(fuel_stats.items())[:10])}

OUT_JSON.write_text(json.dumps(results, indent=1))
print(json.dumps({k: results[k] for k in ["closeout_last_before_1h", "final_hour_ge098", "fuel_crossing"]}, indent=1)[:2000])
print("done ->", OUT_JSON)
