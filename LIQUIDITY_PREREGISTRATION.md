# Liquidity measurement pre-registration: what would the CPI-eve butterfly cost to trade, and how much could be traded?

Written on 2026-10-03, after both Stage 1 and Stage 2-lite results were seen, and before any SPXW quotes or volume for release eves were downloaded. Commit this file, stamp it with `python timestamp_solana.py stamp --network mainnet --label liquidity`, and only then run `python liquidity_measure.py fetch`. Any later change goes under Deviations with a date and reason.

## Why

Stage 2-lite assumed an entry cost of 3% of the straddle value, with 6% as a stress, and had no measured capacity. This measurement replaces both assumptions with real quotes and volume. It is a measurement, not a test of any strategy: it computes no returns, fetches no release-day prices, and cannot change either verdict.

## Data

- **Massive SPXW option quotes** (top-of-book bid, ask and sizes) and **daily option volume**, for contracts expiring on each release day, on the trading day before the release (the release eve).
- **Sample:** the 50 Stage 2-lite releases (VIX1D available on the eve, 2022-06-10 onward), with the two 2025 shutdown releases already excluded.
- **Index level for centring the strike search:** 10 × SPY's close on the eve (from the Stage 1 market data).

## Procedure (all times US Eastern, on the release eve)

1. **At-the-money strike.** Among strikes within 40 points of 10 × SPY's close, in 5-point steps, take the last two-sided quote at or before 16:00 for the call and the put; the ATM strike is the one where the call and put mids are closest.
2. **Wings.** Wing distance = 2 × the ATM straddle mid at 16:00, rounded to the nearest 5 points (at least 5). The butterfly is short the ATM call and put and long the call and put at ATM ± the wing distance, the same structure as Stage 2-lite.
3. **Snapshots.** For each of the four legs, the last two-sided quote at or before each minute from 15:45 to 16:15 (31 marks). A release is usable if every leg has valid quotes at 20 or more marks.
4. **Volume.** Each leg's total volume on the eve, from Massive daily bars.

## Measures (per release, median across marks; then across releases)

- **Entry cost:** the sum of the four half-spreads (selling the straddle at the bid, buying the wings at the ask), in index points and as a share of the straddle mid. Compared with the 3% assumption and the 6% stress.
- **Depth:** the smallest top-of-book size among the four legs (bid size for sold legs, ask size for bought legs).
- **Capacity:** at most 10% of the thinnest leg's eve volume, in butterflies; capital = butterflies × maximum loss per butterfly ($100 × (wing distance − credit at mids)) ÷ 1% risk.

## Reporting

Median and 90th percentile of the entry cost; the share of eves where it exceeds 3% and 6%; median depth; median and minimum capacity in contracts and dollars. Results go in `results/liquidity_results.json` and the note's Liquidity and capacity section, labelled as measured after the main results were known.

## What this cannot do

- It does not re-run Stage 2-lite with measured costs or compute any butterfly return; doing so would be a new analysis after the results were seen.
- Top-of-book quotes show only the first price level; larger orders would walk the book. The 10% volume cap is a conventional participation limit, not a measured market impact.
- Volume is for the whole eve, not the 15:45 to 16:15 window.

## Disclosures

- Before this plan was written, the code was dry-run on two ordinary evenings that are not release eves (2024-06-20 and 2023-03-02) to check the data format and the pipeline. No release-eve options data had been downloaded.
- The project's rule that paid options data is used only after a Stage 1 GO is set aside for this measurement only, because it computes no returns; this is logged as a deviation in `CLAUDE.md`.

## Deviations

None yet.
