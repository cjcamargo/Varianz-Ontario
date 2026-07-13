# Energy baseline energy-baseline-2.1.0

This artifact serves the Wageningen reference demo only. It predicts daily heat
intensity from weather, heating demand, radiation, lighting and crop age.

- Validation: four expanding walk-forward folds and a locked final 20% block.
- Promotion: Elastic Net must improve MAE by at least 5% and no fold may degrade
  by more than 20%; otherwise the rolling seven-day median is served.
- Serving: select only the latest precomputed `as_of` at or before the replay cursor.
- Interpretation: associative operational evidence, not a causal savings estimate.
- Retraining: run `PYTHONPATH=services/api python scripts/build_baseline_artifact.py`,
  review the diff and model evidence, then bump the model version before release.
