# Alert adjudications — standing verdicts

_What the agent loop decided about each recurring alert family, so the same
question is not re-litigated every morning. Update as evidence accumulates._

## KXDIESELD (daily diesel ladder) — EFFICIENT, do not trade the retail-only alerts
Adjudicated 2026-09-26. The retail-only streak model showed a 40pt apparent edge
(fair ~0.55 vs book ~0.95 for print<=6.480). The wholesale convergence check
(`aaa_futures.py gap`) overturned it: ULSD had crashed -11% leaving a 46.7c
excess gap that fully justified the book. The 9/25->9/26 print confirmed the
book's calibration (implied median 6.480, realized 6.4839).
**Rule: diesel alerts are tradeable only when the excess gap is < ~5c AND the
model still disagrees by > fee+margin after the wholesale adjustment.**

## KXAAAGASD* states + national gas — book is NEAR-PERFECT; transfer model dead
Clean per-series forward scores (2026-09-27 print day, deduped): the book beats
the national-transfer model in 22 of 23 series. Several state books price at
Brier 0.0005-0.025 (NJ 0.0012, OH 0.0032, MA 0.0005) — near-perfect against
the model's 0.03-0.72. National gas: book 0.136 vs model 0.226 (n=5). Diesel
national: par (0.0821 vs 0.0856, n=9) — the only competitive series, and par
pays nothing after fees. Two scorer bugs were caught on the way (wrong
underlying per series; lost dedup) — both fixed; the scorer is now idempotent.
**VERDICT: the AAA/state family gets NO size from any national-transfer model.
State gas needs a state-specific model (own-series distribution per state,
n>=30) that beats a near-perfect book — low odds; deprioritize. The diesel
path model (wholesale convergence) is the only live development thread here,
and it must beat par, not the transfer model, to earn size.

## KXAAAGASD national + KXDIESELMON/KXDIESELW — priced fair, hold book
2026-09-26: gas national and the weekly/monthly diesel ladders are internally
consistent with the wholesale convergence model (book medians 6.455/6.40 vs
model 6.45/6.41). The agent's diesel YES positions are roughly fair; hold.

## KXA100MS-26SEP-1.000 — bought 0.39-0.49; watch the seller
2026-09-26: break-even math (remaining prints must average <=0.9075 for the
strike to lose; recent-regime MC P(loss) ~0.24) vs ask 0.39. Position 115 YES @
~0.533 (~7% equity). The seller may hold hourly (paid) Ornn data the public
daily feed lacks - no adds beyond ~9% equity without new public information.

## KXTRUTHSOCIAL-26SEP26 buckets — spree trades placed, resolution tonight
2026-09-26 evening: count 159-160 through 21:00 ET, 6pm burst ended. Holds:
100 YES B189 @0.14 (est ~0.30), 100 YES B209 @0.04 (est ~0.10). The morning
fade (B109/B129 YES) is dead. Resolution: Roll Call count 10am ET Monday.

## KXOPENSHARE-26SEP28 — weekend-dilution thesis, sized small
2026-09-26: Saturday all-request openai share 15.45% (vs 17.9% Fri). Text-share
estimate ~17.5-17.7 final vs strikes 17.8/17.3: leans NO but thinner than the
morning's 0.70/0.80 estimates. Holds: 79 NO @0.27, 100 NO @0.05. Monday 10am
chart settles it.
