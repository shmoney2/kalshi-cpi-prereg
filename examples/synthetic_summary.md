# Fed-liveness sensitivity test

Sample: 57 CPI releases with complete data (2022-01-12 to 2026-09-11).

## Primary result (H1)

| Quantity | Value |
| --- | --- |
| SPX move per +0.1pp core surprise, meeting settled (-1 SD liveness) | -0.66% |
| SPX move per +0.1pp core surprise, average liveness | -0.91% |
| SPX move per +0.1pp core surprise, meeting live (+1 SD liveness) | -1.16% |
| Interaction c (per 1 SD of liveness, % per pp) | -2.496 (HC3 SE 0.822) |
| One-sided p, HC3 | 0.002 |
| One-sided p, within-year permutation of liveness (10,000 draws) | 0.001 |
| 90% wild-bootstrap interval for c | [-3.398, -1.594] |
| Share of leave-one-out fits with the same sign | 1.00 |
| c excluding 2022 | -3.968 |
| R-squared | 0.81 |

**Verdict: GO: liveness predicts CPI sensitivity under every pre-registered condition.**

## Robustness (reported, not used for the decision)

| Variant | n | c | HC3 SE | one-sided p |
| --- | --- | --- | --- | --- |
| Headline instead of core surprise | 57 | -1.619 | 1.343 | 0.117 |
| Close-to-close return (FOMC-day releases dropped) | 57 | -0.787 | 2.362 | 0.370 |
| Sign-free: |return| on |surprise| (expects c > 0) | 57 | 2.166 | 1.479 | 0.075 |
| Liveness = 1 - modal probability | 57 | -2.937 | 0.653 | 0.000 |
| Liveness = entropy | 57 | -3.078 | 0.662 | 0.000 |
| No VIX control | 57 | -2.600 | 0.751 | 0.001 |
| Surprise measured at t0 instead of 08:25 | 57 | -2.518 | 0.820 | 0.002 |
| Return scaled by VIX-implied daily move | 57 | -1.621 | 1.632 | 0.162 |

## Mechanism (H2)

Change in Kalshi's expected fed funds rate (08:25 to 10:00 ET, bp) on surprise x liveness, n = 57: c = 4.092 (HC3 SE 5.121), one-sided p = 0.214. Average response: 3.72 bp per +0.1pp surprise.

## Placebo: liveness and ordinary-day volatility

Mean absolute SPX move over the 5 trading days before t0, on liveness and VIX (n = 57): liveness coefficient 0.013 (HC3 SE 0.032). A large positive value means liveness partly tracks general volatility, so read H1 with care.

## Most influential releases

| Release | c without it | shift |
| --- | --- | --- |
| 2022-10-12 | -3.102 | 0.606 |
| 2022-08-12 | -2.756 | 0.261 |
| 2025-08-13 | -2.752 | 0.256 |
| 2025-05-13 | -2.308 | -0.187 |
| 2025-03-12 | -2.324 | -0.172 |

Figure: sensitivity_by_liveness.png
