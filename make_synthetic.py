"""Generate fake data in exactly the format kalshi_fetch.py writes, with a known effect,
so the whole pipeline can be checked before real data exist.

  python make_synthetic.py --out data_synth --ratio 2.5     # planted effect: live meetings 2.5x as sensitive
  python make_synthetic.py --out data_null  --ratio 1.0     # no effect: the test should usually say NO-GO

The planted mechanism mirrors the hypothesis: CPI surprises shift Kalshi's Fed odds on a
logistic scale (so the expected rate moves most when the meeting is a coin flip), and the
S&P 500's reaction to a surprise scales with how live the next meeting is.
"""
from __future__ import annotations

import argparse
import os
from datetime import timedelta

import numpy as np
import pandas as pd
from scipy import stats

from common import dist_stats, et_timestamp, ladder_to_distribution, zscore


def cpi_ladder(mean, sd, strikes):
    """P(print > k) for a print rounded to 0.1 from a normal belief."""
    return np.array([1 - stats.norm.cdf((k + 0.05 - mean) / sd) for k in strikes])


def fed_ladder(mode, p_hi, strikes, tail=0.01):
    """Two-outcome Fed belief (mode vs mode + 25bp) with thin tails; returns P(UB > k)."""
    support = {mode - 0.25: tail, mode: (1 - p_hi) - tail, mode + 0.25: p_hi - tail, mode + 0.5: tail}
    support = {k: max(v, 1e-4) for k, v in support.items()}
    tot = sum(support.values())
    return np.array([sum(v for u, v in support.items() if u > k) / tot for k in strikes])


def rows_for(release_date, role, label, ts, event, strikes, surv, rng):
    out = []
    for k, s in zip(strikes, surv):
        px = float(np.clip(s + rng.normal(0, 0.008), 0.01, 0.99))
        out.append({"release_date": release_date, "role": role, "label": label, "snapshot_ts": ts,
                    "series": "SYN", "event_ticker": event, "ticker": f"{event}-T{k:.2f}",
                    "strike_type": "greater", "floor_strike": round(k, 2), "cap_strike": None,
                    "last_price": round(px, 2), "last_trade_ts": ts - int(rng.integers(30, 3600)),
                    "yes_bid": round(max(px - 0.01, 0.0), 2), "yes_ask": round(min(px + 0.01, 1.0), 2),
                    "quote_ts": ts - 30, "vol_24h": float(rng.integers(500, 50_000))})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data_synth")
    ap.add_argument("--ratio", type=float, default=2.5, help="sensitivity at +1 SD liveness / at -1 SD")
    ap.add_argument("--beta", type=float, default=-8.0, help="SPX %% move per 1pp core surprise at average liveness")
    ap.add_argument("--noise", type=float, default=0.45, help="SD of non-CPI overnight move (%%)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    os.makedirs(args.out, exist_ok=True)

    days = pd.bdate_range("2021-11-01", "2026-10-01")
    vix = pd.Series(18.0, index=days)
    level = {2021: 19, 2022: 26, 2023: 17, 2024: 15, 2025: 18, 2026: 16}
    x = 0.0
    for i, d in enumerate(days):
        x = 0.9 * x + rng.normal(0, 1.2)
        vix.iloc[i] = max(10.0, level[d.year] + x)

    # One release per month, mid-month weekday
    releases = []
    for m in pd.date_range("2022-01-01", "2026-09-01", freq="MS"):
        cands = [d for d in days if d.year == m.year and d.month == m.month and 10 <= d.day <= 15]
        R = cands[int(rng.integers(0, len(cands)))]
        releases.append(R)

    cpi_strikes_rel = np.round(np.arange(-0.3, 0.31, 0.1), 2)
    snap_rows, rel_rows, info = [], [], []
    mode = 0.5
    for R in releases:
        idx = days.get_loc(R)
        t0d = days[idx - 1]
        ts = {"t0": et_timestamp(t0d.date(), 15, 45), "pre": et_timestamp(R.date(), 8, 25),
              "post": et_timestamp(R.date(), 10, 0)}
        rd = R.date().isoformat()
        # core and headline beliefs
        k_mean = 0.3 + rng.normal(0, 0.08)
        k_sd = rng.uniform(0.07, 0.13)
        actual_core = round(k_mean + rng.normal(0, 0.09), 1)
        h_mean = k_mean + rng.normal(0, 0.05)
        actual_head = round(actual_core + rng.normal(0, 0.08), 1)
        centre = round(k_mean, 1)
        strikes = np.round(centre + cpi_strikes_rel, 2)
        for role, mu, ev in (("cpi_core", k_mean, f"SYNCORE-{rd}"), ("cpi_headline", h_mean, f"SYNCPI-{rd}")):
            surv = cpi_ladder(mu, k_sd, strikes)
            for lab in ("t0", "pre"):
                snap_rows += rows_for(rd, role, lab, ts[lab], ev, strikes, surv, rng)
        v, p = ladder_to_distribution(strikes, cpi_ladder(k_mean, k_sd, strikes), step=0.1)
        kal_mean = dist_stats(v, p, 0.1)["mean"]
        surprise = actual_core - kal_mean

        # Fed: drifting policy rate; liveness = probability of the 25bp-higher outcome
        mode = float(np.clip(mode + rng.choice([-0.25, 0, 0, 0.25]), 0.25, 5.5))
        p_hi = float(np.clip(rng.beta(1.2, 3.0), 0.02, 0.6)) if R.year != 2022 else float(rng.uniform(0.2, 0.6))
        f_strikes = np.round(np.arange(mode - 1.0, mode + 1.01, 0.25), 2)
        fed_ev = f"SYNFED-{rd}"
        for lab in ("t0", "pre"):
            snap_rows += rows_for(rd, "fed", lab, ts[lab], fed_ev, f_strikes, fed_ladder(mode, p_hi, f_strikes), rng)
        logit = np.log(p_hi / (1 - p_hi)) + 0.8 * surprise / 0.1
        p_post = float(np.clip(1 / (1 + np.exp(-logit)), 0.02, 0.98))
        snap_rows += rows_for(rd, "fed", "post", ts["post"], fed_ev, f_strikes, fed_ladder(mode, p_post, f_strikes), rng)
        vf, pf = ladder_to_distribution(f_strikes, fed_ladder(mode, p_hi, f_strikes), step=0.25)
        info.append({"R": R, "t0d": t0d, "surprise": surprise, "fed_sd": dist_stats(vf, pf, 0.25)["sd"]})
        meeting = (R + timedelta(days=int(rng.integers(1, 42)))).date().isoformat()
        rel_rows.append({"release_date": rd, "t0_date": t0d.date().isoformat(),
                         "headline_event": f"SYNCPI-{rd}", "headline_actual": actual_head,
                         "core_event": f"SYNCORE-{rd}", "core_actual": actual_core,
                         "fed_event": fed_ev, "fed_meeting_date": meeting,
                         "t0_ts": ts["t0"], "pre_ts": ts["pre"], "post_ts": ts["post"]})

    # SPX path with planted sensitivity on release mornings
    lz = zscore([i["fed_sd"] for i in info])
    g = np.log(args.ratio) / 2
    react = {i["R"]: args.beta * np.exp(g * z) * i["surprise"] for i, z in zip(info, lz)}
    opens, closes, close = [], [], 4500.0
    for d in days:
        scale = vix[d] / 18
        on = react.get(d, 0.0) + rng.normal(0, args.noise * scale) if d in react else rng.normal(0, 0.3 * scale)
        o = close * np.exp(on / 100)
        close = o * np.exp(rng.normal(0.03, 0.8 * scale) / 100)
        opens.append(o); closes.append(close)

    pd.DataFrame({"date": days.date, "open": np.round(opens, 2), "close": np.round(closes, 2)}).to_csv(
        os.path.join(args.out, "spx_daily.csv"), index=False)
    pd.DataFrame({"date": days.date, "close": np.round(vix.values, 2)}).to_csv(
        os.path.join(args.out, "vix_daily.csv"), index=False)
    pd.DataFrame(rel_rows).to_csv(os.path.join(args.out, "releases.csv"), index=False)
    pd.DataFrame(snap_rows).to_csv(os.path.join(args.out, "kalshi_snapshots.csv"), index=False)
    print(f"Wrote {len(rel_rows)} synthetic releases to {args.out} (planted ratio {args.ratio})")


if __name__ == "__main__":
    main()
