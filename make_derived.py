"""Rebuild derived/ (the committed per-release files run_all.py and the note use) from data/ and results/.

  python make_derived.py            # after the full pipeline in DATA.md
  python run_all.py --write-expected results

Writes only per-release or summary values, never raw price series.
"""
from __future__ import annotations

import json
import os
import shutil

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, RESULTS, DERIVED = (os.path.join(HERE, d) for d in ("data", "results", "derived"))


def main():
    os.makedirs(DERIVED, exist_ok=True)
    for src, name in ((RESULTS, "event_table.csv"), (RESULTS, "distributions.json"), (DATA, "releases.csv")):
        shutil.copy(os.path.join(src, name), os.path.join(DERIVED, name))
    rel = pd.read_csv(os.path.join(DATA, "releases.csv"))
    rel["release_date"], rel["t0_date"] = rel["release_date"].astype(str), rel["t0_date"].astype(str)
    t0 = dict(zip(rel["release_date"], rel["t0_date"]))

    # VIX1D close on release eves (Cboe)
    v1 = pd.read_csv(os.path.join(DATA, "vix1d_daily.csv"))
    v1["date"] = pd.to_datetime(v1["date"]).dt.date.astype(str)
    v1[v1["date"].isin(set(rel["t0_date"]))].sort_values("date").to_csv(
        os.path.join(DERIVED, "vix1d_release_eves.csv"), index=False)

    # VIX close before and on each release day (Cboe)
    vx = pd.read_csv(os.path.join(DATA, "vix_daily.csv"))
    vx["date"] = pd.to_datetime(vx["date"]).dt.date.astype(str)
    vm = dict(zip(vx["date"], vx["close"]))
    out = rel[["release_date", "t0_date"]].copy()
    out["vix_prev_close"], out["vix_release_close"] = out["t0_date"].map(vm), out["release_date"].map(vm)
    out.to_csv(os.path.join(DERIVED, "release_vix.csv"), index=False)

    # Kalshi activity at t0: 24h contract volume and median quoted spread per release and ladder
    sn = pd.read_csv(os.path.join(DATA, "kalshi_snapshots.csv"))
    sn = sn[sn["label"] == "t0"].copy()
    sn["spread"] = sn["yes_ask"] - sn["yes_bid"]
    sn.groupby(["release_date", "role"]).agg(vol_24h_contracts=("vol_24h", "sum"), median_spread=("spread", "median"),
                                             contracts_listed=("ticker", "nunique")).reset_index().to_csv(
        os.path.join(DERIVED, "kalshi_liquidity_t0.csv"), index=False)

    # Median index level on Stage 2 release eves (SPX approximated as 10 x SPY close)
    spy = pd.read_csv(os.path.join(DATA, "spx_daily.csv"))
    spy["date"] = spy["date"].astype(str)
    ev = pd.read_csv(os.path.join(RESULTS, "stage2_events.csv"))
    eves = [t0[d] for d in ev["release_date"].astype(str)]
    closes = spy.set_index("date").loc[eves, "close"]
    with open(os.path.join(DERIVED, "note_inputs.json"), "w") as fh:
        json.dump({"stage2_releases": len(eves), "median_spy_close_on_release_eves": round(float(closes.median()), 2),
                   "spx_approx_multiplier": 10.0,
                   "note": "SPX approximated as 10 x SPY close on the trading day before each Stage 2 release; "
                           "derived from Massive SPY daily bars."}, fh, indent=1)
    print(f"Wrote derived/ from {os.path.relpath(DATA, HERE)}/ and {os.path.relpath(RESULTS, HERE)}/")


if __name__ == "__main__":
    main()
