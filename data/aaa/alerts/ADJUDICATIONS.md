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

## KXAAAGASD* states (21 state ladders) — model PROVEN BAD forward; paper only
Adjudicated 2026-09-26, then CONFIRMED by the first forward scores (n=498 over
the 9/25 sweep): book Brier 0.0539 vs agent model 0.0975 vs Jev 0.1526. The
model was catastrophic on NV (Brier 0.56: priced the 9/26 print median ~5.40
while the realized print cleared 5.45 — book had it right), bad on WI/IL/IN and
YouTube views; competitive only on diesel (0.0215 vs book 0.0206). Root cause
of the NV miss: the sweep priced from a stale state anchor. The morning job now
re-fetches every state page before pricing. **No size on state gas until a
re-run sweep with fresh anchors shows model Brier < book Brier forward.** The
rare big wins (AZ/FL/GA) do not pay for the tail risk at near-empty books.

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
