# MFV2 pre-registration note (DRAFT, 2026-11-10)

Status: draft for review by the authors before data collection. Items marked **[DECIDE]** are placeholders for a choice the authors have not yet made. Committing this file before any MFV2 data are collected is what time-stamps it.

## 1. Question

Do forecasters overreact to the most recent value of a simple stationary process, and does the amount of overreaction depend on the persistence of the process? "Overreaction" is measured, as in Afrouzi et al. (2023, QJE), by the gap between the persistence implied by a participant's forecasts and the true persistence of the series they saw.

## 2. Design

- Process: AR(1), x_t = 50 + ρ(x_{t−1} − 50) + ε_t, integer-valued, bounds 10–90.
- Conditions (between participants): ρ = 0.6 and ρ = 0.8.
- The stationary SD is fixed at 10 in both conditions, so the shock SD is 8 (ρ = 0.6) and 6 (ρ = 0.8). Participants in both conditions therefore see the same distribution of values and differ only in serial dependence. This is a deliberate departure from Afrouzi et al., who fix the shock SD.
- Each participant sees one 270-value series: 20 observation rounds (they type the value shown), then 250 forecast rounds (they forecast the next value, then see it). Distractor tasks are off.
- Series were generated so that, in the observation phase, the forecast phase and overall, the mean is exactly 50, the SD is exactly 10, and the realized ρ is within 0.0005 of nominal. Seed: `20261110-n72-rho06-08-obs20-fc250-stationarysd10-10to90`. `MFV2/static/data/assignments.json` is frozen once data collection starts.
- Scoring: points = round(100 · max(0, 1 − |forecast − actual| / 8)). Bonus = $8 × score ÷ B, with B = 7,000 (ρ = 0.6) and 8,820 (ρ = 0.8), so that the expected bonus is equal across conditions. Flat fee $5.
- Forecasts are two-digit whole numbers; entries outside 10–90 or of the wrong length are refused.

## 3. Sample

- Platform: Prolific. 72 slots (36 per condition): 60 needed plus 12 spares for participants who leave.
- Target: 30 analyzable participants per condition. **[DECIDE]** the stopping rule when exclusions reduce a condition below 30 (collect replacements until 30 analyzable per condition, or stop after the 72 slots).
- **[DECIDE]** power or precision justification. In the pilot (ρ = 0.6 and 0.7), the standard error of the baseline excess was about 0.05 with 14–17 participants per cell.

## 4. Hypotheses and primary analyses

For each participant i, regress the forecast on the last observed value (OLS with intercept) over the 250 forecast rounds. The slope is the implied persistence ρ̂_i. The excess is ρ̂_i − ρ_i, where ρ_i is the realized persistence of the series participant i saw over the forecast window.

- **H1a, H1b:** the mean excess is greater than 0 at ρ = 0.6 and at ρ = 0.8 (one-sided one-sample t-tests).
- **H2:** the mean excess is larger at ρ = 0.6 than at ρ = 0.8 (one-sided Welch t-test on participants' excess).
- Primary tests use Holm correction across H1a, H1b and H2 at α = 0.05. Two-sided 95% intervals are reported for every estimate. **[DECIDE]** confirm one-sided tests and Holm.

## 5. Exclusions (primary analysis)

Participants are excluded if any of the following hold:

1. They did not complete all 250 forecasts, or failed the competency check.
2. Their MAE (forecast vs. actual, over all 250 forecasts) exceeds 2 × the MAE of always forecasting 50 on the same series. This is about 16 in both conditions.
3. A single forecast value accounts for more than 50% of their forecasts.

No trial-level exclusions in the primary analysis. These rules use only the stimuli and the participant's forecast errors. They are not conditioned on the slope outcomes.

## 6. Pre-specified robustness analyses (reported alongside the primary results)

- Strict MAE rule: exclude MAE > 1.5 × always-mean MAE (about 12).
- Trial outliers: exclude a forecast if the modified z-score (MAD-based, per participant) of its error exceeds 3.5 and it is more than 2 shock SDs from the last value (16 at ρ = 0.6, 12 at ρ = 0.8).
- A mixed-effects version of the primary regressions with a random slope by participant.
- Results with no MAE or modal-share exclusions (completion and competency only).
- Exclusion counts and reasons are reported by condition.

## 7. Exploratory (no confirmatory claims)

- Weight on the second lag in a two-lag regression, and the three-lag specification.
- Dependence of forecasts on the participant's previous forecast.
- Whether implied persistence drifts over the 250 rounds (learning).
- Response times and heaping on round numbers.

## 8. What this study does not test

Distractor tasks are off, so there is no task-context manipulation. The context-reinstatement coefficient from the pilot analysis cannot be estimated in MFV2.

## 9. Known issues from the pilot

The pilot (shock SD 20, ρ = 0.6 and 0.7, 40 recruited, 37 analyzable) used outlier and MAE ≤ 30 rules that were set after seeing the data. Those results are exploratory. In the pilot, cleaning raised the baseline excess at ρ = 0.6 from 0.115 to 0.199.

## 10. Open items before launch

Prolific completion and screenout codes; `SECRET_KEY`; a full end-to-end test of the final configuration in both conditions; the time estimate (the consent says 37 minutes on average, while the pilot-based extrapolation gives a median of about 43 minutes); `proposal.pdf` still describes the earlier design.
