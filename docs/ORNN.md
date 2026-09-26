# Ornn Compute Price Index markets (KXA100MS family)

_Built 2026-09-26. Data source: Ornn's free public index API (`data.ornn.com`)._

## Mechanics

* Markets like `KXA100MS-26SEP-1.000` resolve on **the arithmetic mean of hourly
  OCPI-A100 values over the month** (Ornn Compute Price Index, `OCPI-A100`).
  Ornn settles OCPI once per trading day at 4:00 PM ET and publishes the daily
  series free (3-month window, no auth). Bloomberg carries the index.
* Because every day contributes the same 24 hours, **the month's hourly mean
  equals the mean of that month's daily settled prints** — the public daily
  series is exactly the resolution math.
* Strikes are 25c ladders per month. `KXA100MS-26AUG` settled: >1.00 YES (Aug
  mean was in (1.00, 1.25]).

## Data tooling

* `scripts/ornn_data.py fetch` — caches all five GPU histories (A100, H100,
  H200, B200, RTX 5090) under `data/ornn/`; wired into `run_daily.sh`.
* `scripts/ornn_data.py strike --gpu "A100 SXM4" --month 2026-09 --strike 1.00`
  prints n-so-far, mean-so-far, and the **break-even average the remaining
  prints must stay under** for the strike to lose, plus the "flat-at-last"
  verdict.

## 2026-09-26 case study (first live use)

Sep prints through 9/26: mean 1.0142 (n=26); the 9/26 print settled **$0.95 —
the 3-month sample's all-time low** — after the agent had bought 45 YES at avg
0.667 and the book had fallen to 0.47-0.49.

Break-even math: the remaining 4 prints must average **<= 0.9075** for the
>$1.00 strike to lose — i.e. another −4.5% below the freshly-made all-time-low,
sustained. Empirically (92 bars): daily changes mean −0.04c, std 3.2c; the only
prior ≥5c drop (−18c on 8/28) was followed by 1.03/1.03/1.02/1.00 (rebound);
random-walk MC from 0.95: **P(strike loses) ≈ 3%**. Even four prints flat at
0.95 gives a 1.0057 month mean (YES wins).

Action: bought 40 more YES at 0.49 (marketable, ~6% equity total, journaled,
est_prob 0.90 — deliberately below the 0.97 MC point estimate to respect model
error and the unknown information a large seller may hold).

## Standing rules for this family

1. Price strikes from `ornn_data.py strike`, never from vibes or the agent's
   memory of the print level.
2. The break-even quantity is the *average of the remaining prints*, not the
   next print — a single bad print rarely flips a monthly mean.
3. Watch the trend regime: the index fell 1.21 (mid-Aug) → ~1.02 (Sep) → 0.95.
   A sustained oversupply regime could keep sinking prints; the 3% MC assumes
   the historical change distribution, which may understate a regime break.
   Size positions as if the true P(loss) is several times the MC estimate.
4. If a market-implied probability disagrees with the break-even math by a
   wide margin, check first whether the *seller* may hold hourly (paid) data
   the public feed doesn't show — the public feed is daily-settled values only.
