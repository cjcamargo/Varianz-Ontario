from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .metrics import DATA_VERSION, DEFINITIONS_VERSION, ENERGY_MODEL_VERSION


VERSION = ENERGY_MODEL_VERSION.removeprefix("energy-intraday-")
ARTIFACT_DIRECTORY = Path(__file__).resolve().parents[1] / "artifacts" / "intraday-energy" / VERSION


class IntradayArtifactError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class IntradayArtifact:
    directory: Path
    manifest: dict
    allocated: pd.DataFrame
    calibrations: dict[str, dict]

    @property
    def artifact_id(self) -> str:
        return self.manifest["artifact_id"]


def load_intraday_artifact(directory: Path = ARTIFACT_DIRECTORY) -> IntradayArtifact:
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise IntradayArtifactError(f"intraday manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "model_version": ENERGY_MODEL_VERSION,
        "data_version": DATA_VERSION,
        "definitions_version": DEFINITIONS_VERSION,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise IntradayArtifactError(
                f"intraday artifact {field} mismatch: {manifest.get(field)!r} != {value!r}"
            )
    for filename, expected_hash in manifest.get("files", {}).items():
        path = directory / filename
        if not path.exists() or _sha256(path) != expected_hash:
            raise IntradayArtifactError(f"intraday artifact checksum failed: {filename}")
    allocated = pd.read_csv(directory / "allocated.csv.gz", compression="gzip")
    allocated["time"] = pd.to_datetime(allocated.time, utc=True, format="mixed")
    calibrations = json.loads(
        (directory / "calibrations.json").read_text(encoding="utf-8")
    )["calibrations"]
    return IntradayArtifact(directory, manifest, allocated, calibrations)


@lru_cache(maxsize=1)
def get_intraday_artifact() -> IntradayArtifact:
    return load_intraday_artifact()


def intraday_artifact_status() -> dict:
    try:
        artifact = get_intraday_artifact()
        return {
            "ready": True,
            "artifact_id": artifact.artifact_id,
            "model_version": artifact.manifest["model_version"],
            "allocated_observations": len(artifact.allocated),
            "calibration_days": len(artifact.calibrations),
        }
    except IntradayArtifactError as exc:
        return {"ready": False, "error": str(exc)}
