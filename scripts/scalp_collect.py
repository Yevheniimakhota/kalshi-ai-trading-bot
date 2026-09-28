#!/usr/bin/env python
"""Collect settled-market universe + 1-min candlesticks for the close-out scalp study.

READ-ONLY (GET endpoints only). Caches under data/runtime/scalp_study/.
Universe: settled markets with volume>0, close_time in [2026-09-14, 2026-09-26) UTC.
Skips KXMVECROSSCATEGORY multivariate junk markets.
"""
import asyncio, collections, json, os, random, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()
from src.clients.kalshi_client import KalshiClient

OUT = Path("data/runtime/scalp_study")
OUT.mkdir(parents=True, exist_ok=True)
DAYDIR = OUT / "days"
DAYDIR.mkdir(exist_ok=True)
CANDLES = OUT / "candles"
CANDLES.mkdir(exist_ok=True)
CATMAP = OUT / "series_category.json"


def vol(m):
    try:
        return float(m.get("volume_fp") or 0)
    except Exception:
        return 0.0


def ts_of(s):
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def row_of(m):
    return {
        "ticker": m["ticker"], "event": m.get("event_ticker"),
        "series": m["ticker"].split("-")[0], "close_time": m.get("close_time"),
        "open_time": m.get("open_time"),
        "result": m.get("result"), "volume": vol(m),
        "last_price": float(m.get("last_price_dollars") or 0),
        "close_ts": ts_of(m["close_time"]) if m.get("close_time") else None,
    }


async def collect_day(c, day):
    fp = DAYDIR / f"day_{day:02d}.jsonl"
    if fp.exists():
        return [json.loads(l) for l in fp.read_text().splitlines() if l.strip()]
    lo = datetime(2026, 9, day, 0, 0, tzinfo=timezone.utc)
    hi = lo + timedelta(days=1)
    rows, cur, mve = [], None, 0
    while True:
        p = {"status": "settled", "limit": 1000,
             "min_close_ts": int(lo.timestamp()), "max_close_ts": int(hi.timestamp())}
        if cur:
            p["cursor"] = cur
        r = await c._make_authenticated_request("GET", "/trade-api/v2/markets", params=p)
        got = r.get("markets", [])
        for m in got:
            if m["ticker"].split("-")[0] == "KXMVECROSSCATEGORY":
                mve += 1
                continue
            if vol(m) <= 0:
                continue
            rows.append(row_of(m))
        cur = r.get("cursor")
        if not cur or not got:
            break
    with fp.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"day Sep {day:02d}: kept={len(rows)} mve_skipped={mve}", flush=True)
    return rows


def build_sample(rows):
    """~3.5k bounded sample: per (series,day) top-volume anchor + random stratified pools."""
    by_sd = collections.defaultdict(list)
    for r in rows:
        d = datetime.fromtimestamp(r["close_ts"], tz=timezone.utc).strftime("%m%d")
        by_sd[(r["series"], d)].append(r)
    anchors = []
    for (series, d), ms in sorted(by_sd.items()):
        ms.sort(key=lambda m: -m["volume"])
        anchors.append(ms[0])
    big = [r for r in rows if r["volume"] >= 1000]
    mid = [r for r in rows if 100 <= r["volume"] < 1000]
    rng = random.Random(7)
    picks = {r["ticker"]: r for r in anchors}
    for r in rng.sample(big, min(1500, len(big))):
        picks[r["ticker"]] = r
    for r in rng.sample(mid, min(1000, len(mid))):
        picks[r["ticker"]] = r
    out = list(picks.values())
    rng.shuffle(out)
    print(f"SAMPLE anchors={len(anchors)} big_pool={len(big)} mid_pool={len(mid)} -> {len(out)}", flush=True)
    return out


async def pull_candles(c, m, sem):
    fp = CANDLES / (m["ticker"] + ".json")
    if fp.exists():
        return "cached"
    async with sem:
        start_ts = m["close_ts"] - 48 * 3600
        end_ts = m["close_ts"]
        out, cur, pages = [], None, 0
        while True:
            p = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": 1}
            if cur:
                p["cursor"] = cur
            try:
                r = await c._make_authenticated_request(
                    "GET", f"/trade-api/v2/series/{m['series']}/markets/{m['ticker']}/candlesticks", params=p)
            except Exception as e:
                fp.write_text(json.dumps({"ticker": m["ticker"], "error": str(e)[:200]}))
                return "error"
            out += r.get("candlesticks", [])
            cur = r.get("cursor")
            pages += 1
            if not cur or pages > 12:
                break
        compact = []
        for k in out:
            pr = k.get("price") or {}
            yb, ya = k.get("yes_bid") or {}, k.get("yes_ask") or {}
            def f(x):
                try:
                    return float(x.get("close_dollars"))
                except Exception:
                    return None
            compact.append([k.get("end_period_ts"), f(pr), f(yb), f(ya)])
        fp.write_text(json.dumps({"ticker": m["ticker"], "series": m["series"], "close_ts": m["close_ts"],
                                  "result": m["result"], "volume": m["volume"], "candles": compact}))
        return "ok"


async def build_catmap(c, picks):
    if CATMAP.exists():
        return
    cats = {}
    events = sorted(set(m["event"] for m in picks))
    sem = asyncio.Semaphore(5)
    async def one(ev):
        async with sem:
            try:
                r = await c._make_authenticated_request("GET", f"/trade-api/v2/events/{ev}")
                e = r.get("event", r)
                cats[ev] = {"category": e.get("category"), "title": (e.get("title") or "")[:80]}
            except Exception:
                pass
    await asyncio.gather(*(one(ev) for ev in events))
    CATMAP.write_text(json.dumps(cats))
    print(f"CATMAP events mapped={len(cats)}/{len(events)}", flush=True)



def sample_day(rows, picks_seen):
    """Pick from one day: anchors per (series,day) + random big/mid pools; dedupe across days."""
    by_sd = collections.defaultdict(list)
    for r in rows:
        by_sd[r["series"]].append(r)
    picks = {}
    for series, ms in by_sd.items():
        ms.sort(key=lambda m: -m["volume"])
        a = ms[0]
        if a["ticker"] not in picks_seen:
            picks[a["ticker"]] = a
    big = [r for r in rows if r["volume"] >= 1000]
    mid = [r for r in rows if 100 <= r["volume"] < 1000]
    rng = random.Random(7 + day_offset(rows))
    take = lambda pool, n: rng.sample(pool, min(n, len(pool)))
    for r in take(big, 250):
        if r["ticker"] not in picks_seen:
            picks[r["ticker"]] = r
    for r in take(mid, 150):
        if r["ticker"] not in picks_seen:
            picks[r["ticker"]] = r
    for r in picks.values():
        picks_seen.add(r["ticker"])
    out = list(picks.values())
    rng.shuffle(out)
    print(f"  sample_day: big={len(big)} mid={len(mid)} -> {len(out)} picks", flush=True)
    return out


def day_offset(rows):
    if not rows:
        return 0
    return rows[0]["close_ts"] % 1000


async def build_catmap_inc(c, picks):
    cats = json.loads(CATMAP.read_text()) if CATMAP.exists() else {}
    events = sorted(set(m["event"] for m in picks if m["event"] not in cats))
    sem = asyncio.Semaphore(5)
    async def one(ev):
        async with sem:
            try:
                r = await c._make_authenticated_request("GET", f"/trade-api/v2/events/{ev}")
                e = r.get("event", r)
                cats[ev] = {"category": e.get("category"), "title": (e.get("title") or "")[:80]}
            except Exception:
                pass
    await asyncio.gather(*(one(ev) for ev in events))
    CATMAP.write_text(json.dumps(cats))

async def main():
    c = KalshiClient()
    t0 = time.time()
    sem = asyncio.Semaphore(4)
    all_rows = []
    picks_seen = set()
    results = collections.Counter()
    for day in range(14, 26):
        rows = await collect_day(c, day)
        all_rows += rows
        day_picks = sample_day(rows, picks_seen)
        await build_catmap_inc(c, day_picks)
        results.clear()
        for i in range(0, len(day_picks), 250):
            res = await asyncio.gather(*(pull_candles(c, m, sem) for m in day_picks[i:i+250]))
            results.update(res)
        print(f"== day Sep {day:02d}: universe={len(rows)} candles={len(day_picks)} {dict(results)} "
              f"elapsed={round(time.time()-t0)}s", flush=True)
    print(f"DONE universe={len(all_rows)} candles_total_files={len(list((OUT / 'candles').glob('*.json')))} "
          f"elapsed={round(time.time()-t0)}s", flush=True)
    await c.close()

    c = KalshiClient()
    t0 = time.time()
    rows = []
    for day in range(14, 26):
        rows += await collect_day(c, day)
        print(f"  universe so far={len(rows)} elapsed={round(time.time()-t0)}s", flush=True)
    picks = build_sample(rows)
    await build_catmap(c, picks)
    sem = asyncio.Semaphore(4)
    results = collections.Counter()
    batch = 250
    for i in range(0, len(picks), batch):
        res = await asyncio.gather(*(pull_candles(c, m, sem) for m in picks[i:i+batch]))
        results.update(res)
        print(f"candles {min(i+batch,len(picks))}/{len(picks)} {dict(results)} elapsed={round(time.time()-t0)}s", flush=True)
    print(f"DONE {dict(results)} elapsed={round(time.time()-t0)}s", flush=True)
    await c.close()


asyncio.run(main())
