"""Download the Kalshi data the Fed-liveness study needs (public endpoints, no API key).

Run this on your own machine or the cluster; it was written against Kalshi's
published API spec but could not be tested live from the sandbox it was built in.
Start with --probe to confirm field names, then run the full download.

Examples
  python kalshi_fetch.py --probe KXCPI
  python kalshi_fetch.py --list-series
  python kalshi_fetch.py --spx data/spx_daily.csv --out data --since 2021-12-01

Outputs (in --out)
  kalshi_markets.csv    one row per contract: strike metadata, close time, settlement value
  releases.csv          one row per CPI release: actual prints, next FOMC meeting, snapshot times
  kalshi_snapshots.csv  one row per (release, role, snapshot, contract): last trade, bid, ask, volume

Snapshot times (all US Eastern)
  t0    15:45 on the last trading day before the release (when an options trade would be entered)
  pre   08:25 on release day (just before the 08:30 print; used to measure the surprise)
  post  10:00 on release day (Fed ladder only; used for the mechanism test)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from common import ET, et_timestamp, parse_dollars, parse_iso

BASE = "https://api.elections.kalshi.com/trade-api/v2"

# Current tickers carry the "KX" prefix; older contracts may sit under legacy
# series tickers. Use --list-series to confirm the legacy names before relying on them.
DEFAULT_SERIES = {
    "cpi_headline": ["KXCPI", "CPI"],
    "cpi_core": ["KXCPICORE", "CPICORE"],
    "fed": ["KXFED", "FED"],
}
# Official BLS CPI release dates. The 2025 shutdown moved September 2025 CPI to 2025-10-24
# (Kalshi's markets had closed on the original 10-15 date) and October 2025 CPI was never published.
DEFAULT_CPI_DATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cpi_release_dates.csv")
ROLE_SNAPSHOTS = {"cpi_headline": ["t0", "pre"], "cpi_core": ["t0", "pre"],
                  "fed": ["t0", "pre", "post"]}


# ---------------------------------------------------------------- HTTP client
class Kalshi:
    def __init__(self, base=BASE, pause=0.08, retries=6):
        self.base = base.rstrip("/")
        self.pause = pause
        self.retries = retries
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        self.calls = 0

    def get(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None and v != ""}
        for attempt in range(self.retries):
            try:
                r = self.session.get(self.base + path, params=params, timeout=30)
            except requests.RequestException:
                time.sleep(min(30, 2 ** attempt))
                continue
            self.calls += 1
            if r.status_code == 404:
                return None
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(30, 2 ** attempt))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code} on {path} {params}: {r.text[:300]}")
            time.sleep(self.pause)
            return r.json()
        raise RuntimeError(f"Gave up on {path} {params} after {self.retries} attempts")

    def paginate(self, path, key, **params):
        out, cursor, seen = [], None, set()
        while True:
            js = self.get(path, cursor=cursor, **params)
            if not js:
                break
            out.extend(js.get(key) or [])
            cursor = js.get("cursor")
            if not cursor or cursor in seen:
                break
            seen.add(cursor)
        return out


def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _find_key(v, key)
            if found is not None:
                return found
    return None


def historical_cutoff(cl):
    v = _find_key(cl.get("/historical/cutoff") or {}, "market_settled_ts")
    if isinstance(v, (int, float)):
        return float(v)
    dt = parse_iso(v)
    return dt.timestamp() if dt else None


# ---------------------------------------------------------------- events / markets
def events_for_series(cl, series):
    return [e for e in cl.paginate("/events", "events", series_ticker=series, limit=200)
            if e.get("event_ticker")]


def markets_for_event(cl, event_ticker):
    hist = cl.paginate("/historical/markets", "markets", event_ticker=event_ticker, limit=1000)
    live = cl.paginate("/markets", "markets", event_ticker=event_ticker, limit=1000)
    by_ticker = {}
    for m in hist + live:
        t = m.get("ticker")
        if t and (t not in by_ticker or (m.get("result") and not by_ticker[t].get("result"))):
            by_ticker[t] = m
    return list(by_ticker.values())


_TICKER_STRIKE = re.compile(r"-T(N|-)?(\d+(?:\.\d+)?)$")


def strike_from_ticker(ticker):
    """Threshold from a ticker suffix: "-T0.4" means "> 0.4"; "-TN0.2" and "-T-0.3" are negative.

    Contracts settled before about 2023 carry no strike_type/floor_strike fields, only the ticker.
    The ticker stem can differ from the event ticker (FED-22JULY-T2.50 sits in event FED-22JUL),
    so only the suffix is parsed. Returns (strike_type, floor_strike) or (None, None).
    """
    m = _TICKER_STRIKE.search(ticker or "")
    if not m:
        return None, None
    return "greater", -float(m.group(2)) if m.group(1) else float(m.group(2))


def market_row(m, role, series):
    close = parse_iso(m.get("close_time"))
    settle = parse_iso(m.get("settlement_ts"))
    strike_type, floor_strike = m.get("strike_type"), m.get("floor_strike")
    if not strike_type and floor_strike is None and m.get("cap_strike") is None:
        strike_type, floor_strike = strike_from_ticker(m.get("ticker"))
    return {
        "role": role, "series": series, "event_ticker": m.get("event_ticker"),
        "ticker": m.get("ticker"), "strike_type": strike_type,
        "floor_strike": floor_strike, "cap_strike": m.get("cap_strike"),
        "close_time": close.isoformat() if close else None,
        "close_ts": close.timestamp() if close else None,
        "settlement_ts": settle.timestamp() if settle else None,
        "result": m.get("result"), "expiration_value": m.get("expiration_value"),
        "volume": m.get("volume_fp", m.get("volume")),
    }


def summarize_event(rows, evening_rolls_forward=False):
    """Event close time, date and settled value.

    Until early 2022, CPI events closed the evening before the release (19:00 or 23:59 ET);
    with evening_rolls_forward, a close at or after 18:00 ET is dated to the next weekday.
    """
    close_ts = statistics.median([r["close_ts"] for r in rows])
    close_et = datetime.fromtimestamp(close_ts, ET)
    day = close_et.date()
    if evening_rolls_forward and close_et.hour >= 18:
        day += timedelta(days=1)
        while day.weekday() >= 5:
            day += timedelta(days=1)
    actual = None
    for r in rows:
        try:
            actual = float(str(r["expiration_value"]).strip().rstrip("%"))
            break
        except (TypeError, ValueError):
            continue
    return {"close_ts": close_ts, "close_et": close_et, "date": day, "actual": actual}


# ---------------------------------------------------------------- candles / snapshots
def _px(d, key):
    if not isinstance(d, dict):
        return None
    return parse_dollars(d.get(f"{key}_dollars", d.get(key)))


def _vol(c):
    try:
        return float(c.get("volume_fp", c.get("volume")) or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch_candles(cl, series, ticker, start, end, period, historical):
    paths = [f"/historical/markets/{ticker}/candlesticks",
             f"/series/{series}/markets/{ticker}/candlesticks"]
    if not historical:
        paths.reverse()
    for path in paths:
        js = cl.get(path, start_ts=int(start), end_ts=int(end), period_interval=period)
        candles = (js or {}).get("candlesticks") or []
        if candles:
            return candles
    return []


def _clusters(ts_sorted, gap):
    groups, cur = [], [ts_sorted[0]]
    for t in ts_sorted[1:]:
        if t - cur[-1] <= gap:
            cur.append(t)
        else:
            groups.append((cur[0], cur[-1])); cur = [t]
    groups.append((cur[0], cur[-1]))
    return groups


def summarize_candles(hourly, minute, T):
    """Last trade, latest quotes and trailing 24h volume using only candles ending at or before T."""
    tagged = [(c["end_period_ts"], 1, c) for c in minute if c.get("end_period_ts") is not None]
    tagged += [(c["end_period_ts"], 60, c) for c in hourly if c.get("end_period_ts") is not None]
    tagged = [x for x in tagged if x[0] <= T]
    trades = [(ts, _px(c.get("price"), "close")) for ts, _, c in tagged]
    trades = [x for x in trades if x[1] is not None]
    last_ts, last_px = max(trades) if trades else (None, None)
    if tagged:
        q_ts, _, qc = max(tagged, key=lambda x: (x[0], -x[1]))
        bid, ask = _px(qc.get("yes_bid"), "close"), _px(qc.get("yes_ask"), "close")
    else:
        q_ts, bid, ask = None, None, None
    vol24 = sum(_vol(c) for ts, p, c in tagged if p == 60 and ts > T - 86_400)
    return {"last_price": last_px, "last_trade_ts": last_ts, "yes_bid": bid,
            "yes_ask": ask, "quote_ts": q_ts, "vol_24h": vol24}


def market_snapshots(cl, series, ticker, times, historical):
    ts_sorted = sorted(times.values())
    hourly = fetch_candles(cl, series, ticker, ts_sorted[0] - 7 * 86_400, ts_sorted[-1], 60, historical)
    minute = []
    for start, end in _clusters(ts_sorted, gap=3 * 3600):
        minute += fetch_candles(cl, series, ticker, start - 90 * 60, end, 1, historical)
    return {label: summarize_candles(hourly, minute, T) for label, T in times.items()}


# ---------------------------------------------------------------- calendars
def load_trading_days(path):
    if not path:
        return None
    df = pd.read_csv(path)
    col = [c for c in df.columns if c.lower() == "date"][0]
    return sorted(pd.to_datetime(df[col]).dt.date.unique())


def prev_trading_day(d, trading_days):
    if trading_days:
        earlier = [x for x in trading_days if x < d]
        if earlier:
            return earlier[-1]
    x = d - timedelta(days=1)
    while x.weekday() >= 5:
        x -= timedelta(days=1)
    return x


def snap_to(d, candidates, tol_days=3):
    if not candidates:
        return d
    best = min(candidates, key=lambda c: abs((c - d).days))
    return best if abs((best - d).days) <= tol_days else d


def match_release(d, release_dates, tol_days=3):
    """Official release date within tol_days of d, or None (no CPI was published near d)."""
    if not release_dates:
        return None
    best = min(release_dates, key=lambda c: abs((c - d).days))
    return best if abs((best - d).days) <= tol_days else None


# ---------------------------------------------------------------- main routines
def probe(cl, series):
    evs = events_for_series(cl, series)
    print(f"{series}: {len(evs)} events")
    if not evs:
        return
    print("Example event:\n", json.dumps(evs[-1], indent=2)[:1500])
    mk = markets_for_event(cl, evs[-1]["event_ticker"])
    print(f"{len(mk)} markets in that event. Example market:\n", json.dumps(mk[0], indent=2)[:3000])
    close = parse_iso(mk[0].get("close_time"))
    if close:
        c = fetch_candles(cl, series, mk[0]["ticker"], close.timestamp() - 86_400,
                          close.timestamp(), 60, historical=True)
        print("Example candles:\n", json.dumps(c[:2], indent=2))
    print("Historical cutoff:", cl.get("/historical/cutoff"))


def list_series(cl, pattern):
    series = cl.paginate("/series", "series")
    rx = re.compile(pattern, re.I)
    for s in series:
        text = f"{s.get('ticker', '')} {s.get('title', '')}"
        if rx.search(text):
            print(f"{s.get('ticker'):<20} {s.get('title')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data")
    ap.add_argument("--spx", help="CSV with a 'date' column, used as the trading calendar")
    ap.add_argument("--since", default="2021-06-01")
    ap.add_argument("--until", default=None)
    ap.add_argument("--cpi-series", nargs="+", default=DEFAULT_SERIES["cpi_headline"])
    ap.add_argument("--core-series", nargs="+", default=DEFAULT_SERIES["cpi_core"])
    ap.add_argument("--fed-series", nargs="+", default=DEFAULT_SERIES["fed"])
    ap.add_argument("--cpi-dates", default=DEFAULT_CPI_DATES if os.path.exists(DEFAULT_CPI_DATES) else None,
                    help="CSV with column release_date (BLS schedule); CPI events not within 3 days of "
                         f"an official release are skipped. Default: {DEFAULT_CPI_DATES} if present")
    ap.add_argument("--fomc-dates", help="optional CSV with column decision_date")
    ap.add_argument("--pause", type=float, default=0.08, help="seconds between API calls")
    ap.add_argument("--max-releases", type=int, default=None, help="for quick test runs")
    ap.add_argument("--resume", action="store_true", help="skip releases already in the snapshot file")
    ap.add_argument("--probe", metavar="SERIES")
    ap.add_argument("--list-series", action="store_true")
    ap.add_argument("--pattern", default=r"cpi|inflation|fed|fomc|funds rate")
    args = ap.parse_args()

    cl = Kalshi(pause=args.pause)
    if args.probe:
        probe(cl, args.probe); return
    if args.list_series:
        list_series(cl, args.pattern); return

    os.makedirs(args.out, exist_ok=True)
    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until) if args.until else date.today()
    trading_days = load_trading_days(args.spx)
    if not trading_days:
        print("Warning: no --spx calendar given; using previous weekday for t0 (holidays ignored).")
    cpi_dates = (sorted(pd.to_datetime(pd.read_csv(args.cpi_dates)["release_date"]).dt.date)
                 if args.cpi_dates else [])
    fomc_dates = (sorted(pd.to_datetime(pd.read_csv(args.fomc_dates)["decision_date"]).dt.date)
                  if args.fomc_dates else [])
    cutoff = historical_cutoff(cl)
    print(f"Historical cutoff (market_settled_ts): {cutoff}")

    series_map = {"cpi_headline": args.cpi_series, "cpi_core": args.core_series, "fed": args.fed_series}
    markets_by_event, event_info, all_rows = {}, {r: {} for r in series_map}, []
    for role, series_list in series_map.items():
        for s in series_list:
            evs = events_for_series(cl, s)
            print(f"{role:<13} series {s:<10} {len(evs):>4} events")
            for e in evs:
                rows = [market_row(m, role, s) for m in markets_for_event(cl, e["event_ticker"])]
                rows = [r for r in rows if r["close_ts"]]
                if not rows:
                    continue
                info = summarize_event(rows, evening_rolls_forward=role != "fed")
                info.update(series=s, event_ticker=e["event_ticker"])
                if role != "fed" and not (6 <= info["close_et"].hour <= 9 or info["close_et"].hour >= 18):
                    print(f"  note: {e['event_ticker']} closes at {info['close_et']:%H:%M} ET; "
                          "check its release date (use --cpi-dates to pin it)")
                if role != "fed" and cpi_dates:
                    key = match_release(info["date"], cpi_dates)
                    if key is None:
                        print(f"  skip: {e['event_ticker']} (dated {info['date']}) has no official CPI "
                              "release within 3 days")
                        continue
                else:
                    key = snap_to(info["date"], fomc_dates if role == "fed" else cpi_dates)
                info["date"] = key
                event_info[role][e["event_ticker"]] = info
                markets_by_event[e["event_ticker"]] = rows
                all_rows += rows
    pd.DataFrame(all_rows).to_csv(os.path.join(args.out, "kalshi_markets.csv"), index=False)

    by_date = {"cpi_headline": {}, "cpi_core": {}}
    for role in by_date:
        for info in event_info[role].values():
            by_date[role][info["date"]] = info
    fed_events = sorted(event_info["fed"].values(), key=lambda x: x["close_ts"])

    release_dates = sorted(d for d in set(by_date["cpi_headline"]) | set(by_date["cpi_core"])
                           if since <= d <= until)
    if args.max_releases:
        release_dates = release_dates[: args.max_releases]

    snap_path = os.path.join(args.out, "kalshi_snapshots.csv")
    done = set()
    if args.resume and os.path.exists(snap_path):
        done = set(pd.read_csv(snap_path)["release_date"].astype(str))

    releases = []
    for i, R in enumerate(release_dates, 1):
        t0_day = prev_trading_day(R, trading_days)
        times = {"t0": et_timestamp(t0_day, 15, 45), "pre": et_timestamp(R, 8, 25),
                 "post": et_timestamp(R, 10, 0)}
        release_ts = et_timestamp(R, 8, 30)
        nxt = next((f for f in fed_events if f["close_ts"] > release_ts), None)
        h, c = by_date["cpi_headline"].get(R), by_date["cpi_core"].get(R)
        releases.append({
            "release_date": R.isoformat(), "t0_date": t0_day.isoformat(),
            "headline_event": h["event_ticker"] if h else None, "headline_actual": h["actual"] if h else None,
            "core_event": c["event_ticker"] if c else None, "core_actual": c["actual"] if c else None,
            "fed_event": nxt["event_ticker"] if nxt else None,
            "fed_meeting_date": nxt["date"].isoformat() if nxt else None,
            "t0_ts": times["t0"], "pre_ts": times["pre"], "post_ts": times["post"],
        })
        if R.isoformat() in done:
            continue
        snap_rows = []
        for role, info in (("cpi_headline", h), ("cpi_core", c), ("fed", nxt)):
            if not info:
                continue
            want = {lab: times[lab] for lab in ROLE_SNAPSHOTS[role]}
            for m in markets_by_event[info["event_ticker"]]:
                hist = bool(cutoff and (m["settlement_ts"] or m["close_ts"]) < cutoff)
                snaps = market_snapshots(cl, info["series"], m["ticker"], want, hist)
                for lab, sv in snaps.items():
                    snap_rows.append({"release_date": R.isoformat(), "role": role, "label": lab,
                                      "snapshot_ts": want[lab], "series": info["series"],
                                      "event_ticker": info["event_ticker"], "ticker": m["ticker"],
                                      "strike_type": m["strike_type"], "floor_strike": m["floor_strike"],
                                      "cap_strike": m["cap_strike"], **sv})
        pd.DataFrame(snap_rows).to_csv(snap_path, mode="a", index=False,
                                       header=not os.path.exists(snap_path))
        print(f"[{i}/{len(release_dates)}] {R}: {len(snap_rows)} snapshot rows, {cl.calls} API calls so far")

    pd.DataFrame(releases).to_csv(os.path.join(args.out, "releases.csv"), index=False)
    print(f"Done: {len(releases)} releases written to {args.out}/releases.csv")


if __name__ == "__main__":
    main()
