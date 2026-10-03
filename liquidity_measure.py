"""Pre-registered liquidity measurement for the CPI-eve butterfly (LIQUIDITY_PREREGISTRATION.md).

Measures what the SPXW butterfly would cost to enter and how much of it could be traded, from real Massive
quotes and volume on each release eve. It computes NO returns: no release-day prices are fetched, and mid
prices are used only to pick strikes, scale the spread and size the maximum loss.

  python liquidity_measure.py fetch      # quotes and volume for release eves -> data/liquidity_*.csv (gitignored)
  python liquidity_measure.py run        # metrics -> results/liquidity_results.json, results/liquidity_summary.md

Every setting below is fixed in LIQUIDITY_PREREGISTRATION.md.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date

import numpy as np
import pandas as pd

from common import et_timestamp

# ---- pre-registered settings (mirrored in LIQUIDITY_PREREGISTRATION.md) ----
WINDOW_MINUTES = [(15, m) for m in range(45, 60)] + [(16, m) for m in range(0, 16)]   # 15:45 to 16:15 ET, 31 marks
ATM_MARK = (16, 0)            # strikes are chosen from quotes at 16:00 ET
STRIKE_STEP = 5               # SPXW strike spacing near the money (index points)
CANDIDATE_HALF_WIDTH = 40     # ATM candidates: strikes within 40 points of 10 x SPY's prior close
WING_MULT = 2.0               # wings two implied moves from the centre, as in Stage 2-lite
ASSUMED_COST_FRAC = 0.03      # Stage 2-lite's entry-cost assumption (share of the straddle value)
VOLUME_SHARE = 0.10           # capacity: trade at most 10% of the thinnest leg's release-eve volume
RISK = 0.01                   # 1% of capital at risk per release
MULTIPLIER = 100              # SPX option multiplier, dollars per index point
MIN_MARKS = 20                # a leg needs valid two-sided quotes at 20 of the 31 marks


# ---------------------------------------------------------------- pure helpers (tested offline)
def spxw_ticker(expiry: date, cp: str, strike: float) -> str:
    return f"O:SPXW{expiry:%y%m%d}{cp.upper()}{int(round(strike * 1000)):08d}"


def valid(bid, ask):
    return bid is not None and ask is not None and bid > 0 and ask > bid


def quote_at(quotes, ts_ns):
    """Last two-sided quote at or before ts_ns from a list sorted by sip_timestamp: (bid, ask, bid_size, ask_size)."""
    best = None
    for q in quotes:
        if q["sip_timestamp"] > ts_ns:
            break
        if valid(q.get("bid_price"), q.get("ask_price")):
            best = (q["bid_price"], q["ask_price"], q.get("bid_size"), q.get("ask_size"))
    return best


def choose_atm(call_mids: dict, put_mids: dict):
    """Strike where call and put mids are closest (put-call parity); None if no strike has both."""
    both = [k for k in call_mids if k in put_mids]
    return min(both, key=lambda k: (abs(call_mids[k] - put_mids[k]), k)) if both else None


def wing_strikes(atm: float, straddle_mid: float):
    width = max(STRIKE_STEP, STRIKE_STEP * round(WING_MULT * straddle_mid / STRIKE_STEP))
    return atm - width, atm + width, width


def fly_metrics(legs: dict):
    """legs: {'call_atm','put_atm','call_wing','put_wing'} -> (bid, ask, bid_size, ask_size) at one mark.
    Short the ATM straddle (sell at the bid), long the wings (buy at the ask)."""
    mid = {k: (b + a) / 2 for k, (b, a, _, _) in legs.items()}
    half = {k: (a - b) / 2 for k, (b, a, _, _) in legs.items()}
    straddle = mid["call_atm"] + mid["put_atm"]
    credit_mid = straddle - mid["call_wing"] - mid["put_wing"]
    crossing = sum(half.values())                                  # entry cost of crossing every spread
    sizes = [legs["call_atm"][2], legs["put_atm"][2], legs["call_wing"][3], legs["put_wing"][3]]
    return {"straddle_mid": straddle, "credit_mid": credit_mid, "crossing_pts": crossing,
            "assumed_cost_pts": ASSUMED_COST_FRAC * straddle,
            "crossing_share_of_straddle": crossing / straddle if straddle > 0 else float("nan"),
            "min_top_size": min(s for s in sizes if s is not None) if any(s is not None for s in sizes) else None}


def capacity(min_leg_volume: float, max_loss_pts: float):
    contracts = math.floor(VOLUME_SHARE * min_leg_volume)
    loss_usd = max_loss_pts * MULTIPLIER
    return {"contracts": contracts, "max_loss_usd_per_fly": loss_usd, "capital_usd": contracts * loss_usd / RISK}


# ---------------------------------------------------------------- data access
def release_eves(derived="derived"):
    """Stage 2-lite releases (those with VIX1D on the eve): (release date = expiry, eve date)."""
    rel = pd.read_csv(os.path.join(derived, "releases.csv"))
    eves = set(pd.read_csv(os.path.join(derived, "vix1d_release_eves.csv"))["date"].astype(str))
    rel = rel[rel["t0_date"].astype(str).isin(eves)]
    return [(date.fromisoformat(r), date.fromisoformat(t)) for r, t in zip(rel["release_date"].astype(str), rel["t0_date"].astype(str))]


def ns(d: date, hh: int, mm: int) -> int:
    return et_timestamp(d, hh, mm) * 1_000_000_000


def fetch_quotes(m, ticker, start_ns, end_ns):
    js = m.get(f"/v3/quotes/{ticker}", **{"timestamp.gte": start_ns, "timestamp.lte": end_ns, "limit": 50000, "order": "asc"})
    out, nxt = list(js.get("results") or []), js.get("next_url")
    while nxt:
        js = m.get(nxt)
        out += js.get("results") or []
        nxt = js.get("next_url")
    return sorted(out, key=lambda q: q["sip_timestamp"])


def last_quote_before(m, ticker, ts_ns):
    js = m.get(f"/v3/quotes/{ticker}", **{"timestamp.lte": ts_ns, "timestamp.gte": ts_ns - 15 * 60 * 10**9,
                                          "limit": 50, "order": "desc"})
    for q in js.get("results") or []:
        if valid(q.get("bid_price"), q.get("ask_price")):
            return (q["bid_price"], q["ask_price"])
    return None


def cmd_fetch(args):
    import massive_fetch as mf
    mf.load_env()
    m = mf.Massive(os.environ["MASSIVE_API_KEY"])
    spy = pd.read_csv(os.path.join(args.data, "spx_daily.csv"))
    spy_close = dict(zip(spy["date"].astype(str), spy["close"]))
    snap_path, vol_path = os.path.join(args.data, "liquidity_snapshots.csv"), os.path.join(args.data, "liquidity_volume.csv")
    done = set(pd.read_csv(vol_path)["release_date"].astype(str)) if os.path.exists(vol_path) else set()
    for i, (expiry, eve) in enumerate(release_eves(args.derived), 1):
        if expiry.isoformat() in done:
            continue
        centre = STRIKE_STEP * round(10 * spy_close[eve.isoformat()] / STRIKE_STEP)
        cands = range(int(centre - CANDIDATE_HALF_WIDTH), int(centre + CANDIDATE_HALF_WIDTH) + 1, STRIKE_STEP)
        atm_ts = ns(eve, *ATM_MARK)
        cm, pm = {}, {}
        for k in cands:
            for cp, store in (("C", cm), ("P", pm)):
                q = last_quote_before(m, spxw_ticker(expiry, cp, k), atm_ts)
                if q:
                    store[k] = (q[0] + q[1]) / 2
        atm = choose_atm(cm, pm)
        rows, vols = [], []
        if atm is not None:
            put_w, call_w, width = wing_strikes(atm, cm[atm] + pm[atm])
            legs = {"call_atm": ("C", atm), "put_atm": ("P", atm), "call_wing": ("C", call_w), "put_wing": ("P", put_w)}
            for leg, (cp, k) in legs.items():
                tk = spxw_ticker(expiry, cp, k)
                quotes = fetch_quotes(m, tk, ns(eve, *WINDOW_MINUTES[0]) - 15 * 60 * 10**9, ns(eve, *WINDOW_MINUTES[-1]))
                for hh, mm in WINDOW_MINUTES:
                    q = quote_at(quotes, ns(eve, hh, mm))
                    rows.append({"release_date": expiry.isoformat(), "eve": eve.isoformat(), "leg": leg, "ticker": tk,
                                 "strike": k, "mark": f"{hh:02d}:{mm:02d}", "bid": q[0] if q else None, "ask": q[1] if q else None,
                                 "bid_size": q[2] if q else None, "ask_size": q[3] if q else None})
                day = m.aggs(tk, 1, "day", eve.isoformat(), eve.isoformat())
                vols.append({"release_date": expiry.isoformat(), "eve": eve.isoformat(), "leg": leg, "ticker": tk,
                             "strike": k, "eve_volume": float(day[0].get("v", 0)) if day else 0.0, "atm": atm, "wing_width": width})
        else:
            vols.append({"release_date": expiry.isoformat(), "eve": eve.isoformat(), "leg": None, "ticker": None,
                         "strike": None, "eve_volume": None, "atm": None, "wing_width": None})
        pd.DataFrame(rows).to_csv(snap_path, mode="a", index=False, header=not os.path.exists(snap_path))
        pd.DataFrame(vols).to_csv(vol_path, mode="a", index=False, header=not os.path.exists(vol_path))
        print(f"[{i}] {expiry}: ATM {atm}, {len(rows)} snapshot rows, {m.calls} API calls so far", flush=True)


def cmd_run(args):
    snaps = pd.read_csv(os.path.join(args.data, "liquidity_snapshots.csv"))
    vols = pd.read_csv(os.path.join(args.data, "liquidity_volume.csv"))
    per = []
    for rd, g in snaps.groupby("release_date"):
        ok_legs = g.dropna(subset=["bid", "ask"]).query("ask > bid and bid > 0").groupby("leg")["mark"].nunique()
        if len(ok_legs) < 4 or (ok_legs < MIN_MARKS).any():
            per.append({"release_date": rd, "usable": False})
            continue
        marks = []
        for mark, h in g.groupby("mark"):
            legs = {r.leg: (r.bid, r.ask, r.bid_size, r.ask_size) for r in h.itertuples() if valid(r.bid, r.ask)}
            if len(legs) == 4:
                marks.append(fly_metrics(legs))
        mm = pd.DataFrame(marks)
        v = vols[vols["release_date"] == rd]
        width = float(v["wing_width"].iloc[0])
        credit = float(mm["credit_mid"].median())
        cap = capacity(float(v["eve_volume"].min()), width - credit)
        per.append({"release_date": rd, "usable": True, "marks": int(len(mm)),
                    "crossing_pts": float(mm["crossing_pts"].median()),
                    "assumed_cost_pts": float(mm["assumed_cost_pts"].median()),
                    "crossing_share_of_straddle": float(mm["crossing_share_of_straddle"].median()),
                    "min_top_size": float(mm["min_top_size"].median()),
                    "min_leg_eve_volume": float(v["eve_volume"].min()), "wing_width": width,
                    "max_loss_pts": width - credit, **cap})
    pr = pd.DataFrame(per)
    u = pr[pr["usable"]]
    q = lambda col, p: float(np.quantile(u[col], p))
    res = {"n_releases": int(len(pr)), "n_usable": int(len(u)),
           "crossing_share_median": q("crossing_share_of_straddle", 0.5), "crossing_share_p90": q("crossing_share_of_straddle", 0.9),
           "crossing_pts_median": q("crossing_pts", 0.5), "assumed_cost_pts_median": q("assumed_cost_pts", 0.5),
           "share_above_3pct": float((u["crossing_share_of_straddle"] > ASSUMED_COST_FRAC).mean()),
           "share_above_6pct": float((u["crossing_share_of_straddle"] > 2 * ASSUMED_COST_FRAC).mean()),
           "min_top_size_median": q("min_top_size", 0.5), "min_leg_volume_median": q("min_leg_eve_volume", 0.5),
           "capacity_contracts_median": q("contracts", 0.5), "capacity_contracts_min": float(u["contracts"].min()),
           "capacity_capital_median": q("capital_usd", 0.5), "capacity_capital_min": float(u["capital_usd"].min()),
           "max_loss_usd_median": q("max_loss_usd_per_fly", 0.5),
           "settings": {"volume_share": VOLUME_SHARE, "risk": RISK, "assumed_cost_frac": ASSUMED_COST_FRAC,
                        "window": "15:45-16:15 ET", "atm_mark": "16:00 ET"}}
    os.makedirs(args.out, exist_ok=True)
    pr.to_csv(os.path.join(args.out, "liquidity_per_release.csv"), index=False)
    with open(os.path.join(args.out, "liquidity_results.json"), "w") as fh:
        json.dump(res, fh, indent=1)
    lines = ["# Liquidity measurement (pre-registered; no returns computed)", "",
             f"{res['n_usable']} of {res['n_releases']} release eves usable.", "",
             f"- Cost of crossing all four spreads: median {res['crossing_share_median']:.1%} of the straddle "
             f"(90th percentile {res['crossing_share_p90']:.1%}); median {res['crossing_pts_median']:.2f} index points vs "
             f"{res['assumed_cost_pts_median']:.2f} under the 3% assumption. Above 3%: {res['share_above_3pct']:.0%} of eves; "
             f"above 6%: {res['share_above_6pct']:.0%}.",
             f"- Smallest top-of-book size across the four legs: median {res['min_top_size_median']:.0f} contracts.",
             f"- Thinnest leg's release-eve volume: median {res['min_leg_volume_median']:.0f} contracts.",
             f"- Capacity at {VOLUME_SHARE:.0%} of that volume and {RISK:.0%} risk: median {res['capacity_contracts_median']:.0f} "
             f"butterflies (${res['capacity_capital_median']:,.0f} of capital); minimum {res['capacity_contracts_min']:.0f} "
             f"(${res['capacity_capital_min']:,.0f})."]
    open(os.path.join(args.out, "liquidity_summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "run"):
        p = sub.add_parser(name)
        p.add_argument("--data", default="data")
        p.add_argument("--derived", default="derived")
        p.add_argument("--out", default="results")
    args = ap.parse_args()
    {"fetch": cmd_fetch, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
