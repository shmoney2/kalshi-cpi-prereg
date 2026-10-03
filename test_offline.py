"""Offline checks (no network). Run: python test_offline.py"""
import numpy as np

from common import choose_price, dist_stats, ladder_to_distribution, to_greater_than
from kalshi_fetch import _clusters, summarize_candles

T = 1_700_000_000


def test_candles():
    hourly = [
        {"end_period_ts": T - 7200, "yes_bid": {"close_dollars": "0.4000"}, "yes_ask": {"close_dollars": "0.4300"},
         "price": {"close_dollars": "0.4100"}, "volume_fp": "120.00"},
        {"end_period_ts": T + 600, "yes_bid": {"close_dollars": "0.9000"}, "yes_ask": {"close_dollars": "0.9500"},
         "price": {"close_dollars": "0.9200"}, "volume_fp": "999.00"},          # ends after T: ignored
    ]
    minute = [
        {"end_period_ts": T - 60, "yes_bid": {"close_dollars": "0.4400"}, "yes_ask": {"close_dollars": "0.4600"},
         "price": {"close_dollars": None}, "volume_fp": "0.00"},
        {"end_period_ts": T - 1200, "yes_bid": {"close_dollars": "0.4200"}, "yes_ask": {"close_dollars": "0.4500"},
         "price": {"close_dollars": "0.4350"}, "volume_fp": "5.00"},
    ]
    s = summarize_candles(hourly, minute, T)
    assert s["last_price"] == 0.435 and s["last_trade_ts"] == T - 1200
    assert (s["yes_bid"], s["yes_ask"]) == (0.44, 0.46) and s["vol_24h"] == 120.0
    hist = [{"end_period_ts": T - 3600, "yes_bid": {"close": "0.3000"}, "yes_ask": {"close": "0.3200"},
             "price": {"close": "0.3100"}, "volume": "50.00"}]
    s2 = summarize_candles(hist, [], T)
    assert s2["last_price"] == 0.31 and s2["yes_bid"] == 0.30 and s2["vol_24h"] == 50.0
    legacy = [{"end_period_ts": T - 10, "yes_bid": {"close": 30}, "yes_ask": {"close": 33},
               "price": {"close": 31}, "volume": 4}]
    assert abs(summarize_candles(legacy, [], T)["last_price"] - 0.31) < 1e-12
    assert _clusters([0, 100, 20000, 20100], 3 * 3600) == [(0, 100), (20000, 20100)]


def test_strike_from_ticker():
    from kalshi_fetch import market_row, strike_from_ticker
    assert strike_from_ticker("CPI-22JUL-T0.1") == ("greater", 0.1)
    assert strike_from_ticker("FED-22JUL-T2.75") == ("greater", 2.75)
    assert strike_from_ticker("FED-22JULY-T2.50") == ("greater", 2.5)      # stem differs from event FED-22JUL
    assert strike_from_ticker("CPICORE-23FEB-TN0.2") == ("greater", -0.2)
    assert strike_from_ticker("CPI-23JUL-T-0.3") == ("greater", -0.3)
    assert strike_from_ticker("CPI-22JUL-B0.1") == (None, None)
    # pre-2023 payload: no strike fields, so the ticker fills them in
    old = {"ticker": "CPI-22JUL-T0.1", "event_ticker": "CPI-22JUL", "close_time": "2022-08-10T12:25:00Z"}
    r = market_row(old, "cpi_headline", "KXCPI")
    assert (r["strike_type"], r["floor_strike"]) == ("greater", 0.1)
    # explicit fields always win over the ticker
    new = dict(old, strike_type="greater", floor_strike=0.15)
    assert market_row(new, "cpi_headline", "KXCPI")["floor_strike"] == 0.15


def test_event_dates():
    from datetime import date
    from kalshi_fetch import market_row, summarize_event

    def info(close_time, roll, value="0.5"):
        m = {"ticker": "X-T0.1", "event_ticker": "X", "close_time": close_time, "expiration_value": value}
        return summarize_event([market_row(m, "cpi_headline", "KXCPI")], evening_rolls_forward=roll)
    assert info("2022-08-10T12:25:00Z", True)["date"] == date(2022, 8, 10)     # 08:25 ET: release day
    assert info("2022-01-12T04:59:00Z", True)["date"] == date(2022, 1, 12)     # 23:59 ET Jan 11 -> Jan 12
    assert info("2021-12-10T00:00:00Z", True)["date"] == date(2021, 12, 10)    # 19:00 ET Thu -> Fri
    assert info("2021-07-09T23:00:00Z", True)["date"] == date(2021, 7, 12)     # 19:00 ET Fri -> Mon
    assert info("2021-12-14T00:00:00Z", False)["date"] == date(2021, 12, 13)   # Fed events never roll
    assert info("2021-07-13T23:00:00Z", True, ".9%")["actual"] == 0.9


def test_release_matching():
    from datetime import date
    import pandas as pd
    from kalshi_fetch import DEFAULT_CPI_DATES, match_release
    official = sorted(pd.to_datetime(pd.read_csv(DEFAULT_CPI_DATES)["release_date"]).dt.date)
    assert match_release(date(2024, 6, 12), official) == date(2024, 6, 12)
    assert match_release(date(2025, 10, 15), official) is None    # Sep 2025 CPI slipped to 10-24; Kalshi closed 10-15
    assert match_release(date(2025, 11, 13), official) is None    # Oct 2025 CPI was never published
    assert date(2025, 10, 24) in official and match_release(date(2025, 12, 18), official) == date(2025, 12, 18)
    assert match_release(date(2024, 6, 12), []) is None


def test_strikes_and_distribution():
    for args in [("greater", 0.3, None, 0.6), ("greater_or_equal", 0.4, None, 0.6),
                 ("less", None, 0.4, 0.4), ("less_or_equal", None, 0.3, 0.4)]:
        k, p = to_greater_than(*args, 0.1)          # all four mean "print >= 0.4"
        assert abs(k - 0.3) < 1e-9 and abs(p - 0.6) < 1e-9
    true = {0.1: 0.05, 0.2: 0.25, 0.3: 0.40, 0.4: 0.25, 0.5: 0.05}
    strikes = [0.1, 0.2, 0.3, 0.4]
    surv = [sum(v for x, v in true.items() if x > k + 1e-9) for k in strikes]
    v, p = ladder_to_distribution(strikes, surv, step=0.1)
    assert {round(a, 2): round(b, 4) for a, b in zip(v, p) if b > 0} == true
    st = dist_stats(v, p, 0.1)
    assert abs(st["mean"] - 0.3) < 1e-9 and abs(st["sd"] - np.sqrt(0.009)) < 1e-9 and st["median"] == 0.3
    v2, p2 = ladder_to_distribution([0.1, 0.2, 0.3, 0.4], [0.95, 0.70, 0.72, 0.05], step=0.1)
    assert (p2 >= 0).all() and abs(p2.sum() - 1) < 1e-12


def test_price_rule():
    assert abs(choose_price(0.5, T - 90_000, 0.40, 0.44, T) - 0.42) < 1e-12   # stale trade -> midpoint
    assert choose_price(0.5, T - 90_000, 0.0, 1.0, T) is None                 # no market -> dropped
    assert choose_price(0.5, T - 100, 0.40, 0.44, T) == 0.5                   # fresh trade wins



def test_massive_parsing():
    from datetime import datetime
    from common import ET
    from massive_fetch import bars_to_daily, level_at_0935

    def ms(y, mo, d, hh, mm):
        return int(datetime(y, mo, d, hh, mm, tzinfo=ET).timestamp() * 1000)

    daily = bars_to_daily([{"t": ms(2024, 6, 12, 0, 0), "o": 5400.1, "c": 5421.0},
                           {"t": ms(2024, 6, 11, 0, 0), "o": 5350.0, "c": 5375.3}])
    assert list(daily["date"].astype(str)) == ["2024-06-11", "2024-06-12"]

    class FakeMassive:
        def aggs(self, *a):
            return [{"t": ms(2024, 6, 12, 9, 33), "o": 5390, "c": 5392},
                    {"t": ms(2024, 6, 12, 9, 34), "o": 5392, "c": 5395.5},
                    {"t": ms(2024, 6, 12, 9, 35), "o": 5395.6, "c": 5397}]
    from datetime import date
    assert level_at_0935(FakeMassive(), "I:SPX", date(2024, 6, 12)) == 5395.5

    from massive_fetch import dividends_by_date

    class FakeDivs:
        def get(self, url, **params):
            if url.startswith("http"):
                return {"results": [{"ex_dividend_date": "2024-06-21", "cash_amount": 1.759}]}
            return {"results": [{"ex_dividend_date": "2024-03-15", "cash_amount": 1.595},
                                {"ex_dividend_date": "2024-03-15", "cash_amount": 0.005},
                                {"ex_dividend_date": None, "cash_amount": 9.0}],
                    "next_url": "https://api.massive.com/next"}
    divs = dividends_by_date(FakeDivs(), "SPY", "2024-01-01")
    assert set(divs) == {date(2024, 3, 15), date(2024, 6, 21)} and abs(divs[date(2024, 3, 15)] - 1.6) < 1e-12


def test_dividend_added_back():
    import os as _os, tempfile
    import pandas as pd
    from build_dataset import load_prices
    d = tempfile.mkdtemp()
    p = _os.path.join(d, "spx.csv")
    pd.DataFrame({"date": ["2024-03-14", "2024-03-15"], "open": [515.0, 512.0], "close": [514.0, 510.0],
                  "dividend": [0.0, 1.6], "level_0935": [None, 512.4]}).to_csv(p, index=False)
    spx = load_prices(p, need_open=True)
    assert list(spx["dividend"]) == [0.0, 1.6]
    # a 1.6 dividend on a 514 close is not a 0.3% loss: r = ln((512.4 + 1.6) / 514) = 0
    assert abs(np.log((spx["level_0935"][1] + spx["dividend"][1]) / spx["close"][0])) < 1e-12
    pd.DataFrame({"date": ["2024-03-14"], "open": [1.0], "close": [1.0]}).to_csv(p, index=False)
    assert list(load_prices(p, need_open=True)["dividend"]) == [0.0]      # older files: no column, no dividend

def test_solana_stamp():
    """Full stamp + verify cycle against a simulated RPC, in a scratch copy of the project."""
    import json as _json, os as _os, shutil, tempfile
    import timestamp_solana as ts
    from solders.keypair import Keypair
    here = _os.getcwd()
    tmp = tempfile.mkdtemp()
    try:
        for f in ts.frozen_files() + ["timestamp_solana.py"]:
            shutil.copy(f, tmp)
        keyfile = _os.path.join(tempfile.mkdtemp(), "k.json")
        kp = Keypair()
        _json.dump(list(bytes(kp)), open(keyfile, "w"))
        _os.chdir(tmp)
        # CRLF and LF copies of a file hash the same
        open("crlf_check.txt", "wb").write(b"a\r\nb\r\n")
        open("lf_check.txt", "wb").write(b"a\nb\n")
        assert ts.file_sha256("crlf_check.txt") == ts.file_sha256("lf_check.txt")
        _os.remove("crlf_check.txt"); _os.remove("lf_check.txt")
        sent = {}
        def fake_rpc(url, method, params):
            if method == "getLatestBlockhash":
                return {"value": {"blockhash": "11111111111111111111111111111111"}}
            if method == "sendTransaction":
                import base64
                from solders.transaction import Transaction
                tx = Transaction.from_bytes(base64.b64decode(params[0]))
                tx.verify()
                sent["memo"] = bytes(tx.message.instructions[0].data).decode()
                return "FakeSig111"
            if method == "getSignatureStatuses":
                return {"value": [{"confirmationStatus": "confirmed", "err": None}]}
            if method == "getTransaction":
                return {"slot": 123, "blockTime": 1790000000,
                        "transaction": {"message": {"instructions": [
                            {"program": "spl-memo", "programId": ts.MEMO_PROGRAM, "parsed": sent["memo"]}]}},
                        "meta": {"logMessages": []}}
            raise AssertionError(method)
        ts.rpc = fake_rpc
        ts.git_dirty = lambda: False
        ts.git_commit = lambda: "abc123"
        class A: pass
        a = A(); a.network = "devnet"; a.keypair = keyfile; a.rpc = None; a.force = False
        ts.cmd_stamp(a)                                   # practice run writes nothing
        assert not _os.path.exists(ts.STAMP) and not _os.path.exists(ts.MANIFEST)
        a.network = "mainnet"
        ts.cmd_stamp(a)
        stamp = _json.load(open(ts.STAMP))
        assert stamp["signature"] == "FakeSig111" and stamp["manifest_sha256"] in sent["memo"]
        v = A(); v.rpc = None
        try:
            ts.cmd_verify(v)
        except SystemExit as e:
            assert e.code == 0, "verify should pass on an unchanged project"
        # a changed frozen file is reported but the on-chain proof still verifies
        open("common.py", "a").write("# edit\n")
        try:
            ts.cmd_verify(v)
        except SystemExit as e:
            assert e.code == 0
        # tampering with the recorded manifest fails verification
        open(ts.MANIFEST, "a").write("0" * 64 + "  extra.py\n")
        try:
            ts.cmd_verify(v); raise AssertionError("tampered manifest should fail")
        except SystemExit as e:
            assert e.code == 1
        # memo parsing falls back to the program log
        log = {"transaction": {"message": {"instructions": []}},
               "meta": {"logMessages": ['Program log: Memo (len 5): "hello"']}}
        assert ts.memo_from_transaction(log) == "hello"
        # keygen refuses to write inside the project folder
        k = A(); k.out = _os.path.join(tmp, "inside.json")
        try:
            ts.cmd_keygen(k); raise AssertionError("keygen should refuse")
        except SystemExit:
            pass
    finally:
        _os.chdir(here)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_candles(); test_strike_from_ticker(); test_event_dates(); test_release_matching(); test_strikes_and_distribution(); test_price_rule(); test_massive_parsing(); test_dividend_added_back()
    test_solana_stamp()
    print("all offline checks passed")
