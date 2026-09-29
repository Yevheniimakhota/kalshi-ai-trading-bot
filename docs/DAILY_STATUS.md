# Daily status — 2026-09-29 06:49 UTC

## Account
* Equity ≈ $925 (cash $315.60 + marks ~$609); baseline ~$900 at process start (+2.8%).
* Realized P&L (cumulative incl. pre-process): −$59.22. Settled today: diesel weekly +$3.90,
  TOKENUSE +$3.25, share family −$70.67.

## Model scorecard (out-of-sample)
* State transfer (NEW model): first forward scores due this morning's print cycle.
* State OLD model cumulative: n=307, Brier 0.0840 vs book 0.0128 (loses).
* Diesel daily (gap-aware v1): 2 days scored, both lost to book; more evidence needed.
* Gated close-out paper: 13/13 wins, +0.177/ct; 19 open.

## Infrastructure
* Risk governor wired into order path (5% day / 20% DD / 10% position, fail-closed on breach).
* API tier: Advanced (300/300 tok/s). Dataset: 72M trades analyzed (2 passes).
* Weather family: v1 capture live (3 cities, GEFS-31 + NWS obs, ET-day bucketed).

## Pending decisions
* ORNN 115 YES: needs 9/29+9/30 prints avg > 0.905 (9/28 was 0.91). Automated stop logic armed.
* State family tradeability: decided by this morning's forward scores (n accumulates daily).
