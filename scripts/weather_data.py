#!/usr/bin/env python3
"""Weather family data capture (KXHIGH* daily-high ladders). v1: capture only.

Per city, daily:
  * GEFS 31-member daily-max temperature distribution (Open-Meteo ensemble API)
  * NWS station observations daily max (proxy for the CLI report Kalshi settles
    on; may differ from the official CLI max by a few tenths of a degree)

Kalshi weather markets settle on the NWS Daily Climate Report (CLI) per city.
The ensemble-vs-actual history built here powers the bias correction and the
forward scores for docs/WEATHER.md. No pricing, no trading.

Usage: python scripts/weather_data.py capture
State: data/weather/<YYYY-MM-DD>.json (one file per UTC day, idempotent)
"""
import argparse
import datetime as dt
import json
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "weather"
HDRS = {"User-Agent": "trading-research research@example.com"}

CITIES = {
    "NYC": {"station": "KNYC", "lat": 40.7794, "lon": -73.9692},
    "CHI": {"station": "KORD", "lat": 41.8781, "lon": -87.6298},
    "MIA": {"station": "KMIA", "lat": 25.7906, "lon": -80.3164},
}


def ensemble_daily_max(lat: float, lon: float, days: int = 3):
    r = httpx.get("https://ensemble-api.open-meteo.com/v1/ensemble",
                  params={"latitude": lat, "longitude": lon,
                          "daily": "temperature_2m_max", "forecast_days": days,
                          "temperature_unit": "fahrenheit", "models": "gfs025"},
                  timeout=30, headers=HDRS)
    r.raise_for_status()
    daily = r.json().get("daily", {})
    keys = [k for k in daily if "temperature_2m_max" in k]
    out = {"dates": daily.get("time", []), "members": {}}
    for k in keys:
        member = k.split("temperature_2m_max")[-1] or "control"
        out["members"][member] = daily[k]
    return out


def nws_daily_max(station: str) -> dict:
    """Max 5-min-obs temperature bucketed by LOCAL (ET) calendar day — the CLI
    report's day boundary. UTC-day bucketing misassigns the evening peak (bug
    found on first capture: NYC 9/28 ET high ~66F showed as 61F UTC-day max)."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    now = dt.datetime.now(dt.timezone.utc)
    start = (now - dt.timedelta(days=2)).strftime("%Y-%m-%dT00:00:00Z")
    r = httpx.get(f"https://api.weather.gov/stations/{station}/observations",
                  params={"start": start, "limit": 500}, timeout=30, headers=HDRS)
    r.raise_for_status()
    by_day = {}
    for f in r.json().get("features", []):
        p = f["properties"]
        t = p.get("temperature", {}).get("value")
        if t is None:
            continue
        ts = dt.datetime.fromisoformat(p["timestamp"]).astimezone(et)
        f_day = ts.date().isoformat()
        f_val = t * 9 / 5 + 32
        if f_day not in by_day or f_val > by_day[f_day]:
            by_day[f_day] = round(f_val, 2)
    return by_day


def capture() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    day = now.strftime("%Y-%m-%d")
    path = OUT / f"{day}.json"
    if path.exists():
        print(f"{day}: already captured")
        return 0
    rec = {"fetched": now.isoformat(), "cities": {}}
    for city, cfg in CITIES.items():
        try:
            rec["cities"][city] = {"ensemble": ensemble_daily_max(cfg["lat"], cfg["lon"]),
                                   "nws_obs_max": nws_daily_max(cfg["station"])}
            e = rec["cities"][city]["ensemble"]
            per_date = {}
            for d_i, d_name in enumerate(e["dates"]):
                vals = [v[d_i] for v in e["members"].values()
                        if len(v) > d_i and v[d_i] is not None]
                if vals:
                    import statistics
                    per_date[d_name] = {"n": len(vals), "mean": round(statistics.mean(vals), 2),
                                        "sd": round(statistics.pstdev(vals), 2)}
            rec["cities"][city]["ens_by_date"] = per_date
            print(f"{city}: ens {per_date} | obs max {rec['cities'][city]['nws_obs_max']}")
        except Exception as e:
            rec["cities"][city] = {"error": str(e)[:200]}
            print(f"{city}: ERROR {e}")
    path.write_text(json.dumps(rec, indent=1))
    print(f"-> {path}")
    return 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["capture"])
    args = ap.parse_args()
    if args.cmd == "capture":
        capture()


if __name__ == "__main__":
    main()
