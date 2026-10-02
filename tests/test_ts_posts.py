"""ts_posts: ET conversion and weekly counting."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ts_posts import count, et  # noqa: E402


def _post(day_hour_utc: str, reblog=False):
    return {"created_at": day_hour_utc, "reblog": {"id": "1"} if reblog else None}


# count() aggregates whatever it is given (fetch_week does the week filter)
POSTS = [
    _post("2026-09-20T04:00:00.000Z"),           # Sun 00:00 ET
    _post("2026-09-21T05:00:00.000Z", reblog=True),
    _post("2026-09-21T06:00:00.000Z"),
]


def test_et_shifts_utc_to_et():
    assert et("2026-09-20T04:00:00.000Z").date().isoformat() == "2026-09-20"
    assert et("2026-09-20T02:00:00.000Z").date().isoformat() == "2026-09-19"


def test_count_splits_own_and_retruths():
    c = count(POSTS)
    assert c["total"] == 3
    assert c["own"] == 2 and c["retruths"] == 1
    assert c["by_day"]["2026-09-20"] == 1
    assert c["by_day"]["2026-09-21"] == 2
    assert c["last_post_et"].startswith("2026-09-21T02:00")


def test_count_as_of_cutoff():
    import datetime as dt
    # cutoff 2026-09-20T21:00 ET: only the first post is in
    c = count(POSTS, as_of=dt.datetime(2026, 9, 21, 1, 0, tzinfo=dt.timezone.utc) - dt.timedelta(hours=4))
    assert c["total"] == 1
