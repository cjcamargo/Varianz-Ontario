from __future__ import annotations

import hashlib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from varianz.analytics import energy_baseline_frames
from varianz.baseline_artifact import get_baseline_artifact
from varianz.dataset import load_replay_frame, load_resources


ZIP = ROOT / "Wageningen MVP Dataset.zip"


class BaselineArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = get_baseline_artifact()
        cls.operational = load_replay_frame(ZIP)
        cls.resources = load_resources(ZIP)

    def test_manifest_checksums_and_versions_are_validated(self):
        self.assertEqual(len(self.artifact.predictions), 166)
        for filename, expected in self.artifact.manifest["files"].items():
            actual = hashlib.sha256((self.artifact.directory / filename).read_bytes()).hexdigest()
            self.assertEqual(actual, expected)

    def test_lookup_never_uses_a_future_prediction(self):
        as_of = self.artifact.timestamps[80]
        cursor = as_of + timedelta(hours=12)
        result = self.artifact.prediction_at(cursor)
        self.assertEqual(result, self.artifact.predictions[80]["baseline"])
        self.assertLessEqual(as_of, cursor)

    def test_serving_does_not_retrain(self):
        cursor = datetime(2020, 5, 20, 12, tzinfo=timezone.utc)
        with patch(
            "varianz.analytics.compute_energy_baseline_frames",
            side_effect=AssertionError("runtime training is forbidden"),
        ):
            result = energy_baseline_frames(self.operational, self.resources, cursor)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["serving_source"], "versioned_artifact")
        self.assertLessEqual(result["artifact_as_of"], cursor.isoformat())


if __name__ == "__main__":
    unittest.main()
