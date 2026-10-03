"""Build event_table.csv: one row per CPI release.

Inputs (in --data)
  releases.csv          from kalshi_fetch.py
  kalshi_snapshots.csv  from kalshi_fetch.py
  spx_daily.csv         columns: date, open, close, optional dividend and level_0935 (SPY; from massive_fetch.py)
                        dividend = cash paid on the ex-dividend date; it is added back to that day's prices
  vix_daily.csv         columns: date, close         (FRED's VIXCLS column name is accepted)
  consensus.csv         optional: release_date, core_consensus, headline_consensus

Every rule below is fixed in PREREGISTRATION.md; change CONFIG only before looking at results.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from common import choose_price, dist_stats, ladder_to_distribution, to_greater_than

CONFIG = {
    "grid": {"cpi_headline": 0.1, "cpi_core": 0.1, "fed": 0.25},  # outcome grid in percentage points
    "max_trade_age_s": 86_400,   # last trade must be within 24h of the snapshot
    "max_spread": 0.10,          # otherwise use the bid-ask midpoint if the spread is <= $0.10
    "price_rule": "trade",       # "trade" = last trade first, "mid" = midpoint first
    "min_strikes": 4,            # fewer usable strikes -> distribution treated as missing
    "upper_tail_steps": 1.0,     # mass above the top strike sits one grid step above it
}


def _nn(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else x


def build_distributions(snaps, cfg):
    out = {}
    for (rd, role, label), g in snaps.groupby(["release_date", "role", "label"]):
        step = cfg["grid"][role]
        pts = []
        for r in g.itertuples(index=False):
            price = choose_price(_nn(r.last_price), _nn(r.last_trade_ts), _nn(r.yes_bid), _nn(r.yes_ask),
                                 r.snapshot_ts, cfg["max_trade_age_s"], cfg["max_spread"], cfg["price_rule"])
            conv = to_greater_than(r.strike_type, _nn(r.floor_strike), _nn(r.cap_strike), price, step)
            if conv:
                pts.append(conv)
        rec = {"n_strikes": len(pts)}
        if len(pts) >= cfg["min_strikes"]:
            k, s = zip(*pts)
            values, probs = ladder_to_distribution(k, s, step=step, upper_tail_steps=cfg["upper_tail_steps"])
            if values is not None:
                rec.update(dist_stats(values, probs, step))
                rec["values"] = [round(float(x), 4) for x in values]
                rec["probs"] = [round(float(x), 5) for x in probs]
        out[(str(rd), role, label)] = rec
    return out


def load_prices(path, need_open):
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    date_col = cols.get("date") or cols.get("observation_date") or df.columns[0]
    close_col = cols.get("close") or cols.get("vixcls") or cols.get("adj close")
    out = pd.DataFrame({"date": pd.to_datetime(df[date_col]).dt.date,
                        "close": pd.to_numeric(df[close_col], errors="coerce")})
    if need_open:
        out["open"] = pd.to_numeric(df[cols["open"]], errors="coerce")
        if "level_0935" in cols:
            out["level_0935"] = pd.to_numeric(df[cols["level_0935"]], errors="coerce")
        out["dividend"] = (pd.to_numeric(df[cols["dividend"]], errors="coerce").fillna(0.0)
                           if "dividend" in cols else 0.0)
    out = out.dropna(subset=[c for c in ("close", "open") if c in out.columns])
    return out.sort_values("date").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    rel = pd.read_csv(os.path.join(args.data, "releases.csv"))
    snaps = pd.read_csv(os.path.join(args.data, "kalshi_snapshots.csv"))
    spx = load_prices(os.path.join(args.data, "spx_daily.csv"), need_open=True)
    vix = load_prices(os.path.join(args.data, "vix_daily.csv"), need_open=False)
    cons_path = os.path.join(args.data, "consensus.csv")
    cons = pd.read_csv(cons_path) if os.path.exists(cons_path) else None
    if cons is not None:
        cons["release_date"] = pd.to_datetime(cons["release_date"]).dt.date.astype(str)
        cons = cons.set_index("release_date")

    dists = build_distributions(snaps, CONFIG)
    spx_idx = {d: i for i, d in enumerate(spx["date"])}
    vix_map = dict(zip(vix["date"], vix["close"]))
    close = spx["close"].to_numpy()
    div = spx["dividend"].to_numpy()
    # daily log return with the ex-date dividend added back: ln((C_k + D_k) / C_{k-1})
    daily_ret = 100 * np.log((close[1:] + div[1:]) / close[:-1])

    rows = []
    for r in rel.itertuples(index=False):
        rd = str(r.release_date)
        R = pd.to_datetime(rd).date()

        def g(role, label, key, scale=1.0):
            v = dists.get((rd, role, label), {}).get(key, np.nan)
            return v * scale if isinstance(v, (int, float)) and not np.isnan(v) else np.nan

        rec = {"release_date": rd, "year": R.year,
               "headline_actual": r.headline_actual, "core_actual": r.core_actual,
               "fed_meeting_date": r.fed_meeting_date}
        for pfx, role in (("core", "cpi_core"), ("headline", "cpi_headline")):
            for lab in ("t0", "pre"):
                rec[f"{pfx}_mean_{lab}"] = g(role, lab, "mean")
                rec[f"{pfx}_median_{lab}"] = g(role, lab, "median")
            rec[f"{pfx}_sd_t0"] = g(role, "t0", "sd")
            rec[f"{pfx}_iqr_t0"] = g(role, "t0", "iqr")
            rec[f"n_{pfx}_strikes_t0"] = g(role, "t0", "n_strikes")
            actual = rec[f"{pfx}_actual"]
            exp_pre = rec[f"{pfx}_mean_pre"]
            rec[f"surprise_{pfx}"] = actual - (exp_pre if not np.isnan(exp_pre) else rec[f"{pfx}_mean_t0"])
            rec[f"surprise_{pfx}_t0"] = actual - rec[f"{pfx}_mean_t0"]

        rec["fed_sd_t0_bp"] = g("fed", "t0", "sd", 100)
        rec["fed_iqr_t0_bp"] = g("fed", "t0", "iqr", 100)
        rec["fed_notmode_t0"] = 1 - g("fed", "t0", "pmode")
        rec["fed_entropy_t0"] = g("fed", "t0", "entropy")
        rec["n_fed_strikes_t0"] = g("fed", "t0", "n_strikes")
        for lab in ("t0", "pre", "post"):
            rec[f"fed_mean_{lab}"] = g("fed", lab, "mean")
        rec["d_fed_mean_bp"] = 100 * (rec["fed_mean_post"] - rec["fed_mean_pre"])
        rec["days_to_meeting"] = ((pd.to_datetime(r.fed_meeting_date).date() - R).days
                                  if isinstance(r.fed_meeting_date, str) else np.nan)
        rec["fomc_same_day"] = rec["days_to_meeting"] == 0

        prev = pd.to_datetime(r.t0_date).date() if isinstance(r.t0_date, str) else None
        if R in spx_idx and prev in spx_idx:
            i, j = spx_idx[R], spx_idx[prev]
            lvl = spx["level_0935"].iloc[i] if "level_0935" in spx.columns else np.nan
            use_935 = isinstance(lvl, (int, float)) and not np.isnan(lvl)
            px = lvl if use_935 else spx["open"].iloc[i]
            rec["r_open"] = 100 * np.log((px + div[i]) / close[j])
            rec["r_open_source"] = "09:35 level" if use_935 else "official open"
            rec["r_close"] = 100 * np.log((close[i] + div[i]) / close[j])
            daily = np.abs(daily_ret[max(j - 5, 0): j])
            rec["abs_pre5"] = float(daily.mean()) if len(daily) else np.nan
        else:
            rec["r_open"] = rec["r_close"] = rec["abs_pre5"] = np.nan
            rec["r_open_source"] = None
        rec["vix_prev"] = vix_map.get(prev, np.nan)

        if cons is not None and rd in cons.index:
            for pfx in ("core", "headline"):
                col = f"{pfx}_consensus"
                if col in cons.columns:
                    c = cons.loc[rd, col]
                    rec[col] = c
                    rec[f"gap_{pfx}"] = abs(rec[f"{pfx}_median_pre"] - c)
                    rec[f"cons_surprise_{pfx}"] = rec[f"{pfx}_actual"] - c
        rows.append(rec)

    dist_out = {}
    for (rd, role, label), rec in dists.items():
        if "values" in rec:
            dist_out.setdefault(rd, {}).setdefault(role, {})[label] = {
                k: rec[k] for k in ("values", "probs", "mean", "sd", "n_strikes")}
    with open(os.path.join(args.out, "distributions.json"), "w") as fh:
        json.dump(dist_out, fh)

    table = pd.DataFrame(rows)
    path = os.path.join(args.out, "event_table.csv")
    table.to_csv(path, index=False)
    need = ["surprise_core", "fed_sd_t0_bp", "r_open", "vix_prev"]
    usable = table.dropna(subset=need)
    print(f"{len(table)} releases; {len(usable)} usable for the primary test "
          f"({usable['release_date'].min()} to {usable['release_date'].max()}). Wrote {path}")
    for col in need:
        miss = table[col].isna().sum()
        if miss:
            print(f"  missing {col}: {miss}")


if __name__ == "__main__":
    main()
