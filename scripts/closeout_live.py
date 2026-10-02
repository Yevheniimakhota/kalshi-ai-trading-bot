#!/usr/bin/env python3
"""LIVE gated close-out pilot (small, capped, autonomous).

Buys 5 contracts (taker, at the ask) on strikes that pass ALL of:
  * model fair >= 0.995        (the pricer's own near-certainty)
  * ask in [0.90, 0.98]        (a genuine close-out price, not a phantom gap)
  * spread <= 0.25             (a real two-sided book)
  * the series has no open pilot fill today (max 1 new fill/series/day)

Caps: <= 3 new fills per invocation, <= 3 invocations/day => worst case
$15/day risk (1.6% of equity). Journal + commit every action.

Usage: python scripts/closeout_live.py [--dry]
"""
import argparse
import asyncio
import json
import math
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")
from src.clients.kalshi_client import KalshiClient

PRICINGS = REPO / "data" / "aaa" / "pricings"
JOURNAL = REPO / "data" / "runtime" / "decision_journal.jsonl"
STATE = REPO / "data" / "runtime" / "closeout_live.jsonl"
CLIP = 5
MAX_FILLS_PER_RUN = 3
DAILY_FILL_LIMIT = 6


def log(action: str, ticker: str, text: str) -> None:
    e = {"ts": datetime.now(timezone.utc).isoformat(), "action": action,
         "ticker": ticker, "rationale": text}
    with open(JOURNAL, "a") as f:
        f.write(json.dumps(e) + "\n")
    print(text)


def today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_state() -> dict:
    done_tickers = set()
    fills_today = 0
    if STATE.exists():
        for line in STATE.open():
            try:
                e = json.loads(line)
            except Exception:
                continue
            done_tickers.add(e["ticker"])
            if e["ts"][:10] == today_key():
                fills_today += 1
    return done_tickers, fills_today


def candidates() -> list:
    snaps = {}
    for p in sorted(PRICINGS.glob("*.json")):
        try:
            s = json.loads(p.read_text())
        except Exception:
            continue
        if s.get("rows") and s["target_date"]:
            snaps[s["series"]] = s
    today = datetime.now(timezone.utc).date().isoformat()
    out = []
    for series, s in snaps.items():
        if s["target_date"] < today:
            continue  # market already settled/removed - 404 source
        for r in s["rows"]:
            fair, ask, bid = r.get("fair_yes"), r.get("yes_ask"), r.get("yes_bid")
            if None in (fair, ask, bid):
                continue
            spread = ask - bid
            if fair >= 0.995 and 0.90 <= ask <= 0.98 and spread <= 0.25:
                out.append({"ticker": r["ticker"], "series": series,
                            "target": s["target_date"], "ask": ask, "fair": fair})
    out.sort(key=lambda x: -(x["fair"] - x["ask"]))
    return out


async def main(dry: bool) -> None:
    done_tickers, fills_today = load_state()
    cands = [c for c in candidates() if c["ticker"] not in done_tickers]
    print(f"{len(cands)} candidates (fills today: {fills_today}/{DAILY_FILL_LIMIT})")
    if dry or fills_today >= DAILY_FILL_LIMIT:
        return
    c = KalshiClient()
    n = 0
    for cand in cands:
        if n >= MAX_FILLS_PER_RUN or fills_today >= DAILY_FILL_LIMIT:
            break
        coid = f"closeout-{uuid.uuid4().hex[:10]}"
        try:
            r = await c.place_order(cand["ticker"], coid, side="yes", action="buy",
                                    count=CLIP, type_="limit",
                                    yes_price=int(cand["ask"] * 100))
            filled = float(r.get("order", r).get("fill_count") or 0)
            remaining = float(r.get("order", r).get("remaining_count") or 0)
            e = {"ts": datetime.now(timezone.utc).isoformat(), "ticker": cand["ticker"],
                 "series": cand["series"], "target": cand["target"],
                 "entry": cand["ask"], "fair": cand["fair"], "qty": CLIP,
                 "filled": filled, "remaining": remaining,
                 "order_id": r.get("order", r).get("order_id"), "status": "placed"}
            with open(STATE, "a") as f:
                f.write(json.dumps(e) + "\n")
            fills_today += 1 if filled > 0 else 0
            n += 1
            log("order-placed", cand["ticker"],
                f"closeout pilot: {CLIP} YES @ {cand['ask']:.2f} (fair {cand['fair']:.3f}, "
                f"target {cand['target']}), filled {filled}, resting {remaining}")
        except Exception as ex:
            log("order-error", cand["ticker"], f"closeout pilot error: {str(ex)[:160]}")
    await c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.dry))
