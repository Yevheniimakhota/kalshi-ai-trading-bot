# Kalshi trade-dataset findings (Becker replication, our copy)

_Data: 72.1M trades (2023-03 → 2025-11-25), 7,314,377 settled markets with results.
Tool: `scripts/kalshi_dataset_analysis.py`; results JSON: `data/external/analysis_results.json`._

## 1. The close-out "0.99c scalp" at exchange scale — dead as a taker trade

Last trade at least 1h before close, win rate by price:

| bucket | n | win rate |
|---|---|---|
| [0.90,0.95) | 5,813 | 93.5% |
| [0.95,0.97) | 3,947 | 95.6% |
| [0.97,0.99) | 7,035 | 97.3% |
| **[0.99,1.0)** | **25,150** | **99.01%** |

Buying at 0.99 with a 1h lead = +0.1% gross, negative after fees. At a 3h lead it is
*worse* (98.45%). The last-trade print is well calibrated — there is no free 1%.
This confirms and generalizes the 1-minute study (which measured the *fill*
population, where adverse selection is stronger: 93.8%).

## 2. Calibration is excellent everywhere except the longshots

Win rates track price within ~1-2pts across the whole curve. The single exception:
**YES contracts priced 1-20c massively underperform**: 1-5c YES wins 1.08% vs ~2.2c
avg price (−50% of risked capital, n=1.16B contracts); 5-10c: −36%; 10-20c: −17%.
This is the longshot bias / optimism tax, confirmed on 72M trades.

## 3. Final-hour taker flow at ≥0.98

99M contracts of taker YES at avg 0.986 in the final hour won 98.22% (−0.4%/ct).
Even in the last hour, taking YES at 98-99c is slightly -EV. The counterparty
(maker) earns the mirror.

## 4. Policy implications (adopted)

1. **Never take near-certain prices** — the level is priced. Enter certainty only
   as a maker, model-gated (fair − price > spread + fee), small clips.
2. **Never buy YES longshots** (≤20c) as takers — that is the casino side of the
   exchange; the mirror (selling them via NO, with a model gate) is where the
   structural premium sits.
3. **Maker role is the durable edge** (Becker: +0.8-1.3pp per trade, symmetric by
   side) — our order placement should default to resting limits, not marketable
   orders, wherever timing allows.
4. Our own data families behave like "Finance" (near-efficient) — forecasting
   edges there must be measured, not assumed; the emotional categories carry
   flow edge but we lack a model, so we stay out of sports/media as takers.

## Notes

* NO-side EV columns in the JSON have a known label bug (risked uses yes_price for
  both sides); YES-side numbers are correct. Fix queued.
* Fuel-ladder crossing pass returned n=0 (filter bug: settled fuel tickers were
  skipped); rerun queued — non-blocking.
