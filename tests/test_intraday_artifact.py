from __future__ import annotations

import hashlib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from varianz.dataset import load_replay_frame, load_resources
from varianz.energy import (
    compute_intraday_energy_frame,
    intraday_energy_frame,
    reconstruction_metadata,
)
from varianz.intraday_artifact import get_intraday_artifact


ZIP = ROOT / "Wageningen MVP Dataset.zip"


class IntradayArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = get_intraday_artifact()
        cls.operational = load_replay_frame(ZIP)
        cls.resources = load_resources(ZIP)
        cls.cursor = datetime(2020, 5, 20, 12, tzinfo=timezone.utc)

    def test_manifest_and_materialized_coverage_are_valid(self):
        self.assertEqual(len(self.artifact.allocated), 47808)
        self.assertEqual(len(self.artifact.calibrations), 167)
        for filename, expected in self.artifact.manifest["files"].items():
            actual = hashlib.sha256((self.artifact.directory / filename).read_bytes()).hexdigest()
            self.assertEqual(actual, expected)

    def test_serving_uses_cache_without_full_runtime_reconstruction(self):
        with patch(
            "varianz.energy.compute_intraday_energy_frame",
            side_effect=AssertionError("full reconstruction is forbidden online"),
        ):
            result = intraday_energy_frame(
                self.operational, self.resources, self.cursor, grain="5min"
            )
        day = pd.Timestamp(self.cursor).floor("D")
        times = pd.to_datetime(result.time, utc=True)
        self.assertTrue(
            result.loc[times < day, "quality"].isin({"allocated", "imputed"}).all()
        )
        self.assertEqual(set(result.loc[times >= day, "quality"]), {"provisional"})
        self.assertEqual(result.attrs["serving_source"], "versioned_artifact")

    def test_reconstruction_diagnostic_is_precomputed(self):
        with patch(
            "varianz.energy.reconstruction_fit",
            side_effect=AssertionError("fit diagnostic is forbidden online"),
        ):
            metadata = reconstruction_metadata(
                self.operational, self.resources, self.cursor
            )
        self.assertEqual(metadata["serving_source"], "versioned_artifact")
        self.assertGreaterEqual(metadata["fit_r2"]["heat"], 0.9)

    def test_materialization_is_numerically_equivalent_to_reference_flow(self):
        cached = intraday_energy_frame(
            self.operational, self.resources, self.cursor, grain="5min"
        )
        reference = compute_intraday_energy_frame(
            self.operational, self.resources, self.cursor, grain="5min"
        )
        self.assertEqual(cached.quality.tolist(), reference.quality.tolist())
        np.testing.assert_allclose(
            cached[["heat_mj_m2", "elec_kwh_m2", "co2_kg_m2"]],
            reference[["heat_mj_m2", "elec_kwh_m2", "co2_kg_m2"]],
            rtol=1e-10,
            atol=1e-12,
        )


if __name__ == "__main__":
    unittest.main()
