# Pilot robustness tables

Key estimates across three cleaning specifications. Stars denote one-sided
p < 0.10 / 0.05 / 0.01 (\* / \*\* / \*\*\*). n is participants at rho = 0.6 / 0.7.
Specifications: (1) as-is; (2) no outliers; (3) no outliers and participant MAE <= 30.

## Two-lag specification

| Estimate | rho | (1) As-is | (2) No outliers | (3) No outliers, MAE <= 30 |
|---|---|---|---|---|
| n | --- | 20 / 17 | 20 / 17 | 17 / 14 |
| Baseline overreaction (mean excess persistence) | 0.6 | 0.115 (p=.126) | 0.101 (p=.076\*) | 0.202 (p=.0002\*\*\*) |
| | 0.7 | -0.017 (p=.553) | -0.094 (p=.970) | -0.045 (p=.892) |
| Post-switch gamma (matching-train effect) | 0.6 | 0.153 (p=.081\*) | 0.085 (p=.166) | 0.106 (p=.003\*\*\*) |
| | 0.7 | 0.691 (p=.161) | 0.080 (p=.108) | -0.007 (p=.566) |
| Reinstatement gamma_0 (switch-point effect) | 0.6 | 0.132 (p=.172) | 0.046 (p=.349) | 0.107 (p=.026\*\*) |
| | 0.7 | 0.569 (p=.160) | 0.090 (p=.083\*) | 0.009 (p=.431) |
| Reinstatement gamma_1 (decay over p_t) | 0.6 | 0.330 (p=.917) | -0.006 (p=.396) | -0.009 (p=.345) |
| | 0.7 | -0.049 (p=.247) | -0.008 (p=.343) | -0.002 (p=.464) |
| Persistence interaction (gamma_0.7 - gamma_0.6) | --- | 0.538 (p=.221) | -0.005 (p=.519) | -0.113 (p=.976) |

## Three-lag specification

| Estimate | rho | (1) As-is | (2) No outliers | (3) No outliers, MAE <= 30 |
|---|---|---|---|---|
| n | --- | 20 / 17 | 20 / 17 | 17 / 14 |
| Baseline overreaction (mean excess persistence) | 0.6 | 0.115 (p=.126) | 0.101 (p=.076\*) | 0.202 (p=.0002\*\*\*) |
| | 0.7 | -0.017 (p=.553) | -0.094 (p=.970) | -0.045 (p=.892) |
| Post-switch gamma (matching-train effect) | 0.6 | 0.181 (p=.061\*) | 0.089 (p=.132) | 0.115 (p=.002\*\*\*) |
| | 0.7 | 0.707 (p=.158) | 0.076 (p=.109) | -0.006 (p=.564) |
| Reinstatement gamma_0 (switch-point effect) | 0.6 | 0.151 (p=.145) | 0.054 (p=.324) | 0.108 (p=.023\*\*) |
| | 0.7 | 0.631 (p=.161) | 0.086 (p=.080\*) | 0.009 (p=.432) |
| Reinstatement gamma_1 (decay over p_t) | 0.6 | 0.325 (p=.915) | -0.011 (p=.317) | -0.008 (p=.351) |
| | 0.7 | -0.082 (p=.217) | -0.004 (p=.408) | -0.000 (p=.494) |
| Persistence interaction (gamma_0.7 - gamma_0.6) | --- | 0.526 (p=.229) | -0.013 (p=.553) | -0.121 (p=.986) |
