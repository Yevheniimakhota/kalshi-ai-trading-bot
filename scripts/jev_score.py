#!/usr/bin/env python3
"""Score the Jev forward-pricing log against settled markets.

``data/runtime/jev_forward_log.jsonl`` records pricing events (one row per
market): the agent model's P(YES), Jev's P(YES), and the live book
(yes_ask / no_ask). Nothing scored it — until settlements land, the sample is
write-only. This tool:

  1. groups the log's tickers by series and pulls each series' settled markets
     from Kalshi once (cached in data/runtime/jev_settled_cache.json),
  2. matches each log entry to its settled result (exact ticker, else the
     series' strike bracket nearest the ticker's strike),
  3. appends per-entry score rows to data/runtime/jev_scores.jsonl (idempotent:
     already-scored tickers are skipped),
  4. prints Brier/logloss for the agent model vs Jev vs the book mid.

Only forward-settled rows count (the market settled strictly after the pricing
event, which the log guarantees by construction since results are fetched
afterwards). Unsettled entries stay pending.

Usage:
  python scripts/jev_score.py [--dry]   # --dry: report without writing
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG_PATH = REPO / "data" / "runtime" / "jev_forward_log.jsonl"
SCORES_PATH = REPO / "data" / "runtime" / "jev_scores.jsonl"
CACHE_PATH = REPO / "data" / "runtime" / "jev_settled_cache.json"

MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def series_of(ticker: str) -> str | None:
    parts = ticker.split("-")
    return parts[0] if parts else None


def parse_strike(ticker: str) -> float | None:
    tail = ticker.rsplit("-", 1)[-1]
    try:
        return float(tail[1:] if tail.startswith("T") else tail)
    except ValueError:
        return None


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, indent=1))


def extract_settled(mks) -> dict[str, dict]:
    """{ticker: {result, strike}} from a settled-markets payload. Pure; tested."""
    results = {}
    for m in mks:
        res = m.get("result")
        if res not in ("yes", "no"):
            continue
        results[m["ticker"]] = {"result": res, "strike": parse_strike(m["ticker"])}
    return results


async def pull_all(series_list) -> dict[str, dict[str, dict]]:
    """Fetch settled markets for each series once (uses the per-series cache)."""
    from src.clients.kalshi_client import KalshiClient
    cache = load_cache()
    # empty cached results mean an earlier failed fetch: refetch them
    missing = [s for s in series_list if not cache.get(s)]
    fetched = {}
    if missing:
        c = KalshiClient()
        for s in missing:
            try:
                r = await c.get_markets(series_ticker=s, status="settled", limit=200)
                fetched[s] = extract_settled(r.get("markets", r) if isinstance(r, dict) else r)
            except Exception as e:
                print(f"series {s}: fetch failed ({e})", file=sys.stderr)
                # do NOT cache failures - the next run retries them
                continue
        await c.close()
    return {**fetched, **{s: cache[s] for s in series_list if s in cache}}


def resolve_entry(entry: dict, by_series: dict[str, dict[str, dict]]) -> dict | None:
    """Attach the settled outcome to one log entry, or None if unresolved."""
    t = entry["ticker"]
    series = series_of(t)
    results = by_series.get(series, {})
    if t in results:
        return results[t]
    # strike-ladder fallback: exact ticker absent but the series settled around it
    strike = parse_strike(t)
    if strike is None:
        return None
    yes_max, no_min = None, None
    for tk, res in results.items():
        if not tk.startswith(series + "-"):
            continue
        tparts = t.split("-")
        day = tk.split("-")[1] if len(tk.split("-")) > 1 else ""
        if day and len(tparts) > 1 and day != tparts[1]:
            continue
        s = res["strike"]
        if s is None:
            continue
        if res["result"] == "yes":
            yes_max = s if yes_max is None else max(yes_max, s)
        else:
            no_min = s if no_min is None else min(no_min, s)
    if yes_max is None or no_min is None or yes_max >= no_min:
        return None
    return {"result": "bracket", "lo": yes_max, "hi": no_min, "strike": strike}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if not LOG_PATH.exists():
        print("no forward log yet")
        return 0
    entries = [json.loads(line) for line in LOG_PATH.open() if line.strip()]
    scored_keys = set()
    if SCORES_PATH.exists():
        for line in SCORES_PATH.open():
            try:
                scored_keys.add(json.loads(line)["ticker"])
            except Exception:
                continue
    sys.path.insert(0, str(REPO))
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    import asyncio

    series_list = sorted({series_of(e["ticker"]) for e in entries if series_of(e["ticker"])})
    try:
        by_series = asyncio.run(pull_all(series_list))
        save_cache(by_series)
    except Exception as e:
        print(f"settled fetch failed: {e}", file=sys.stderr)
        by_series = {}
    # score
    new_scores = []
    for e in entries:
        t = e["ticker"]
        if t in scored_keys:
            continue
        res = resolve_entry(e, by_series)
        if res is None:
            continue
        if res.get("result") == "bracket":
            y = None  # bracket: strike inside (lo, hi] -> use strike vs bracket only if asked
            # P(YES)=1 if strike <= lo (strike at/below the settled YES max)
            y = 1 if e.get("model_p_yes") is not None and res["strike"] is not None and res["strike"] <= res["lo"] else 0
            actual = f"bracket({res['lo']},{res['hi']}]"
        else:
            y = 1 if res["result"] == "yes" else 0
            actual = res["result"]
        book_mid = None
        ya, na = e.get("yes_ask"), e.get("no_ask")
        if ya is not None and na is not None and na is not None:
            book_mid = (ya + (1 - na)) / 2
        row = {"ticker": t, "ts": e.get("ts"), "family": e.get("family", "")[:80],
               "y": y, "actual": actual,
               "model_p_yes": e.get("model_p_yes"), "jev_p_yes": e.get("jev_p_yes"),
               "book_mid": round(book_mid, 4) if book_mid is not None else None,
               "yes_ask": ya, "no_ask": na}
        new_scores.append(row)
    if not new_scores:
        print(f"nothing new scored ({len(scored_keys)} already scored; rest pending)")
        return 0
    import numpy as np
    def brier(ps):
        ys = np.array([s["y"] for s in new_scores])
        ps = np.clip(np.array(ps), 0, 1)
        return float(((ps - ys) ** 2).mean())
    def logloss(ps):
        ys = np.array([s["y"] for s in new_scores])
        ps = np.clip(np.array(ps), 1e-6, 1 - 1e-6)
        return float(-(ys * np.log(ps) + (1 - ys) * np.log(1 - ps)).mean())
    cols = {}
    if all(s.get("model_p_yes") is not None for s in new_scores):
        cols["model"] = (brier([s["model_p_yes"] for s in new_scores]),
                         logloss([s["model_p_yes"] for s in new_scores]))
    if all(s.get("jev_p_yes") is not None for s in new_scores):
        cols["jev"] = (brier([s["jev_p_yes"] for s in new_scores]),
                       logloss([s["jev_p_yes"] for s in new_scores]))
    if all(s.get("book_mid") is not None for s in new_scores):
        cols["book"] = (brier([s["book_mid"] for s in new_scores]),
                        logloss([s["book_mid"] for s in new_scores]))
    print(f"scored {len(new_scores)} new (total scored {len(scored_keys) + len(new_scores)})")
    for name, (br, ll) in cols.items():
        print(f"  {name:5s} Brier {br:.4f}  logloss {ll:.4f}")
    if not args.dry:
        with SCORES_PATH.open("a") as f:
            for s in new_scores:
                f.write(json.dumps(s) + "\n")
        print(f"appended -> {SCORES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
