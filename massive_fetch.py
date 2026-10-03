"""Market data from Massive (formerly Polygon.io) for the CPI study.

  python massive_fetch.py check-access                     # what your plan can reach (about 8 calls)
  python massive_fetch.py market --since 2021-11-01 --out data --releases data/releases.csv

Needs MASSIVE_API_KEY in the environment or in a .env file in this folder.

Writes
  data/spx_daily.csv   date, open, close, dividend, level_0935 (09:35 ET level, filled on CPI release days)
  data/vix_daily.csv   date, close

The S&P 500 is measured with SPY by default (the Massive plan has no index data; see
PREREGISTRATION.md). `dividend` is SPY's cash dividend on its ex-dividend date, 0 otherwise;
Massive's adjusted=true covers splits only, so build_dataset.py adds it back to that day's price.

Why 09:35: the official 09:30 opening value is partly computed from stale prices of
stocks that have not opened yet. Five minutes in, nearly every component has traded.
"""
from __future__ import annotations

import argparse
import io
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from common import ET

BASE = os.environ.get("MASSIVE_BASE_URL", "https://api.massive.com")
CBOE_VIX_CSV = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class AccessDenied(Exception):
    pass


class Massive:
    def __init__(self, key):
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {key}"
        self.calls = 0

    def get(self, url, **params):
        if not url.startswith("http"):
            url = BASE + url
        for attempt in range(8):
            r = self.session.get(url, params=params or None, timeout=30)
            self.calls += 1
            if r.status_code == 429:                      # free tiers allow about 5 calls a minute
                time.sleep(min(60, 12 * (attempt + 1)))
                continue
            if r.status_code in (401, 403):
                raise AccessDenied(f"HTTP {r.status_code}: {r.text[:160]}")
            if r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            js = r.json()
            if js.get("status") == "NOT_AUTHORIZED":
                raise AccessDenied(js.get("message", "not authorized"))
            return js
        raise RuntimeError(f"Gave up on {url}")

    def aggs(self, ticker, mult, span, start, end):
        js = self.get(f"/v2/aggs/ticker/{ticker}/range/{mult}/{span}/{start}/{end}",
                      adjusted="true", sort="asc", limit=50000)
        out, nxt = list(js.get("results") or []), js.get("next_url")
        while nxt:
            js = self.get(nxt)
            out += js.get("results") or []
            nxt = js.get("next_url")
        return out


def bars_to_daily(bars):
    rows = [{"date": datetime.fromtimestamp(b["t"] / 1000, ET).date(), "open": b.get("o"), "close": b.get("c")}
            for b in bars]
    return pd.DataFrame(rows).drop_duplicates("date").sort_values("date")


def dividends_by_date(m, ticker, since):
    """Cash dividends summed by ex-dividend date: {date: amount}."""
    js = m.get("/v3/reference/dividends", ticker=ticker, **{"ex_dividend_date.gte": since},
               limit=1000, order="asc")
    out, nxt = list(js.get("results") or []), js.get("next_url")
    while nxt:
        js = m.get(nxt)
        out += js.get("results") or []
        nxt = js.get("next_url")
    divs = {}
    for d in out:
        if d.get("ex_dividend_date") and d.get("cash_amount") is not None:
            day = date.fromisoformat(d["ex_dividend_date"])
            divs[day] = divs.get(day, 0.0) + float(d["cash_amount"])
    return divs


def level_at_0935(m, ticker, d):
    """Index level as of 09:35 ET: close of the 09:34 minute bar (open of the 09:35 bar as fallback)."""
    bars = m.aggs(ticker, 1, "minute", d.isoformat(), d.isoformat())
    by_minute = {datetime.fromtimestamp(b["t"] / 1000, ET).strftime("%H:%M"): b for b in bars}
    if "09:34" in by_minute:
        return by_minute["09:34"].get("c")
    if "09:35" in by_minute:
        return by_minute["09:35"].get("o")
    return None


# ---------------------------------------------------------------- commands
def check_access(m):
    probes = [
        ("S&P 500 index, daily, recent", lambda: m.aggs("I:SPX", 1, "day", (date.today() - timedelta(days=20)).isoformat(),
                                                       date.today().isoformat()), "Stage 1 market data"),
        ("S&P 500 index, daily, June 2022", lambda: m.aggs("I:SPX", 1, "day", "2022-06-01", "2022-06-15"),
         "Full Stage 1 history"),
        ("S&P 500 index, minute, June 2024", lambda: m.aggs("I:SPX", 1, "minute", "2024-06-12", "2024-06-12"),
         "09:35 level (clean opening reaction)"),
        ("VIX index, daily, June 2022", lambda: m.aggs("I:VIX", 1, "day", "2022-06-01", "2022-06-15"),
         "VIX control (Cboe's free file is the fallback)"),
        ("SPY, daily, June 2022", lambda: m.aggs("SPY", 1, "day", "2022-06-01", "2022-06-15"),
         "Fallback if index data is not in your plan"),
        ("SPX option contracts, reference", lambda: m.get("/v3/reference/options/contracts",
                                                          underlying_ticker="SPX", expiration_date="2024-06-12",
                                                          expired="true", limit=1),
         "Stage 2: finding event-day contracts"),
        ("SPXW option, minute bars, June 2024", lambda: m.aggs("O:SPXW240612C05400000", 1, "minute",
                                                              "2024-06-11", "2024-06-11"),
         "Stage 2: straddle prices from trades"),
        ("SPXW option, quotes, June 2024", lambda: m.get("/v3/quotes/O:SPXW240612C05400000",
                                                         **{"timestamp.gte": "2024-06-11T19:40:00Z",
                                                            "timestamp.lte": "2024-06-11T19:46:00Z", "limit": 1}),
         "Stage 2: bid/ask at entry (best)"),
    ]
    print(f"{'Capability':<38} {'Result':<14} Unlocks")
    for name, fn, unlocks in probes:
        try:
            js = fn()
            n = len(js) if isinstance(js, list) else len(js.get("results") or [])
            status = "OK" if n else "OK, no rows"
        except AccessDenied:
            status = "not in plan"
        except Exception as e:                                    # noqa: BLE001 - report and continue
            status = f"error ({type(e).__name__})"
        print(f"{name:<38} {status:<14} {unlocks}")


def market(m, since, out_dir, releases_path, spx_ticker="SPY"):
    os.makedirs(out_dir, exist_ok=True)
    end = date.today().isoformat()
    spx = bars_to_daily(m.aggs(spx_ticker, 1, "day", since, end))
    if spx_ticker.startswith("I:"):
        spx["dividend"] = 0.0
    else:
        divs = dividends_by_date(m, spx_ticker, since)
        spx["dividend"] = spx["date"].map(divs).fillna(0.0)
        print(f"{spx_ticker}: {int((spx['dividend'] > 0).sum())} ex-dividend days in range")

    spx["level_0935"] = pd.NA
    if releases_path and os.path.exists(releases_path):
        dates = sorted(pd.to_datetime(pd.read_csv(releases_path)["release_date"]).dt.date)
        dates = [d for d in dates if d >= date.fromisoformat(since)]
        print(f"Fetching 09:35 levels for {len(dates)} release days from {spx_ticker} minute bars")
        levels = {}
        for d in dates:
            try:
                levels[d] = level_at_0935(m, spx_ticker, d)
            except AccessDenied:
                print("Minute bars are not in your plan; the official open will be used instead.")
                break
        spx["level_0935"] = spx["date"].map(levels)
    else:
        print("No releases file given: run kalshi_fetch.py first, then rerun this to add 09:35 levels.")
    spx.to_csv(os.path.join(out_dir, "spx_daily.csv"), index=False)
    print(f"Wrote {len(spx)} days to {out_dir}/spx_daily.csv ({spx_ticker})")

    try:
        vix = bars_to_daily(m.aggs("I:VIX", 1, "day", since, end))[["date", "close"]]
        src = "Massive I:VIX"
    except AccessDenied:
        raw = pd.read_csv(io.StringIO(requests.get(CBOE_VIX_CSV, timeout=30).text))
        raw.columns = [c.strip().lower() for c in raw.columns]
        vix = pd.DataFrame({"date": pd.to_datetime(raw["date"]).dt.date, "close": raw["close"]})
        vix = vix[vix["date"] >= date.fromisoformat(since)]
        src = "Cboe VIX_History.csv"
    vix.to_csv(os.path.join(out_dir, "vix_daily.csv"), index=False)
    print(f"Wrote {len(vix)} days to {out_dir}/vix_daily.csv ({src}); {m.calls} Massive calls in total")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-access")
    mk = sub.add_parser("market")
    mk.add_argument("--since", default="2021-11-01")
    mk.add_argument("--out", default="data")
    mk.add_argument("--releases", default="data/releases.csv")
    mk.add_argument("--ticker", default="SPY", help="pre-registered: SPY (I:SPX needs the Indices tier)")
    args = ap.parse_args()

    load_env()
    key = os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise SystemExit("Set MASSIVE_API_KEY (copy .env.example to .env and paste your key).")
    m = Massive(key)
    if args.cmd == "check-access":
        check_access(m)
    else:
        market(m, args.since, args.out, args.releases, args.ticker)


if __name__ == "__main__":
    main()
