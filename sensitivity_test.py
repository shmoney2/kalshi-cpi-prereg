"""Pre-registered test: does Kalshi's Fed-meeting "liveness" predict how strongly the
S&P 500 reacts to CPI surprises?

Primary model (see PREREGISTRATION.md):
    r_open = a + b*S + c*(S x L) + d*L + e*VIX + error
    S = core CPI m/m print minus Kalshi's mean expectation at 08:25 ET (percentage points)
    L = standard deviation of Kalshi's distribution for the next FOMC upper bound at t0 (bp), standardized
    H1: c < 0  (a hot print hurts stocks more when the next meeting is live)

Input:  results/event_table.csv (from build_dataset.py)
Output: results/summary.md, results/sensitivity_by_liveness.png, results/leave_one_out.csv
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from common import coef_fast, ols_hc3, one_sided_p, zscore

# ---- pre-registered settings: change only before looking at real results ----
PRIMARY = {"y": "r_open", "surprise": "surprise_core", "liveness": "fed_sd_t0_bp",
           "control": "vix_prev", "direction": "neg"}
ALPHA = 0.10            # one-sided screening threshold for the go/no-go decision
N_PERM = 10_000         # within-year permutations of liveness
N_BOOT = 9_999          # wild bootstrap draws
LOO_SIGN_SHARE = 0.90   # sign must survive dropping any single release in >= 90% of cases
MIN_N = 25              # below this, no verdict
SEED = 20261002


def design(df, y, surprise, liveness, control=None, absval=False, ytransform=None):
    S = df[surprise].to_numpy(float)
    Y = df[y].to_numpy(float)
    if ytransform is not None:
        Y = ytransform(df, Y)
    if absval:
        S, Y = np.abs(S), np.abs(Y)
    L = zscore(df[liveness])
    cols, names = [np.ones(len(df)), S, S * L, L], ["const", "S", "SxL", "L"]
    if control:
        cols.append(zscore(df[control])); names.append(control)
    return Y, np.column_stack(cols), names, S, L


def fit_spec(df, spec):
    need = [spec["y"], spec["surprise"], spec["liveness"]] + ([spec["control"]] if spec.get("control") else [])
    sub = df.dropna(subset=need)
    if spec.get("exclude_fomc_same_day"):
        sub = sub[~sub["fomc_same_day"].astype(bool)]
    sub = sub.reset_index(drop=True)
    Y, X, names, S, L = design(sub, spec["y"], spec["surprise"], spec["liveness"], spec.get("control"),
                               spec.get("absval", False), spec.get("ytransform"))
    fit = ols_hc3(Y, X, names)
    p = one_sided_p(fit["t"]["SxL"], fit["df"], spec["direction"])
    return sub, Y, X, names, S, L, fit, p


def permutation_p(sub, Y, X, names, S, L, direction, n, rng):
    j, li = names.index("SxL"), names.index("L")
    c_obs = coef_fast(Y, X, j)
    groups = [np.where(sub["year"].to_numpy() == yr)[0] for yr in np.unique(sub["year"])]
    Xp, hits = X.copy(), 0
    for _ in range(n):
        Lp = L.copy()
        for g in groups:
            Lp[g] = rng.permutation(L[g])
        Xp[:, j], Xp[:, li] = S * Lp, Lp
        c = coef_fast(Y, Xp, j)
        hits += c <= c_obs if direction == "neg" else c >= c_obs
    return (1 + hits) / (n + 1)


def wild_bootstrap_ci(Y, X, j, n, rng, level=0.90):
    beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    fitted, resid = X @ beta, Y - X @ beta
    draws = [coef_fast(fitted + resid * rng.choice([-1.0, 1.0], size=len(Y)), X, j) for _ in range(n)]
    return tuple(np.quantile(draws, [(1 - level) / 2, 1 - (1 - level) / 2]))


def leave_one_out(sub, Y, X, j):
    c_all = coef_fast(Y, X, j)
    loo = np.array([coef_fast(np.delete(Y, i), np.delete(X, i, axis=0), j) for i in range(len(Y))])
    out = pd.DataFrame({"release_date": sub["release_date"], "c_without": loo,
                        "shift": c_all - loo}).sort_values("shift", key=np.abs, ascending=False)
    return out, float(np.mean(np.sign(loo) == np.sign(c_all)))


def fmt(x, d=3):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


def make_figure(sub, spec, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    S, Y, L = sub[spec["surprise"]].to_numpy(), sub[spec["y"]].to_numpy(), sub[spec["liveness"]].to_numpy()
    hi = L >= np.median(L)
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for mask, color, label in ((~hi, "#7a8ca5", "Next meeting settled (lower half)"),
                               (hi, "#c0392b", "Next meeting live (upper half)")):
        ax.scatter(S[mask], Y[mask], s=28, color=color, alpha=0.8, label=label)
        if mask.sum() >= 3 and np.ptp(S[mask]) > 0:
            b1, b0 = np.polyfit(S[mask], Y[mask], 1)
            xs = np.linspace(S.min(), S.max(), 50)
            ax.plot(xs, b0 + b1 * xs, color=color, lw=2)
    ax.axhline(0, color="#999", lw=0.8); ax.axvline(0, color="#999", lw=0.8)
    ax.set_xlabel("Core CPI surprise vs Kalshi mean (pp)")
    ax.set_ylabel("S&P 500, prior close to open (%)")
    ax.set_title("SPX reaction to CPI surprises, by Fed-meeting liveness")
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", default="results/event_table.csv")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rng = np.random.default_rng(SEED)
    df = pd.read_csv(args.table)
    lines = ["# Fed-liveness sensitivity test", ""]
    res = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "settings": {"alpha": ALPHA, "n_perm": N_PERM, "n_boot": N_BOOT,
                        "loo_sign_share": LOO_SIGN_SHARE, "min_n": MIN_N, "seed": SEED}}

    # ---------------- primary
    sub, Y, X, names, S, L, fit, p_hc3 = fit_spec(df, PRIMARY)
    n = len(sub)
    lines += [f"Sample: {n} CPI releases with complete data "
              f"({sub['release_date'].min()} to {sub['release_date'].max()}).", ""]
    if n < MIN_N:
        lines += [f"**Verdict: INSUFFICIENT DATA** (need at least {MIN_N}).", ""]
        res.update(n=n, verdict="INSUFFICIENT", verdict_text=f"Fewer than {MIN_N} usable releases.")
        open(os.path.join(args.out, "summary.md"), "w").write("\n".join(lines))
        json.dump(res, open(os.path.join(args.out, "results.json"), "w"), indent=1)
        print("\n".join(lines)); return

    j = names.index("SxL")
    b, c = fit["beta"]["S"], fit["beta"]["SxL"]
    p_perm = permutation_p(sub, Y, X, names, S, L, PRIMARY["direction"], N_PERM, rng)
    ci_lo, ci_hi = wild_bootstrap_ci(Y, X, j, N_BOOT, rng)
    loo, loo_share = leave_one_out(sub, Y, X, j)
    loo.to_csv(os.path.join(args.out, "leave_one_out.csv"), index=False)
    ex22 = df[df["year"] != 2022]
    c_ex22 = (fit_spec(ex22, PRIMARY)[6]["beta"]["SxL"]
              if len(ex22.dropna(subset=["r_open", "surprise_core", "fed_sd_t0_bp"])) >= 10 else np.nan)

    lo_sens, mid_sens, hi_sens = (b - c) * 0.1, b * 0.1, (b + c) * 0.1
    lines += ["## Primary result (H1)", "",
              "| Quantity | Value |", "| --- | --- |",
              f"| SPX move per +0.1pp core surprise, meeting settled (-1 SD liveness) | {fmt(lo_sens, 2)}% |",
              f"| SPX move per +0.1pp core surprise, average liveness | {fmt(mid_sens, 2)}% |",
              f"| SPX move per +0.1pp core surprise, meeting live (+1 SD liveness) | {fmt(hi_sens, 2)}% |",
              f"| Interaction c (per 1 SD of liveness, % per pp) | {fmt(c)} (HC3 SE {fmt(fit['se']['SxL'])}) |",
              f"| One-sided p, HC3 | {fmt(p_hc3)} |",
              f"| One-sided p, within-year permutation of liveness ({N_PERM:,} draws) | {fmt(p_perm)} |",
              f"| 90% wild-bootstrap interval for c | [{fmt(ci_lo)}, {fmt(ci_hi)}] |",
              f"| Share of leave-one-out fits with the same sign | {fmt(loo_share, 2)} |",
              f"| c excluding 2022 | {fmt(c_ex22)} |",
              f"| R-squared | {fmt(fit['r2'], 2)} |", ""]

    right_sign = c < 0
    go = (right_sign and p_hc3 < ALPHA and p_perm < ALPHA and loo_share >= LOO_SIGN_SHARE
          and not np.isnan(c_ex22) and c_ex22 < 0)
    if go:
        verdict = "GO: liveness predicts CPI sensitivity under every pre-registered condition."
    elif right_sign:
        verdict = "NO-GO: the sign is right, but at least one pre-registered condition failed."
    else:
        verdict = "NO-GO: the interaction has the wrong sign."
    lines += [f"**Verdict: {verdict}**", ""]
    res.update(
        n=n, date_range=[str(sub["release_date"].min()), str(sub["release_date"].max())],
        sample_dates=[str(d) for d in sub["release_date"]],
        liveness_median=float(np.median(sub[PRIMARY["liveness"]])),
        verdict="GO" if go else "NO-GO", verdict_text=verdict,
        primary={"b": b, "c": c, "se_c": fit["se"]["SxL"], "p_hc3": p_hc3, "p_perm": p_perm,
                 "ci90": [ci_lo, ci_hi], "loo_share": loo_share,
                 "c_ex2022": None if np.isnan(c_ex22) else c_ex22, "r2": fit["r2"],
                 "sens_settled": lo_sens, "sens_average": mid_sens, "sens_live": hi_sens},
        checks=[
            {"name": "Hot prints hurt more when the meeting is live (c < 0)", "passed": bool(right_sign),
             "detail": f"c = {c:.3f}"},
            {"name": f"HC3 one-sided p below {ALPHA}", "passed": bool(p_hc3 < ALPHA), "detail": f"p = {p_hc3:.3f}"},
            {"name": f"Permutation one-sided p below {ALPHA}", "passed": bool(p_perm < ALPHA),
             "detail": f"p = {p_perm:.3f}"},
            {"name": f"Same sign after dropping any one release (at least {LOO_SIGN_SHARE:.0%})",
             "passed": bool(loo_share >= LOO_SIGN_SHARE), "detail": f"{loo_share:.0%} of fits"},
            {"name": "Same sign without 2022", "passed": bool(not np.isnan(c_ex22) and c_ex22 < 0),
             "detail": "c = n/a" if np.isnan(c_ex22) else f"c = {c_ex22:.3f}"},
        ],
        loo=[{"release_date": str(r.release_date), "c_without": float(r.c_without), "shift": float(r.shift)}
             for r in loo.itertuples(index=False)],
        open_source_counts=(sub["r_open_source"].value_counts().to_dict() if "r_open_source" in sub else {}),
        robustness=[], mechanism=None, placebo=None, consensus=None)

    # ---------------- robustness (reported, not used for the decision)
    def std_return(d, y):
        return y / (d["vix_prev"].to_numpy(float) / np.sqrt(252))

    robust = [
        ("Headline instead of core surprise", {**PRIMARY, "surprise": "surprise_headline"}),
        ("Close-to-close return (FOMC-day releases dropped)", {**PRIMARY, "y": "r_close", "exclude_fomc_same_day": True}),
        ("Sign-free: |return| on |surprise| (expects c > 0)", {**PRIMARY, "absval": True, "direction": "pos"}),
        ("Liveness = 1 - modal probability", {**PRIMARY, "liveness": "fed_notmode_t0"}),
        ("Liveness = entropy", {**PRIMARY, "liveness": "fed_entropy_t0"}),
        ("No VIX control", {**PRIMARY, "control": None}),
        ("Surprise measured at t0 instead of 08:25", {**PRIMARY, "surprise": "surprise_core_t0"}),
        ("Return scaled by VIX-implied daily move", {**PRIMARY, "control": None, "ytransform": std_return}),
    ]
    lines += ["## Robustness (reported, not used for the decision)", "",
              "| Variant | n | c | HC3 SE | one-sided p |", "| --- | --- | --- | --- | --- |"]
    for label, spec in robust:
        try:
            if spec["liveness"] not in df or spec["surprise"] not in df:
                raise KeyError
            s2, *_, f2, p2 = fit_spec(df, spec)
            lines.append(f"| {label} | {len(s2)} | {fmt(f2['beta']['SxL'])} | {fmt(f2['se']['SxL'])} | {fmt(p2)} |")
            res["robustness"].append({"label": label, "n": len(s2), "c": f2["beta"]["SxL"],
                                      "se": f2["se"]["SxL"], "p": p2, "direction": spec["direction"]})
        except (KeyError, ValueError, np.linalg.LinAlgError):
            lines.append(f"| {label} | - | not available | | |")
            res["robustness"].append({"label": label, "n": 0, "c": None, "se": None, "p": None,
                                      "direction": spec["direction"]})
    lines.append("")

    # ---------------- mechanism (H2): do CPI surprises move Kalshi's Fed odds more when the meeting is live?
    mech = {"y": "d_fed_mean_bp", "surprise": "surprise_core", "liveness": "fed_sd_t0_bp",
            "control": None, "direction": "pos"}
    lines += ["## Mechanism (H2)", ""]
    try:
        s3, *_, f3, p3 = fit_spec(df, mech)
        lines += [f"Change in Kalshi's expected fed funds rate (08:25 to 10:00 ET, bp) on surprise x liveness, "
                  f"n = {len(s3)}: c = {fmt(f3['beta']['SxL'])} (HC3 SE {fmt(f3['se']['SxL'])}), "
                  f"one-sided p = {fmt(p3)}. Average response: {fmt(f3['beta']['S'] * 0.1, 2)} bp per +0.1pp surprise.", ""]
        res["mechanism"] = {"n": len(s3), "c": f3["beta"]["SxL"], "se": f3["se"]["SxL"], "p": p3,
                            "bp_per_tenth": f3["beta"]["S"] * 0.1}
    except (KeyError, ValueError, np.linalg.LinAlgError):
        lines += ["Not available (post-release Fed snapshots missing).", ""]

    # ---------------- placebo: does liveness just proxy general volatility?
    lines += ["## Placebo: liveness and ordinary-day volatility", ""]
    pl = df.dropna(subset=["abs_pre5", "fed_sd_t0_bp", "vix_prev"]).reset_index(drop=True)
    if len(pl) >= 10:
        Xp = np.column_stack([np.ones(len(pl)), zscore(pl["fed_sd_t0_bp"]), zscore(pl["vix_prev"])])
        f4 = ols_hc3(pl["abs_pre5"].to_numpy(float), Xp, ["const", "L", "vix"])
        lines += [f"Mean absolute SPX move over the 5 trading days before t0, on liveness and VIX (n = {len(pl)}): "
                  f"liveness coefficient {fmt(f4['beta']['L'])} (HC3 SE {fmt(f4['se']['L'])}). "
                  "A large positive value means liveness partly tracks general volatility, so read H1 with care.", ""]
        res["placebo"] = {"n": len(pl), "coef": f4["beta"]["L"], "se": f4["se"]["L"]}

    # ---------------- consensus gap (H4), if consensus data were supplied
    if "gap_core" in df and df["gap_core"].notna().sum() >= 10:
        cg = df.dropna(subset=["gap_core", "cons_surprise_core"]).reset_index(drop=True)
        f5 = ols_hc3(np.abs(cg["cons_surprise_core"].to_numpy(float)),
                     np.column_stack([np.ones(len(cg)), cg["gap_core"].to_numpy(float)]), ["const", "gap"])
        p5 = one_sided_p(f5["t"]["gap"], f5["df"], "pos")
        lines += ["## Consensus gap (H4)", "",
                  f"|Actual - consensus| on |Kalshi median - consensus| (n = {len(cg)}): "
                  f"slope {fmt(f5['beta']['gap'])} (HC3 SE {fmt(f5['se']['gap'])}), one-sided p = {fmt(p5)}.", ""]
        res["consensus"] = {"n": len(cg), "slope": f5["beta"]["gap"], "se": f5["se"]["gap"], "p": p5}

    lines += ["## Most influential releases", "",
              "| Release | c without it | shift |", "| --- | --- | --- |"]
    for r in loo.head(5).itertuples(index=False):
        lines.append(f"| {r.release_date} | {fmt(r.c_without)} | {fmt(r.shift)} |")
    lines += ["", "Figure: sensitivity_by_liveness.png"]

    make_figure(sub, PRIMARY, os.path.join(args.out, "sensitivity_by_liveness.png"))
    with open(os.path.join(args.out, "summary.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(args.out, "results.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
