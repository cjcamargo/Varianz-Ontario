from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from varianz.analytics import compute_energy_baseline_frames
from varianz.config import settings
from varianz.dataset import load_replay_frame, load_resources, source_sha256
from varianz.metrics import DATA_VERSION, DEFINITIONS_VERSION, MODEL_VERSION


ROOT = Path(__file__).resolve().parents[1]
VERSION = MODEL_VERSION.removeprefix("energy-baseline-")
OUTPUT = ROOT / "services" / "api" / "artifacts" / "energy-baseline" / VERSION


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def write_json(path: Path, value: object) -> str:
    content = canonical_json(value)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    operational = load_replay_frame(settings.dataset_zip)
    resources = load_resources(settings.dataset_zip)
    predictions = []
    selected = Counter()
    for as_of in resources.observed_at:
        baseline = compute_energy_baseline_frames(
            operational, resources, as_of.to_pydatetime(warn=False)
        )
        selected[baseline.get("selected_model", baseline["status"])] += 1
        predictions.append({"as_of": as_of.isoformat(), "baseline": baseline})

    OUTPUT.mkdir(parents=True, exist_ok=True)
    model = {
        "model_version": MODEL_VERSION,
        "target": {"metric": "Heat_cons", "unit": "MJ/m2/day"},
        "features": [
            "tout_mean", "heating_degree_hours", "radiation_mean",
            "lighting_hours", "crop_age_days",
        ],
        "candidate": {"algorithm": "elastic_net", "alpha": 0.02, "l1_ratio": 0.25},
        "fallback": {"algorithm": "rolling_7d_median", "window_days": 7},
        "promotion_gate": {
            "minimum_locked_test_improvement_pct": 5,
            "maximum_fold_degradation_pct": 20,
            "validation": "four expanding walk-forward folds plus locked final 20 percent",
        },
        "interval_method": "empirical residual quantiles p10/p90",
        "selection_counts": dict(sorted(selected.items())),
    }
    model_hash = write_json(OUTPUT / "model.json", model)
    model_card = f"""# Energy baseline {MODEL_VERSION}

This artifact serves the Wageningen reference demo only. It predicts daily heat
intensity from weather, heating demand, radiation, lighting and crop age.

- Validation: four expanding walk-forward folds and a locked final 20% block.
- Promotion: Elastic Net must improve MAE by at least 5% and no fold may degrade
  by more than 20%; otherwise the rolling seven-day median is served.
- Serving: select only the latest precomputed `as_of` at or before the replay cursor.
- Interpretation: associative operational evidence, not a causal savings estimate.
- Retraining: run `PYTHONPATH=services/api python scripts/build_baseline_artifact.py`,
  review the diff and model evidence, then bump the model version before release.
"""
    model_card_bytes = model_card.encode("utf-8")
    (OUTPUT / "model-card.md").write_bytes(model_card_bytes)
    model_card_hash = hashlib.sha256(model_card_bytes).hexdigest()
    prediction_payload = {
        "schema_version": 1,
        "future_safe": True,
        "selection_rule": "latest as_of less than or equal to replay cursor",
        "predictions": predictions,
    }
    predictions_hash = write_json(OUTPUT / "predictions.json", prediction_payload)
    artifact_id = f"energy-baseline-{VERSION}-{predictions_hash[:12]}"
    manifest = {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "artifact_kind": "daily_walk_forward_baseline",
        "model_version": MODEL_VERSION,
        "data_version": DATA_VERSION,
        "definitions_version": DEFINITIONS_VERSION,
        "source_dataset_sha256": source_sha256(settings.dataset_zip),
        "future_safe": True,
        "coverage": {
            "start": predictions[0]["as_of"],
            "end": predictions[-1]["as_of"],
            "prediction_count": len(predictions),
        },
        "files": {
            "model-card.md": model_card_hash,
            "model.json": model_hash,
            "predictions.json": predictions_hash,
        },
    }
    write_json(OUTPUT / "manifest.json", manifest)
    print({"artifact_id": artifact_id, "output": str(OUTPUT), "predictions": len(predictions)})


if __name__ == "__main__":
    main()
