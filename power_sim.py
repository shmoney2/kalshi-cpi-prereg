"""How often does the pre-registered decision rule say GO, with and without a real effect?

Applies the full rule from sensitivity_test.py (HC3 p, within-year permutation p,
leave-one-out sign stability, sign excluding 2022) to simulated event tables.

  python power_sim.py                                         # assumed parameters
  python power_sim.py --calibrate results/event_table.csv     # keep your real surprises, liveness,
                                                              # VIX and years; simulate only returns

Effect size is the ratio of SPX sensitivity at +1 SD liveness to sensitivity at -1 SD.
A ratio of 1.0 means no effect, so its GO rate is the false-positive rate.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from common import coef_fast, ols_hc3, one_sided_p, zscore
from sensitivity_test import ALPHA, LOO_SIGN_SHARE, PRIMARY, design, leave_one_out, permutation_p


def synthetic_design(n, rng):
    months = pd.date_range("2022-01-01", periods=n, freq="MS")
    years = months.year.to_numpy()
    live = rng.lognormal(0, 0.6, n) * np.where(years == 2022, 1.8, 1.0)
    vix = np.where(years == 2022, 26, 17) + rng.normal(0, 3, n)
    return pd.DataFrame({"release_date": months.strftime("%Y-%m-%d"), "year": years,
                         "fed_sd_t0_bp": live, "vix_prev": vix})


def decide(df, n_perm, rng):
    Y, X, names, S, L = design(df, PRIMARY["y"], PRIMARY["surprise"], PRIMARY["liveness"], PRIMARY["control"])
    fit = ols_hc3(Y, X, names)
    c = fit["beta"]["SxL"]
    if c >= 0:
        return False
    if one_sided_p(fit["t"]["SxL"], fit["df"], "neg") >= ALPHA:
        return False
    if permutation_p(df, Y, X, names, S, L, "neg", n_perm, rng) >= ALPHA:
        return False
    _, share = leave_one_out(df, Y, X, names.index("SxL"))
    if share < LOO_SIGN_SHARE:
        return False
    ex = df[df["year"] != 2022].reset_index(drop=True)
    Ye, Xe, ne, *_ = design(ex, PRIMARY["y"], PRIMARY["surprise"], PRIMARY["liveness"], PRIMARY["control"])
    return coef_fast(Ye, Xe, ne.index("SxL")) < 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=50, help="number of releases (ignored with --calibrate)")
    ap.add_argument("--sd-surprise", type=float, default=0.09, help="SD of core surprise (pp)")
    ap.add_argument("--beta", type=float, default=-8.0, help="SPX %% per 1pp surprise at average liveness")
    ap.add_argument("--noise", type=float, default=0.5, help="SD of the non-CPI part of the move (%%)")
    ap.add_argument("--hetero", type=float, default=0.3, help="noise SD multiplier per 1 SD of VIX (log scale)")
    ap.add_argument("--ratios", type=float, nargs="+", default=[1.0, 1.5, 2.0, 3.0])
    ap.add_argument("--reps", type=int, default=400)
    ap.add_argument("--n-perm", type=int, default=999)
    ap.add_argument("--calibrate", help="event_table.csv to take the real design and noise level from")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    fixed = None
    if args.calibrate:
        t = pd.read_csv(args.calibrate).dropna(
            subset=["surprise_core", "fed_sd_t0_bp", "r_open", "vix_prev"]).reset_index(drop=True)
        X0 = np.column_stack([np.ones(len(t)), t["surprise_core"], zscore(t["fed_sd_t0_bp"]), zscore(t["vix_prev"])])
        f0 = ols_hc3(t["r_open"].to_numpy(float), X0, ["const", "S", "L", "vix"])
        args.beta, args.noise = f0["beta"]["S"], float(np.std(f0["resid"], ddof=4))
        fixed = t[["release_date", "year", "surprise_core", "fed_sd_t0_bp", "vix_prev"]].copy()
        print(f"Calibrated from {args.calibrate}: n = {len(t)}, beta = {args.beta:.2f} %/pp, "
              f"residual SD = {args.noise:.2f}%, surprise SD = {t['surprise_core'].std():.3f}pp")

    print(f"Decision rule: one-sided alpha {ALPHA}, permutation draws {args.n_perm}, {args.reps} datasets per ratio")
    print("ratio  P(GO)")
    for ratio in args.ratios:
        g = np.log(ratio) / 2
        go = 0
        for _ in range(args.reps):
            if fixed is not None:
                d = fixed.copy()
            else:
                d = synthetic_design(args.n, rng)
                d["surprise_core"] = rng.normal(0, args.sd_surprise, len(d))
            lz, vz = zscore(d["fed_sd_t0_bp"]), zscore(d["vix_prev"])
            sens = args.beta * np.exp(g * lz)
            d["r_open"] = sens * d["surprise_core"] + rng.normal(0, 1, len(d)) * args.noise * np.exp(args.hetero * vz)
            go += decide(d, args.n_perm, rng)
        label = "  <- false-positive rate" if ratio == 1.0 else ""
        print(f"{ratio:>5.2f}  {go / args.reps:.3f}{label}")


if __name__ == "__main__":
    main()
