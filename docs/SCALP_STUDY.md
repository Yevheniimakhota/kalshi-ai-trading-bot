# Close-out scalping study (the "buy at 0.99" strategy) — measured

_Built 2026-09-28 by the trading loop. Data: hourly candlesticks for 1,059 settled
markets (Sep 14–28) across 15 series (gas/diesel ladders, OpenRouter share,
token-use, Trump-say, Truth Social pace, MLB, misc.). Tool: `scripts/scalp_study.py`
(candles cached under `data/backtest/scalp_candles/`)._

## The structural finding that kills the naive version

**When the last bid is ≥ 0.99, the ask is 1.00 in 239/239 cases.** The last 1% is
never offered to buyers — the sell side has already gone to parity by the time the
bid prints 0.99. Buying "at 0.99" as a taker is not a trade that exists.

The level is right, though: of markets whose last 1h-pre-close bid was ≥ 0.99,
**239/239 settled YES** (also 215/215 at 3h, 166/166 at 6h, 35/35 and 27/27 at
24h/48h). At bid 0.90–0.95 the win rate drops to 89–94%. So near-settled ladders
at ≥ 0.99 are genuinely near-certain — you just can't buy the last cent.

## What IS buyable

Entries with **bid ≥ 0.97 and ask ≤ 0.99** (a lazy seller still sitting at 0.99 or
below): 30 observations in 13.3 days (**2.3/day**), average entry 0.989, **30/30
settled YES** (15 gas ladders, 9 diesel, 4 MLB, 2 Truth Social).

Fee math (fee = round-up(0.07 × C × p × (1−p)) per ORDER, so a 100-contract clip
at 0.989 pays ~$0.07):

* net win ≈ +1.04% per flip, net loss ≈ −99.0%
* breakeven win rate ≈ 99.1%
* in-sample 30/30 — but the rule-of-three bound on 0 failures in 30 only says the
  true failure rate is < 10%. Not enough. Need n ≈ 300+ (≈ 4 months of paper
  tracking) before the bound reaches the 1% that matters.
* Compounding note: one full loss at 0.99 wipes ~460 compounding wins. Full-stake
  compounding requires true P(win) ≳ 99.9%; Kelly sizing for a 99.5%-true edge
  says ~0.5% of bankroll per flip. Either way, per-flip size must be small.

## The version that can actually work: maker close-outs

Instead of taking, **rest a bid at 0.98–0.99 on markets whose outcome is already
locked by the resolution source** (published print, confirmed result). Then:

* you're the maker: fee ≈ 0.0175 × C × p × (1−p) (quarter taker), a 100-ct order
  at 0.99 pays ~$0.02 → net win ≈ +0.98%;
* fills come from panic sellers and lazy limit orders — the 17/313 ask-at-0.99
  episodes show they exist;
* the adverse-selection risk is real: the seller at 0.99 may know the resolution
  source moved. Mitigation: only rest when our own data model prices fair ≥ 0.995
  (for the gas/diesel ladders we have exactly that pricer);
* measure first: paper-log every resting bid + fill for ~4-6 weeks before any
  real size. Target sample ≥ 100 fills with 0 failures before scaling.

## Verdict

* Taker version: **dead** — structurally unfillable at 0.99 (ask always 1.00).
* Maker version: **plausible, small, and measurable** — ~2-5 fillable opportunities
  per day concentrated in the gas/diesel ladders where we already run a pricer.
  Treat as a low-yield carry overlay with strict model confirmation, not a core
  strategy; the tail risk (one loss = ~100x the win) caps it at small size forever.
* Not yet traded. Needs: (1) paper log of resting-bid fills, (2) Ryan's historical
  manual fills if he has records, (3) model-fair ≥ 0.995 gate on every fill.
