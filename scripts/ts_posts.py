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
import time
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


def main() -> None:
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
