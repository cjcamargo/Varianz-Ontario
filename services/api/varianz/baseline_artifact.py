from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .metrics import DATA_VERSION, DEFINITIONS_VERSION, MODEL_VERSION


ARTIFACT_DIRECTORY = Path(__file__).resolve().parents[1] / "artifacts" / "energy-baseline" / "2.1.0"


class BaselineArtifactError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class BaselineArtifact:
    directory: Path
    manifest: dict
    model: dict
    predictions: tuple[dict, ...]
    timestamps: tuple[pd.Timestamp, ...]

    @property
    def artifact_id(self) -> str:
        return self.manifest["artifact_id"]

    def prediction_at(self, cursor) -> dict | None:
        timestamp = pd.Timestamp(cursor)
        index = bisect_right(self.timestamps, timestamp) - 1
        if index < 0:
            return None
        # Return an independent structure because callers add request-specific evidence.
        return json.loads(json.dumps(self.predictions[index]["baseline"]))


def load_baseline_artifact(directory: Path = ARTIFACT_DIRECTORY) -> BaselineArtifact:
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise BaselineArtifactError(f"baseline manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "model_version": MODEL_VERSION,
        "data_version": DATA_VERSION,
        "definitions_version": DEFINITIONS_VERSION,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise BaselineArtifactError(
                f"baseline artifact {field} mismatch: {manifest.get(field)!r} != {value!r}"
            )
    for filename, expected_hash in manifest.get("files", {}).items():
        path = directory / filename
        if not path.exists() or _sha256(path) != expected_hash:
            raise BaselineArtifactError(f"baseline artifact checksum failed: {filename}")
    model = json.loads((directory / "model.json").read_text(encoding="utf-8"))
    predictions = tuple(
        json.loads((directory / "predictions.json").read_text(encoding="utf-8"))["predictions"]
    )
    timestamps = tuple(pd.Timestamp(item["as_of"]) for item in predictions)
    if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
        raise BaselineArtifactError("baseline predictions must be unique and ordered")
    return BaselineArtifact(directory, manifest, model, predictions, timestamps)


@lru_cache(maxsize=1)
def get_baseline_artifact() -> BaselineArtifact:
    return load_baseline_artifact()


def baseline_artifact_status() -> dict:
    try:
        artifact = get_baseline_artifact()
        return {
            "ready": True,
            "artifact_id": artifact.artifact_id,
            "model_version": artifact.manifest["model_version"],
            "prediction_count": len(artifact.predictions),
        }
    except BaselineArtifactError as exc:
        return {"ready": False, "error": str(exc)}
