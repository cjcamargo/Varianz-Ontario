import base64
import hashlib
import hmac
import json
import sys
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "services" / "api"))

from varianz.analytics import dashboard_snapshot, energy_baseline, operational_snapshot
from varianz.agent import (
    RESPONSE_SCHEMA,
    _allowed_evidence,
    _conversation_text,
    _evidence_json,
    _response_language,
    _valid_claims,
)
from varianz.auth import DEMO_USER_ID, verify_supabase_access_token, verify_supabase_jwt
from varianz.dataset import load_replay_frame, profile_source, quality_report, read_source
from varianz.energy import (
    apply_intraday_cost,
    efficiency_events,
    efficiency_indicators,
    intraday_energy_frame,
    ontario_tou_holidays,
    reconstruction_metadata,
    tou_period_masks,
    tou_peak_mask,
)
from varianz.replay import ReplaySession
from fastapi.testclient import TestClient
from varianz.main import (
    _agent_evidence,
    _business_impact,
    _cost_tariff,
    _performance_accounting,
    _schedule_tariff,
    app,
)
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
        self.assertNotIn("language", RESPONSE_SCHEMA["required"])
        self.assertEqual(RESPONSE_SCHEMA["properties"]["suggested_actions"]["maxItems"], 3)

    def test_response_language_is_determined_without_model_output(self):
        self.assertEqual(_response_language("¿Qué recomienda para reducir la energía?"), "es")
        self.assertEqual(_response_language("Explain the current heating deviation."), "en")

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

    def test_grounding_accepts_nested_efficiency_and_reconstruction_evidence(self):
        evidence = {
            "evidence_ids": ["snapshot:24h"],
            "efficiency": {
                "heat_degree_intensity": {"evidence_ids": ["enpi:heat-degree"]}
            },
            "reconstruction": {"evidence_ids": ["intraday:heat"]},
        }
        allowed = _allowed_evidence(evidence)
        self.assertEqual(
            allowed, {"snapshot:24h", "enpi:heat-degree", "intraday:heat"}
        )
        self.assertTrue(
            _valid_claims(
                {"claims": [{"evidence_ids": ["enpi:heat-degree"]}]}, allowed
            )
        )
        self.assertFalse(
            _valid_claims({"claims": [{"evidence_ids": ["invented:id"]}]}, allowed)
        )

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
            "business_impact": {},
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
        self.assertEqual(snapshot["definitions_version"], "2.2.0")
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


class IntradayEnergyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.operational = load_replay_frame(ZIP)
        cls.resources = read_source(ZIP, "Reference/Resources.csv")
        cls.cursor = datetime(2020, 5, 20, 12, tzinfo=timezone.utc)
        cls.five_min = intraday_energy_frame(
            cls.operational, cls.resources, cls.cursor, grain="5min"
        )

    def test_completed_days_conserve_authoritative_meters(self):
        actual = self.five_min.copy()
        actual["day"] = pd.to_datetime(actual.time, utc=True).dt.floor("D")
        totals = actual[actual.day < pd.Timestamp(self.cursor).floor("D")].groupby("day").agg(
            heat=("heat_mj_m2", "sum"), electricity=("elec_kwh_m2", "sum"), co2=("co2_kg_m2", "sum")
        )
        meter = self.resources.copy()
        meter["day"] = pd.to_datetime(meter.observed_at, utc=True).dt.floor("D")
        meter = meter.set_index("day")
        meter["meter_electricity"] = meter.ElecHigh.fillna(0) + meter.ElecLow.fillna(0)
        joined = totals.join(meter[["Heat_cons", "meter_electricity", "CO2_cons"]], how="inner")
        np.testing.assert_allclose(joined.heat, joined.Heat_cons, rtol=1e-6, atol=1e-9)
        np.testing.assert_allclose(joined.electricity, joined.meter_electricity, rtol=1e-6, atol=1e-9)
        np.testing.assert_allclose(joined.co2, joined.CO2_cons, rtol=1e-6, atol=1e-9, equal_nan=True)

    def test_current_day_is_future_safe_and_meter_independent(self):
        self.assertLessEqual(pd.to_datetime(self.five_min.time, utc=True).max(), pd.Timestamp(self.cursor))
        current = pd.to_datetime(self.five_min.time, utc=True).dt.floor("D") == pd.Timestamp(self.cursor).floor("D")
        self.assertTrue(current.any())
        self.assertEqual(set(self.five_min.loc[current, "quality"]), {"provisional"})
        altered = self.resources.copy()
        day = pd.to_datetime(altered.observed_at, utc=True).dt.floor("D") == pd.Timestamp(self.cursor).floor("D")
        altered.loc[day, ["Heat_cons", "ElecHigh", "ElecLow", "CO2_cons"]] = 999999
        reconstructed = intraday_energy_frame(self.operational, altered, self.cursor, grain="5min")
        columns = ["heat_mj_m2", "elec_kwh_m2", "co2_kg_m2"]
        np.testing.assert_allclose(self.five_min.loc[current, columns], reconstructed.loc[current, columns])

    def test_proxy_fidelity_meets_acceptance_thresholds(self):
        fit = reconstruction_metadata(self.operational, self.resources, self.cursor)["fit_r2"]
        self.assertGreaterEqual(fit["heat"], 0.90)
        self.assertGreaterEqual(fit["elec"], 0.97)
        self.assertGreaterEqual(fit["co2"], 0.99)

    def test_hourly_grain_conserves_five_minute_total(self):
        hourly = intraday_energy_frame(self.operational, self.resources, self.cursor, grain="1h")
        for column in ["heat_mj_m2", "elec_kwh_m2", "co2_kg_m2"]:
            self.assertAlmostEqual(float(hourly[column].sum()), float(self.five_min[column].sum()), places=8)

    def test_tou_boundaries_and_cost_guardrail(self):
        times = pd.Series(pd.to_datetime(["2020-01-06T11:59:00Z", "2020-01-06T12:00:00Z", "2020-01-06T17:00:00Z"]))
        windows = [{"label":"peak","days":"mon-fri","start":"07:00","end":"12:00"}]
        self.assertEqual(tou_peak_mask(times, windows, "UTC").tolist(), [True, False, False])
        self.assertTrue(apply_intraday_cost(self.five_min.head(2), None).cost_cad_m2.isna().all())

    def test_ontario_tou_is_seasonal_and_holidays_are_offpeak(self):
        windows = [
            {"label":"midpeak","days":"mon-fri","season":"summer","start":"07:00","end":"11:00"},
            {"label":"peak","days":"mon-fri","season":"summer","start":"11:00","end":"17:00"},
            {"label":"midpeak","days":"mon-fri","season":"summer","start":"17:00","end":"19:00"},
            {"label":"peak","days":"mon-fri","season":"winter","start":"07:00","end":"11:00"},
            {"label":"midpeak","days":"mon-fri","season":"winter","start":"11:00","end":"17:00"},
            {"label":"peak","days":"mon-fri","season":"winter","start":"17:00","end":"19:00"},
        ]
        summer = pd.Series(pd.to_datetime([
            "2020-07-06T06:59:00-04:00", "2020-07-06T07:00:00-04:00",
            "2020-07-06T11:00:00-04:00", "2020-07-06T17:00:00-04:00",
            "2020-07-06T19:00:00-04:00",
        ], utc=True))
        masks = tou_period_masks(summer, windows)
        self.assertEqual(masks["peak"].tolist(), [False, False, True, False, False])
        self.assertEqual(masks["midpeak"].tolist(), [False, True, False, True, False])
        self.assertEqual(masks["offpeak"].tolist(), [True, False, False, False, True])
        winter = pd.Series(pd.to_datetime([
            "2020-01-06T07:00:00-05:00", "2020-01-06T11:00:00-05:00",
            "2020-01-06T17:00:00-05:00", "2020-01-06T19:00:00-05:00",
        ], utc=True))
        winter_masks = tou_period_masks(winter, windows)
        self.assertEqual(winter_masks["peak"].tolist(), [True, False, True, False])
        self.assertEqual(winter_masks["midpeak"].tolist(), [False, True, False, False])
        weekend_and_holiday = pd.Series(pd.to_datetime([
            "2020-07-04T12:00:00-04:00", "2020-07-01T12:00:00-04:00",
        ], utc=True))
        self.assertEqual(tou_period_masks(weekend_and_holiday, windows)["offpeak"].tolist(), [True, True])
        self.assertIn(date(2020, 7, 1), ontario_tou_holidays(2020))

    def test_enpis_and_events_are_evidenced_and_non_prescriptive(self):
        indicators = efficiency_indicators(
            self.five_min, self.operational, self.resources, self.cursor,
            {"electricity_peak_per_kwh":.2,"electricity_offpeak_per_kwh":.1,"heat_per_mj":.01,"co2_per_kg":.1,"tou_windows":[]},
        )
        for indicator in indicators.values():
            if not isinstance(indicator, dict) or "status" not in indicator:
                continue
            self.assertTrue(indicator["unit"])
            self.assertTrue(indicator["evidence_ids"])
        without_tariff = efficiency_indicators(
            self.five_min, self.operational, self.resources, self.cursor, None,
        )["peak_share"]
        self.assertEqual(without_tariff["status"], "insufficient_data")
        self.assertIn("time-of-use schedule", without_tariff["unavailable_reason"])
        times = pd.date_range("2020-05-20T10:00:00Z", periods=6, freq="5min")
        synthetic = pd.DataFrame({"observed_at":times,"PipeLow":35,"PipeGrow":30,"Tair":20,"VentLee":25,"Tot_PAR_Lamps":0,"AssimLight":0,"co2_dos":0,"Iglob":50,"Tout":8,"EnScr":50})
        events = efficiency_events(synthetic, times[-1].to_pydatetime())
        self.assertIn("heating_against_ventilation", {event["code"] for event in events})
        forbidden = ("save", "savings", "reduce cost by")
        self.assertFalse(any(term in event["message"].lower() for event in events for term in forbidden))


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
        self.assertEqual(client.get("/api/v1/ready").json()["state"], "ready")
        created = client.post("/api/v1/replay-sessions")
        self.assertEqual(created.status_code, 200)
        session = created.json()
        dashboard = client.get(f"/api/v1/replay-sessions/{session['id']}/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        body = dashboard.json()
        self.assertEqual(body["revision"], 0)
        self.assertIn("kpis", body)
        self.assertGreater(body["replay"]["progress_pct"], 0)
        self.assertEqual(body["quality"]["data_status"], "warning")
        self.assertIn("timestamps", body["quality"]["validation_scope"])

    @patch("varianz.main._data_is_ready", return_value=False)
    def test_readiness_reports_background_warmup(self, _ready):
        response = TestClient(app).get("/api/v1/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["state"], "loading_operational_history")
        self.assertEqual(response.headers["retry-after"], "3")

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

    def test_energy_endpoint_exposes_intraday_contract(self):
        client = TestClient(app)
        session = client.post("/api/v1/replay-sessions").json()
        response = client.get(
            f"/api/v1/replay-sessions/{session['id']}/energy-resources?window=24h&grain=1h"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreater(payload["replay"]["progress_pct"], 0)
        self.assertGreaterEqual(
            payload["replay"]["observations_total"],
            payload["replay"]["observations_seen"],
        )
        self.assertEqual(payload["intraday"]["grain"], "1h")
        self.assertEqual(payload["intraday"]["serving_source"], "versioned_artifact")
        self.assertEqual(
            payload["intraday"]["reconstruction"]["model_version"],
            "energy-intraday-1.2.0",
        )
        self.assertTrue(
            any(point["quality"] == "provisional" for point in payload["intraday"]["series"])
        )
        self.assertTrue(
            all(point["time"] <= payload["cursor"] for point in payload["intraday"]["series"])
        )
        self.assertIn("efficiency", payload)
        self.assertIn("current_rate", payload["intraday"]["summary"]["co2"])
        self.assertIn(payload["intraday"]["summary"]["co2"]["status"], {
            "estimated", "estimated_zero", "reconciled", "measured_zero",
        })

    def test_tou_schedule_enables_peak_share_without_enabling_cost(self):
        schedule_only = {
            "tou_windows": [{"label":"peak","days":"mon-fri","start":"07:00","end":"11:00"}],
            "electricity_peak_per_kwh": None,
            "electricity_midpeak_per_kwh": None,
            "electricity_offpeak_per_kwh": None,
            "heat_per_mj": None, "co2_per_kg": None, "water_per_m3": None,
        }
        self.assertIs(_schedule_tariff(schedule_only), schedule_only)
        self.assertIsNone(_cost_tariff(schedule_only))
        complete = {**schedule_only, "electricity_peak_per_kwh": 0.2,
                    "electricity_midpeak_per_kwh": 0.15,
                    "electricity_offpeak_per_kwh": 0.1, "heat_per_mj": 0.01,
                    "co2_per_kg": 0.1, "water_per_m3": None}
        self.assertIs(_cost_tariff(complete), complete)

    def test_business_impact_is_directional_and_area_scaled(self):
        baseline = {
            "status": "ready", "actual_mj_m2": 8, "expected_mj_m2": 10,
            "confidence": "medium", "selected_model": "rolling_7d_median",
            "evidence_ids": ["ev_baseline"], "artifact_as_of": "2020-05-20T00:00:00+00:00",
        }
        tariff = {"currency": "CAD", "heat_per_mj": 0.1, "id": "tariff-1"}
        impact = _business_impact(baseline, tariff, 62.5, current_cost_cad_m2=0.5)
        self.assertEqual(impact["energy_performance_pct"], 20.0)
        self.assertEqual(impact["performance_state"], "favorable")
        self.assertEqual(impact["estimated_heat_cost_variance_cad"], 12.5)
        self.assertEqual(impact["current_cost_to_cursor_cad"], 31.25)
        self.assertIn("tariff:tariff-1", impact["evidence_ids"])

    def test_business_impact_hides_money_without_tariff(self):
        impact = _business_impact(
            {"status": "ready", "actual_mj_m2": 11, "expected_mj_m2": 10},
            None, 62.5,
        )
        self.assertEqual(impact["energy_performance_pct"], -10.0)
        self.assertEqual(impact["status"], "tariff_required")
        self.assertIsNone(impact["estimated_heat_cost_variance_cad"])

    def test_point_in_time_impact_and_cumulative_target_move_with_cursor(self):
        history_times = pd.to_datetime([
            "2020-01-31T00:00:00Z", "2020-01-31T06:00:00Z",
            "2020-01-31T12:00:00Z", "2020-01-31T18:00:00Z",
        ])
        current_times = pd.to_datetime([
            "2020-02-01T00:00:00Z", "2020-02-01T06:00:00Z",
            "2020-02-01T12:00:00Z",
        ])
        frame = pd.DataFrame({
            "time": [*history_times, *current_times],
            "heat_mj_m2": [1, 1, 1, 1, 0.5, 0.5, 8],
        })
        baseline = {
            "status": "ready", "actual_mj_m2": 9, "expected_mj_m2": 10,
            "confidence": "medium", "selected_model": "rolling_7d_median",
            "evidence_ids": ["ev_baseline"],
        }
        tariff = {"currency": "CAD", "heat_per_mj": 0.1, "id": "tariff-1"}
        with patch("varianz.main.get_baseline_artifact") as artifact:
            artifact.return_value.predictions = ()
            at_six = _performance_accounting(
                baseline, pd.Timestamp("2020-02-01T06:00:00Z").to_pydatetime(),
                frame[frame.time <= pd.Timestamp("2020-02-01T06:00:00Z")],
            )
            at_noon = _performance_accounting(
                baseline, pd.Timestamp("2020-02-01T12:00:00Z").to_pydatetime(), frame,
            )
        impact_six = _business_impact(baseline, tariff, 62.5, performance=at_six)
        impact_noon = _business_impact(baseline, tariff, 62.5, performance=at_noon)
        self.assertEqual(impact_six["energy_performance_pct"], 50.0)
        self.assertEqual(impact_noon["energy_performance_pct"], -200.0)
        self.assertGreater(impact_six["cumulative_estimated_heat_cost_variance_cad"], 0)
        self.assertLess(impact_noon["cumulative_estimated_heat_cost_variance_cad"], 0)
        self.assertEqual(impact_noon["target_improvement_pct"], 5.0)
        self.assertGreater(impact_noon["remaining_target_potential_cad"], 0)
        self.assertEqual(len(impact_noon["performance_series"]), 1)

    def test_agent_fails_closed_without_server_key(self):
        client = TestClient(app)
        session = client.post("/api/v1/replay-sessions").json()
        with patch.object(settings, "openai_api_key", None):
            response = client.post(
                f"/api/v1/replay-sessions/{session['id']}/agent/explain",
                json={"question": "Explain the current energy status."},
            )
        self.assertEqual(response.status_code, 503)

    def test_voice_transcription_fails_closed_without_server_key(self):
        client = TestClient(app)
        session = client.post("/api/v1/replay-sessions").json()
        with patch.object(settings, "openai_api_key", None):
            response = client.post(
                f"/api/v1/replay-sessions/{session['id']}/assistant/transcriptions",
                files={"audio": ("voice.webm", b"demo-audio", "audio/webm")},
            )
        self.assertEqual(response.status_code, 503)

    def test_voice_transcription_rejects_unsupported_media(self):
        client = TestClient(app)
        session = client.post("/api/v1/replay-sessions").json()
        response = client.post(
            f"/api/v1/replay-sessions/{session['id']}/assistant/transcriptions",
            files={"audio": ("voice.txt", b"not-audio", "text/plain")},
        )
        self.assertEqual(response.status_code, 415)

    def test_speech_reply_fails_closed_without_server_key(self):
        client = TestClient(app)
        session = client.post("/api/v1/replay-sessions").json()
        with patch.object(settings, "openai_api_key", None):
            response = client.post(
                f"/api/v1/replay-sessions/{session['id']}/assistant/speech",
                json={"text": "Revise el circuito de calefacción.", "language": "es"},
            )
        self.assertEqual(response.status_code, 503)

    def test_speech_reply_returns_audio_with_language_metadata(self):
        client = TestClient(app)
        session = client.post("/api/v1/replay-sessions").json()
        result = {
            "audio": b"demo-mp3", "content_type": "audio/mpeg", "model": "tts-1",
            "voice": "alloy", "language": "en",
        }
        with patch("varianz.main.synthesize_speech", new=AsyncMock(return_value=result)):
            response = client.post(
                f"/api/v1/replay-sessions/{session['id']}/assistant/speech",
                json={"text": "Check the heating circuit.", "language": "en"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"demo-mp3")
        self.assertEqual(response.headers["x-varianz-language"], "en")
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_speech_reply_rejects_language_outside_mvp(self):
        client = TestClient(app)
        session = client.post("/api/v1/replay-sessions").json()
        response = client.post(
            f"/api/v1/replay-sessions/{session['id']}/assistant/speech",
            json={"text": "Bonjour", "language": "fr"},
        )
        self.assertEqual(response.status_code, 422)


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
