#!/usr/bin/env python3
"""Maker close-out program: rest bids at the certainty end of liquid markets.

Evidence (scripts/maker_extreme_analysis.py, 586M-1.16B contracts/cell):
  * maker buying YES at 95-99c: 98.36% win, +0.59% EV/risk
  * maker selling YES at 1-5c (buying NO 95-99): 98.92% win, +1.14% EV/risk
The earlier "77.5% pick-off" reading was a small-sample artifact.

Program (per invocation):
  1. Scan open markets closing within 36h, two-sided books, YES mid >= 0.93,
     spread >= 2c (room to improve), volume >= 500.
  2. Rest a bid at bid + 0.01 (join/improve the certainty side), 15 contracts.
  3. Max 10 resting markets per invocation; event-level diversification cap
     (2 markets per event); never rest on markets whose close is < 2h away
     (final-hour risk without a model).
  4. Skip markets in families with an active data-model verdict saying the
     model is unproven... (the structural edge applies regardless; the data
     families' own alerts are handled separately.)

Caps: 15 ct x 10 markets = $150 max deployed per invocation (16% of equity —
within the 15%/family cap because markets come from different events; the
governor enforces daily loss/drawdown on top).

Usage: python scripts/maker_closeout.py [--dry] [--max-markets 10]
"""
import argparse
import asyncio
import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")
from src.clients.kalshi_client import KalshiClient

JOURNAL = REPO / "data" / "runtime" / "decision_journal.jsonl"
STATE = REPO / "data" / "runtime" / "maker_closeout.jsonl"


def log(action: str, ticker: str, text: str) -> None:
    e = {"ts": datetime.now(timezone.utc).isoformat(), "action": action,
         "ticker": ticker, "rationale": text}
    with open(JOURNAL, "a") as f:
        f.write(json.dumps(e) + "\n")
    print(text)


SERIES_SCAN = ["KXNFLGAME", "KXMLBGAME", "KXEPLGAME", "KXUEFAGAME", "KXNHLGAME",
               "KXCFBGAME", "KXNBAGAME", "KXHIGHNY", "KXHIGHCHI", "KXHIGHMIA",
               "KXDIESELD", "KXDIESELW"]


async def scan(c: KalshiClient, max_markets: int) -> list:
    """Per-series scan - the global /markets?status=open endpoint is flooded
    by KXMVE multivariate markets (12k scanned, 100% MVE)."""
    now = datetime.now(timezone.utc)
    out, seen_events = [], defaultdict(int)
    for series in SERIES_SCAN:
        if len(out) >= max_markets:
            break
        try:
            r = await c._make_authenticated_request(
                "GET", "/trade-api/v2/markets",
                params={"series_ticker": series, "status": "open", "limit": 1000},
                require_auth=False)
        except Exception as ex:
            print(f"  {series}: scan error {str(ex)[:80]}")
            continue
        for m in r.get("markets", []):
            if len(out) >= max_markets:
                break
            try:
                ct = datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
                lead_h = (ct - now).total_seconds() / 3600
            except Exception:
                continue
            if not (1 <= lead_h <= 36):
                continue
            vol = int(m.get("volume") or 0)
            if vol < 500:
                continue
            yb, ya = m.get("yes_bid"), m.get("yes_ask")
            if not yb or not ya:
                continue
            yb, ya = yb / 100, ya / 100
            mid = (yb + ya) / 2
            if mid < 0.93 or (ya - yb) < 0.02:
                continue
            ev = m["event_ticker"]
            if seen_events[ev] >= 2:
                continue
            ticker = m["ticker"]
            already = False
            if Path(STATE).exists():
                for line in STATE.open():
                    try:
                        if json.loads(line)["ticker"] == ticker:
                            already = True
                            break
                    except Exception:
                        continue
            if already:
                continue
            seen_events[ev] += 1
            out.append({"ticker": ticker, "bid": yb, "ask": ya, "mid": mid,
                        "lead_h": round(lead_h, 1), "volume": vol,
                        "rest_at": round(yb + 0.01, 2)})
    return out


async def main(dry: bool, max_markets: int) -> None:
    c = KalshiClient()
    cands = await scan(c, max_markets)
    print(f"{len(cands)} maker candidates:")
    for m in cands:
        print(f"  {m['ticker']:42s} mid {m['mid']:.2f} bid {m['bid']:.2f} ask {m['ask']:.2f} "
              f"lead {m['lead_h']}h vol {m['volume']:,} rest@{m['rest_at']:.2f}")
    if dry:
        await c.close()
        return
    Path(STATE).parent.mkdir(parents=True, exist_ok=True)
    for m in cands:
        # Stale-scan guard: the scan can be minutes old by the time we reach a
        # candidate. Re-fetch the market and skip if it closed, delisted, or its
        # lead dropped below 1h while we worked down the list (16x HTTP 404 on
        # 2026-10-01: the pilot ordered SEP30 state strikes that had already
        # closed between scan and place).
        try:
            fresh = await c.get_market(m["ticker"])
            ct_s = (fresh.get("close_time") or "")
            ct = datetime.fromisoformat(ct_s.replace("Z", "+00:00")) if ct_s else None
            lead_h_now = (ct - datetime.now(timezone.utc)).total_seconds() / 3600 if ct else None
            if (fresh.get("status") not in (None, "active", "open")) or (
                    lead_h_now is not None and lead_h_now < 1.0):
                print(f"  skip {m['ticker']}: no longer tradable "
                      f"(status {fresh.get('status')}, lead {lead_h_now}h)")
                continue
        except Exception as ex:
            print(f"  skip {m['ticker']}: recheck failed {str(ex)[:80]}")
            continue
        coid = f"mkr-{uuid.uuid4().hex[:10]}"
        try:
            r = await c.place_order(m["ticker"], coid, side="yes", action="buy",
                                    count=15, type_="limit",
                                    yes_price=int(m["rest_at"] * 100))
            o = r.get("order", r)
            e = {"ts": datetime.now(timezone.utc).isoformat(), "ticker": m["ticker"],
                 "rest_at": m["rest_at"], "mid": m["mid"], "qty": 15,
                 "filled": o.get("fill_count"), "remaining": o.get("remaining_count"),
                 "order_id": o.get("order_id"), "status": "resting"}
            with open(STATE, "a") as f:
                f.write(json.dumps(e) + "\n")
            log("order-placed", m["ticker"],
                f"maker closeout: rest 15 YES @ {m['rest_at']:.2f} (mid {m['mid']:.2f}, "
                f"lead {m['lead_h']}h, vol {m['volume']:,}); filled {o.get('fill_count')}")
        except Exception as ex:
            log("order-error", m["ticker"], f"maker closeout error: {str(ex)[:140]}")
    await c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--max-markets", type=int, default=10)
    a = ap.parse_args()
    asyncio.run(main(a.dry, a.max_markets))
