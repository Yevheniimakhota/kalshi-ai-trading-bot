# Human review queue — for Ryan

_Updated 2026-09-28 06:15 UTC. Anything I need from you (approvals, data, accounts) lives here.
Items are ordered by urgency._

## 1. APPROVAL NEEDED — KXA100MS-26SEP-1.000 (Sep A100 compute index, >$1.000 strike)

Live position: **115 YES, cost $61.35 (avg 0.533)**. The 9/27 print came in **0.91 — second
consecutive all-time low** (1.02 → 0.95 → 0.91). Sep mean 1.01037 with 3 prints left; the strike
loses if the last 3 prints average ≤ 0.9067 — i.e. any single print ≤ 0.90 flips it.

* Book now: YES ask 0.29 (130 deep) / 0.38 (1051 deep). Market P(YES) ≈ 0.29–0.38.
* Model: P(YES) 0.39 (recent-30 bootstrap) – 0.53 (full history). No edge either way.
* **Recommendation: exit ~half (57 contracts) into the 0.38 bid now** (recovers ~$21,
  cuts tail risk), hold the rest with a hard exit if the 9/28 print ≤ 0.90. Full exit at 0.38 is
  also defensible. No adds.
* I cannot place these orders myself — say the word (or place them in the Kalshi UI: sell 57 YES
  limit at 0.38, marketable).

## 2. Settling today — informational, no action

OpenRouter share week (Sep 21–27) settled values (from the 05:40Z snapshot; official 10am ET
update will be re-captured at 14:05Z): deepseek 24.4, google 20.5, openai 17.9, anthropic 2.7,
xiaomi 2.5. Our NOs: DEEPSHARE-24.1 −$42.55, OPENSHARE-17.8 −$21.22, OPENSHARE-17.3 −$4.00,
XIAOMI −$4.00/−$4.50, ANTHSHARE-2.8 **+$5.60**. Net ≈ −$70.7. Weekend-dilution lesson recorded:
dilution was real but weaker than last weekend (openai Sunday ~15–16% vs 13.6–14.1% prior);
never size off a single weekend's dilution.

## 3. Your 99c scalping idea — being tested now

Buying near-certain contracts at 0.99 for the last 1%, compounding. The math:
* Fee at 0.99 ≈ 0.07%/contract → net win ≈ +0.93%. Breakeven win rate ≈ 99.07%.
* One loss at 0.99 wipes ~460 wins of compounding. Full-stake compounding needs true P(win)
  ≳ 99.9% to survive indefinitely; Kelly sizing says even a 99.5% edge deserves only ~0.5% of
  bankroll per flip.
* The version that can actually work: outcome **already locked by the source** (print published /
  result confirmed) but the market still trades before settlement. Then true P ≈ 100% and the
  only risks are settlement surprises (source revision, dispute) and fees.
* **Fee catch (important)**: Kalshi rounds the fee up per ORDER. One contract at 0.99 pays a
  1¢ minimum fee → net win exactly $0.00 per contract. Buying at 0.99 one contract at a time
  is strictly −EV. The strategy needs either (a) larger clips (fee is rounded up on the order
  total: 100 contracts at 0.99 → $0.07 fee → +0.93% net) or entry ≤ 0.985. Worker replaced by
  an in-repo study: `scripts/scalp_study.py` (running; report → `docs/SCALP_STUDY.md`). If you have historical fills from when you ran this manually, they'd
  sharpen the test — drop them anywhere in the repo and I'll fold them in.

## 4. Data sources I'd like (highest value first)

1. **Hourly / paid Ornn OCPI data** — the public feed is daily-settled values only; a large
   seller was right against us on KXA100MS. Hourly OCPI-A100 (paid feed, or any Bloomberg
   export) would show intraday direction before the daily settle. Even a screenshot export is
   useful.
2. **GasBuddy or OPIS access** (or an account you already have) — gas traders price off
   GasBuddy before AAA prints; a pre-print retail gauge would sharpen all KXAAAGAS* families.
3. **Any historical fills/records from your manual 99c scalping** (dates, tickers, entry price)
   — turns the scalp study from estimated to measured.
4. **Your risk budget in numbers**: current bankroll you want me to manage, max single-position
   %, max family %. The docs assume ~6-10% caps; confirm or correct.
5. Kalshi **fee schedule confirmation** — I'm using 0.07 × p × (1−p) per contract; if your
   account has different maker/taker terms, tell me and I'll re-derive every edge calc.

## 5. Note

The repo's old `docs/QUICK_FLIP_STRATEGY.md` (1–20c lottery scalps with AI prediction) is a
different, unshipped idea and I don't rate it; your 99c version is the one worth testing.

## 6. Portfolio mark-to-market (2026-09-28 ~08:00 UTC, equity assumed $1000 — confirm)

Cost $762.75 across 33 positions; conservative bid marks $523 (unrealized ≈ −$240, overstated
where books have no bids — the OpenRouter markets are settled-but-unpaid (≈ −$70 expected) and
the A100 book has no YES bids (real exit ≈ 0.38 → −$19.6 not −$61)). Real clusters:
paranormal/KXALIENS +$12 (biggest single exposure $150), nobel +$14.5, trump_say −$20,
diesel weekly/monthly ≈ −$11 to −$1, ORNN as above. Full report: `scripts/portfolio_risk.py`.
