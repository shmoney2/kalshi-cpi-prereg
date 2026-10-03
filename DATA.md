# Full data download

`python run_all.py` needs only the committed files in `derived/`. This page rebuilds `derived/` from the original sources. Raw downloads go in `data/` and outputs in `results/`; both are gitignored and must not be committed.

## Sources

| Data | Source | Needs | Used for |
| --- | --- | --- | --- |
| CPI and core CPI ladders, actual prints | Kalshi public API (`KXCPI`, `KXCPICORE`) | Nothing | Surprise, CPI uncertainty |
| Next-meeting Fed ladders | Kalshi public API (`KXFED`) | Nothing | Liveness |
| SPY daily bars, 09:35 level on release days, dividends | Massive (formerly Polygon.io) | A Massive plan with stocks data and a key in `.env` | Market reaction |
| VIX daily close | Cboe `VIX_History.csv` (free) | Nothing | Control |
| VIX1D daily close | Cboe `VIX1D_History.csv` (free) | Nothing | Stage 2-lite option price |
| CPI release calendar | BLS, committed as `cpi_release_dates.csv` | Nothing | Release-date matching |

The study uses SPY because the Massive plan used had no index data; see the Data section of `PREREGISTRATION.md`.

## Steps

Commands use `python` directly so they work without `make` (the `Makefile` has the same steps).

```bash
pip install -r requirements.txt
cp .env.example .env            # then paste MASSIVE_API_KEY into .env yourself; never commit it

# 1. SPY daily data, dividends, VIX (writes data/spx_daily.csv, data/vix_daily.csv)
python massive_fetch.py market --since 2021-11-01 --out data --releases data/releases.csv

# 2. Kalshi ladders and snapshots, resumable (about an hour; writes data/kalshi_*.csv, data/releases.csv)
python kalshi_fetch.py --out data --since 2021-12-01 --spx data/spx_daily.csv --resume

# 3. Rerun step 1 to add SPY 09:35 levels on release days
python massive_fetch.py market --since 2021-11-01 --out data --releases data/releases.csv

# 4. Event table and Stage 1 test
python build_dataset.py --data data --out results
python sensitivity_test.py --table results/event_table.csv --out results

# 5. VIX1D and Stage 2-lite test
python stage2_lite.py fetch
python stage2_lite.py run

# 6. Track reporting additions
python track_report.py --table results/event_table.csv --stage2 results --out results
```

To refresh `derived/`, copy `results/event_table.csv`, `results/distributions.json` and `data/releases.csv` into it, keep only release-eve rows of `data/vix1d_daily.csv` in `derived/vix1d_release_eves.csv`, then run `python run_all.py --write-expected results`.

## Notes

- Kalshi markets settled before the historical cutoff come from the `/historical/...` endpoints; the downloader handles both.
- Contracts settled before about 2023 have no strike fields; strikes are read from ticker suffixes.
- Kalshi emits candles only for periods with activity, so standing quotes are found with a 120-day daily-candle lookback.
- September 2025 CPI (published 2025-10-24 after the shutdown, with Kalshi's markets closed on the original 10-15 date) and October 2025 CPI (never published) are excluded.
- Download results can differ slightly if Kalshi or Massive revise historical records. The committed `derived/` files are the ones the reported results use.
