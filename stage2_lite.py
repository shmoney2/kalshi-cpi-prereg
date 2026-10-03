"""Stage 2-lite: does Kalshi help decide when to sell CPI-day volatility? No paid options data.

Cboe's 1-Day Volatility Index (VIX1D) is calculated from 4:00 to 4:15 p.m. using only SPX options
that expire the next trading day. Its close on the evening before a CPI release is therefore the
options market's own price for release-day risk. Comparing it with the move that followed measures
the event premium, and lets us test whether Kalshi flags the releases where selling it goes wrong.

  python stage2_lite.py fetch           # VIX1D history -> data/vix1d_daily.csv (Massive, else Cboe)
  python stage2_lite.py run             # the pre-registered test -> results/stage2_*
  python stage2_lite.py synth-vix1d     # test fixture for the synthetic dry run

Every rule is fixed in STAGE2_PREREGISTRATION.md. Pre-May-2022 VIX1D values don't exist; values
before its April 2023 launch were back-calculated by Cboe from actual historical option prices.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import requests
from scipy.stats import norm

# ---- pre-registered settings (mirrored in STAGE2_PREREGISTRATION.md) ----
BURN_IN = 6            # releases before any filter may skip; every strategy trades them
WING_MULT = 2.0        # butterfly wings two implied moves from the centre
COST_FRAC = 0.03       # entry cost as a share of the straddle value (assumption; 0% and 6% also shown)
RISK_PER_EVENT = 0.01  # maximum loss per release = 1% of capital
N_PERM = 10_000
ALPHA = 0.10
SEED = 20261003
# Releases excluded as in Stage 1 (2025 government shutdown). Listed explicitly so Stage 2 drops them
# even if they ever reach the event table.
EXCLUDED_RELEASES = {
    "2025-10-15": "September 2025 CPI: Kalshi markets closed on this original date; BLS published 2025-10-24",
    "2025-10-24": "September 2025 CPI: no Kalshi ladder traded at the snapshot times",
    "2025-11-13": "October 2025 CPI: never published by BLS",
}
CBOE_VIX1D = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX1D_History.csv"


# ---------------------------------------------------------------- maths
def fly_pnl(sigma, r, wing_mult=WING_MULT, cost_frac=COST_FRAC):
    """Short iron butterfly priced from a normal distribution with daily SD sigma (% of index).

    straddle = E|X| = sigma*sqrt(2/pi); each wing = E[(|X|-W)+]/2; payoff = -min(|r|, W).
    Returns P&L, maximum loss and the return on capital when each release risks RISK_PER_EVENT.
    """
    straddle = sigma * math.sqrt(2 / math.pi)
    wing = wing_mult * straddle
    c = wing / sigma
    wings = 2 * (sigma * norm.pdf(c) - wing * (1 - norm.cdf(c)))
    credit = straddle - wings - cost_frac * straddle
    pnl = credit - min(abs(r), wing)
    max_loss = wing - credit
    return {"straddle": straddle, "wing": wing, "credit": credit, "pnl_points": pnl,
            "max_loss": max_loss, "ret": RISK_PER_EVENT * pnl / max_loss}


def top_third_flags(values, burn_in=BURN_IN):
    """True when a value is above the 2/3 quantile of all EARLIER values (expanding window)."""
    flags, hist = [], []
    for v in values:
        ok = v is not None and not (isinstance(v, float) and math.isnan(v))
        flags.append(bool(ok and len(hist) >= burn_in and v > np.quantile(hist, 2 / 3)))
        if ok:
            hist.append(v)
    return np.array(flags)


def drop_excluded(table):
    """Remove the shutdown releases listed in EXCLUDED_RELEASES."""
    mask = table["release_date"].astype(str).str[:10].isin(EXCLUDED_RELEASES)
    return table[~mask], int(mask.sum())


def strategy_metrics(ev, skip):
    kept = ev[~skip]
    rets = np.where(skip, 0.0, ev["ret"].to_numpy())
    eq = np.cumprod(1 + rets)
    dd = 1 - eq / np.maximum.accumulate(eq)
    tr = kept["ret"].to_numpy()
    sharpe = float(tr.mean() / tr.std(ddof=1) * math.sqrt(12)) if len(tr) > 2 and tr.std(ddof=1) > 0 else None
    return {"trades": int((~skip).sum()), "skipped": int(skip.sum()),
            "mean_var_premium": float(kept["var_prem"].mean()),
            "mean_move_ratio": float(kept["move_ratio"].mean()),
            "mean_return_pct": float(100 * tr.mean()), "total_return_pct": float(100 * (eq[-1] - 1)),
            "sharpe_annual": sharpe, "max_drawdown_pct": float(100 * dd.max()),
            "worst_release_pct": float(100 * tr.min()), "blowouts_traded": int((kept["move_ratio"] > 2).sum()),
            "equity": [float(x) for x in eq]}


def permutation_p(ev, skip, n, rng):
    """Share of random skip sets (same size, post-burn-in) whose kept releases earn at least as much."""
    k = int(skip.sum())
    eligible = np.arange(BURN_IN, len(ev))
    vp = ev["var_prem"].to_numpy()
    obs = vp[~skip].mean()
    if k == 0 or k >= len(eligible):
        return None
    hits = 0
    for _ in range(n):
        s = np.zeros(len(ev), bool)
        s[rng.choice(eligible, size=k, replace=False)] = True
        hits += vp[~s].mean() >= obs
    return (1 + hits) / (n + 1)


# ---------------------------------------------------------------- commands
def cmd_fetch(args):
    os.makedirs(args.out, exist_ok=True)
    out, df, src = os.path.join(args.out, "vix1d_daily.csv"), None, None
    try:
        from massive_fetch import Massive, bars_to_daily, load_env
        load_env()
        key = os.environ.get("MASSIVE_API_KEY")
        if key:
            df = bars_to_daily(Massive(key).aggs("I:VIX1D", 1, "day", args.since, date.today().isoformat()))
            df, src = df[["date", "close"]], "Massive I:VIX1D"
    except Exception as e:                                   # noqa: BLE001 - fall back to Cboe
        print(f"Massive VIX1D unavailable ({type(e).__name__}); trying Cboe's free file.")
        df = None
    if df is None or df.empty:
        try:
            raw = pd.read_csv(io.StringIO(requests.get(CBOE_VIX1D, timeout=30).text))
            raw.columns = [c.strip().lower() for c in raw.columns]
            df = pd.DataFrame({"date": pd.to_datetime(raw["date"]).dt.date,
                               "close": pd.to_numeric(raw["close"], errors="coerce")}).dropna()
            src = "Cboe VIX1D_History.csv"
        except Exception:                                    # noqa: BLE001
            raise SystemExit("Could not download VIX1D. Save the history CSV from Cboe's VIX1D page "
                             "as data/vix1d_daily.csv with columns date, close.")
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} days to {out} from {src} ({df['date'].min()} to {df['date'].max()})")


def cmd_synth(args):
    """Fixture: options price CPI days from general volatility (VIX) plus a premium, but cannot see liveness."""
    t = pd.read_csv(args.table).dropna(subset=["r_close", "vix_prev"])
    rel = pd.read_csv(os.path.join(args.data, "releases.csv"))
    rms = math.sqrt((t["r_close"] ** 2).mean())
    t0 = dict(zip(rel["release_date"].astype(str), rel["t0_date"].astype(str)))
    rows = [{"date": t0[str(r.release_date)],
             "close": 1.15 * rms * (r.vix_prev / t["vix_prev"].mean()) * math.sqrt(252)}
            for r in t.itertuples() if str(r.release_date) in t0]
    pd.DataFrame(rows).to_csv(os.path.join(args.data, "vix1d_daily.csv"), index=False)
    print(f"Wrote synthetic VIX1D for {len(rows)} release eves to {args.data}/vix1d_daily.csv")


def cmd_run(args):
    os.makedirs(args.out, exist_ok=True)
    rng = np.random.default_rng(SEED)
    table, n_excluded = drop_excluded(pd.read_csv(args.table))
    vix1d = pd.read_csv(args.vix1d)
    vix1d["date"] = pd.to_datetime(vix1d["date"]).dt.date.astype(str)
    v1 = dict(zip(vix1d["date"], vix1d["close"]))
    rel = pd.read_csv(os.path.join(args.data, "releases.csv"))
    t0 = dict(zip(rel["release_date"].astype(str), rel["t0_date"].astype(str)))
    verdict = None
    if os.path.exists(args.stage1):
        verdict = json.load(open(args.stage1)).get("verdict")
    primary_col = "fed_sd_t0_bp" if verdict == "GO" else "core_sd_t0"
    primary_name = "Fed liveness" if verdict == "GO" else "CPI uncertainty"

    rows = []
    for r in table.sort_values("release_date").itertuples(index=False):
        rd = str(r.release_date)
        vx = v1.get(t0.get(rd))
        if vx is None or pd.isna(vx) or pd.isna(r.r_close):
            continue
        sigma = float(vx) / math.sqrt(252)
        rec = {"release_date": rd, "year": int(rd[:4]), "vix1d_eve": float(vx), "sigma_implied": sigma,
               "r_close": float(r.r_close), "move_ratio": abs(r.r_close) / sigma,
               "var_prem": sigma ** 2 - r.r_close ** 2, "vix_prev": r.vix_prev,
               "core_sd_t0": getattr(r, "core_sd_t0", np.nan), "core_iqr_t0": getattr(r, "core_iqr_t0", np.nan),
               "fed_sd_t0_bp": getattr(r, "fed_sd_t0_bp", np.nan)}
        rec.update(fly_pnl(sigma, r.r_close))
        rows.append(rec)
    ev = pd.DataFrame(rows).reset_index(drop=True)
    if len(ev) < BURN_IN + 6:
        raise SystemExit(f"Only {len(ev)} releases have VIX1D and returns; need at least {BURN_IN + 6}.")

    combo = (ev["core_sd_t0"] * ev["fed_sd_t0_bp"]).tolist()
    skips = {
        "Always sell": np.zeros(len(ev), bool),
        f"Kalshi filter ({primary_name})": top_third_flags(ev[primary_col].tolist()),
        "Kalshi news x sensitivity": top_third_flags(combo),
        # reported only: CPI uncertainty as the interquartile range, less sensitive to ladder width than the SD
        "CPI uncertainty IQR (reported only)": top_third_flags(ev["core_iqr_t0"].tolist()),
        "Fed liveness (reported only)": top_third_flags(ev["fed_sd_t0_bp"].tolist()),
        "Option price only (VIX1D)": top_third_flags(ev["sigma_implied"].tolist()),
        "VIX only": top_third_flags(ev["vix_prev"].tolist()),
    }
    kname = f"Kalshi filter ({primary_name})"
    for name, s in skips.items():
        ev["skip_" + name.split(" (")[0].lower().replace(" ", "_")] = s
    strategies = {name: strategy_metrics(ev, s) for name, s in skips.items()}

    ks = skips[kname]
    post = np.arange(len(ev)) >= BURN_IN
    skipped_mean = float(ev.loc[ks, "var_prem"].mean()) if ks.any() else None
    kept_post_mean = float(ev.loc[~ks & post, "var_prem"].mean())
    p_perm = permutation_p(ev, ks, N_PERM, rng)
    beats_price = strategies[kname]["mean_var_premium"] > strategies["Option price only (VIX1D)"]["mean_var_premium"]
    boot = [ev["var_prem"].sample(len(ev), replace=True, random_state=int(rng.integers(1e9))).mean()
            for _ in range(5000)]
    premium_ci = [float(np.quantile(boot, 0.05)), float(np.quantile(boot, 0.95))]
    checks = [
        {"name": "Releases Kalshi skips are worse for sellers than the ones it keeps",
         "passed": bool(skipped_mean is not None and skipped_mean < kept_post_mean),
         "detail": f"skipped {skipped_mean:.3f} vs kept {kept_post_mean:.3f}" if skipped_mean is not None else "nothing skipped"},
        {"name": f"Better than skipping the same number at random (p < {ALPHA})",
         "passed": bool(p_perm is not None and p_perm < ALPHA), "detail": "n/a" if p_perm is None else f"p = {p_perm:.3f}"},
        {"name": "Better than filtering on the option price alone",
         "passed": bool(beats_price),
         "detail": f"{strategies[kname]['mean_var_premium']:.3f} vs {strategies['Option price only (VIX1D)']['mean_var_premium']:.3f}"},
    ]
    improved = all(c["passed"] for c in checks)
    cost_rows = []
    for cf in (0.0, 0.03, 0.06):
        rets = np.array([fly_pnl(s, r, cost_frac=cf)["ret"] for s, r in zip(ev["sigma_implied"], ev["r_close"])])
        for name in ("Always sell", kname):
            k = skips[name]
            cost_rows.append({"cost": cf, "strategy": name, "mean_return_pct": float(100 * rets[~k].mean())})

    res = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "stage1_verdict": verdict, "primary_input": primary_name, "n": len(ev),
           "excluded_releases": EXCLUDED_RELEASES, "n_excluded_in_table": n_excluded,
           "date_range": [ev["release_date"].iloc[0], ev["release_date"].iloc[-1]],
           "dates": ev["release_date"].tolist(),
           "premium": {"mean_var_premium": float(ev["var_prem"].mean()), "ci90": premium_ci,
                       "mean_move_ratio": float(ev["move_ratio"].mean()),
                       "share_premium_positive": float((ev["var_prem"] > 0).mean())},
           "verdict": "IMPROVED" if improved else "NO EVIDENCE",
           "verdict_text": ("Kalshi improved the decision of when to sell, under every pre-registered check."
                            if improved else "No evidence that Kalshi improved the decision of when to sell."),
           "checks": checks, "p_perm": p_perm, "strategies": strategies, "cost_sensitivity": cost_rows,
           "skipped_by_kalshi": ev.loc[ks, ["release_date", "move_ratio", "var_prem"]].to_dict("records"),
           "settings": {"burn_in": BURN_IN, "wing_mult": WING_MULT, "cost_frac": COST_FRAC,
                        "risk_per_event": RISK_PER_EVENT, "n_perm": N_PERM, "alpha": ALPHA, "seed": SEED}}
    ev.to_csv(os.path.join(args.out, "stage2_events.csv"), index=False)
    with open(os.path.join(args.out, "stage2_results.json"), "w") as fh:
        json.dump(res, fh, indent=1, default=float)

    lines = ["# Stage 2-lite: does Kalshi help decide when to sell CPI-day volatility?", "",
             f"{len(ev)} releases, {res['date_range'][0]} to {res['date_range'][1]}. "
             f"Stage 1 verdict: {verdict or 'not found'}, so the Kalshi input is {primary_name}. "
             f"Shutdown releases excluded: {', '.join(sorted(EXCLUDED_RELEASES))} "
             f"({n_excluded} present in the event table and dropped).", "",
             f"**Event premium:** VIX1D-implied variance minus realized variance averaged {res['premium']['mean_var_premium']:.3f} "
             f"(90% interval {premium_ci[0]:.3f} to {premium_ci[1]:.3f}); realized moves averaged "
             f"{res['premium']['mean_move_ratio']:.2f} implied standard deviations.", "",
             f"**Verdict: {res['verdict_text']}**", "", "| Check | Passed | Detail |", "| --- | --- | --- |"]
    lines += [f"| {c['name']} | {'yes' if c['passed'] else 'no'} | {c['detail']} |" for c in checks]
    lines += ["", "| Strategy | Trades | Mean variance premium | Mean return per trade | Total return | Max drawdown | Worst release |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for name, m in strategies.items():
        lines.append(f"| {name} | {m['trades']} | {m['mean_var_premium']:.3f} | {m['mean_return_pct']:.2f}% | "
                     f"{m['total_return_pct']:.1f}% | {m['max_drawdown_pct']:.1f}% | {m['worst_release_pct']:.2f}% |")
    lines += ["", "Returns are approximate: butterfly prices come from VIX1D with a normal distribution, "
              f"entry costs are assumed at {COST_FRAC:.0%} of the straddle, and each release risks {RISK_PER_EVENT:.0%} of capital."]
    open(os.path.join(args.out, "stage2_summary.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--since", default="2022-05-01"); f.add_argument("--out", default="data")
    s = sub.add_parser("synth-vix1d"); s.add_argument("--data", default="data_synth")
    s.add_argument("--table", default="results_synth/event_table.csv")
    r = sub.add_parser("run")
    r.add_argument("--table", default="results/event_table.csv")
    r.add_argument("--vix1d", default="data/vix1d_daily.csv")
    r.add_argument("--data", default="data")
    r.add_argument("--stage1", default="results/results.json")
    r.add_argument("--out", default="results")
    args = ap.parse_args()
    {"fetch": cmd_fetch, "synth-vix1d": cmd_synth, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
