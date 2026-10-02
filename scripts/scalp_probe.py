#!/usr/bin/env python
"""Measure enumeration cost: events vs markets, one day (Sep 20)."""
import asyncio, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
from src.clients.kalshi_client import KalshiClient

async def main():
    c = KalshiClient()
    lo = int(datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp())
    hi = lo + 86400
    # events
    t0 = time.time(); pages = 0; n = 0; cur = None; mve_events = 0
    while True:
        p = {"status": "settled", "limit": 200, "min_close_ts": lo, "max_close_ts": hi}
        if cur: p["cursor"] = cur
        r = await c._make_authenticated_request("GET", "/trade-api/v2/events", params=p)
        evs = r.get("events", [])
        n += len(evs)
        mve_events += sum(1 for e in evs if e.get("event_ticker","").startswith("KXMVECROSSCATEGORY"))
        pages += 1
        cur = r.get("cursor")
        if not cur or not evs or pages > 60: break
    print(f"EVENTS Sep20: pages={pages} events={n} mve={mve_events} elapsed={round(time.time()-t0,1)}s")
    # markets
    t0 = time.time(); pages = 0; n = 0; cur = None; mve = 0; traded = 0
    while True:
        p = {"status": "settled", "limit": 1000, "min_close_ts": lo, "max_close_ts": hi}
        if cur: p["cursor"] = cur
        r = await c._make_authenticated_request("GET", "/trade-api/v2/markets", params=p)
        ms = r.get("markets", [])
        n += len(ms)
        for m in ms:
            pre = m["ticker"].split("-")[0]
            if pre == "KXMVECROSSCATEGORY": mve += 1
            elif (m.get("volume_fp") or 0) != 0 and float(m.get("volume_fp") or 0) > 0: traded += 1
        pages += 1
        cur = r.get("cursor")
        if not cur or not ms or pages > 60: break
    print(f"MARKETS Sep20: pages={pages} markets={n} mve={mve} traded={traded} elapsed={round(time.time()-t0,1)}s")
    await c.close()

asyncio.run(main())
