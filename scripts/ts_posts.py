#!/usr/bin/env python3
"""Trump Truth Social weekly post count (Kalshi KXTRUTHSOCIAL bucket source).

The weekly post-count buckets resolve on **Roll Call's** tracker (count recorded
10:00 AM ET Monday; window 12:00 AM ET Sunday-start through 11:59 PM ET the
following Saturday; Truths + ReTruths + Quote Truths count; replies count if
captured; deleted posts don't). This tool uses the public Mastodon-style API
(``/api/v1/accounts/{id}/statuses``, paginated with max_id) as a proxy and
validates it against known Roll Call anchors (2026-09-25: proxy=100 vs Roll
Call 99 — off-by-one, treat the proxy as ±1).

The API rate-limits hard (HTTP 429): pace one request per ~25s.

Usage:
  python scripts/ts_posts.py count --week 2026-09-20 [--json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import httpx
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}
ACCOUNT_ID = "107780257626128497"  # @realDonaldTrump
STATUSES_URL = f"https://truthsocial.com/api/v1/accounts/{ACCOUNT_ID}/statuses"
ET_OFFSET = dt.timedelta(hours=-4)

# Anchors: (week_start_ET, as_of_ET, roll_call_count) — extend as weeks settle.
ANCHORS = [
    (dt.date(2026, 9, 20), dt.datetime(2026, 9, 25, 23, 7), 99),
]


def et(created_at: str) -> dt.datetime:
    return dt.datetime.fromisoformat(created_at.replace("Z", "+00:00")) + ET_OFFSET


def fetch_week(week_start: dt.date, week_end: dt.date, max_pages: int = 12,
               sleep_s: float = 25.0) -> list[dict]:
    """Fetch this week's posts (ET-dated) via the statuses API, paced."""
    posts: list[dict] = []
    max_id = None
    for _ in range(max_pages):
        params = {"limit": "40"}
        if max_id:
            params["max_id"] = max_id
        r = httpx.get(STATUSES_URL, params=params, timeout=20, headers=HEADERS)
        if r.status_code == 429:
            time.sleep(sleep_s + 10)
            continue
        if r.status_code != 200:
            break
        try:
            rows = r.json()
        except ValueError:
            time.sleep(sleep_s)
            continue
        if not isinstance(rows, list) or not rows:
            break
        if any(not isinstance(p, dict) or not isinstance(p.get("created_at"), str) for p in rows):
            time.sleep(sleep_s)
            continue
        posts.extend(rows)
        max_id = rows[-1]["id"]
        if et(rows[-1]["created_at"]).date() < week_start:
            break
        time.sleep(sleep_s)
    return [p for p in posts if week_start <= et(p["created_at"]).date() <= week_end]


def count(posts: list[dict], as_of: dt.datetime | None = None) -> dict:
    if as_of is None:
        sel = posts
    else:
        sel = [p for p in posts if et(p["created_at"]) <= as_of]
    own = sum(1 for p in sel if not p.get("reblog"))
    rets = sum(1 for p in sel if p.get("reblog"))
    return {"total": len(sel), "own": own, "retruths": rets,
            "by_day": {d: sum(1 for p in sel if et(p["created_at"]).date().isoformat() == d)
             for d in sorted({et(p["created_at"]).date().isoformat() for p in sel})},
            "last_post_et": max((et(p["created_at"]) for p in sel), default=None).isoformat() if sel else None}


def backfill(months: int = 3, sleep_s: float = 22.0, max_pages: int = 400) -> list[dict]:
    """Paced full-history pagination into data/truthsocial/posts.jsonl (resumable).

    The API rate-limits hard; one request per ~sleep_s seconds. Pages are
    cached incrementally so an interrupted backfill resumes where it stopped.
    """
    out_dir = REPO / "data" / "truthsocial"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "posts.jsonl"
    have: dict[str, dict] = {}
    if path.exists():
        for line in path.open():
            try:
                p = json.loads(line)
                if isinstance(p, dict) and isinstance(p.get("created_at"), str):
                    have[p["id"]] = p
            except json.JSONDecodeError:
                continue
    print(f"resume with {len(have)} cached posts", file=sys.stderr)
    max_id = None
    if have:
        oldest = min(have.values(), key=lambda p: p["created_at"])
        max_id = oldest["id"]
    fetched = 0
    with open(path, "a") as f:
        for _ in range(max_pages):
            params = {"limit": "40"}
            if max_id:
                params["max_id"] = max_id
            r = httpx.get(STATUSES_URL, params=params, timeout=20, headers=HEADERS)
            if r.status_code in (429, 403):
                time.sleep(sleep_s + 20)
                continue
            if r.status_code != 200:
                print(f"stop: status {r.status_code}", file=sys.stderr)
                break
            rows = r.json()
            if not isinstance(rows, list) or not rows:
                break
            if any(not isinstance(p, dict) or not isinstance(p.get("created_at"), str) for p in rows):
                time.sleep(sleep_s)
                continue
            new = 0
            for p in rows:
                if p["id"] not in have:
                    have[p["id"]] = p
                    f.write(json.dumps(p) + "\n")
                    new += 1
                    fetched += 1
            f.flush()
            max_id = rows[-1]["id"]
            oldest = et(rows[-1]["created_at"])
            print(f"page: +{new} (total {len(have)}), oldest {oldest.date()}", file=sys.stderr)
            if oldest < dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30 * months):
                break
            time.sleep(sleep_s)
    return list(have.values())


def conditional_final(posts: list[dict], cutoff_et: str, min_by_cutoff: int = 30) -> dict:
    """P(final day total | count by cutoff ET) from history. Pure.

    The stat that prices the weekly post buckets: how many MORE posts follow a
    given count-at-cutoff. Verified 2026-09-26: on days with >=50 posts by
    18:28 ET, the evening added only 1-5 posts (sprees end by evening).
    """
    cutoff = dt.time.fromisoformat(cutoff_et)
    by_day = defaultdict(list)
    for p in posts:
        t = et(p["created_at"])
        by_day[t.date()].append(t)
    rows = []
    for d, times in sorted(by_day.items()):
        by_cut = sum(1 for t in times if t.time() <= cutoff)
        rows.append({"date": d.isoformat(), "by_cutoff": by_cut, "final": len(times),
                     "adds_after_cutoff": len(times) - by_cut})
    sel = [r for r in rows if r["by_cutoff"] >= min_by_cutoff]
    adds = sorted(r["adds_after_cutoff"] for r in sel)
    return {"cutoff_et": cutoff_et, "min_by_cutoff": min_by_cutoff,
            "n_days": len(sel),
            "adds_after_cutoff": adds,
            "median_adds": adds[len(adds) // 2] if adds else None,
            "max_adds": adds[-1] if adds else None,
            "rows": rows}


def pace_histogram(posts: list[dict]) -> dict:
    """Hour-of-day (ET) x weekday posting histogram + spree-day stats. Pure."""
    hist: dict[str, int] = {}
    by_day: dict[str, int] = {}
    for p in posts:
        t = et(p["created_at"])
        key = f"{t.strftime('%a')}{t.hour:02d}"
        hist[key] = hist.get(key, 0) + 1
        d = t.date().isoformat()
        by_day[d] = by_day.get(d, 0) + 1
    days = sorted(by_day.values())
    return {"by_hour_weekday": dict(sorted(hist.items())),
            "by_day": by_day,
            "daily_posts": {"median": sorted(days)[len(days) // 2] if days else 0,
                            "p90": sorted(days)[int(0.9 * len(days))] if days else 0,
                            "max": max(days) if days else 0}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--week", default=None, help="week start (ET), e.g. 2026-09-20; default: current week's Monday")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--backfill", type=int, default=None, metavar="MONTHS",
                    help="pace-limited full history backfill (resumable)")
    ap.add_argument("--pace", action="store_true", help="posting-pace histogram from the cached backfill")
    ap.add_argument("--conditional", nargs=2, metavar=("CUTOFF_ET", "MIN_COUNT"),
                    help="e.g. --conditional 18:28 50 -> P(final | count by cutoff)")
    args = ap.parse_args()
    if args.backfill is not None:
        backfill(args.backfill)
        return
    if args.conditional:
        cutoff_et, min_count = args.conditional
        path = REPO / "data" / "truthsocial" / "posts.jsonl"
        posts = []
        if path.exists():
            for line in path.open():
                try:
                    p = json.loads(line)
                    if isinstance(p, dict):
                        posts.append(p)
                except json.JSONDecodeError:
                    continue
        print(json.dumps(conditional_final(posts, cutoff_et, int(min_count)), indent=1))
        return
    if args.pace:
        path = REPO / "data" / "truthsocial" / "posts.jsonl"
        posts = []
        if path.exists():
            for line in path.open():
                try:
                    p = json.loads(line)
                    if isinstance(p, dict):
                        posts.append(p)
                except json.JSONDecodeError:
                    continue
        print(json.dumps(pace_histogram(posts), indent=1))
        return
    if args.week:
        week_start = dt.date.fromisoformat(args.week)
    else:
        today = dt.datetime.now().date()
        week_start = today - dt.timedelta(days=today.weekday())
    week_end = week_start + dt.timedelta(days=6)
    posts = fetch_week(week_start, week_end)
    c = count(posts)
    out = {"week_start": week_start.isoformat(), "week_end": week_end.isoformat(), **c,
           "proxy_caveat": "Mastodon API proxy for Roll Call, +/-1 validated 2026-09-25"}
    print(json.dumps(out, indent=1) if args.json else
          f"week {week_start}..{week_end}: {c['total']} posts (own {c['own']}, retruths {c['retruths']}) "
          f"through {c['last_post_et']}")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--week", default=None, help="week start (ET), e.g. 2026-09-20; default: current week's Monday")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.week:
        week_start = dt.date.fromisoformat(args.week)
    else:
        today = dt.datetime.now().date()
        week_start = today - dt.timedelta(days=today.weekday())
    week_end = week_start + dt.timedelta(days=6)
    posts = fetch_week(week_start, week_end)
    c = count(posts)
    out = {"week_start": week_start.isoformat(), "week_end": week_end.isoformat(), **c,
           "proxy_caveat": "Mastodon API proxy for Roll Call, +/-1 validated 2026-09-25"}
    print(json.dumps(out, indent=1) if args.json else
          f"week {week_start}..{week_end}: {c['total']} posts (own {c['own']}, retruths {c['retruths']}) "
          f"through {c['last_post_et']}")


if __name__ == "__main__":
    main()
