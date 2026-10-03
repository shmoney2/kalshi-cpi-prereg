# Stage 2-lite pre-registration: does Kalshi help decide when to sell CPI-day volatility?

Written after the Stage 1 verdict and before any VIX1D data are downloaded. Commit this file, stamp it with `make stamp-stage2`, and only then run `make stage2-fetch`. Any later change goes under Deviations with a date and reason.

## Question

Selling CPI-day volatility earns a premium on average. Do Kalshi's signals identify the releases where selling loses, better than chance and better than the option price itself?

## Data

- **VIX1D**, Cboe's 1-Day Volatility Index, at its close on the trading day before each release. From 4:00 to 4:15 p.m. it is calculated using only the next-day SPX expiry, so on a release eve it prices the release-day options. Source: Massive `I:VIX1D`, or Cboe's free history file. Values before its April 2023 launch were back-calculated by Cboe from historical option prices; the series starts in May 2022.
- **From Stage 1's event table:** the S&P 500 return from the prior close to the release-day close, measured with SPY as in Stage 1 (the Massive plan has no index data; SPY's cash dividend is added back on ex-dividend dates), Kalshi's core CPI uncertainty and Fed liveness at t0, and VIX at the prior close (Cboe's free history).
- **Sample:** every release with VIX1D and returns available. The two releases affected by the 2025 government shutdown are excluded, as in Stage 1, and listed in `EXCLUDED_RELEASES` in `stage2_lite.py`: September 2025 CPI (scheduled 2025-10-15, published 2025-10-24; Kalshi's markets closed on the original date, so no ladder traded at the snapshot times) and October 2025 CPI (scheduled 2025-11-13, never published).

## Measures

- **Implied daily move:** σ = VIX1D ÷ √252, in percent.
- **Move ratio:** |r| ÷ σ, the realized move in implied standard deviations.
- **Variance premium:** σ² − r². Positive means sellers earned money on that release.
- **Butterfly proxy:** a short at-the-money straddle with wings two implied moves away (implied move = σ√(2/π)), priced from a normal distribution with standard deviation σ. Entry cost is assumed at 3% of the straddle value, with 0% and 6% also reported. P&L = credit − min(|r|, wing distance). Each release risks 1% of capital.

## Strategies

Every rule uses only earlier releases. The first 6 releases are traded by every strategy.

- **Always sell.**
- **Kalshi filter (primary):** skip a release when the Kalshi input is above the two-thirds point of all earlier values. The input is Fed liveness if Stage 1 said GO, and core CPI uncertainty otherwise.
- **Kalshi news × sensitivity (variant):** the same rule on CPI uncertainty × liveness.
- **CPI uncertainty IQR (reported only):** the same rule on the interquartile range of Kalshi's core CPI distribution at t0, which is less sensitive to ladder width than the standard deviation. It does not enter the decision rule.
- **Fed liveness (reported only):** the same rule on Kalshi's Fed liveness at t0. It does not enter the decision rule.
- **Option price only:** the same rule on VIX1D.
- **VIX only:** the same rule on VIX.

## Decision rule

"Kalshi improved the decision" requires all three:

1. The mean variance premium of releases the Kalshi filter skips is below that of releases it keeps, after the burn-in.
2. Skipping the same number of post-burn-in releases at random does at least as well in fewer than 10% of 10,000 draws (seed 20261003).
3. The releases the Kalshi filter keeps have a higher mean variance premium than those the option-price-only filter keeps.

Otherwise the result is "no evidence that Kalshi improved the decision".

## Why the variance premium decides

VIX1D squared is the options market's fair variance for the day, so σ² − r² compares price with outcome without a pricing model. Butterfly returns depend on a normal approximation and an assumed cost, so they illustrate a tradeable version but don't decide anything.

## Limitations, stated in advance

- About 50 releases, so power is limited, as in Stage 1.
- These are proxies, not traded prices: there are no actual bid-ask quotes, and real straddles can be priced differently from the normal approximation because of skew and fat tails.
- The close-to-close window includes the whole release day, not just the CPI reaction.
- This plan was written after seeing the Stage 1 verdict. The verdict only selects which Kalshi input is primary; both CPI uncertainty and Fed liveness are reported.
- Release-day returns were computed and partly shown in Stage 1: the close-to-close robustness check reported a regression result, and the Stage 1 report shows each release's move to 09:35. VIX1D had not been downloaded, so the variance premium of any release was unknown when this plan was frozen.
- The primary input, CPI uncertainty, is the standard deviation of Kalshi's core CPI ladder. Stage 1 found that a ladder standard deviation can reflect how widely Kalshi lists strikes (far strikes quoted 0.00/0.01 add tail mass) as well as genuine uncertainty. The interquartile-range variant is reported for that reason.

## Deviations

- **2026-10-03, reporting additions required by the competition track rules (full-sample real results had been seen).** No decision rule, setting, strategy or sample changes; the verdict stands as computed. Added, reported only: (1) an out-of-sample split by the track's mechanical rule, the most recent 20% of the sample's date span (the track rule takes the shorter of 20% of the span and two years; 20% of this roughly four-year span is under two years, so 20% binds). For each strategy, in-sample and out-of-sample results at 3% and 6% entry costs: annualized return (12 releases a year), annualized volatility, Sharpe ratio, maximum drawdown, turnover (option premium traded per year as a multiple of capital) and trade count, plus one equity-curve figure with the out-of-sample period shaded. Filters keep their expanding-window rule, so out-of-sample decisions use only earlier releases. The split was defined after the full-sample results were seen, but it follows the track's fixed rule. (2) A post-hoc pricing sensitivity: the butterfly repriced under Student-t distributions with 6 and 4 degrees of freedom, scaled to VIX1D's variance, reporting always-sell's mean and total return. (3) A table counting every test, variant, strategy and cost level run across both stages. (4) The reproduction script `run_all.py`.
- **2026-10-03, risk reporting additions (full-sample real results had been seen).** No decision rule, setting, strategy or sample changes. Added, reported only, for always-sell at 3% entry cost: (1) factor exposure, an OLS regression with HC3 errors of per-release returns on SPY's release-day return, its absolute value, the release-day VIX change and VIX1D on the release eve; (2) regime results, by year (2022 vs 2023 to 2026) and by VIX at the prior close (above vs at or below its sample median); (3) stress scenarios: the worst historical releases, a single move of 3 to 5 implied standard deviations at the median release, and runs of consecutive maximum losses against the operating rules (halve size at a 6% drawdown, stop at 10%); (4) explicit exposure limits. All use data already downloaded; the release-day VIX close comes from Cboe's file used in Stage 1.
