# Analytics, ML and Optimization

## Metric contract

Each metric declares ID, label, formula, unit, boundary, source, grain, aggregation, missing-data rule, quality threshold, version and owner. Electricity-to-energy uses `1 kWh = 3.6 MJ`; costs use a versioned tariff, never a hard-coded UI value.

Initial daily metrics: heat/electricity/CO₂/irrigation/drain per m²; total energy; drain ratio; internal temperature/RH/humidity-deficit compliance minutes; setpoint deviation; peak/off-peak electricity share; anomaly minutes. Yield and economic values are explicitly contextual.

## Models

- EnB: daily Elastic Net with heating-degree/external temperature, radiation, lighting duration and crop-age candidates. Feature inclusion requires domain rationale, stable availability, temporal cross-validation and residual diagnostics. GAM is a challenger where nonlinearity materially improves validation.
- Forecast: LightGBM quantile models (P10/P50/P90) for 1 h and 24 h heat/electricity and internal temperature/humidity deficit. Compare against seasonal-naive/last-value baselines using rolling-origin MAE, RMSE, pinball loss and interval coverage.
- Anomaly: standardized forecast residuals with robust median/MAD thresholds, persistence/debounce, plus Isolation Forest as a labelled secondary signal. Alerts merge adjacent windows and report contributors; no automatic causal label.
- Drift: input PSI/missingness and rolling error; warning triggers review, not silent retraining.

ML-01: temporal splits precede feature fitting; no future-filled/as-of leakage. Promotion requires improvement over naive baseline, acceptable interval coverage, reproducible artifact, model card and approval. Otherwise deploy the naive baseline.

### Promotion gates

Use expanding-window backtesting with at least four ordered folds when coverage permits; the final 20% of time is a locked test set. Training code, features and hyperparameters are versioned and deterministic from the dataset version.

| Output | Minimum gate versus baseline |
|---|---|
| P50 forecast | ≥5% lower MAE on locked test and no fold >20% worse |
| P10/P90 interval | empirical coverage 75–95% for nominal 80% interval; report width |
| EnB | adjusted R²/MAE reported, stable coefficient signs where domain-constrained, residual time/weather bias reviewed |
| Seeded anomaly detector | recall ≥90%, false-positive windows ≤5%, median detection delay ≤15 min |
| Scenario surrogate | candidate passes holdout error gate for every optimized target and no extrapolation block |

Statistical uncertainty must reflect the small sample; confidence intervals use block bootstrap where serial correlation exists. Performance is segmented by season/day-night/lighting state. If gates conflict, safety and calibration take precedence over average accuracy. Model cards record intended use, exclusions, data window, features, metrics by segment, limitations, approvers and rollback artifact.

### Leakage and causality controls

- Production/crop variables are joined only when their measurement would have been available at the replay cursor.
- Daily totals cannot predict an earlier intraday point; forecasts use partial-day features explicitly marked as such.
- Setpoint and actuator associations may be confounded by operator/weather decisions; optimization outputs are counterfactual model estimates, not treatment effects.
- No model trains on synthetic anomalies used for final detection acceptance unless a separate untouched fixture set exists.

## Scenario optimizer

The approved forecast surrogate evaluates observed controllable setpoints only. Differential evolution searches bounds limited to historical 5th–95th percentiles and configured rate-of-change limits. Objective minimizes versioned energy cost plus penalties for temperature, RH/humidity deficit, CO₂ and light-integral constraints. Weather is fixed per scenario; uncertainty is propagated from prediction quantiles.

Every result returns baseline and candidate inputs, expected absolute/percent delta, P10/P50/P90, constraint margins, extrapolation score, assumptions and model/data/constraint versions. Extrapolated or infeasible scenarios are blocked. Wording is “model-estimated association,” never guaranteed savings or causal effect.

Initial hard constraints are configuration, not inferred constants: permitted temperature, RH/humidity-deficit, CO₂ and daily-light-integral ranges; setpoint 5th–95th percentile bounds; maximum change per 5-minute step; and minimum confidence/coverage. Until an Ontario operator approves site-specific values, scenarios carry `demo_constraints=true` and cannot be exported as operating instructions.
