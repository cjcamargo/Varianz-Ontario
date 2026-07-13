import base64
import hashlib
import hmac
import json
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).parents[1] / "services" / "api"))

from varianz.analytics import dashboard_snapshot, energy_baseline, operational_snapshot
from varianz.agent import RESPONSE_SCHEMA, _conversation_text, _evidence_json
from varianz.auth import DEMO_USER_ID, verify_supabase_access_token, verify_supabase_jwt
from varianz.dataset import load_replay_frame, profile_source, quality_report, read_source
from varianz.replay import ReplaySession
from fastapi.testclient import TestClient
from varianz.main import _agent_evidence, app
from varianz.config import settings

ZIP = Path(__file__).parents[1] / "Wageningen MVP Dataset.zip"


def _mint_jwt(secret: str, subject: str, *, expires_in: int = 3600) -> str:
    def segment(payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    header = segment({"alg": "HS256", "typ": "JWT"})
    claims = segment({"sub": subject, "exp": int(time.time()) + expires_in})
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), f"{header}.{claims}".encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{header}.{claims}.{signature}"


class AgentTests(unittest.TestCase):
    def test_agent_contract_leads_with_recommendation(self):
        self.assertIn("recommendation", RESPONSE_SCHEMA["required"])
        self.assertEqual(RESPONSE_SCHEMA["properties"]["suggested_actions"]["maxItems"], 3)

    def test_conversation_context_keeps_recent_turns(self):
        history = [
            {"role": "operator", "content": "Explain heating energy."},
            {"role": "varianz", "content": "Check the heating circuit."},
        ]
        transcript = _conversation_text(history)
        self.assertIn("Operator: Explain heating energy.", transcript)
        self.assertIn("Varianz: Check the heating circuit.", transcript)

    def test_evidence_serializes_point_in_time_metadata(self):
        payload = _evidence_json(
            {
                "cursor": datetime(2020, 5, 20, 12, tzinfo=timezone.utc),
                "session_id": UUID("11111111-1111-1111-1111-111111111111"),
            }
        )
        self.assertIn('"cursor":"2020-05-20T12:00:00+00:00"', payload)
        self.assertIn('"session_id":"11111111-1111-1111-1111-111111111111"', payload)

    def test_agent_bundle_excludes_chart_series_and_keeps_focus(self):
        snapshot = {
            "session_id": "session",
            "revision": 1,
            "cursor": "2020-05-20T12:00:00+00:00",
            "window": "24h",
            "site": {},
            "data_version": "data",
            "definitions_version": "definitions",
            "model_version": "model",
            "quality": {},
            "evidence_ids": ["ev_snapshot"],
            "kpis": {},
            "latest": {},
            "baseline": {},
            "tariff": {},
            "metric_definitions": {},
            "anomalies": [{"id": "an_focus", "active": False}],
            "climate_series": [{"time": "large-payload"}],
            "resource_series": [{"time": "large-payload"}],
        }
        bundle = _agent_evidence(snapshot, "an_focus")
        self.assertNotIn("climate_series", bundle)
        self.assertNotIn("resource_series", bundle)
        self.assertEqual(bundle["focus_anomaly"]["id"], "an_focus")
        self.assertIn("terminology", bundle)


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
        self.assertEqual(snapshot["definitions_version"], "2.1.0")
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
        self.assertEqual(
            snapshot["metric_definitions"]["HumDef"]["label"],
            "Greenhouse humidity deficit",
        )
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
    def test_demo_start_cursor_is_independent_from_historical_minimum(self):
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        demo_start = start + timedelta(days=45)
        session = ReplaySession.create(
            uuid4(), start, start + timedelta(days=90), initial_cursor=demo_start
        )
        self.assertEqual(session.cursor, demo_start)
        self.assertEqual(session.minimum, start)
        self.assertEqual(session.mutate("reset", 0).cursor, demo_start)

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
        self.supabase_url = settings.supabase_url
        self.supabase_publishable_key = settings.supabase_publishable_key
        settings.data_backend = "zip"
        settings.supabase_url = None
        settings.supabase_publishable_key = None

    def tearDown(self):
        settings.data_backend = self.data_backend
        settings.supabase_url = self.supabase_url
        settings.supabase_publishable_key = self.supabase_publishable_key

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


class AuthTests(unittest.TestCase):
    SECRET = "test-supabase-jwt-secret"

    def setUp(self):
        self.data_backend = settings.data_backend
        self.supabase_url = settings.supabase_url
        self.supabase_publishable_key = settings.supabase_publishable_key
        settings.data_backend = "zip"
        settings.supabase_url = None
        settings.supabase_publishable_key = None

    def tearDown(self):
        settings.data_backend = self.data_backend
        settings.supabase_url = self.supabase_url
        settings.supabase_publishable_key = self.supabase_publishable_key

    @patch("varianz.auth.httpx.get")
    def test_hosted_supabase_token_verification(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "demo@varianz.ai",
        }
        claims = verify_supabase_access_token(
            "unique-hosted-token",
            "https://example.supabase.co",
            "publishable-key",
            now=1_000,
        )
        self.assertEqual(claims["sub"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(claims["email"], "demo@varianz.ai")
        get.assert_called_once_with(
            "https://example.supabase.co/auth/v1/user",
            headers={"apikey": "publishable-key", "Authorization": "Bearer unique-hosted-token"},
            timeout=10,
        )

    @patch("varianz.auth.httpx.get")
    def test_hosted_supabase_rejects_invalid_token(self, get):
        get.return_value.status_code = 401
        with self.assertRaisesRegex(Exception, "invalid_or_expired_token"):
            verify_supabase_access_token(
                "invalid-hosted-token",
                "https://example.supabase.co",
                "publishable-key",
            )

    def test_anonymous_demo_owns_and_reads_its_session(self):
        client = TestClient(app)
        session = client.post("/api/v1/replay-sessions").json()
        self.assertEqual(session["owner_id"], str(DEMO_USER_ID))
        overview = client.get(f"/api/v1/replay-sessions/{session['id']}/overview")
        self.assertEqual(overview.status_code, 200)

    def test_session_owner_is_isolated_from_other_users(self):
        client = TestClient(app)
        with patch.object(settings, "supabase_jwt_secret", self.SECRET):
            owner = _mint_jwt(self.SECRET, "11111111-1111-1111-1111-111111111111")
            other = _mint_jwt(self.SECRET, "22222222-2222-2222-2222-222222222222")
            session = client.post(
                "/api/v1/replay-sessions", headers={"Authorization": f"Bearer {owner}"}
            ).json()
            same = client.get(
                f"/api/v1/replay-sessions/{session['id']}/overview",
                headers={"Authorization": f"Bearer {owner}"},
            )
            foreign = client.get(
                f"/api/v1/replay-sessions/{session['id']}/overview",
                headers={"Authorization": f"Bearer {other}"},
            )
        self.assertEqual(session["owner_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(same.status_code, 200)
        self.assertEqual(foreign.status_code, 403)

    def test_tampered_signature_is_rejected(self):
        client = TestClient(app)
        with patch.object(settings, "supabase_jwt_secret", self.SECRET):
            forged = _mint_jwt("wrong-secret", "33333333-3333-3333-3333-333333333333")
            response = client.post(
                "/api/v1/replay-sessions", headers={"Authorization": f"Bearer {forged}"}
            )
        self.assertEqual(response.status_code, 401)

    def test_auth_required_rejects_anonymous_calls(self):
        client = TestClient(app)
        with patch.object(settings, "auth_required", True):
            response = client.post("/api/v1/replay-sessions")
        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_rejected(self):
        expired = _mint_jwt(self.SECRET, "44444444-4444-4444-4444-444444444444", expires_in=-10)
        with self.assertRaises(Exception) as caught:
            verify_supabase_jwt(expired, self.SECRET)
        self.assertEqual(getattr(caught.exception, "status_code", None), 401)


if __name__ == "__main__":
    unittest.main()
