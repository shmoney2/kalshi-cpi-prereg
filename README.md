# Kalshi signals for selling CPI-day volatility: a pre-registered test

Two pre-registered, Solana-timestamped tests of whether Kalshi prediction markets help decide when to sell the CPI event premium in S&P 500 options.

- **Stage 1** (`PREREGISTRATION.md`): does Kalshi's uncertainty about the next FOMC decision ("liveness") predict how strongly the S&P 500 reacts to CPI surprises? **Verdict: NO-GO** (49 releases, July 2022 to September 2026).
- **Stage 2-lite** (`STAGE2_PREREGISTRATION.md`): using VIX1D as the option price, does a Kalshi filter pick out the releases where selling loses? **Verdict: no evidence that Kalshi improved the decision** (50 releases).

Both plans log every deviation with its date and whether results had been seen.

## Reproduce every headline number

Works on Windows, macOS and Linux with Python 3.12 or later (tested on 3.14). No API key and no downloads are needed.

```bash
pip install -r requirements.txt
python run_all.py
```

`run_all.py` reruns the Stage 1 test, the Stage 2-lite test and the track reporting additions (out-of-sample split, pricing sensitivity, count of every test run) from the per-release files in `derived/`. It then checks 100 headline numbers against `derived/headline_numbers.json` and writes the summaries and figures to `reproduced/`:

| Output | Contents |
| --- | --- |
| `reproduced/summary.md` | Stage 1: primary model, decision conditions, robustness, mechanism, placebo |
| `reproduced/stage2_summary.md` | Stage 2-lite: event premium, decision checks, every strategy |
| `reproduced/track_summary.md` | Out-of-sample split, Student-t pricing sensitivity, test count |
| `reproduced/stage2_equity_oos.png` | Strategy equity curves with the out-of-sample period shaded |

## Committed derived data

| File | Contents |
| --- | --- |
| `derived/event_table.csv` | One row per CPI release: Kalshi distribution statistics, surprises, liveness, SPY returns (prior close to 09:35 and to the close), VIX |
| `derived/distributions.json` | Kalshi probability distributions per release and snapshot |
| `derived/releases.csv` | Release dates, Kalshi events, actual prints and snapshot times |
| `derived/vix1d_release_eves.csv` | VIX1D close on the trading day before each release (Cboe) |
| `derived/headline_numbers.json` | The numbers `run_all.py` must reproduce |

No raw market data or API keys are committed. Rebuilding `derived/` from the original sources is documented in `DATA.md`.

## Verify the timestamps

Each plan's SHA-256 manifest is recorded in a Solana mainnet memo transaction (`PREREG_STAMP.json` and `PREREG_STAMP.stage2.json`). To check them against the chain (needs internet, no key):

```bash
python timestamp_solana.py verify                  # Stage 1
python timestamp_solana.py verify --label stage2   # Stage 2-lite
```

Files changed after a stamp are listed; each change is either a data-plumbing fix committed with a test or a logged deviation.

## Files

| File | Purpose |
| --- | --- |
| `PREREGISTRATION.md`, `STAGE2_PREREGISTRATION.md` | The frozen plans, with dated deviations and disclosures |
| `run_all.py` | Reproduces every headline number from `derived/` |
| `kalshi_fetch.py`, `massive_fetch.py` | Data download (see `DATA.md`) |
| `build_dataset.py` | Builds `event_table.csv` and `distributions.json` |
| `sensitivity_test.py` | Stage 1 pre-registered test |
| `stage2_lite.py` | Stage 2-lite: VIX1D download and pre-registered test |
| `track_report.py` | Out-of-sample split, pricing sensitivity, test count (reported only) |
| `report.py`, `report_stage2.py` | HTML dashboards |
| `power_sim.py` | Power and false-positive rate of the Stage 1 decision rule |
| `make_synthetic.py` | Synthetic data with a planted effect, for dry runs |
| `test_offline.py`, `test_stage2.py` | Offline checks |
| `timestamp_solana.py` | Solana timestamping and verification |
| `cpi_release_dates.csv` | Official BLS CPI release calendar |
| `CLAUDE.md` | Guardrails and checklist used with Claude Code |

## Limitations

- About 50 releases give limited power: "NO-GO" and "no evidence" do not prove the effects are absent.
- Stage 1's liveness measure, a ladder standard deviation, partly reflects how widely Kalshi lists strikes.
- Stage 2-lite uses VIX1D and a normal-distribution butterfly instead of traded option quotes. Repriced under fatter-tailed Student-t distributions, the always-sell strategy's small profit disappears (`reproduced/track_summary.md`).
- The out-of-sample split was defined after the full-sample results were seen, following the competition track's mechanical rule.
