#!/usr/bin/env python3
"""Maker-side EV at extreme prices: does resting at 98-99c get picked off?

Cells (maker perspective):
  A: taker_side=no, yes_price 95-99  -> maker BOUGHT YES at 95-99c (resting bid)
  B: taker_side=no, yes_price 1-5    -> maker BOUGHT NO at 95-99c (sold YES cheap)
  C: taker_side=yes, yes_price 1-5   -> maker SOLD YES at 1-5c (= bought NO 95-99)
Win rates + EV per unit risked, exchange-wide, all history.
"""
import glob, json
from collections import defaultdict
from pathlib import Path
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
TRADES = sorted(glob.glob(str(REPO / "data/external/data/kalshi/trades/*.parquet")))
MARKETS = sorted(glob.glob(str(REPO / "data/external/data/kalshi/markets/*.parquet")))

result_by_ticker = {}
for f in MARKETS:
    t = pq.read_table(f, columns=["ticker", "status", "result"])
    df = t.to_pandas()
    df = df[(df["status"].isin(["finalized", "settled", "closed"])) &
            (df["result"].isin(["yes", "no"]))]
    for tk, res in zip(df["ticker"], df["result"]):
        result_by_ticker[tk] = 1 if res == "yes" else 0
print(f"settled: {len(result_by_ticker)}")

agg = defaultdict(lambda: [0, 0, 0])  # cell -> [contracts, wins, risked]
for i, f in enumerate(TRADES):
    t = pq.read_table(f, columns=["ticker", "count", "yes_price", "taker_side"])
    df = t.to_pandas()
    for tk, cnt, yp, side in zip(df["ticker"], df["count"], df["yes_price"], df["taker_side"]):
        res = result_by_ticker.get(tk)
        if res is None:
            continue
        cnt = int(cnt)
        p = yp / 100.0
        if side == "no" and 0.95 <= p < 1.0:      # A: maker bought YES 95-99
            cell, risk, win = "A_yes_95_99", p, res
        elif side == "no" and 0.01 <= p < 0.05:   # B: maker bought NO 95-99
            cell, risk, win = "B_no_95_99", 1 - p, 1 - res
        elif side == "yes" and 0.01 <= p < 0.05:  # C: maker sold YES 1-5 (bought NO 95-99)
            cell, risk, win = "C_sellyes_1_5", 1 - p, 1 - res
        elif side == "yes" and 0.95 <= p < 1.0:   # D: maker sold YES 95-99 (took NO cheap?)
            cell, risk, win = "D_sellyes_95_99", 1 - p, 1 - res
        else:
            continue
        a = agg[cell]
        a[0] += cnt; a[1] += cnt * win; a[2] += cnt * risk

out = {}
for cell, (n, w, r) in sorted(agg.items()):
    if n >= 1000:
        out[cell] = {"contracts": n, "win_rate": round(w / n, 4),
                     "avg_risk": round(r / n, 4),
                     "ev_per_risk": round((w - r) / r, 4) if r else None}
print(json.dumps(out, indent=1))
(REPO / "data/external/maker_extreme.json").write_text(json.dumps(out, indent=1))
