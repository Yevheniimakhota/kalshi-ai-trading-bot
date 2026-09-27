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

## KXAAAGASD* states (21 state ladders) — book is SHARP; transfer model loses
Adjudicated 2026-09-26; CONFIRMED with valid forward scores 2026-09-27 (the
9/27 print day, 21 states): book Brier 0.0283 vs transfer-model 0.1572 over
141 strike-observations. NOTE an earlier "model wins by 0.28" reading was a
SCORER BUG (state gas strikes were scored against the national diesel value -
every y was 1); after the per-series realized-value fix the book wins clearly.
The state books are informed (state prints move faster than the national
average and the books track them). **No size on state gas; revisit only with a
state-specific change model (own-series distribution, n>=30 per state) that
beats the book forward.** Diesel national stays at par (0.0889 vs 0.0870 on the
9/27 day, n=17) - the pre-registered rule fired as written: print 6.4709 landed
in the adjudicated 6.45-6.47 band.

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
