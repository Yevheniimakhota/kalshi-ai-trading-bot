#!/usr/bin/env python
"""Analyze close-out scalp data: P(settle YES | price bucket, lead time), fees, EV, sim.

Inputs: data/runtime/scalp_study/{days/*.jsonl, candles/*.json, series_category.json}
Outputs: data/runtime/scalp_study/analysis.json + printed tables (consumed by report writer).
"""
import collections, glob, json, math, os, random, statistics, sys
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("data/runtime/scalp_study")
CUTS = [1, 3, 6, 24, 48]           # hours before close
BUCKETS = [(0.95, 0.97), (0.97, 0.99), (0.99, 1.0001)]


def fee(p):
    return math.ceil(0.07 * p * (1 - p) * 100) / 100


def load_universe():
    rows = []
    for fp in sorted(glob.glob(str(OUT / "days" / "*.jsonl"))):
        rows += [json.loads(l) for l in open(fp) if l.strip()]
    return rows


def load_candles():
    ms = []
    for fp in glob.glob(str(OUT / "candles" / "*.json")):
        d = json.loads(open(fp).read())
        if "error" in d or not d.get("candles"):
            continue
        if not d.get("result") in ("yes", "no"):
            continue
        ms.append(d)
    return ms


def price_at(candles, close_ts, hours_before):
    """Last trade price, last bid, last ask with ts <= cutoff. Returns (price, ts, src, ask, ask_ts)."""
    cutoff = close_ts - hours_before * 3600
    last_t = last_b = last_a = None
    for t, pr, yb, ya in candles:
        if t > cutoff:
            break
        if pr is not None:
            last_t = (pr, t)
        if yb is not None:
            last_b = (yb, t)
        if ya is not None:
            last_a = (ya, t)
    ask = last_a[0] if last_a else None
    ask_ts = last_a[1] if last_a else None
    if last_t and last_t[0] > 0:
        return last_t[0], last_t[1], "trade", ask, ask_ts
    if last_b:
        return last_b[0], last_b[1], "bid", ask, ask_ts
    return None, None, None, ask, ask_ts


def first_cross(candles, close_ts, thresh):
    """First minute whose traded price >= thresh. Returns (price, ts) or None."""
    for t, pr, yb, ya in candles:
        if pr is not None and pr >= thresh:
            return (pr, t)
    return None


def in_bucket(p):
    for i, (lo, hi) in enumerate(BUCKETS):
        if lo <= p < hi:
            return i
    return None


def main():
    universe = load_universe()
    ms = load_candles()
    catmap = json.loads((OUT / "series_category.json").read_text()) if (OUT / "series_category.json").exists() else {}
    print(f"universe rows={len(universe)} candle markets={len(ms)}")

    # ---- per-market features
    feats = []
    for d in ms:
        cs = d["candles"]
        cs.sort(key=lambda k: k[0])
        close_ts = d["close_ts"]
        y = 1 if d["result"] == "yes" else 0
        f = {"ticker": d["ticker"], "series": d["series"], "event": d.get("event"), "y": y, "volume": d["volume"],
             "close_ts": close_ts, "span_min": (cs[-1][0] - cs[0][0]) / 60 if cs else 0,
             "n_candles": len(cs)}
        # price at each cutoff
        for h in CUTS:
            p, t, src_, a, at = price_at(cs, close_ts, h)
            f[f"p{h}"] = p
            f[f"t{h}"] = t
            f[f"src{h}"] = src_
            f[f"ask{h}"] = a
            f[f"askts{h}"] = at
            f[f"ask_age_min{h}"] = (close_ts - at) / 60 - h * 60 if at else None
            f[f"entryable{h}"] = bool(p is not None and p >= 0.99 and a is not None and a <= 0.999
                                      and at and (close_ts - at) <= 60 * 60)
        # crossing behavior at 0.99
        fc = first_cross(cs, close_ts, 0.99)
        f["x99_ts"] = fc[1] if fc else None
        f["x99_lead_h"] = (close_ts - fc[1]) / 3600 if fc else None
        # minutes (candles) with last-trade price >= 0.99
        above = [t for t, pr, yb, ya in cs if pr is not None and pr >= 0.99]
        f["min_above99"] = len(above)
        f["frac_above99"] = len(above) / max(1, len(cs))
        # persistent proxy: >=0.99 already at 6h AND never trades <0.99 in final 6h
        p6, t6, src6, _a6, _at6 = price_at(cs, close_ts, 6)
        dipped = [pr for t, pr, yb, ya in cs if t > close_ts - 6 * 3600 and pr is not None and pr < 0.99]
        f["persistent6"] = bool(p6 and p6 >= 0.99 and not dipped)
        # max price, last trade price
        priced = [(pr, t) for t, pr, yb, ya in cs if pr is not None]
        f["max_p"] = max(pr for pr, _ in priced) if priced else None
        f["last_p"] = priced[-1][0] if priced else None
        feats.append(f)

    # ---- buckets per cutoff
    tables = {}
    for h in CUTS:
        rows = []
        for bi, (lo, hi) in enumerate(BUCKETS):
            sub = [f for f in feats if f[f"p{h}"] is not None and lo <= f[f"p{h}"] < hi]
            ent = [f for f in sub if f[f"entryable{h}"]]
            nw = sum(f["y"] for f in ent)
            rows.append({"bucket": f"[{lo:.2f},{hi:.2f})", "n": len(sub), "wins": sum(f["y"] for f in sub),
                         "p_win": round(sum(f["y"] for f in sub) / len(sub), 5) if sub else None,
                         "n_entryable": len(ent), "wins_entryable": nw,
                         "p_win_entryable": round(nw / len(ent), 5) if ent else None})
            n = len(sub)
            w = sum(f["y"] for f in sub)
            ttcs = sorted((close_ts_h(f, h)) for f in sub)
            rows.append({"bucket": f"[{lo:.2f},{hi:.2f})", "n": n, "wins": w,
                         "p_win": round(w / n, 5) if n else None,
                         "ttc_med_min": (statistics.median(ttcs) if ttcs else None),
                         "ttc_p10_min": (ttcs[int(0.10 * (len(ttcs)-1))] if ttcs else None),
                         "ttc_p90_min": (ttcs[int(0.90 * (len(ttcs)-1))] if ttcs else None)})
        tables[h] = rows
    analysis = {"n_markets": len(feats), "buckets_by_lead": tables}

    # ---- >=0.99 subset by lead time
    hi_rows = {}
    for h in CUTS:
        sub = [f for f in feats if f[f"p{h}"] is not None and f[f"p{h}"] >= 0.99]
        n = len(sub)
        w = sum(f["y"] for f in sub)
        ent = [f for f in sub if f[f"entryable{h}"]]
        losses = [f for f in sub if f["y"] == 0]
        hi_rows[h] = {"n": n, "wins": w, "p_win": round(w / n, 5) if n else None,
                      "n_entryable": len(ent), "wins_entryable": sum(f["y"] for f in ent),
                      "p_win_entryable": round(sum(f["y"] for f in ent) / len(ent), 5) if ent else None,
                      "losses": [{"ticker": f["ticker"], "series": f["series"], "volume": f["volume"],
                                  "p_at_cut": f[f"p{h}"], "ask_at_cut": f[f"ask{h}"],
                                  "x99_lead_h": f["x99_lead_h"],
                                  "min_above99": f["min_above99"]} for f in losses]}
    analysis["ge99_by_lead"] = hi_rows

    # ---- opportunity frequency (per day, volume-class extrapolation)
    by_day = collections.Counter()
    by_day_big = collections.Counter()
    universe_by_day = collections.Counter()
    universe_by_day_big = collections.Counter()
    for f in feats:
        day = datetime.fromtimestamp(f["close_ts"], tz=timezone.utc).strftime("%m%d")
        by_day[day] += 1
        if f["volume"] >= 1000:
            by_day_big[day] += 1
    for r in load_universe():
        day = datetime.fromtimestamp(r["close_ts"], tz=timezone.utc).strftime("%m%d")
        universe_by_day[day] += 1
        if r["volume"] >= 1000:
            universe_by_day_big[day] += 1
    # opp = has x99 with lead >= 1h; also >=3h, >=6h
    opp = {"ge1h": [], "ge3h": [], "ge6h": []}
    for f in feats:
        lead = f["x99_lead_h"]
        if lead is None:
            continue
        if lead >= 1: opp["ge1h"].append(f)
        if lead >= 3: opp["ge3h"].append(f)
        if lead >= 6: opp["ge6h"].append(f)
    n_days = len([d for d in universe_by_day if universe_by_day[d] > 0]) or 1
    def extrapolate(subset):
        """scale sample rates per (day, volume-class) to universe counts."""
        tot = 0.0
        detail = []
        for day in sorted(universe_by_day):
            samp_day = [f for f in subset if datetime.fromtimestamp(f["close_ts"], tz=timezone.utc).strftime("%m%d") == day]
            samp_big = [f for f in samp_day if f["volume"] >= 1000]
            rate_big = len(samp_big) / by_day_big[day] if by_day_big[day] else 0.0
            est_big = rate_big * universe_by_day_big[day]
            # mid class: sample counts are uniform-ish; scale by universe/sample ratio for rest
            samp_mid = len(samp_day) - len(samp_big)
            uni_mid = universe_by_day[day] - universe_by_day_big[day]
            samp_mid_denom = by_day[day] - by_day_big[day]
            est_mid = (samp_mid / samp_mid_denom) * uni_mid if samp_mid_denom else 0
            tot += est_big + est_mid
            detail.append({"day": day, "est": round(est_big + est_mid, 1),
                           "rate_big": round(rate_big, 4), "n_samp_big": len(samp_big)})
        return tot / n_days, detail
    freq = {}
    for k, sub in opp.items():
        per_day, detail = extrapolate(sub)
        leads = sorted(f["x99_lead_h"] for f in sub)
        freq[k] = {"n_sample": len(sub), "per_day_est": round(per_day, 1),
                   "median_lead_h": statistics.median(leads) if leads else None,
                   "p25_lead_h": leads[int(0.25*(len(leads)-1))] if leads else None,
                   "p75_lead_h": leads[int(0.75*(len(leads)-1))] if leads else None,
                   "detail": detail}
    analysis["opportunity_freq"] = freq
    analysis["universe_by_day"] = dict(universe_by_day)
    analysis["universe_by_day_big"] = dict(universe_by_day_big)
    analysis["sample_by_day"] = dict(by_day)

    # ---- persistent vs spike (locked-outcome behavioral proxy)
    pers = [f for f in feats if f["persistent6"]]
    spike = [f for f in feats if f["x99_lead_h"] is not None and f["x99_lead_h"] <= 1 and not f["persistent6"]]
    analysis["persistent6"] = {"n": len(pers), "wins": sum(f["y"] for f in pers),
                               "p_win": round(sum(f["y"] for f in pers)/len(pers), 5) if pers else None}
    analysis["spike_le1h_not_persist"] = {"n": len(spike), "wins": sum(f["y"] for f in spike),
                                          "p_win": round(sum(f["y"] for f in spike)/len(spike), 5) if spike else None}


    # ---- standing-bid fill model v2: bid 0.99 at close-W, filled when yes_ask <= 0.99
    # entry price = the ask that crossed (a 0.99 bid fills at min(0.99, ask)).
    pair = list(zip(ms, feats))
    fill_stats = {}
    for W in (0.25, 1, 3, 6):
        rows_f = []
        for d, f in pair:
            close_ts = f["close_ts"]
            w0 = close_ts - W * 3600
            fill = None
            for t, pr, yb, ya in d["candles"]:
                if t <= w0:
                    continue
                if ya is not None and ya <= 0.999:
                    fill = (min(ya, 0.999), t)
                    break
            if not fill:
                continue
            entry, ft = fill
            y = f["y"]
            fe = fee(entry)
            ev_flip = y * (1 - entry - fe) - (1 - y) * (entry + fe)
            rows_f.append({"y": y, "volume": f["volume"], "series": f["series"], "entry": entry,
                           "fill_lead_min": (close_ts - ft) / 60, "ev": ev_flip,
                           "was99_before": bool(f["x99_ts"] and f["x99_ts"] <= w0)})
        n = len(rows_f); w = sum(r["y"] for r in rows_f)
        losses = [r for r in rows_f if r["y"] == 0]
        ev_avg = statistics.mean(r["ev"] for r in rows_f) if rows_f else None
        hi_entry = [r for r in rows_f if r["entry"] >= 0.98]
        fill_rows_hi = [{"series": r["series"], "entry": r["entry"], "y": r["y"],
                         "fill_lead_min": round(r["fill_lead_min"], 1)} for r in hi_entry]
        bands = [(0.99, 0.991), (0.991, 0.999), (0.999, 1.0001)]
        band_stats = []
        for blo, bhi in bands:
            br = [r for r in rows_f if blo <= r["entry"] < bhi]
            bn, bw = len(br), sum(r["y"] for r in br)
            band_stats.append({"band": f"[{blo:.3f},{bhi:.3f})", "n": bn, "wins": bw,
                               "p_win": round(bw / bn, 5) if bn else None,
                               "ev": round(statistics.mean(r["ev"] for r in br), 5) if br else None})
        fill_stats[W] = {
            "n_fills": n, "wins": w, "p_win": round(w / n, 5) if n else None,
            "avg_entry": round(statistics.mean(r["entry"] for r in rows_f), 4) if rows_f else None,
            "ev_per_fill": round(ev_avg, 5) if ev_avg is not None else None,
            "n_entry_ge98": len(hi_entry),
            "rows_entry_ge98": fill_rows_hi,
            "entry_bands": band_stats,
            "p_win_entry_ge98": round(sum(r["y"] for r in hi_entry) / len(hi_entry), 5) if hi_entry else None,
            "ev_entry_ge98": round(statistics.mean(r["ev"] for r in hi_entry), 5) if hi_entry else None,
            "median_fill_lead_min": statistics.median([r["fill_lead_min"] for r in rows_f]) if rows_f else None,
            "n_already99_before_window": sum(1 for r in rows_f if r["was99_before"]),
            "p_win_already99": round(sum(r["y"] for r in rows_f if r["was99_before"]) /
                                     max(1, sum(1 for r in rows_f if r["was99_before"])), 5),
            "top_losses": sorted([{"series": r["series"], "volume": round(r["volume"], 0),
                                   "entry": r["entry"], "fill_lead_min": round(r["fill_lead_min"], 1)}
                                  for r in losses], key=lambda r: -r["volume"])[:20]}
    analysis["standing_bid_fills"] = fill_stats

    # ---- taker strategy: buy at first ask in [0.99, 0.999] within final W hours
    taker = {}
    for W in (1, 3, 6, 24):
        rows_t = []
        for d, f in pair:
            close_ts = f["close_ts"]
            w0 = close_ts - W * 3600
            for t, pr, yb, ya in d["candles"]:
                if t <= w0:
                    continue
                if ya is not None and 0.99 <= ya <= 0.999:
                    entry = ya
                    y = f["y"]
                    fe = fee(entry)
                    rows_t.append({"y": y, "entry": entry, "series": f["series"],
                                   "volume": f["volume"], "lead_min": (close_ts - t) / 60,
                                   "ev": y * (1 - entry - fe) - (1 - y) * (entry + fe)})
                    break
        n = len(rows_t); w = sum(r["y"] for r in rows_t)
        losses = [r for r in rows_t if r["y"] == 0]
        taker[W] = {"n": n, "wins": w, "p_win": round(w / n, 5) if n else None,
                    "ev_per_trade": round(statistics.mean(r["ev"] for r in rows_t), 5) if rows_t else None,
                    "median_lead_min": statistics.median([r["lead_min"] for r in rows_t]) if rows_t else None,
                    "n_vol_ge1000": sum(1 for r in rows_t if r["volume"] >= 1000),
                    "p_win_vol_ge1000": round(sum(r["y"] for r in rows_t if r["volume"] >= 1000) /
                                              max(1, sum(1 for r in rows_t if r["volume"] >= 1000)), 5),
                    "losses": [{"series": r["series"], "entry": r["entry"], "volume": round(r["volume"], 0),
                                "lead_min": round(r["lead_min"], 1)} for r in
                               sorted(losses, key=lambda r: -r["volume"])[:20]]}
    analysis["taker_0p99_ask"] = taker

    # ---- stability-filtered taker: require last 30 min of trade prints all >= 0.99 before entry
    taker_stable = {}
    for W in (1, 3, 6):
        rows_s = []
        for d, f in pair:
            close_ts = f["close_ts"]
            w0 = close_ts - W * 3600
            for t, pr, yb, ya in d["candles"]:
                if t <= w0:
                    continue
                if ya is not None and 0.99 <= ya <= 0.999:
                    # stability: every trade print in the prior 30 min >= 0.99 and at least 3 prints
                    prior = [pr2 for t2, pr2, yb2, ya2 in d["candles"]
                             if t2 < t and t2 >= t - 30 * 60 and pr2 is not None]
                    if len(prior) >= 3 and all(p2 >= 0.99 for p2 in prior):
                        entry = ya
                        y = f["y"]
                        fe = fee(entry)
                        rows_s.append({"y": y, "entry": entry, "series": f["series"],
                                       "volume": f["volume"], "lead_min": (close_ts - t) / 60,
                                       "ev": y * (1 - entry - fe) - (1 - y) * (entry + fe)})
                    break
        n = len(rows_s); w = sum(r["y"] for r in rows_s)
        losses = [r for r in rows_s if r["y"] == 0]
        taker_stable[W] = {"n": n, "wins": w, "p_win": round(w / n, 5) if n else None,
                           "ev_per_trade": round(statistics.mean(r["ev"] for r in rows_s), 5) if rows_s else None,
                           "median_lead_min": statistics.median([r["lead_min"] for r in rows_s]) if rows_s else None,
                           "losses": [{"series": r["series"], "volume": round(r["volume"], 0),
                                       "lead_min": round(r["lead_min"], 1)} for r in
                                      sorted(losses, key=lambda r: -r["volume"])[:20]]}
    analysis["taker_stable30"] = taker_stable

    # ---- category mix
    cats = collections.Counter()
    cat_stats = collections.defaultdict(lambda: [0, 0, 0])  # n, ge99opp, losses_at_99
    for f in feats:
        c = (catmap.get(f.get("event")) or catmap.get(f["series"]) or {}).get("category") or "?"
        cats[c] += 1
        st = cat_stats[c]
        st[0] += 1
        if f["x99_lead_h"] is not None and f["x99_lead_h"] >= 1:
            st[1] += 1
            if f["y"] == 0:
                st[2] += 1
    analysis["category_mix"] = {c: {"n": v, "n_series": len(set(f['series'] for f in feats if ((catmap.get(f['series']) or {}).get('category') or '?') == c)),
                                    "ge99_opp": cat_stats[c][1], "ge99_losses": cat_stats[c][2]}
                                for c, v in cats.most_common()}

    # ---- EV per bucket (fee-adjusted), per lead time
    ev = {}
    for h in CUTS:
        ev[h] = []
        for bi, (lo, hi_) in enumerate(BUCKETS):
            sub = [f for f in feats if f[f"p{h}"] is not None and lo <= f[f"p{h}"] < hi_]
            if not sub:
                ev[h].append({"bucket": f"[{lo:.2f},{hi_:.2f})", "n": 0})
                continue
            pavg = statistics.mean(f[f"p{h}"] for f in sub)
            w = sum(f["y"] for f in sub) / len(sub)
            fe = fee(pavg)
            net_win = 1 - pavg - fe
            net_loss = pavg + fe
            evd = w * net_win - (1 - w) * net_loss
            ev[h].append({"bucket": f"[{lo:.2f},{hi_:.2f})", "n": len(sub), "p_avg": round(pavg, 4),
                          "p_win": round(w, 5), "fee": round(fe, 4),
                          "net_win": round(net_win, 4), "net_loss": round(net_loss, 4),
                          "ev_per_flip": round(evd, 5)})
    analysis["ev_by_lead"] = ev

    # ---- last-minute reversal: markets whose last trade < 0.97 but max >= 0.99 earlier
    rev = [f for f in feats if f["max_p"] and f["max_p"] >= 0.99 and f["last_p"] is not None and f["last_p"] < 0.97]
    analysis["late_reversals"] = {"n": len(rev), "tickers": [f["ticker"] for f in rev][:50]}

    json.dump(analysis, open(OUT / "analysis.json", "w"), indent=1)
    # print compact
    print(json.dumps({k: analysis[k] for k in ("ge99_by_lead", "opportunity_freq", "persistent6",
                                               "spike_le1h_not_persist", "standing_bid_fills",
                                               "taker_0p99_ask", "late_reversals")}, indent=1)[:11000])
    print("category_mix:", json.dumps(analysis["category_mix"], indent=1)[:2000])
    return analysis


def close_ts_h(f, h):
    return (f["close_ts"] - f[f"t{h}"]) / 60 if f[f"t{h}"] else None


if __name__ == "__main__":
    main()
