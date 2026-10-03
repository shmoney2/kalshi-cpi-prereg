"""Shared helpers for the Fed-liveness sensitivity study.

Covers: Eastern-time timestamps, Kalshi price parsing, converting a ladder of
"outcome > strike" contracts into a discrete probability distribution, summary
statistics of that distribution, and OLS with HC3 standard errors.
"""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import numpy as np
from scipy import stats

ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------- time / parsing
def et_timestamp(d: date, hh: int, mm: int) -> int:
    """Unix timestamp for a wall-clock time in New York on date d."""
    return int(datetime.combine(d, time(hh, mm), tzinfo=ET).timestamp())


def parse_iso(s):
    """Parse an ISO-8601 string (with Z or offset) into an aware datetime, or None."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_dollars(v):
    """Kalshi prices arrive as fixed-point dollar strings ("0.5600").

    Very old payloads used integer cents; values above 1.5 are treated as cents.
    """
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if np.isnan(x):
        return None
    return x / 100.0 if x > 1.5 else x


def choose_price(last_price, last_trade_ts, yes_bid, yes_ask, snapshot_ts,
                 max_trade_age_s=86_400, max_spread=0.10, prefer="trade"):
    """Pre-registered price rule for one contract at one snapshot.

    prefer="trade": last trade if it happened within max_trade_age_s before the
    snapshot, otherwise the bid-ask midpoint if the spread is at most max_spread,
    otherwise None (the strike is dropped). prefer="mid" reverses the order.
    """
    def ok(x):
        return x is not None and not (isinstance(x, float) and np.isnan(x))

    trade_ok = (ok(last_price) and ok(last_trade_ts)
                and 0 <= snapshot_ts - last_trade_ts <= max_trade_age_s)
    quotes_ok = (ok(yes_bid) and ok(yes_ask) and yes_ask > yes_bid
                 and (yes_ask - yes_bid) <= max_spread)
    mid = (yes_bid + yes_ask) / 2 if quotes_ok else None
    if prefer == "trade":
        return last_price if trade_ok else mid
    return mid if mid is not None else (last_price if trade_ok else None)


# ---------------------------------------------------------------- distributions
def _pava_nondecreasing(y, w):
    vals, wts, cnts = [], [], []
    for yi, wi in zip(y, w):
        vals.append(float(yi)); wts.append(float(wi)); cnts.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            wt = wts[-2] + wts[-1]
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / wt
            c = cnts[-2] + cnts[-1]
            vals[-2:] = [v]; wts[-2:] = [wt]; cnts[-2:] = [c]
    out = []
    for v, c in zip(vals, cnts):
        out.extend([v] * c)
    return np.array(out)


def pava_nonincreasing(y, w=None):
    """Isotonic (non-increasing) least-squares fit; used to make survival curves monotone."""
    y = np.asarray(y, float)
    w = np.ones(len(y)) if w is None else np.asarray(w, float)
    return -_pava_nondecreasing(-y, w)


def to_greater_than(strike_type, floor_strike, cap_strike, price, grid_step):
    """Convert one contract into (k, P(X > k)) for an outcome on a discrete grid.

    Returns None for contract types that are not one-sided thresholds.
    """
    if price is None:
        return None
    st = (strike_type or "").lower()
    if st == "greater" and floor_strike is not None:
        return float(floor_strike), price
    if st == "greater_or_equal" and floor_strike is not None:
        return float(floor_strike) - grid_step, price            # X >= k  <=>  X > k - step
    if st == "less" and cap_strike is not None:
        return float(cap_strike) - grid_step, 1.0 - price        # P(X >= k) = 1 - P(X < k)
    if st == "less_or_equal" and cap_strike is not None:
        return float(cap_strike), 1.0 - price                    # P(X > k) = 1 - P(X <= k)
    return None


def ladder_to_distribution(strikes, surv, step=None, upper_tail_steps=1.0):
    """Turn P(X > k_i) prices into a discrete distribution.

    Convention: the bucket (k_i, k_{i+1}] is placed at k_{i+1} (the grid point it
    contains when strikes are one grid step apart); everything at or below the
    lowest strike sits at k_0; everything above the highest strike sits at
    k_max + upper_tail_steps * step. The survival curve is made monotone with
    isotonic regression before differencing. Returns (values, probs) or (None, None).
    """
    k = np.asarray(strikes, float)
    s = np.clip(np.asarray(surv, float), 0.0, 1.0)
    if len(k) == 0:
        return None, None
    uk = np.unique(k)
    s = np.array([s[k == u].mean() for u in uk])
    k = uk
    s = np.clip(pava_nonincreasing(s), 0.0, 1.0)
    if step is None:
        step = float(np.median(np.diff(k))) if len(k) > 1 else 0.1
    values = np.concatenate([[k[0]], k[1:], [k[-1] + upper_tail_steps * step]])
    probs = np.concatenate([[1.0 - s[0]], s[:-1] - s[1:], [s[-1]]])
    probs = np.clip(probs, 0.0, None)
    total = probs.sum()
    if total <= 0:
        return None, None
    return values, probs / total


def _interp_quantile(values, probs, q, step):
    cdf = np.cumsum(probs)
    xs = np.concatenate([[values[0] - step], values])
    ys = np.concatenate([[0.0], cdf])
    i = int(np.searchsorted(ys, q - 1e-12))
    i = min(max(i, 1), len(xs) - 1)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return float(x1 if y1 == y0 else x0 + (q - y0) * (x1 - x0) / (y1 - y0))


def dist_stats(values, probs, step):
    """Mean, SD, median, interpolated IQR, modal probability and entropy."""
    v = np.asarray(values, float)
    p = np.asarray(probs, float)
    mean = float((v * p).sum())
    sd = float(np.sqrt(((v - mean) ** 2 * p).sum()))
    cdf = np.cumsum(p)
    median = float(v[min(int(np.searchsorted(cdf, 0.5 - 1e-12)), len(v) - 1)])
    iqr = _interp_quantile(v, p, 0.75, step) - _interp_quantile(v, p, 0.25, step)
    nz = p[p > 0]
    return {"mean": mean, "sd": sd, "median": median, "iqr": iqr,
            "pmode": float(p.max()), "entropy": float(-(nz * np.log(nz)).sum())}


# ---------------------------------------------------------------- regression
def ols_hc3(y, X, names):
    """OLS with HC3 heteroskedasticity-robust standard errors (t distribution, n-k df)."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    n, k = X.shape
    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    resid = y - X @ beta
    h = np.clip(np.einsum("ij,jk,ik->i", X, xtx_inv, X), 0.0, 0.999)
    omega = (resid / (1.0 - h)) ** 2
    cov = xtx_inv @ (X.T * omega) @ X @ xtx_inv
    se = np.sqrt(np.clip(np.diag(cov), 1e-300, None))
    tvals = beta / se
    df = max(n - k, 1)
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1.0 - (resid ** 2).sum() / ss_tot if ss_tot > 0 else np.nan
    return {"names": list(names), "beta": dict(zip(names, beta)), "se": dict(zip(names, se)),
            "t": dict(zip(names, tvals)), "df": df, "n": n, "r2": r2,
            "resid": resid, "fitted": X @ beta}


def one_sided_p(t, df, direction):
    """direction='neg' tests coefficient < 0; 'pos' tests coefficient > 0."""
    return float(stats.t.cdf(t, df) if direction == "neg" else stats.t.sf(t, df))


def coef_fast(y, X, j):
    """Coefficient j from a least-squares fit (no inference) for resampling loops."""
    return float(np.linalg.lstsq(X, y, rcond=None)[0][j])


def zscore(x):
    x = np.asarray(x, float)
    sd = np.nanstd(x)
    return (x - np.nanmean(x)) / sd if sd > 0 else x * 0.0
