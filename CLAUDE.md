# CPI × Fed-liveness study

## What this project is

Stage 1 of a systematic trading competition entry. The strategy sells the CPI event premium in S&P 500 options with defined risk and uses Kalshi prediction markets to decide when to stand aside. This stage is a pre-registered test of the crucial link: does Kalshi's uncertainty about the next FOMC decision ("liveness") predict how strongly the S&P 500 reacts to CPI surprises? Stage 2, which uses options data, starts only if this stage says GO.

Read `PREREGISTRATION.md` before changing anything. The competition caps the evidence score if judges find lookahead or tuning on out-of-sample data, so these rules matter.

## Ground rules

- `PREREGISTRATION.md`, `CONFIG` in `build_dataset.py`, and the settings block at the top of `sensitivity_test.py` are frozen once committed. Never change them after real results exist. If a change is unavoidable, log it under Deviations in `PREREGISTRATION.md` with the date, the reason, and whether real results had been seen.
- Never adjust thresholds, variants or the sample to improve results, even if asked casually. Explain the rule and log any requested change as a deviation instead.
- Data-plumbing fixes are allowed at any time: field names, pagination, rate limits, ticker discovery, date matching. Add a check to `test_offline.py` for every parsing fix.
- Never print, log or commit API keys. Keys live in `.env`, which is gitignored.
- Never put a Solana keypair inside the project folder, print it, or commit it. Re-stamping is only allowed after logging a deviation, and `timestamp_solana.py` refuses otherwise.
- Raw downloads go in `data/` and outputs in `results/`; both are gitignored.

## Commands

| Command | What it does |
| --- | --- |
| `make test` | Offline checks of parsing and distribution building |
| `make synth` | Full pipeline on synthetic data, ending in `results_synth/report.html` |
| `make access` | Lists what the Massive plan can reach |
| `make kalshi-probe` | Prints raw Kalshi responses and matching series tickers |
| `make market` | SPX and VIX daily data from Massive (run before `make kalshi` for the trading calendar) |
| `make kalshi-smoke` | Kalshi download for 3 releases |
| `make kalshi` | Full Kalshi download, resumable, about an hour |
| `make market-935` | Re-runs the market download to add 09:35 levels on release days |
| `make build`, `make analyze`, `make report` | Event table, pre-registered test, dashboard |
| `make keygen`, `make airdrop` | Create a Solana keypair outside the project; get free devnet SOL |
| `make stamp-test`, `make stamp` | Practice timestamp on devnet (writes nothing); the real one on mainnet |
| `make verify-stamp` | Re-hash the frozen files and check them against the on-chain record |
| `make real` | All real-data steps in order |

Without `make` (for example on Windows), run the Python commands listed in the `Makefile`.

## First-session checklist

Work through these with the user, one at a time, and stop to report after each step. The order matters: everything that could change the plan happens before the plan is frozen, and no real data are downloaded until it is.

1. **Set up.** Create a virtual environment, install `requirements.txt`, run `make test`.
2. **Dry run.** Run `make synth` and open `results_synth/report.html` with the user to confirm everything works.
3. **Check access.** Copy `.env.example` to `.env` and ask the user to paste `MASSIVE_API_KEY` into it themselves. Run `make access` and summarize what the plan covers: index data, minute bars, futures, and Stage 2 option quotes.
4. **Check Kalshi.** Run `make kalshi-probe`. Compare the raw fields with what `kalshi_fetch.py` expects (market fields `strike_type`, `floor_strike`, `cap_strike`, `close_time`, `expiration_value`; candlestick fields `yes_bid`, `yes_ask`, `price`, each with `close` or `close_dollars`). Fix mismatches and add tests. From `--list-series`, agree the legacy series tickers for 2021-2024 contracts with the user.
5. **Decide the reaction window.** If the plan includes futures minute data, discuss switching the reaction measure to S&P 500 futures from 08:20 to 08:50 ET, which cuts overnight noise. Any change to the plan happens now, in `PREREGISTRATION.md` and the code, before the freeze.
6. **Freeze.** `git init` if needed, commit everything, and tell the user the commit hash.
7. **Timestamp on Solana.** Ask the user where their Solana keypair is (or run `make keygen`, which writes one outside the project). Run `make airdrop` and `make stamp-test` for a free devnet practice run, then `make stamp` for the real mainnet timestamp. Commit `PREREG_MANIFEST.txt` and `PREREG_STAMP.json`, and give the user the explorer link.
8. **Download.** Run `make market` and `make kalshi-smoke`, check the release dates in `data/releases.csv` against the BLS CPI schedule, then run the full `make kalshi` and `make market-935`.
9. **Build and review coverage.** Run `make build` and review `results/event_table.csv` with the user before running the test.
10. **Run the test.** Run `make analyze`, `make report` and `make verify-stamp`. Explain the verdict in plain language, including the power caveat in `PREREGISTRATION.md`: a NO-GO does not prove the effect is absent.

## Data facts

- **Kalshi:** public market data needs no key. Base URL `https://api.elections.kalshi.com/trade-api/v2`. Markets settled before the historical cutoff are only available from the `/historical/...` endpoints. Current tickers carry a `KX` prefix (`KXCPI`, `KXCPICORE`, `KXFED`); older contracts may use legacy series.
- **Massive (formerly Polygon.io):** base URL `https://api.massive.com`, bearer-token auth. SPX and VIX index data need a paid Indices tier. Historical option quotes need the Options Advanced tier (records start March 2022); lower Options tiers include minute aggregates. Index options use the bare symbol in reference endpoints (`SPX`) and `I:SPX` in snapshots.
- **VIX fallback:** Cboe's free `VIX_History.csv`.
- **Webull:** not used for research data. It may matter later for paper trading.
- **Solana:** used only to timestamp the pre-registration. The memo transaction holds the SHA-256 of `PREREG_MANIFEST.txt`, which lists a hash for every frozen file. A mainnet stamp costs about 0.000005 SOL; devnet is free but can be reset, so only mainnet counts.

## Data audit before trusting results

- Releases delayed by the 2025 government shutdown can land on unusual dates. Pin dates with `--cpi-dates` if anything is off.
- Releases with fewer than 4 usable strikes are dropped automatically. Report how many.
- Spot-check one release by hand on Kalshi's website: the ladder, the expected value, and the actual print.
- Releases where the FOMC decides on CPI day are flagged `fomc_same_day`. The primary test is unaffected because it measures to 09:35.

## Stage 2 (only after GO)

Write and commit a Stage 2 pre-registration before downloading any options data. The plan: build an event-day dataset of SPXW straddle and iron-butterfly prices from Massive quotes at 15:45 ET on the day before each release, settle at the release-day close, then test whether Kalshi inputs improve forecasts of those payoffs beyond the option prices themselves. Evaluate the long and short sides separately, with real bid-ask costs.
