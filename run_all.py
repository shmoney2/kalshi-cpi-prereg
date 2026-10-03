"""Reproduce every headline number from the committed per-release files in derived/. No API key needed.

  python run_all.py                              # recompute into reproduced/ and check against derived/headline_numbers.json
  python run_all.py --write-expected results     # maintainers: record headline numbers from a full-pipeline results folder

Steps: Stage 1 pre-registered test (sensitivity_test.py) -> Stage 2-lite test (stage2_lite.py) -> track
reporting additions (track_report.py). Raw data are not needed; see DATA.md for the full download.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DERIVED = os.path.join(HERE, "derived")
OUT = os.path.join(HERE, "reproduced")
EXPECTED = os.path.join(DERIVED, "headline_numbers.json")


def run(script, *args):
    cmd = [sys.executable, os.path.join(HERE, script), *args]
    print(f"\n$ python {script} {' '.join(os.path.relpath(a, HERE) if os.path.isabs(a) else a for a in args)}", flush=True)
    done = subprocess.run(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if done.returncode != 0:
        print(done.stdout)
        raise SystemExit(f"{script} failed with exit code {done.returncode}")
    return done.stdout


def headline(folder):
    """The numbers quoted in the write-up, read from a results folder."""
    s1 = json.load(open(os.path.join(folder, "results.json")))
    s2 = json.load(open(os.path.join(folder, "stage2_results.json")))
    tr = json.load(open(os.path.join(folder, "track_results.json")))
    p = s1["primary"]
    h = {
        "stage1.n": s1["n"], "stage1.verdict": s1["verdict"], "stage1.c": p["c"], "stage1.se_c": p["se_c"],
        "stage1.p_hc3": p["p_hc3"], "stage1.p_perm": p["p_perm"], "stage1.ci90_low": p["ci90"][0],
        "stage1.ci90_high": p["ci90"][1], "stage1.loo_share": p["loo_share"], "stage1.c_ex2022": p["c_ex2022"],
        "stage1.sens_settled": p["sens_settled"], "stage1.sens_live": p["sens_live"],
        "stage1.h2_c": s1["mechanism"].get("c"), "stage1.h2_p": s1["mechanism"].get("p"),
        "stage2.n": s2["n"], "stage2.verdict": s2["verdict"], "stage2.primary_input": s2["primary_input"],
        "stage2.mean_var_premium": s2["premium"]["mean_var_premium"], "stage2.p_perm": s2["p_perm"],
        "stage2.premium_ci90_low": s2["premium"]["ci90"][0], "stage2.premium_ci90_high": s2["premium"]["ci90"][1],
    }
    for name, m in s2["strategies"].items():
        h[f"stage2.total_return_pct[{name}]"] = m["total_return_pct"]
    st1 = tr["stage1_split"]
    h["track.stage1_cutoff"] = st1["cutoff"]
    for k, v in st1["periods"].items():
        h[f"track.stage1.{k}.n"], h[f"track.stage1.{k}.c"], h[f"track.stage1.{k}.p_hc3"] = v["n"], v["c"], v["p_hc3"]
    st2 = tr["stage2_split"]
    h["track.stage2_cutoff"], h["track.stage2_n_oos"] = st2["cutoff"], st2["n_out_of_sample"]
    for r in st2["rows"]:
        key = f"track.stage2[{r['strategy']}|{r['period']}|{r['cost']:.0%}]"
        h[key + ".ann_return_pct"], h[key + ".sharpe"] = r["ann_return_pct"], r["sharpe"]
    for r in tr["t_sensitivity"]:
        h[f"track.t[{r['pricing']}|{r['cost']:.0%}].total_return_pct"] = r["total_return_pct"]
    h["track.test_count_total"] = tr["test_count_total"]
    rk = tr["risk"]
    for r in rk["factors"]:
        h[f"risk.beta[{r['factor']}]"], h[f"risk.t[{r['factor']}]"] = r["beta"], r["t"]
    h["risk.simple_beta"] = rk["simple_beta"]
    for r in rk["regimes"]:
        h[f"risk.regime[{r['regime']}].total_return_pct"] = r["total_return_pct"]
    h["risk.max_loss_count"] = rk["scenarios"]["max_loss_count"]
    return h


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return a is None and b is None
        return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-9)
    return a == b


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write-expected", metavar="RESULTS_FOLDER")
    args = ap.parse_args()
    if args.write_expected:
        h = headline(args.write_expected)
        with open(EXPECTED, "w") as fh:
            json.dump(h, fh, indent=1, sort_keys=True)
        print(f"Wrote {len(h)} headline numbers to {os.path.relpath(EXPECTED, HERE)}")
        return

    os.makedirs(OUT, exist_ok=True)
    table = os.path.join(DERIVED, "event_table.csv")
    run("sensitivity_test.py", "--table", table, "--out", OUT)
    run("stage2_lite.py", "run", "--table", table, "--vix1d", os.path.join(DERIVED, "vix1d_release_eves.csv"),
        "--data", DERIVED, "--stage1", os.path.join(OUT, "results.json"), "--out", OUT)
    run("track_report.py", "--table", table, "--stage2", OUT, "--out", OUT)

    got, want = headline(OUT), json.load(open(EXPECTED))
    bad = [k for k in sorted(set(got) | set(want)) if not same(got.get(k), want.get(k))]
    print(f"\nStage 1: {got['stage1.verdict']} (n = {got['stage1.n']}, c = {got['stage1.c']:.3f}, "
          f"HC3 p = {got['stage1.p_hc3']:.3f}, permutation p = {got['stage1.p_perm']:.3f})")
    print(f"Stage 2: {got['stage2.verdict']} (n = {got['stage2.n']}, input = {got['stage2.primary_input']}, "
          f"random-skip p = {got['stage2.p_perm']:.3f})")
    print(f"Track additions: Stage 1 cutoff {got['track.stage1_cutoff']}, Stage 2 cutoff {got['track.stage2_cutoff']}, "
          f"{got['track.test_count_total']} specifications counted")
    print(f"Outputs in {os.path.relpath(OUT, HERE)}/ (summary.md, stage2_summary.md, track_summary.md, figures)")
    if bad:
        for k in bad:
            print(f"  MISMATCH {k}: reproduced {got.get(k)!r}, expected {want.get(k)!r}")
        raise SystemExit(f"{len(bad)} of {len(want)} headline numbers did not reproduce")
    print(f"All {len(want)} headline numbers reproduced.")


if __name__ == "__main__":
    main()
