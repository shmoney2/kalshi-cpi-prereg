# Fed-liveness sensitivity test

Tests whether Kalshi's odds on the next FOMC decision predict how strongly the S&P 500 reacts to CPI surprises. The hypotheses and the go/no-go rule are fixed in `PREREGISTRATION.md`. `CLAUDE.md` tells Claude Code how to run the project safely.

## Open it in Claude Code

```bash
cd fed_sensitivity
claude
```

Then ask: "Read CLAUDE.md and walk me through the first-session checklist. Stop after each step."

## Where the data come from

| Data | Source | Needs | Used for |
| --- | --- | --- | --- |
| CPI and core CPI forecast ladders, actual prints | Kalshi public API | Nothing (no key) | Surprise, CPI uncertainty |
| Odds for the next Fed meeting | Kalshi public API | Nothing | Liveness (the key input) |
| S&P 500 daily closes and 09:35 level | Massive (formerly Polygon.io), `SPY` daily and minute bars, plus SPY dividends | Stocks data in the Massive plan | Market reaction |
| VIX daily close | Massive `I:VIX`, or Cboe's free VIX history | Nothing for the Cboe file | Control |
| Economists' consensus (optional) | Bloomberg terminal or similar, saved as `data/consensus.csv` | Access | Consensus-gap test |
| Pre-registration timestamp | Solana mainnet memo transaction | About 0.000005 SOL | Proof the plan predates the results |
| SPX option quotes (Stage 2 only) | Massive options quotes | Options Advanced tier | Straddle prices |

Webull isn't needed for research; it may matter later for paper trading.

## Files

| File | Purpose |
| --- | --- |
| `PREREGISTRATION.md` | Hypotheses, variables, decision rule, power. Commit before touching real data. |
| `CLAUDE.md` | Context, guardrails and checklist for Claude Code. |
| `Makefile` | One-word commands for every step. |
| `kalshi_fetch.py` | Kalshi ladders, release dates, actual prints and snapshots. |
| `massive_fetch.py` | Plan access check; SPY and VIX data. |
| `build_dataset.py` | `event_table.csv` and `distributions.json`, one entry per CPI release. |
| `sensitivity_test.py` | The pre-registered test; writes `summary.md`, `results.json` and a figure. |
| `report.py` | `report.html`, an interactive dashboard to review results together. |
| `power_sim.py` | False-positive rate and power of the decision rule. |
| `make_synthetic.py` | Fake data with a planted effect, for testing. |
| `test_offline.py` | Offline checks of all parsing logic. |
| `timestamp_solana.py` | Timestamps the frozen plan on Solana and verifies it later. |
| `common.py` | Shared helpers. |
| `examples/` | Output from a synthetic run. |

## Run order without Claude Code

```bash
pip install -r requirements.txt
make test && make synth                  # check everything works; open results_synth/report.html
cp .env.example .env                     # paste your Massive key into .env
make access                              # what your Massive plan covers
make kalshi-probe                        # confirm Kalshi field names and find legacy tickers
git init && git add . && git commit -m "Pre-registration"
make keygen && make airdrop && make stamp-test   # free practice timestamp on devnet
make stamp                               # the real timestamp; then commit PREREG_*.{txt,json}
make market && make kalshi-smoke         # small test run; check data/releases.csv
make real                                # full run, ending in results/report.html
make verify-stamp                        # proof the plan predates the results
```

## Known limitations

- The Kalshi and Massive downloaders follow the published API specs and pass offline tests, but were not run against the live APIs. `make kalshi-probe` and `make access` show raw responses so mismatches are quick to fix.
- About 50 releases give limited power: a NO-GO is not proof the effect is absent. See `PREREGISTRATION.md`.
