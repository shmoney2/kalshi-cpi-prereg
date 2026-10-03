"""Reporting additions required by the competition track (see Deviations in both plans, 2026-10-03).

Reported only; nothing here feeds a decision rule.
  1. Out-of-sample split: the most recent 20% of each sample's date span.
     Stage 1: the primary model fitted separately in each period.
     Stage 2: each strategy's in-sample and out-of-sample results at 3% and 6% entry costs, and an
     equity-curve figure with the out-of-sample period shaded.
  2. Post-hoc pricing sensitivity: the butterfly repriced under Student-t distributions (6 and 4
     degrees of freedom) scaled to VIX1D's variance.
  3. A count of every test, variant, strategy and cost level run across both stages.

  python track_report.py --table results/event_table.csv --stage2 results --out results
"""
from __future__ import annotations

import argparse
import json
import math
import os

import numpy as np
import pandas as pd
from scipy.special import gammaln
from scipy.stats import t as student_t

import sensitivity_test as s1
from stage2_lite import RISK_PER_EVENT, WING_MULT, fly_pnl

OOS_SHARE = 0.20
RELEASES_PER_YEAR = 12
COSTS = (0.03, 0.06)
T_DOFS = (6, 4)


def split_cutoff(dates):
    """Releases dated after the cutoff are out of sample: the most recent OOS_SHARE of the date span."""
    d = pd.to_datetime(pd.Series(dates))
    cutoff = d.max() - (d.max() - d.min()) * OOS_SHARE
    return cutoff.date().isoformat()


def skip_column(name):
    return "skip_" + name.split(" (")[0].lower().replace(" ", "_")     # same naming as stage2_lite.py


# ---------------------------------------------------------------- Stage 1
def stage1_split(table):
    spec = s1.PRIMARY
    need = [spec["y"], spec["surprise"], spec["liveness"], spec["control"]]
    sample = table.dropna(subset=need).sort_values("release_date").reset_index(drop=True)
    cutoff = split_cutoff(sample["release_date"])
    out = {"cutoff": cutoff, "periods": {}}
    for label, part in (("in_sample", sample[sample["release_date"] <= cutoff]),
                        ("out_of_sample", sample[sample["release_date"] > cutoff])):
        sub, Y, X, names, S, L, fit, p = s1.fit_spec(part, spec)
        rng = np.random.default_rng(s1.SEED)
        p_perm = s1.permutation_p(sub, Y, X, names, S, L, spec["direction"], s1.N_PERM, rng)
        out["periods"][label] = {"n": int(len(sub)), "first": str(sub["release_date"].iloc[0]),
                                 "last": str(sub["release_date"].iloc[-1]),
                                 "c": float(fit["beta"]["SxL"]), "se_hc3": float(fit["se"]["SxL"]),
                                 "p_hc3": float(p), "p_perm": float(p_perm)}
    return out


# ---------------------------------------------------------------- Stage 2
def trade_record(sigma, r, cost):
    """fly_pnl plus option premium traded (straddle sold + wings bought) as a share of capital."""
    f = fly_pnl(sigma, r, cost_frac=cost)
    wings = f["straddle"] - f["credit"] - cost * f["straddle"]
    f["premium_traded"] = RISK_PER_EVENT * (f["straddle"] + wings) / f["max_loss"]
    return f


def period_metrics(rets, prem, skip):
    r = np.where(skip, 0.0, rets)
    eq = np.cumprod(1 + r)
    dd = 1 - eq / np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    vol = float(r.std(ddof=1) * math.sqrt(RELEASES_PER_YEAR)) if len(r) > 1 else float("nan")
    ann = float(r.mean() * RELEASES_PER_YEAR)
    return {"releases": int(len(r)), "trades": int((~skip).sum()),
            "ann_return_pct": 100 * ann, "ann_vol_pct": 100 * vol,
            "sharpe": ann / vol if vol > 0 else None, "max_drawdown_pct": float(100 * dd.max()),
            "turnover_x_capital": float(np.where(skip, 0.0, prem).mean() * RELEASES_PER_YEAR),
            "total_return_pct": float(100 * (eq[-1] - 1))}


def stage2_split(ev, strategies):
    ev = ev.sort_values("release_date").reset_index(drop=True)
    cutoff = split_cutoff(ev["release_date"])
    oos = (ev["release_date"] > cutoff).to_numpy()
    out = {"cutoff": cutoff, "n_in_sample": int((~oos).sum()), "n_out_of_sample": int(oos.sum()),
           "first_oos": str(ev.loc[oos, "release_date"].iloc[0]), "rows": []}
    for cost in COSTS:
        recs = [trade_record(s, r, cost) for s, r in zip(ev["sigma_implied"], ev["r_close"])]
        rets = np.array([x["ret"] for x in recs])
        prem = np.array([x["premium_traded"] for x in recs])
        for name in strategies:
            skip = ev[skip_column(name)].astype(bool).to_numpy()
            for label, m in (("in_sample", ~oos), ("out_of_sample", oos)):
                out["rows"].append({"cost": cost, "strategy": name, "period": label,
                                    **period_metrics(rets[m], prem[m], skip[m])})
    return out, oos


def equity_figure(ev, strategies, oos, path, cost=0.03):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ev = ev.sort_values("release_date").reset_index(drop=True)
    rets = np.array([trade_record(s, r, cost)["ret"] for s, r in zip(ev["sigma_implied"], ev["r_close"])])
    x = pd.to_datetime(ev["release_date"])
    fig, ax = plt.subplots(figsize=(9, 4.8))
    first = x[oos].iloc[0]
    ax.axvspan(first - pd.Timedelta(days=15), x.iloc[-1] + pd.Timedelta(days=15), color="#999999", alpha=0.18,
               label="Out of sample (last 20% of span)")
    for name in strategies:
        skip = ev[skip_column(name)].astype(bool).to_numpy()
        eq = np.cumprod(1 + np.where(skip, 0.0, rets))
        ax.plot(x, 100 * (eq - 1), lw=2.2 if name.startswith(("Always", "Kalshi filter")) else 1.2,
                ls="-" if "reported only" not in name else "--", label=name)
    ax.axhline(0, color="#555555", lw=0.8)
    ax.set_ylabel(f"Cumulative return, % of capital ({cost:.0%} entry cost)")
    ax.set_title("Stage 2-lite strategies: growth of capital, 1% risked per release")
    ax.legend(fontsize=7.5, loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------- Student-t pricing sensitivity
def t_abs_mean(scale, dof):
    """E|X| for a Student-t with the given scale and degrees of freedom."""
    return scale * 2 * math.sqrt(dof) / (math.sqrt(math.pi) * (dof - 1)) * math.exp(
        gammaln((dof + 1) / 2) - gammaln(dof / 2))


def t_upper_partial(w, scale, dof):
    """E[(X - w)+] for a Student-t with the given scale: one wing's value."""
    z = w / scale
    return scale * (dof + z * z) / (dof - 1) * student_t.pdf(z, dof) - w * student_t.sf(z, dof)


def fly_pnl_t(sigma, r, dof, cost):
    """The pre-registered butterfly, priced under a Student-t with variance sigma^2 instead of a normal."""
    scale = sigma * math.sqrt((dof - 2) / dof)
    straddle = t_abs_mean(scale, dof)
    wing = WING_MULT * straddle
    credit = straddle - 2 * t_upper_partial(wing, scale, dof) - cost * straddle
    pnl = credit - min(abs(r), wing)
    return RISK_PER_EVENT * pnl / (wing - credit)


def t_sensitivity(ev):
    rows = []
    for cost in COSTS:
        for label, f in [("Normal (pre-registered)", lambda s, r: fly_pnl(s, r, cost_frac=cost)["ret"])] + \
                        [(f"Student-t, {d} df", (lambda d: lambda s, r: fly_pnl_t(s, r, d, cost))(d)) for d in T_DOFS]:
            rets = np.array([f(s, r) for s, r in zip(ev["sigma_implied"], ev["r_close"])])
            rows.append({"cost": cost, "pricing": label, "trades": int(len(rets)),
                         "mean_return_pct": float(100 * rets.mean()),
                         "total_return_pct": float(100 * (np.prod(1 + rets) - 1))})
    return rows


# ---------------------------------------------------------------- test count
TEST_COUNT = [
    # stage, category, item, specifications, used for a decision
    ("Stage 1", "Pre-registered", "Primary model H1 (decides GO/NO-GO)", 1, "yes"),
    ("Stage 1", "Pre-registered", "H1 decision conditions: sign, HC3 p, within-year permutation p (10,000), "
                                  "leave-one-out sign share, fit excluding 2022", 5, "yes"),
    ("Stage 1", "Pre-registered", "90% wild-bootstrap interval for c (9,999 draws)", 1, "no"),
    ("Stage 1", "Pre-registered", "Robustness variants (headline, close-to-close, sign-free H3, 1 - modal, "
                                  "entropy, no VIX, surprise at t0, VIX-scaled return)", 8, "no"),
    ("Stage 1", "Pre-registered", "Mechanism H2 (Kalshi expected rate response)", 1, "no"),
    ("Stage 1", "Pre-registered", "Placebo (ordinary-day volatility on liveness)", 1, "no"),
    ("Stage 1", "Pre-registered", "Consensus gap H4 (not run: no consensus data)", 0, "no"),
    ("Stage 1", "Data diagnostic", "Liveness from 7-day vs fixed quote lookback (correlation, size of changes)", 1, "no"),
    ("Stage 1", "Data diagnostic", "Ladder width vs liveness SD (correlation with strike span, tick-quoted strikes)", 1, "no"),
    ("Stage 2", "Pre-registered", "Strategies: always sell, Kalshi filter (primary), news x sensitivity, "
                                  "CPI uncertainty IQR, Fed liveness, option price only, VIX only", 7, "primary only"),
    ("Stage 2", "Pre-registered", "Decision checks (skipped worse than kept; random-skip permutation, 10,000; "
                                  "beats option-price filter)", 3, "yes"),
    ("Stage 2", "Pre-registered", "90% bootstrap interval for the mean variance premium (5,000 draws)", 1, "no"),
    ("Stage 2", "Pre-registered", "Entry-cost levels (0%, 3%, 6%) for always sell and the Kalshi filter", 3, "no"),
    ("Post hoc", "Track rule", "Stage 1 primary model, in-sample and out-of-sample fits (each with permutation p)", 2, "no"),
    ("Post hoc", "Track rule", "Stage 2 strategy x period x cost cells (7 x 2 x 2), six metrics each", 28, "no"),
    ("Post hoc", "Sensitivity", "Butterfly pricing under Student-t (6 and 4 df) at 3% and 6% costs, always sell", 4, "no"),
]


def test_count_table():
    rows = [{"stage": a, "category": b, "item": c, "specifications": d, "decision": e} for a, b, c, d, e in TEST_COUNT]
    return rows, int(sum(r["specifications"] for r in rows))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", default="results/event_table.csv")
    ap.add_argument("--stage2", default="results", help="folder with stage2_events.csv and stage2_results.json")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    table = pd.read_csv(args.table)
    ev = pd.read_csv(os.path.join(args.stage2, "stage2_events.csv"))
    strategies = list(json.load(open(os.path.join(args.stage2, "stage2_results.json")))["strategies"])

    st1 = stage1_split(table)
    st2, oos = stage2_split(ev, strategies)
    equity_figure(ev, strategies, oos, os.path.join(args.out, "stage2_equity_oos.png"))
    tsens = t_sensitivity(ev.sort_values("release_date"))
    counts, total = test_count_table()
    res = {"stage1_split": st1, "stage2_split": st2, "t_sensitivity": tsens,
           "test_count": counts, "test_count_total": total,
           "settings": {"oos_share": OOS_SHARE, "releases_per_year": RELEASES_PER_YEAR, "costs": COSTS, "t_dofs": T_DOFS}}
    with open(os.path.join(args.out, "track_results.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=float)

    L = ["# Track reporting additions (reported only; see Deviations, 2026-10-03)", "",
         "## Out-of-sample split: the most recent 20% of each sample's date span", "",
         "Defined after the full-sample results were seen; it follows the track's mechanical rule.", "",
         f"**Stage 1:** cutoff {st1['cutoff']}. "
         f"In sample {st1['periods']['in_sample']['n']} releases ({st1['periods']['in_sample']['first']} to "
         f"{st1['periods']['in_sample']['last']}), out of sample {st1['periods']['out_of_sample']['n']} "
         f"({st1['periods']['out_of_sample']['first']} to {st1['periods']['out_of_sample']['last']}). "
         "About 10 releases cannot support inference; the out-of-sample fit is descriptive.", "",
         "| Period | n | c (per 1 SD liveness) | HC3 SE | one-sided p, HC3 | one-sided p, permutation |",
         "| --- | --- | --- | --- | --- | --- |"]
    for k, v in st1["periods"].items():
        L.append(f"| {k.replace('_', ' ')} | {v['n']} | {v['c']:.3f} | {v['se_hc3']:.3f} | {v['p_hc3']:.3f} | {v['p_perm']:.3f} |")
    L += ["", f"**Stage 2:** cutoff {st2['cutoff']}. In sample {st2['n_in_sample']} releases, out of sample "
              f"{st2['n_out_of_sample']} (from {st2['first_oos']}). Annualized at {RELEASES_PER_YEAR} releases a year; "
              "returns count skipped releases as zero; turnover is option premium traded per year as a multiple of capital.", ""]
    for cost in COSTS:
        L += [f"Entry cost {cost:.0%}:", "",
              "| Strategy | Period | Trades | Ann. return | Ann. vol | Sharpe | Max drawdown | Turnover (x capital) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for r in [r for r in st2["rows"] if r["cost"] == cost]:
            sh = "n/a" if r["sharpe"] is None else f"{r['sharpe']:.2f}"
            L.append(f"| {r['strategy']} | {r['period'].replace('_', ' ')} | {r['trades']} | {r['ann_return_pct']:.2f}% | "
                     f"{r['ann_vol_pct']:.2f}% | {sh} | {r['max_drawdown_pct']:.2f}% | {r['turnover_x_capital']:.2f} |")
        L.append("")
    L += ["Figure: stage2_equity_oos.png (3% cost, out-of-sample period shaded).", "",
          "## Post-hoc pricing sensitivity: always sell, butterfly priced under fatter tails", "",
          "Student-t scaled so its variance equals VIX1D's; wings stay two implied moves from the centre.", "",
          "| Cost | Pricing | Trades | Mean return per trade | Total return |", "| --- | --- | --- | --- | --- |"]
    L += [f"| {r['cost']:.0%} | {r['pricing']} | {r['trades']} | {r['mean_return_pct']:.3f}% | {r['total_return_pct']:.2f}% |"
          for r in tsens]
    L += ["", "## Every test, variant, strategy and cost level run", "",
          "| Stage | Category | Item | Specifications | Used for a decision |", "| --- | --- | --- | --- | --- |"]
    L += [f"| {r['stage']} | {r['category']} | {r['item']} | {r['specifications']} | {r['decision']} |" for r in counts]
    L += [f"| **Total** | | | **{total}** | |", "",
          "Resampling draws (permutations, bootstraps) are counted once per test, not per draw. "
          "Synthetic dry runs are excluded because they use no real data."]
    open(os.path.join(args.out, "track_summary.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
