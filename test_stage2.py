"""Offline checks for Stage 2-lite. Run: python test_stage2.py"""
import numpy as np
import pandas as pd

from stage2_lite import drop_excluded, fly_pnl, permutation_p, top_third_flags


def test_shutdown_releases_excluded():
    t = pd.DataFrame({"release_date": ["2025-09-11", "2025-10-15", "2025-10-24", "2025-11-13", "2025-12-18"]})
    kept, n = drop_excluded(t)
    assert kept["release_date"].tolist() == ["2025-09-11", "2025-12-18"] and n == 3


def test_fly_pricing():
    rng = np.random.default_rng(1)
    sigma = 1.2
    x = rng.normal(0, sigma, 1_000_000)
    p = fly_pnl(sigma, 0.0, cost_frac=0.0)
    assert abs((p["credit"] - np.minimum(np.abs(x), p["wing"])).mean()) < 0.003   # fair price earns ~0
    assert abs(fly_pnl(sigma, 0.0)["pnl_points"] - fly_pnl(sigma, 0.0)["credit"]) < 1e-12
    big = fly_pnl(sigma, 10.0)
    assert abs(big["pnl_points"] + big["max_loss"]) < 1e-12 and abs(big["ret"] + 0.01) < 1e-12


def test_flags_use_only_the_past():
    f = top_third_flags([1, 2, 3, 4, 5, 6, 100, 0.5, float("nan"), 50])
    assert f.tolist() == [False] * 6 + [True, False, False, True]


def test_permutation_detects_a_perfect_filter():
    rng = np.random.default_rng(0)
    vp = rng.normal(1, 1, 60)
    ev = pd.DataFrame({"var_prem": vp})
    skip = np.zeros(60, bool)
    worst = np.argsort(vp[6:])[:15] + 6
    skip[worst] = True
    assert permutation_p(ev, skip, 2000, rng) < 0.01            # skipping the worst is never luck
    rand = np.zeros(60, bool); rand[rng.choice(np.arange(6, 60), 15, replace=False)] = True
    assert permutation_p(ev, rand, 2000, rng) > 0.02            # a random skip set is unremarkable


def test_track_report_maths():
    import math
    from scipy import integrate
    from scipy.stats import t as student_t
    from track_report import fly_pnl_t, period_metrics, split_cutoff, t_abs_mean, t_upper_partial
    scale, dof, w = 0.8, 4, 1.3
    f = lambda x: student_t.pdf(x / scale, dof) / scale
    assert abs(t_abs_mean(scale, dof) - 2 * integrate.quad(lambda x: x * f(x), 0, np.inf)[0]) < 1e-7
    assert abs(t_upper_partial(w, scale, dof) - integrate.quad(lambda x: (x - w) * f(x), w, np.inf)[0]) < 1e-7
    for r in (0.0, 0.7, 5.0):                                   # many degrees of freedom -> the normal price
        assert abs(fly_pnl_t(1.1, r, 2000, 0.03) - fly_pnl(1.1, r, cost_frac=0.03)["ret"]) < 2e-5
    assert fly_pnl_t(1.1, 50.0, 4, 0.03) == -0.01                # a huge move loses exactly the 1% risked
    assert split_cutoff(["2020-01-01", "2020-06-01", "2025-01-01"]) == "2024-01-01"
    m = period_metrics(np.array([0.01, -0.01, 0.02]), np.array([0.5, 0.5, 0.5]), np.array([False, True, False]))
    assert m["trades"] == 2 and abs(m["turnover_x_capital"] - 12 * 1.0 / 3) < 1e-12
    assert abs(m["ann_return_pct"] - 100 * 12 * 0.01) < 1e-9 and m["max_drawdown_pct"] == 0.0


if __name__ == "__main__":
    test_shutdown_releases_excluded(); test_fly_pricing(); test_flags_use_only_the_past(); test_permutation_detects_a_perfect_filter()
    test_track_report_maths()
    print("stage 2 checks passed")
