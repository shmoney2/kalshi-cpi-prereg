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


if __name__ == "__main__":
    test_shutdown_releases_excluded(); test_fly_pricing(); test_flags_use_only_the_past(); test_permutation_detects_a_perfect_filter()
    print("stage 2 checks passed")
