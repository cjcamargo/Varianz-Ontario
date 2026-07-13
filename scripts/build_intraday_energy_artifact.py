from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from varianz.config import settings
from varianz.dataset import load_replay_frame, load_resources, source_sha256
from varianz.energy import build_intraday_materialization
from varianz.metrics import DATA_VERSION, DEFINITIONS_VERSION, ENERGY_MODEL_VERSION


ROOT = Path(__file__).resolve().parents[1]
VERSION = ENERGY_MODEL_VERSION.removeprefix("energy-intraday-")
OUTPUT = ROOT / "services" / "api" / "artifacts" / "intraday-energy" / VERSION


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write(path: Path, content: bytes) -> str:
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    operational = load_replay_frame(settings.dataset_zip)
    resources = load_resources(settings.dataset_zip)
    allocated, calibrations = build_intraday_materialization(operational, resources)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    csv = allocated.to_csv(index=False, float_format="%.12g", lineterminator="\n").encode("utf-8")
    allocated_hash = write(OUTPUT / "allocated.csv.gz", gzip.compress(csv, compresslevel=9, mtime=0))
    calibration_content = canonical_json({
        "schema_version": 1,
        "future_safe": True,
        "calibrations": calibrations,
    })
    calibration_hash = write(OUTPUT / "calibrations.json", calibration_content)
    model_card = f"""# Intraday energy reconstruction {ENERGY_MODEL_VERSION}

Completed days allocate authoritative daily heat, electricity and carbon-dioxide meters over
five-minute equipment proxies. Each allocation reconciles to its daily meter. Intervals without
an official completed-day meter are provisional and use median conversion factors fitted only on
the previous seven completed days. Tariff windows and costs are applied at request time.

The committed artifact is the reproducible seed. Supabase is the production serving cache, and
the current incomplete day remains an incremental causal transformation.
""".encode("utf-8")
    card_hash = write(OUTPUT / "model-card.md", model_card)
    artifact_id = f"intraday-energy-{VERSION}-{allocated_hash[:12]}"
    manifest = {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "artifact_kind": "intraday_energy_materialization",
        "model_version": ENERGY_MODEL_VERSION,
        "data_version": DATA_VERSION,
        "definitions_version": DEFINITIONS_VERSION,
        "source_dataset_sha256": source_sha256(settings.dataset_zip),
        "future_safe": True,
        "coverage": {
            "start": allocated.time.min().isoformat(),
            "end": allocated.time.max().isoformat(),
            "allocated_observations": len(allocated),
            "calibration_days": len(calibrations),
        },
        "files": {
            "allocated.csv.gz": allocated_hash,
            "calibrations.json": calibration_hash,
            "model-card.md": card_hash,
        },
    }
    write(OUTPUT / "manifest.json", canonical_json(manifest))
    print({"artifact_id": artifact_id, **manifest["coverage"], "output": str(OUTPUT)})


if __name__ == "__main__":
    main()
