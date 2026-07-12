import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).parents[1] / "services" / "api"))

from varianz.analytics import dashboard_snapshot, energy_baseline, operational_snapshot
from varianz.agent import _evidence_json
from varianz.dataset import load_replay_frame, profile_source, quality_report, read_source
from varianz.replay import ReplaySession
from fastapi.testclient import TestClient
from varianz.main import app
from varianz.config import settings

ZIP = Path(__file__).parents[1] / "Wageningen MVP Dataset.zip"


class AgentTests(unittest.TestCase):
    def test_evidence_serializes_point_in_time_metadata(self):
        payload = _evidence_json(
            {
                "cursor": datetime(2020, 5, 20, 12, tzinfo=timezone.utc),
                "session_id": UUID("11111111-1111-1111-1111-111111111111"),
            }
        )
        self.assertIn('"cursor":"2020-05-20T12:00:00+00:00"', payload)
        self.assertIn('"session_id":"11111111-1111-1111-1111-111111111111"', payload)


class DatasetTests(unittest.TestCase):
    def test_source_contracts(self):
        profile = profile_source(ZIP, "Reference/Resources.csv")
        self.assertEqual(profile.rows, 166)
        self.assertEqual(profile.duplicate_timestamps, 0)
        self.assertEqual(profile.start[:10], "2019-12-16")

    def test_replay_frame_is_ordered_and_joined(self):
        frame = load_replay_frame(ZIP)
        self.assertEqual(len(frame), 47809)
        self.assertTrue(frame.observed_at.is_monotonic_increasing)

    def test_all_sources_parse_and_reconcile(self):
        report = quality_report(ZIP)
        self.assertEqual(report["totals"]["sources"], 8)
        self.assertEqual(report["totals"]["rows"], 143658)
        quality = read_source(ZIP, "Reference/TomQuality.csv")
        self.assertEqual(
            list(quality.columns),
            ["observed_at", "Flavour", "TSS", "Acid", "%Juice", "Bite", "Weight", "DMC_fruit"],
        )

    def test_dashboard_is_point_in_time_safe(self):
        cursor = datetime(2020, 3, 1, 12, tzinfo=timezone.utc)
        snapshot = dashboard_snapshot(ZIP, cursor)
        self.assertTrue(
            all(point["time"] <= cursor.isoformat() for point in snapshot["climate_series"])
        )
        self.assertEqual(snapshot["definitions_version"], "2.0.0")
        self.assertTrue(snapshot["quality"]["future_safe"])

    def test_operational_kpis_have_units_and_reconcile(self):
        cursor = datetime(2020, 5, 20, 12, tzinfo=timezone.utc)
        snapshot = operational_snapshot(load_replay_frame(ZIP), read_source(ZIP, "Reference/Resources.csv"), cursor)
        heat = snapshot["kpis"]["daily_heat_mj_m2"]
        electricity = snapshot["kpis"]["daily_electricity_kwh_m2"]
        self.assertAlmostEqual(
            snapshot["kpis"]["daily_total_energy_mj_m2"], heat + 3.6 * electricity, places=2
        )
        self.assertEqual(snapshot["metric_definitions"]["Heat_cons"]["unit"], "MJ/m2/day")
        self.assertIsNone(snapshot["kpis"]["operating_cost_cad_m2"])

    def test_window_does_not_expose_future_data(self):
        cursor = datetime(2020, 2, 15, 10, tzinfo=timezone.utc)
        snapshot = operational_snapshot(
            load_replay_frame(ZIP), read_source(ZIP, "Reference/Resources.csv"), cursor, "6h"
        )
        times = [point["time"] for point in snapshot["climate_series"]]
        self.assertTrue(times)
        self.assertTrue(all(time <= cursor.isoformat() for time in times))

    def test_energy_baseline_has_explicit_state(self):
        result = energy_baseline(ZIP, datetime(2020, 5, 20, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "ready")
        self.assertGreaterEqual(result["training_days"], 30)


class ReplayTests(unittest.TestCase):
    def test_clock_and_revision_conflict(self):
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        session = ReplaySession.create(uuid4(), start, start + timedelta(days=1))
        playing = session.mutate("play", 0, now=start)
        self.assertEqual(
            playing.effective_cursor(start + timedelta(seconds=10)), start + timedelta(seconds=10)
        )
        with self.assertRaisesRegex(ValueError, "replay_revision_conflict"):
            playing.mutate("pause", 0, now=start)

    def test_private_sessions_do_not_share_state(self):
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        left = ReplaySession.create(uuid4(), start, start + timedelta(days=1))
        right = ReplaySession.create(uuid4(), start, start + timedelta(days=1))
        self.assertNotEqual(left.id, right.id)
        self.assertTrue(left.mutate("play", 0, now=start).playing)
        self.assertFalse(right.playing)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.data_backend = settings.data_backend
        settings.data_backend = "zip"

    def tearDown(self):
        settings.data_backend = self.data_backend

    def test_versioned_dashboard_contract(self):
        client = TestClient(app)
        self.assertEqual(client.get("/api/v1/health").status_code, 200)
        created = client.post("/api/v1/replay-sessions")
        self.assertEqual(created.status_code, 200)
        session = created.json()
        dashboard = client.get(f"/api/v1/replay-sessions/{session['id']}/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        body = dashboard.json()
        self.assertEqual(body["revision"], 0)
        self.assertIn("kpis", body)

    def test_stale_replay_revision_is_rejected(self):
        client = TestClient(app)
        session = client.post("/api/v1/replay-sessions").json()
        url = f"/api/v1/replay-sessions/{session['id']}"
        self.assertEqual(
            client.patch(url, json={"action": "play", "expected_revision": 0}).status_code, 200
        )
        self.assertEqual(
            client.patch(url, json={"action": "pause", "expected_revision": 0}).status_code, 409
        )

    def test_agent_fails_closed_without_server_key(self):
        client = TestClient(app)
        session = client.post("/api/v1/replay-sessions").json()
        with patch.object(settings, "openai_api_key", None):
            response = client.post(
                f"/api/v1/replay-sessions/{session['id']}/agent/explain",
                json={"question": "Explain the current energy status."},
            )
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
