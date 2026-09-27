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
import asyncio
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

    retail_col = getattr(args, "retail", None) or (
        "regular" if "GAS" in args.series.upper() else "diesel")
    state = None
    if args.series.upper().startswith("KXAAAGASD") and len(args.series) > len("KXAAAGASD"):
        state = args.series[len("KXAAAGASD"):len("KXAAAGASD") + 2].upper()
    if state:
        state_rows = aaa_data.load_state(state)
        seq = aaa_data.build_print_series(state_rows, value_col=retail_col)
        if not seq:
            print(f"state {state}: no series yet; run scripts/aaa_data.py fetch_state first",
                  file=sys.stderr)
            return 1
        nat_seq = aaa_data.build_print_series(aaa_data.load_csv(), value_col=retail_col)
        if len(seq) >= 30:
            deltas = [s["delta_cents"] for s in seq]
            model_note = f"state {state} own series (n={len(deltas)})"
        else:
            deltas = [s["delta_cents"] for s in nat_seq]
            model_note = (f"state {state} value with national change distribution "
                          f"(state n={len(seq)} < 30)")
        cur = seq[-1]["value"]
        cur_date = seq[-1]["date"]
        rows = state_rows  # for wholesale diagnostics
    else:
        rows = aaa_data.load_csv()
        seq = aaa_data.build_print_series(rows, value_col=retail_col)
        deltas = [s["delta_cents"] for s in seq]
        cur = seq[-1]["value"]
        cur_date = seq[-1]["date"]
        model_note = "national series"
    if not seq:
        print("no AAA series; run scripts/aaa_data.py backfill first", file=sys.stderr)
        return 1
    streak = 0
    for d in reversed(deltas):
        if d <= -0.4:
            streak += 1
        else:
            break
    model = fit_model(deltas, current_streak=streak)
    print(f"{model_note}: last known print {cur} ({cur_date}), decline streak={streak}, "
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
        sym = "HO=F" if retail_col == "diesel" else "RB=F"
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
        "last_print_date": cur_date,
        "state": state,
        "streak": streak,
        "p_extend": model["p_extend"],
        "wholesale": wholesale,
        "rows": rows_out,
    }
    path = PRICINGS_DIR / f"{snap['ts'].replace(':', '').replace('-', '')}_{args.series}.json"
    path.write_text(json.dumps(snap, indent=1))
    print(f"snapshot -> {path}")
    # gap alarm: materialize large model-vs-book gaps for the agent loop
    threshold = getattr(args, "alert_min", None)
    if threshold is not None:
        alerts = [r for r in rows_out if max(r["buy_yes_edge"], r["buy_no_edge"]) >= threshold]
        if alerts:
            alerts_dir = REPO / "data" / "aaa" / "alerts"
            alerts_dir.mkdir(parents=True, exist_ok=True)
            apath = alerts_dir / f"{snap['ts'].replace(':', '').replace('-', '')}_{args.series}.json"
            apath.write_text(json.dumps({"ts": snap["ts"], "series": args.series,
                                         "target_date": args.target,
                                         "threshold": threshold, "rows": alerts}, indent=1))
            print(f"ALERT: {len(alerts)} strikes with edge >= {threshold} -> {apath}")


MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def target_to_ticker_date(target: str) -> str | None:
    """'2026-09-27' -> '26SEP27' (Kalshi ticker date fragment)."""
    try:
        d = dt.date.fromisoformat(target)
    except ValueError:
        return None
    return f"{d.year % 100:02d}{MONTHS[d.strftime('%b').upper()]}{d.day:02d}"


async def settled_print_bracket(series: str, target: str) -> dict | None:
    """Realized print bracket for target date from the series' settled ladder.

    Returns {"lo": x, "hi": y, "mid": m} where the print is in (lo, hi]
    (max settled-YES strike < print <= min settled-NO strike), or None.
    """
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    from src.clients.kalshi_client import KalshiClient
    day = target_to_ticker_date(target)
    if day is None:
        return None
    c = KalshiClient()
    try:
        r = await c.get_markets(series_ticker=series, status="settled", limit=200)
        mks = r.get("markets", r) if isinstance(r, dict) else r
        yes_strikes, no_strikes = [], []
        for m in mks:
            if not m.get("ticker", "").split("-")[1].startswith(day):
                continue
            strike = parse_strike(m["ticker"])
            if strike is None:
                continue
            (yes_strikes if m.get("result") == "yes" else no_strikes).append(strike)
        if not yes_strikes or not no_strikes:
            return None
        lo, hi = max(yes_strikes), min(no_strikes)
        if lo >= hi:
            return None
        return {"lo": lo, "hi": hi, "mid": (lo + hi) / 2}
    finally:
        await c.close()


def fit_path_model(deltas: list[float], excess_gap_cents: float | None,
                   current_streak: int = 0) -> dict:
    """Multi-day path model for weekly/monthly print ladders.

    Daily delta distribution = empirical consecutive-print changes; the drift
    is max(empirical mean, -convergence_rate) where the convergence rate is
    min(2.2c/day, 0.03 * excess_gap_cents) while the retail-vs-wholesale gap
    is elevated (the 2026-09-26 lesson: gap closing runs ~2c/day historically).
    Pure; tested.
    """
    import numpy as np
    arr = np.asarray(deltas, dtype=float)
    emp_drift = float(arr.mean())
    drift = emp_drift
    if excess_gap_cents is not None and excess_gap_cents > 5:
        conv = -min(2.2, 0.03 * excess_gap_cents)
        drift = min(emp_drift, conv)
    return {"deltas": arr, "drift_c": drift, "emp_drift_c": emp_drift}


def path_mcs(model: dict, days: int, n_sims: int = 20000, seed: int = 3) -> "object":
    """Simulate cumulative print changes over `days`; returns the array."""
    import numpy as np
    rng = np.random.default_rng(seed)
    samp = model["deltas"][rng.integers(0, len(model["deltas"]), size=(n_sims, days))]
    drift_adj = model["drift_c"] - model["emp_drift_c"]
    return np.cumsum(samp + drift_adj, axis=1)


def cmd_path(series: str, target_date: str) -> int:
    """Price weekly/monthly print ladders with the wholesale-convergence path model."""
    import asyncio
    import datetime as dt
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    from src.clients.kalshi_client import KalshiClient
    import aaa_futures

    retail_col = "diesel"
    rows = aaa_data.load_csv()
    seq = aaa_data.build_print_series(rows, value_col=retail_col)
    if not seq:
        print("no AAA series", file=sys.stderr)
        return 1
    deltas = [s["delta_cents"] for s in seq]
    cur = seq[-1]["value"]
    # horizon: days until the target print (inclusive count of prints ahead)
    target = dt.date.fromisoformat(target_date)
    last_date = dt.date.fromisoformat(seq[-1]["date"])
    horizon = max((target - last_date).days, 1)
    # days until the target print: the value published ON target_date is
    # horizon prints after the last known print
    sym = "HO=F"
    wholesale = aaa_futures.convergence(rows, sym, retail_col)
    excess = (wholesale or {}).get("excess_gap_cents")
    model = fit_path_model(deltas, excess)
    print(f"cur {cur} ({seq[-1]['date']}), horizon {horizon} prints to {target_date}, "
          f"drift {model['drift_c']:+.2f}c/day (emp {model['emp_drift_c']:+.2f}, excess gap {excess}c)")
    cum_dollars = path_mcs(model, horizon) / 100.0  # model deltas are in cents
    async def run():
        c = KalshiClient()
        r = await c.get_markets(series_ticker=series, status="open", limit=200)
        mks = r.get("markets", r) if isinstance(r, dict) else r
        out_rows = []
        for m in sorted(mks, key=lambda x: parse_strike(x["ticker"]) or 0):
            strike = parse_strike(m["ticker"])
            if strike is None:
                continue
            fair_yes = float((cur + cum_dollars[:, -1] > strike).mean())
            book = await fetch_book(c, m["ticker"])
            e = fee_aware_edges(fair_yes, book)
            out_rows.append({"ticker": m["ticker"], "strike": strike,
                             "fair_yes": round(fair_yes, 4), **book, **e})
        await c.close()
        return out_rows
    rows_out = asyncio.run(run())
    rows_out.sort(key=lambda r: -abs(max(r["buy_yes_edge"], r["buy_no_edge"])))
    print(f"{'ticker':36s} {'fairYES':>8s} {'bid':>5s} {'ask':>5s} {'edgeY':>8s} {'edgeN':>8s}")
    for r in rows_out[:14]:
        print(f"{r['ticker']:36s} {r['fair_yes']:8.3f} {r['yes_bid']:5.2f} {r['yes_ask']:5.2f} "
              f"{r['buy_yes_edge']:+8.3f} {r['buy_no_edge']:+8.3f}")
    PRICINGS_DIR.mkdir(parents=True, exist_ok=True)
    snap = {"ts": dt.datetime.now(dt.UTC).isoformat(), "series": series,
            "target_date": target_date, "model": "convergence_path",
            "last_print": cur, "horizon": horizon, "excess_gap_cents": excess,
            "rows": rows_out}
    path = PRICINGS_DIR / f"{snap['ts'].replace(':', '').replace('-', '')}_{series}_path.json"
    path.write_text(json.dumps(snap, indent=1))
    print(f"snapshot -> {path}")
    return 0


def cmd_score() -> int:
    """Score saved pricing snapshots against realized prints (forward-only).

    Realized print precedence: (1) Kalshi's settled strike bracket for the
    target date (authoritative, 0.5c precision — the source the market itself
    resolved on), (2) the AAA series page value for that date. If neither is
    available the snapshot is pending and skipped. Writes/updates
    data/aaa/scores.jsonl with per-strike Brier for the model fair and the book
    mid, so model-vs-book calibration accumulates over time.
    """
    # realized values are PER-SERIES: diesel series resolve on the national
    # diesel column, national-gas on the national REGULAR column, state series
    # on that state's REGULAR column. Mixing them manufactures bogus scores
    # (2026-09-27 bug: state gas strikes scored against the national diesel).
    nat_rows = aaa_data.load_csv()
    realized_diesel, realized_regular = {}, {}
    for date, r in nat_rows.items():
        try:
            realized_diesel[date] = float(r["diesel"])
        except (TypeError, ValueError):
            pass
        try:
            realized_regular[date] = float(r["regular"])
        except (TypeError, ValueError):
            pass
    state_realized = {}
    for st in ("NV", "WA", "OR", "MA", "NJ", "CA", "AZ", "CO", "CT", "FL", "GA",
               "IL", "MI", "MN", "NC", "NY", "OH", "PA", "TX", "VA", "WI"):
        vals = {}
        for date, r in aaa_data.load_state(st).items():
            try:
                vals[date] = float(r["regular"])
            except (TypeError, ValueError):
                pass
        state_realized[st] = vals

    def realized_for(series: str, target: str):
        if series.startswith("KXAAAGASD") and len(series) > len("KXAAAGASD"):
            st = series[len("KXAAAGASD"):len("KXAAAGASD") + 2]
            return state_realized.get(st, {}).get(target), "state_page"
        if "GAS" in series.upper():
            return realized_regular.get(target), "aaa_page_regular"
        return realized_diesel.get(target), "aaa_page_diesel"

    scores = []
    for path in sorted(PRICINGS_DIR.glob("*.json")):
        try:
            snap = json.loads(path.read_text())
        except Exception:
            continue
        target = snap.get("target_date")
        actual = None
        source = None
        page_val, page_src = realized_for(snap.get("series", ""), target)
        if page_val is not None:
            actual, source = page_val, page_src
        else:
            try:
                bracket = asyncio.run(settled_print_bracket(snap.get("series", ""), target))
            except Exception:
                bracket = None
            if bracket:
                actual, source = bracket["mid"], f"settled_bracket({bracket['lo']},{bracket['hi']}]"
        if actual is None:
            continue
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
                "source": source,
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
    p.add_argument("--retail", choices=["diesel", "regular"], default=None,
                   help="AAA column to model (default: regular for *GAS*, diesel otherwise)")
    p.add_argument("--alert-min", type=float, default=None,
                   help="write an alerts JSON for strikes with |edge| >= this (e.g. 0.10)")
    sub.add_parser("score")
    pp = sub.add_parser("path")
    pp.add_argument("--series", default="KXDIESELMON")
    pp.add_argument("--target", required=True)
    args = ap.parse_args()
    if args.cmd == "price":
        raise SystemExit(cmd_price(args))
    if args.cmd == "score":
        raise SystemExit(cmd_score())
    if args.cmd == "path":
        raise SystemExit(cmd_path(args.series, args.target))


if __name__ == "__main__":
    main()
