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


def test_risk_helpers():
    from track_report import longest_run, losses_to_rules, regime_stats
    k_halve, k_stop = losses_to_rules(0.01)
    assert (k_halve, k_stop) == (7, 14)                          # 1 - 0.99**7 = 6.8%; then 7 half-size losses to 10%
    assert 1 - 0.99 ** 6 < 0.06 <= 1 - 0.99 ** 7
    assert longest_run([True, True, False, True, True, True, False]) == 3 and longest_run([]) == 0
    s = regime_stats([0.01, -0.01, 0.02])
    assert s["n"] == 3 and abs(s["hit_rate"] - 2 / 3) < 1e-12 and s["worst_pct"] == -1.0


def test_liquidity_helpers():
    from datetime import date
    from liquidity_measure import capacity, choose_atm, fly_metrics, quote_at, spxw_ticker, wing_strikes
    assert spxw_ticker(date(2024, 6, 21), "c", 5500) == "O:SPXW240621C05500000"
    assert spxw_ticker(date(2022, 7, 13), "P", 3790) == "O:SPXW220713P03790000"
    qs = [{"sip_timestamp": 10, "bid_price": 1.0, "ask_price": 1.2, "bid_size": 5, "ask_size": 7},
          {"sip_timestamp": 20, "bid_price": 0.0, "ask_price": 1.3, "bid_size": 0, "ask_size": 7},   # one-sided: ignored
          {"sip_timestamp": 30, "bid_price": 1.1, "ask_price": 1.3, "bid_size": 9, "ask_size": 4}]
    assert quote_at(qs, 25) == (1.0, 1.2, 5, 7) and quote_at(qs, 30) == (1.1, 1.3, 9, 4) and quote_at(qs, 5) is None
    assert choose_atm({5490: 30.0, 5495: 27.0, 5500: 24.0}, {5490: 21.0, 5495: 24.5, 5500: 28.0}) == 5495
    assert choose_atm({5490: 1.0}, {5495: 1.0}) is None
    assert wing_strikes(5500, 51.0) == (5400, 5600, 100)               # 2 x 51 = 102 -> nearest 5 = 100
    assert wing_strikes(5500, 1.0)[2] == 5                              # never narrower than one strike
    legs = {"call_atm": (24.0, 25.0, 10, 12), "put_atm": (23.0, 24.0, 8, 9),
            "call_wing": (1.0, 1.4, 50, 40), "put_wing": (1.5, 1.9, 30, 20)}
    fm = fly_metrics(legs)
    assert abs(fm["straddle_mid"] - 48.0) < 1e-12 and abs(fm["credit_mid"] - (48.0 - 1.2 - 1.7)) < 1e-12
    assert abs(fm["crossing_pts"] - (0.5 + 0.5 + 0.2 + 0.2)) < 1e-12 and fm["min_top_size"] == 8
    assert abs(fm["assumed_cost_pts"] - 0.03 * 48.0) < 1e-12
    cap = capacity(1234, 55.0)
    assert cap["contracts"] == 123 and cap["max_loss_usd_per_fly"] == 5500.0 and cap["capital_usd"] == 123 * 5500.0 / 0.01

    # the pricing check reproduces Stage 2-lite's normal-model prices, scaled from % of index to points
    import math
    import pandas as pd
    from liquidity_measure import model_prices, per_release_metrics
    vix1d, atm, c, p = 17.0, 5500.0, 30.0, 28.0
    fwd, sig = 5502.0, 17.0 / math.sqrt(252)
    ref = fly_pnl(sig, 0.0, cost_frac=0.0)
    width = ref["wing"] * fwd / 100
    mp = model_prices(atm, c, p, width, vix1d)
    assert abs(mp["forward"] - fwd) < 1e-12 and abs(mp["model_straddle"] - ref["straddle"] * fwd / 100) < 1e-9
    assert abs(mp["model_wings"] - (ref["straddle"] - ref["credit"]) * fwd / 100) < 1e-9

    # coverage: a release with a leg that is never quoted is excluded, not imputed
    marks = [f"15:{m}" for m in range(45, 60)] + [f"16:{m:02d}" for m in range(16)]
    rows = []
    for rd, missing in (("2024-01-11", None), ("2024-02-13", "put_wing")):
        for leg, (b, a) in {"call_atm": (24, 25), "put_atm": (23, 24), "call_wing": (1.0, 1.4), "put_wing": (1.5, 1.9)}.items():
            for mk in marks:
                q = (None, None) if leg == missing else (b, a)
                rows.append({"release_date": rd, "leg": leg, "mark": mk, "bid": q[0], "ask": q[1], "bid_size": 10, "ask_size": 10})
    vols = pd.DataFrame([{"release_date": rd, "eve": e, "leg": lg, "eve_volume": 1000.0, "atm": 4800.0, "wing_width": 100.0}
                         for rd, e in (("2024-01-11", "2024-01-10"), ("2024-02-13", "2024-02-12"))
                         for lg in ("call_atm", "put_atm", "call_wing", "put_wing")])
    pr = per_release_metrics(pd.DataFrame(rows), vols, {"2024-01-10": 13.0, "2024-02-12": 14.0}).set_index("release_date")
    assert bool(pr.loc["2024-01-11", "usable"]) and bool(pr.loc["2024-01-11", "priced_1615"])
    assert not bool(pr.loc["2024-02-13", "usable"]) and not bool(pr.loc["2024-02-13", "priced_1615"])
    assert pr.loc["2024-01-11", "marks"] == 31 and pr.loc["2024-02-13", "min_leg_marks"] == 0


if __name__ == "__main__":
    test_shutdown_releases_excluded(); test_fly_pricing(); test_flags_use_only_the_past(); test_permutation_detects_a_perfect_filter()
    test_track_report_maths(); test_risk_helpers(); test_liquidity_helpers()
    print("stage 2 checks passed")
