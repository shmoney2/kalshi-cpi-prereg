# Pre-registration: does Kalshi's Fed "liveness" predict CPI sensitivity?

Commit this file and the code to version control **before** downloading any real data, then timestamp the commit on Solana with `make stamp`. That writes a hash of this file and the code into a public transaction, so anyone can verify the plan existed before the analysis. Put the commit hash and the transaction link in the competition write-up. Any later change goes in the Deviations section with a date and reason.

## Question

When Kalshi shows the next FOMC decision as genuinely uncertain, does the S&P 500 react more strongly to a CPI surprise?

## Why it matters

An announcement's market impact depends on how much news it releases and how sensitive the market is to that news (the decomposition in Knox, Londono, Samadi and Vissing-Jorgensen, "Equity Premium Events", Federal Reserve Board). Kalshi's CPI ladders measure the first part. This test asks whether Kalshi's Fed ladders measure the second. If they don't, the Kalshi overlay in the options strategy loses its economic justification.

## Data

- **Sample:** every CPI release with usable Kalshi core-CPI and Fed ladders at the snapshot times, from first availability through the latest release (expected: mid-2022 onward, about 50 releases).
- **Kalshi:** public API. Core and headline CPI month-over-month ladders; the Fed target-rate ladder for the first FOMC decision after the release. Contracts settled before about 2023 carry no strike fields; their threshold is read from the ticker suffix (`-T0.4` means "above 0.4"), a rule that agrees with the explicit strike on every newer contract.
- **Snapshots (US Eastern):** t0 = 15:45 on the previous trading day; pre = 08:25 on release day; post = 10:00 on release day (Fed ladder only).
- **Actual prints:** Kalshi's settlement value, which is the first-print figure markets reacted to.
- **Market data:** the S&P 500 is measured with SPY, the S&P 500 ETF: daily closes and its 09:35 level on release days from Massive (formerly Polygon.io) daily and minute bars. The available Massive plan does not include index data, so SPY replaces the index; the switch was made before the freeze and before any release-day prices were downloaded. SPY's cash dividend is added back to its price on each ex-dividend date. VIX daily close comes from Cboe's free VIX history.

## Variables

- **S, surprise:** core CPI actual minus Kalshi's mean expectation at 08:25 (t0 if 08:25 is missing), in percentage points.
- **L, liveness:** standard deviation of Kalshi's distribution for the next meeting's upper bound at t0, in basis points, standardized across the sample.
- **r_open:** 100 × ln((SPY level at 09:35 ET on release day + D) ÷ its close on the previous trading day), where D is SPY's cash dividend if release day is an ex-dividend date and 0 otherwise. The 09:35 level is the close of the 09:34 minute bar (the open of the 09:35 bar if that is missing). Close-to-close returns used in the robustness checks and placebo add D back in the same way. CPI prints at 08:30, before the cash open, so this window captures the reaction while excluding most of the trading day. The 09:35 level is used instead of the official 09:30 open because the official opening value is partly computed from stale prices of stocks that have not yet traded. If minute data are unavailable, the official open is used and the dashboard reports how many releases used each.
- **VIX:** close on the previous trading day, standardized. It is known before the 08:30 print.
- **Price rule:** last trade within 24 hours before the snapshot; otherwise the bid-ask midpoint if the spread is at most $0.10; otherwise the strike is dropped. Survival curves are made monotone with isotonic regression. A ladder with fewer than 4 usable strikes counts as missing. Mass above the top strike sits one grid step above it.

## Hypotheses

- **H1 (primary, decides go/no-go):** r_open = a + b·S + c·(S×L) + d·L + e·VIX + error, with **c < 0**. A hot print should hurt stocks more when the next meeting is live.
- **H2 (mechanism, reported):** the change in Kalshi's expected fed funds rate from 08:25 to 10:00 (bp) = a + b·S + c·(S×L) + d·L + error, with c > 0. CPI should move Fed odds more when the meeting is live.
- **H3 (sign-free, reported):** |r_open| on |S|, |S|×L, L and VIX, with c > 0.
- **H4 (consensus gap, reported if consensus data are obtained):** |actual − consensus| on |Kalshi median at 08:25 − consensus|, with a positive slope.

## Inference

HC3 standard errors with one-sided tests; within-calendar-year permutation of L (10,000 draws, seed 20261002); 90% wild-bootstrap interval (9,999 draws); leave-one-out fits; a fit excluding 2022.

## Decision rule

**GO** (proceed to the options-data stage with liveness as a pre-specified input) only if all of these hold:

1. c < 0.
2. HC3 one-sided p < 0.10.
3. Permutation one-sided p < 0.10.
4. c keeps its sign in at least 90% of leave-one-out fits.
5. c < 0 when 2022 is excluded.

With fewer than 25 usable releases there is no verdict. Anything else is **NO-GO** for the Fed-liveness input.

The 0.10 level is a screening threshold for an expensive next step, not a claim of proof. Because all five conditions must hold, the simulated false-positive rate of the full rule is about 5–6%.

## Power

From `power_sim.py` with 57 releases. The effect ratio is SPX sensitivity at +1 SD liveness divided by sensitivity at −1 SD; 1.0 means no effect.

| Effect ratio | P(GO), optimistic: −8% per pp, 0.5% noise | P(GO), pessimistic: −5% per pp, 0.7% noise |
| --- | --- | --- |
| 1.0 (no effect) | 0.06 | 0.06 |
| 1.5 | 0.47 | 0.22 |
| 2.0 | 0.80 | 0.36 |
| 3.0 | 0.94 | 0.72 |

A NO-GO therefore does not show the mechanism is absent: effects smaller than roughly a doubling of sensitivity will often be missed. After the data are assembled, `power_sim.py --calibrate` may be run to replace the assumed noise level with the realized one; it does not change the decision rule.

## Robustness (reported, never used for the decision)

Headline instead of core surprise; close-to-close returns with FOMC-day releases dropped; the sign-free version; liveness measured as 1 − modal probability or as entropy; no VIX control; surprise measured at t0; returns scaled by the VIX-implied daily move; a placebo regressing ordinary-day volatility on liveness.

## What happens next

- **GO:** liveness enters the options-stage forecasting model as a pre-specified input, alongside the option price and Kalshi CPI uncertainty, with no further tuning.
- **NO-GO:** the Fed overlay is reported as a tested, negative (or underpowered) result. The project continues with the consensus-gap input and the default event-premium strategy.

## Disclosures before the freeze

- **2026-10-03, thinkorswim:** while checking whether thinkorswim could supply futures minute data for an 08:20–08:50 reaction window, the author viewed the market reaction around 08:30 ET on 2022-06-10 (the May 2022 CPI release) in an OnDemand replay and saw a large drop. That release has no Kalshi core-CPI ladder, so it is outside the primary sample. The futures window was then rejected because the data could not be exported with verifiable timestamps.
- **2026-10-03, access checks:** the Massive access checks requested SPY minute bars for 2022-06-10 and 2024-06-12 (both CPI release days) SPY daily bars for 2022-06-01 to 2022-06-15, and SPXW option minute bars and quotes for 2024-06-11. Only the number of rows returned was printed; no prices were viewed.

## Deviations

- **2026-10-03, reporting additions required by the competition track rules (full-sample real results had been seen).** No decision rule, threshold, variant or sample changes; the GO/NO-GO verdict stands as computed. Added, reported only: (1) an out-of-sample split by the track's mechanical rule, the most recent 20% of the sample's date span (the track rule takes the shorter of 20% of the span and two years; 20% of this roughly four-year span is under two years, so 20% binds), with the primary model fitted separately in each period; the out-of-sample period holds about 10 releases, too few to support inference. The split was defined after the full-sample results were seen, but it follows the track's fixed rule rather than any choice made here. (2) A table counting every test, variant, strategy and cost level run across both stages, including data diagnostics. (3) A reproduction script, `run_all.py`, that recomputes every headline number from committed per-release derived files.
