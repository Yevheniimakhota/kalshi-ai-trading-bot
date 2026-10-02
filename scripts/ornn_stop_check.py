#!/usr/bin/env python3
"""ORNN Sep >$1.000 strike: print-contingent position management (autonomous).

Runs shortly after the 4pm-ET Ornn print. Logic (see decision journal 2026-09-28):
* fetch the fresh OCPI-A100 print + book;
* print >= 0.93  -> strike likely survives; rest a GTC sell on HALF the position
  at (model_fair - 5c, floor 0.30) to capture returning bids;
* print <= 0.88  -> strike effectively dead (needs the last two prints to average
  > 0.91 after 0.88); sell ALL into any YES bid >= 0.03;
* print 0.89-0.92 -> compute the exact remaining-print requirement, log it, and
  sell ALL only if a bid >= (model fair - 10c) exists; else hold and re-check.

This is real-money automation but ONLY for risk reduction on an existing
position; it never opens new risk. Ryan granted full autonomy 2026-09-28.
"""
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from dotenv import load_dotenv
load_dotenv(REPO / ".env")
from src.clients.kalshi_client import KalshiClient

import calendar
_NOW = datetime.now(timezone.utc)
_MON_ABBR = calendar.month_abbr[_NOW.month].upper()          # e.g. "OCT"
_MON_DAYS = calendar.monthrange(_NOW.year, _NOW.month)[1]
_MON_STR = f"{_NOW:%y%m}"[:2] + _MON_ABBR                    # e.g. "26OCT"
T = f"KXA100MS-26{_MON_ABBR}-1.000"                          # active month's mean>1.000 strike
JOURNAL = REPO / "data" / "runtime" / "decision_journal.jsonl"
GPU = "A100 SXM4"


def log(action: str, text: str) -> None:
    e = {"ts": datetime.now(timezone.utc).isoformat(), "action": action,
         "ticker": T, "rationale": text}
    with open(JOURNAL, "a") as f:
        f.write(json.dumps(e) + "\n")
    print(text)


def strike_math(prices: list[float]) -> dict:
    """Sep mean-so-far and the remaining-prints requirement for the >1.000 strike.

    Counts prints IN SEPTEMBER (month days 1..30), not a trailing window — the
    remaining-prints count must be 30 minus the September prints done, else the
    requirement drifts as the window slides (bug found 2026-09-28: window said 3
    remaining when only 2 prints were left).
    """
    d = json.load(open(REPO / "data" / "ornn" / "a100-sxm4.json"))["data"]
    seen = set()
    sep = []
    mon_prefix = f"{_NOW:%Y-%m}"                                # e.g. "2026-10"
    for x in d:
        day = x["timestamp"][:10]
        if day.startswith(mon_prefix) and day not in seen:
            seen.add(day)
            sep.append(x["index_value"])
    n = _MON_DAYS
    msf = sum(sep) / len(sep) if sep else 0.0
    remaining = n - len(sep)
    # need (n - len(sep)*msf) total over remaining prints for mean > 1.000
    need = float(n) - len(sep) * msf
    return {"sep_n": len(sep), "mean_ms": msf, "remaining": remaining,
            "need_sum": need, "need_avg": need / remaining if remaining else None,
            "resolved": remaining <= 0}


async def main() -> None:
    c = KalshiClient()
    # fresh print
    out = await asyncio.create_subprocess_exec(
        ".venv/bin/python", "scripts/ornn_data.py", "fetch",
        cwd=REPO, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    await out.wait()
    d = json.load(open(REPO / "data" / "ornn" / "a100-sxm4.json"))["data"]
    seen = set()
    series = []
    for x in d:
        day = x["timestamp"][:10]
        if day not in seen:
            seen.add(day)
            series.append(x["index_value"])
    last = series[-1]
    m = strike_math(series)
    print(f"print {last}; month mean {m['mean_ms']:.5f} ({m['sep_n']} prints); remaining {m['remaining']} "
          + (f"need avg {m['need_avg']:.4f}" if m["remaining"] else f"RESOLVED (final mean {m['mean_ms']:.5f} vs 1.000)"))
    if m.get("resolved"):
        log("stop-checked", f"{T} resolved: final month mean {m['mean_ms']:.5f} "
            f"({'>' if m['mean_ms'] > 1.0 else '<'} 1.000) - strike "
            f"{'WINS' if m['mean_ms'] > 1.0 else 'loses'}; no book action on a settled market.")
        await c.close()
        return

    ob = await c.get_orderbook(T, depth=20)
    fp = ob.get("orderbook_fp", ob)
    yb = sorted([(float(p), float(q)) for p, q in (fp.get("yes_dollars") or [])])
    best_bid = yb[-1][0] if yb else 0.0
    pos = await c.get_positions()
    mine = [p for p in pos.get("market_positions", []) if p["ticker"] == T]
    held = float(mine[0]["position_fp"]) if mine else 0.0
    print(f"book: YES bid {best_bid}; held {held}")

    if held <= 0:
        await c.close()
        return
    if last >= 0.93:
        sell_n = min(held / 2, held) if held >= 4 else held
        px = max(0.30, round(best_bid, 2)) if best_bid > 0.05 else 0.30
        coid = f"ornn-stop-{uuid.uuid4().hex[:10]}"
        r = await c.place_order(T, coid, side="yes", action="sell", count=int(sell_n),
                                type_="limit", yes_price=int(px * 100))
        log("order-placed",
            f"print {last} >= 0.93: strike alive (need avg {m['need_avg']:.3f} vs "
            f"last {last}); resting GTC sell {int(sell_n)} YES @ {px:.2f} "
            f"(book bid {best_bid}). resp={json.dumps(r)[:200]}")
    elif last <= 0.88:
        if best_bid >= 0.03:
            coid = f"ornn-stop-{uuid.uuid4().hex[:10]}"
            r = await c.place_order(T, coid, side="yes", action="sell",
                                    count=int(held), type_="limit",
                                    yes_price=max(3, int(best_bid * 100)))
            log("order-placed",
                f"print {last} <= 0.88: strike dead (need avg {m['need_avg']:.3f}); "
                f"selling all {int(held)} into bid {best_bid}")
        else:
            log("stop-checked",
                f"print {last} <= 0.88 but NO YES bid (book bid {best_bid}) - "
                f"cannot exit; holding to settlement, will re-check hourly")
    else:
        if best_bid >= m["need_avg"] - 0.10 and best_bid >= 0.20:
            coid = f"ornn-stop-{uuid.uuid4().hex[:10]}"
            r = await c.place_order(T, coid, side="yes", action="sell",
                                    count=int(held), type_="limit",
                                    yes_price=max(3, int(best_bid * 100)))
            log("order-placed",
                f"print {last} (0.89-0.92 band): need avg {m['need_avg']:.3f}, bid "
                f"{best_bid} >= fair-10c; selling all {int(held)}")
        else:
            log("stop-checked",
                f"print {last} (0.89-0.92 band): need avg {m['need_avg']:.3f} from "
                f"{m['remaining']} prints; book bid {best_bid} below threshold - HOLD")
    await c.close()


if __name__ == "__main__":
    asyncio.run(main())
