#!/usr/bin/env python3
"""Price Kalshi AAA gas/diesel strike ladders against a data-fed print model.

The daily markets (KXDIESELD, KXAAAGASD) resolve on the AAA national daily
average for date D but CLOSE before the D print is published. Pricing therefore
reduces to forecasting the change from the last known print.

Model (deliberately simple, episode-based):
  * The sample of consecutive-print changes comes from the AAA page pairs
    (Current - Yesterday) stitched by scripts/aaa_data.py (no calendar gap
    assumptions).
  * Decline streaks are counted on the *settled* series semantics: consecutive
    prints with delta <= -0.4c. We split the next-print forecast by whether
    historical streaks of the SAME length extended past that length or broke:
      - streak-continuation days inherit the mid-streak change distribution
        (empirical, streak length >= current).
      - streak-break days inherit the post-episode day-after distribution.
    The blend weight is the empirical extend-rate of streaks of at least the
    current length (Laplace-smoothed).
  * Normal-fit fallback when the empirical sample is thin.

Outputs, per strike: model fair P(print > strike), live book (best YES bid/ask
derived from the orderbook, where a NO bid at p equals a YES ask at 1-p),
fee-aware edges for buying YES and buying NO, and a JSON snapshot under
data/aaa/pricings/ for forward scoring (score subcommand).

Usage:
  python scripts/aaa_pricer.py price --series diesel --target 2026-09-27
  python scripts/aaa_pricer.py score           # score saved pricings vs realized
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import aaa_data  # noqa: E402

PRICINGS_DIR = REPO / "data" / "aaa" / "pricings"

# Kalshi taker fee (general markets): fee_cents = ceil(0.07 * C * P * (1-P)).
# Maker orders pay no fee. We size per-contract with the ceiling as a
# conservative approximation for small orders.
def taker_fee_per_contract(price: float) -> float:
    if price <= 0 or price >= 1:
        return 0.0
    return math.ceil(7.0 * price * (1.0 - price)) / 100.0


def streak_runs(deltas: list[float], thresh: float = -0.4) -> list[tuple[int, int]]:
    """Indices+lengths of maximal consecutive-decline runs (delta <= thresh).

    Pure function; covered by tests.
    """
    runs = []
    start = None
    for i, x in enumerate(deltas):
        if x <= thresh:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= 2:
                runs.append((start, i - start))
            start = None
    if start is not None and len(deltas) - start >= 2:
        runs.append((start, len(deltas) - start))
    return runs


def fit_model(deltas: list[float], current_streak: int) -> dict:
    """Return a forecast distribution (quantile function) for the next change.

    ``current_streak`` = number of consecutive decline-days ending with the last
    known print (0 if the last change was not a decline). Returns {"cdf": fn}
    where cdf(x) = P(next change <= x), plus diagnostics.
    Pure function; covered by tests.
    """
    arr = np.asarray(deltas, dtype=float)
    runs = streak_runs(list(arr))
    # extend-rate of streaks at least as long as the current one (Laplace)
    reached = [L for _, L in runs if L >= current_streak] if current_streak >= 2 else []
    if current_streak >= 2 and reached:
        n_reach = len(reached)
        n_extend = sum(1 for _, L in runs if L > current_streak and L >= current_streak)
        # episodes that reached `current_streak` and continued beyond it
        n_extend = sum(1 for _, L in runs if L > current_streak)
        p_extend = (n_extend + 1) / (n_reach + 2)
        # changes that occur ON continuation days: the deltas inside runs
        cont_vals = []
        for s, L in runs:
            cont_vals.extend(arr[s:s + L])
        cont_vals = np.asarray(cont_vals)
        # day-after (break) changes: the first delta after each run
        break_vals = []
        for s, L in runs:
            if s + L < len(arr):
                break_vals.append(arr[s + L])
        break_vals = np.asarray(break_vals)
    else:
        p_extend = 0.0
        cont_vals = arr
        break_vals = arr
    return {
        "p_extend": float(p_extend),
        "cont": cont_vals,
        "break": break_vals,
        "uncond": arr,
        "current_streak": current_streak,
    }


def cdf_from_samples(vals: np.ndarray, x: float) -> float:
    if len(vals) == 0:
        return 0.5
    return float((vals <= x).mean())


def forecast_cdf(model: dict, x: float) -> float:
    """P(next change <= x) blending continuation and break branches."""
    pe = model["p_extend"]
    if pe <= 0 or len(model["break"]) == 0:
        return cdf_from_samples(model["uncond"], x)
    p_cont = cdf_from_samples(model["cont"], x)
    p_break = cdf_from_samples(model["break"], x)
    return pe * p_cont + (1 - pe) * p_break


def parse_strike(ticker: str) -> float | None:
    tail = ticker.rsplit("-", 1)[-1]
    try:
        return float(tail[1:] if tail.startswith("T") else tail)
    except ValueError:
        return None


async def fetch_book(client, ticker: str) -> dict:
    ob = await client.get_orderbook(ticker)
    fp = ob.get("orderbook_fp", ob)
    yes_bids = sorted([(float(p), float(q)) for p, q in (fp.get("yes_dollars") or [])])
    no_bids = sorted([(float(p), float(q)) for p, q in (fp.get("no_dollars") or [])])
    y_bid = yes_bids[-1][0] if yes_bids else 0.0
    y_ask = 1.0 - (no_bids[-1][0] if no_bids else 0.0)
    return {"yes_bid": y_bid, "yes_ask": y_ask, "n_levels": len(yes_bids) + len(no_bids)}


def fee_aware_edges(fair_yes: float, book: dict) -> dict:
    y_ask, y_bid = book["yes_ask"], book["yes_bid"]
    buy_yes_cost = min(y_ask + taker_fee_per_contract(y_ask), 1.0)
    no_ask = 1.0 - y_bid
    buy_no_cost = min(no_ask + taker_fee_per_contract(no_ask), 1.0)
    return {
        "buy_yes_edge": round(fair_yes - buy_yes_cost, 4),
        "buy_no_edge": round((1.0 - fair_yes) - buy_no_cost, 4),
        "buy_yes_cost": round(buy_yes_cost, 4),
        "buy_no_cost": round(buy_no_cost, 4),
    }


def settled_streak(rows: dict[str, dict], as_of: str) -> tuple[int, float]:
    """Count the current decline streak ending at the latest known print.

    Uses the page-pair sequence; the last known print's date may lag its
    calendar date (site lag), which is fine for streak counting.
    """
    seq = aaa_data.build_print_series(rows)
    if not seq:
        return 0, float("nan")
    last = seq[-1]
    streak = 1 if last["delta_cents"] <= -0.4 else 0
    return streak, last["value"]


def cmd_price(args) -> None:
    import asyncio
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    from src.clients.kalshi_client import KalshiClient

    rows = aaa_data.load_csv()
    seq = aaa_data.build_print_series(rows)
    if not seq:
        print("no AAA series; run scripts/aaa_data.py backfill first", file=sys.stderr)
        return 1
    deltas = [s["delta_cents"] for s in seq]
    last = seq[-1]
    streak = 0
    for d in reversed(deltas):
        if d <= -0.4:
            streak += 1
        else:
            break
    model = fit_model(deltas, current_streak=streak)
    cur = last["value"]
    print(f"last known print {cur} ({last['date']}), current decline streak={streak}, "
          f"p_extend={model['p_extend']:.2f}")

    async def run():
        c = KalshiClient()
        r = await c.get_markets(series_ticker=args.series, status="open", limit=100)
        mks = r.get("markets", r) if isinstance(r, dict) else r
        out_rows = []
        for m in sorted(mks, key=lambda x: x["ticker"]):
            strike = parse_strike(m["ticker"])
            if strike is None:
                continue
            fair_yes = 1.0 - forecast_cdf(model, (strike - cur) * 100)
            book = await fetch_book(c, m["ticker"])
            edges = fee_aware_edges(fair_yes, book)
            out_rows.append({"ticker": m["ticker"], "strike": strike,
                             "fair_yes": round(fair_yes, 4), **book, **edges,
                             "last": m.get("last_price_fp") or m.get("last_price_dollars")})
        await c.close()
        return out_rows

    rows_out = asyncio.run(run())
    rows_out.sort(key=lambda r: -max(r["buy_yes_edge"], r["buy_no_edge"]))
    print(f"{'ticker':32s} {'fairYES':>8s} {'bid':>5s} {'ask':>5s} {'buyY_edge':>9s} {'buyN_edge':>9s}")
    for r in rows_out:
        print(f"{r['ticker']:32s} {r['fair_yes']:8.3f} {r['yes_bid']:5.2f} {r['yes_ask']:5.2f} "
              f"{r['buy_yes_edge']:+9.3f} {r['buy_no_edge']:+9.3f}")
    PRICINGS_DIR.mkdir(parents=True, exist_ok=True)
    # wholesale convergence diagnostics (the 2026-09-26 lesson: retail history
    # alone misses the dominant driver; futures lag drives multi-day declines)
    wholesale = None
    try:
        import aaa_futures
        sym = "HO=F" if "DIESEL" in args.series.upper() else "RB=F"
        retail_col = "diesel" if "DIESEL" in args.series.upper() else "regular"
        wholesale = aaa_futures.convergence(rows, sym, retail_col)
        if wholesale:
            print("wholesale:", wholesale)
    except Exception as e:
        print(f"wholesale diagnostics unavailable: {e}", file=sys.stderr)
    snap = {
        "ts": dt.datetime.now(dt.UTC).isoformat(),
        "series": args.series,
        "target_date": args.target,
        "last_print": cur,
        "last_print_date": last["date"],
        "streak": streak,
        "p_extend": model["p_extend"],
        "wholesale": wholesale,
        "rows": rows_out,
    }
    path = PRICINGS_DIR / f"{snap['ts'].replace(':', '').replace('-', '')}_{args.series}.json"
    path.write_text(json.dumps(snap, indent=1))
    print(f"snapshot -> {path}")


def cmd_score() -> int:
    """Score saved pricing snapshots against realized prints (forward-only).

    Realized print for a snapshot's target_date = the AAA series value with that
    calendar date (written by scripts/aaa_data.py). If the date is not yet in the
    series the snapshot is pending and skipped. Writes/updates
    data/aaa/scores.jsonl with per-strike Brier for the model fair and the book
    mid, so model-vs-book calibration accumulates over time.
    """
    rows = aaa_data.load_csv()
    realized = {}
    for date, r in rows.items():
        try:
            realized[date] = float(r["diesel"])
        except (TypeError, ValueError):
            pass
    scores = []
    for path in sorted(PRICINGS_DIR.glob("*.json")):
        try:
            snap = json.loads(path.read_text())
        except Exception:
            continue
        target = snap.get("target_date")
        if target not in realized:
            continue
        actual = realized[target]
        for r in snap.get("rows", []):
            y_bid, y_ask = r.get("yes_bid", 0.0), r.get("yes_ask", 1.0)
            if not (0 < y_bid < 1 and 0 < y_ask < 1) or y_ask - y_bid > 0.25:
                continue  # untradeable / one-sided book: not a scored observation
            mid = (y_bid + y_ask) / 2
            fair = r.get("fair_yes")
            if fair is None:
                continue
            y = 1.0 if actual > r.get("strike", -1) else 0.0
            scores.append({
                "ts": snap.get("ts"), "series": snap.get("series"), "target": target,
                "ticker": r.get("ticker"), "actual": actual, "y": y,
                "fair_yes": fair, "book_mid": round(mid, 4),
                "brier_model": round((fair - y) ** 2, 4),
                "brier_book": round((mid - y) ** 2, 4),
            })
    if not scores:
        print("no scoreable snapshots yet (prints not realized or books one-sided)")
        return 0
    out = REPO / "data" / "aaa" / "scores.jsonl"
    with open(out, "a") as f:
        for s in scores:
            f.write(json.dumps(s) + "\n")
    import numpy as np
    bm = np.mean([s["brier_model"] for s in scores])
    bb = np.mean([s["brier_book"] for s in scores])
    print(f"scored {len(scores)} strike-observations -> {out}")
    print(f"mean Brier: model {bm:.4f}  book {bb:.4f}  (model - book: {bm - bb:+.4f})")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("price")
    p.add_argument("--series", default="KXDIESELD", help="Kalshi series ticker")
    p.add_argument("--target", required=True, help="target print date, e.g. 2026-09-27")
    sub.add_parser("score")
    args = ap.parse_args()
    if args.cmd == "price":
        raise SystemExit(cmd_price(args))
    if args.cmd == "score":
        raise SystemExit(cmd_score())


if __name__ == "__main__":
    main()
