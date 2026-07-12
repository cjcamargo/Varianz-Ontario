from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import psycopg
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent import AgentUnavailable, explain_operational
from .analytics import operational_snapshot
from .config import settings
from .dataset import quality_report
from .replay import ReplaySession
from .store import ORG_ID, SITE_ID, get_operational_data
from .tariffs import get_tariff, put_tariff


app = FastAPI(title="Varianz Operational Intelligence API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT"],
    allow_headers=["Content-Type", "Idempotency-Key"],
)
api = APIRouter(prefix="/api/v1")
sessions: dict[UUID, ReplaySession] = {}


class ReplayMutation(BaseModel):
    action: str
    expected_revision: int
    value: float | datetime | None = None


class AgentQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    anomaly_id: str | None = None


class TariffProfile(BaseModel):
    currency: str = Field(default="CAD", pattern="^[A-Z]{3}$")
    effective_from: date
    electricity_peak_per_kwh: float = Field(ge=0)
    electricity_offpeak_per_kwh: float = Field(ge=0)
    heat_per_mj: float = Field(ge=0)
    co2_per_kg: float = Field(ge=0)
    water_per_m3: float = Field(ge=0)
    source: str = Field(min_length=3, max_length=300)


def _data():
    try:
        return get_operational_data(settings)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(503, "operational_data_unavailable") from exc


def _session(session_id: UUID) -> ReplaySession:
    if session_id not in sessions:
        raise HTTPException(404, "replay_session_not_found")
    return sessions[session_id]


def _snapshot(session_id: UUID, window: str) -> dict:
    session = _session(session_id)
    data = _data()
    cursor = session.effective_cursor()
    try:
        tariff = get_tariff(settings.database_url, SITE_ID, cursor.date())
    except psycopg.Error:
        tariff = None
    try:
        snapshot = operational_snapshot(
            data.operational,
            data.resources,
            cursor,
            window,
            backend=data.backend,
            quality=data.quality,
            tariff=tariff,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "session_id": session.id,
        "revision": session.revision,
        "playing": session.playing,
        "speed": session.speed,
        "site": {
            "id": SITE_ID,
            "name": "Wageningen Reference Greenhouse",
            "area_m2": 96,
            "growing_area_m2": 62.5,
            "timezone": "Europe/Amsterdam",
        },
        **snapshot,
    }


@api.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment, "version": "0.2.0"}


@api.get("/demo/profile")
def demo_profile():
    return quality_report(settings.dataset_zip)


@api.post("/replay-sessions")
def create_replay_session():
    data = _data()
    minimum = data.operational.observed_at.min().to_pydatetime(warn=False)
    maximum = data.operational.observed_at.max().to_pydatetime(warn=False)
    session = ReplaySession.create(
        uuid4(),
        minimum,
        maximum,
        initial_cursor=min(minimum + timedelta(days=45), maximum),
    )
    sessions[session.id] = session
    return session


@api.patch("/replay-sessions/{session_id}")
def update_replay_session(session_id: UUID, mutation: ReplayMutation):
    session = _session(session_id)
    try:
        sessions[session_id] = session.mutate(
            mutation.action, mutation.expected_revision, value=mutation.value
        )
    except ValueError as exc:
        raise HTTPException(
            409 if str(exc) == "replay_revision_conflict" else 422, str(exc)
        ) from exc
    return sessions[session_id]


@api.get("/replay-sessions/{session_id}/snapshot")
def replay_snapshot(session_id: UUID):
    payload = _snapshot(session_id, "1h")
    return {
        key: payload[key]
        for key in ["session_id", "revision", "cursor", "latest", "quality", "data_version"]
    }


@api.get("/replay-sessions/{session_id}/overview")
def overview(session_id: UUID, window: str = Query("24h", pattern="^(1h|6h|24h|7d|all)$")):
    return _snapshot(session_id, window)


@api.get("/replay-sessions/{session_id}/energy-resources")
def energy_resources(session_id: UUID, window: str = Query("7d", pattern="^(1h|6h|24h|7d|all)$")):
    payload = _snapshot(session_id, window)
    return {
        key: payload[key]
        for key in [
            "session_id", "revision", "cursor", "window", "site", "data_version",
            "definitions_version", "model_version", "quality", "evidence_ids", "kpis",
            "baseline", "resource_series", "anomalies", "tariff", "metric_definitions",
        ]
    }


@api.get("/replay-sessions/{session_id}/climate")
def climate(session_id: UUID, window: str = Query("24h", pattern="^(1h|6h|24h|7d|all)$")):
    payload = _snapshot(session_id, window)
    return {
        key: payload[key]
        for key in [
            "session_id", "revision", "cursor", "window", "site", "data_version",
            "definitions_version", "model_version", "quality", "evidence_ids", "kpis",
            "latest", "climate_series", "anomalies", "metric_definitions",
        ]
    }


@api.get("/replay-sessions/{session_id}/anomalies")
def anomalies(session_id: UUID, window: str = Query("7d", pattern="^(1h|6h|24h|7d|all)$")):
    payload = _snapshot(session_id, window)
    return {
        key: payload[key]
        for key in [
            "session_id", "revision", "cursor", "data_version", "definitions_version",
            "model_version", "quality", "evidence_ids", "anomalies",
        ]
    }


@api.get("/anomalies/{anomaly_id}")
def anomaly_detail(anomaly_id: str, session_id: UUID):
    payload = _snapshot(session_id, "7d")
    anomaly = next((item for item in payload["anomalies"] if item["id"] == anomaly_id), None)
    if not anomaly:
        raise HTTPException(404, "anomaly_not_found")
    return {
        "session_id": session_id,
        "revision": payload["revision"],
        "cursor": payload["cursor"],
        "data_version": payload["data_version"],
        "definitions_version": payload["definitions_version"],
        "model_version": payload["model_version"],
        "quality": payload["quality"],
        "evidence_ids": anomaly["evidence_ids"],
        "anomaly": anomaly,
    }


@api.post("/replay-sessions/{session_id}/assistant/messages")
def assistant_message(session_id: UUID, request: AgentQuestion):
    evidence = _snapshot(session_id, "24h")
    if request.anomaly_id:
        evidence["focus_anomaly"] = next(
            (item for item in evidence["anomalies"] if item["id"] == request.anomaly_id), None
        )
    try:
        return explain_operational(request.question.strip(), evidence, settings)
    except AgentUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, "openai_upstream_error") from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, "openai_connection_unavailable") from exc


@api.get("/sites/{site_id}/tariff-profile")
def tariff_profile(site_id: UUID, effective_on: date | None = None):
    if site_id != SITE_ID:
        raise HTTPException(404, "site_not_found")
    try:
        profile = get_tariff(settings.database_url, site_id, effective_on or date.today())
    except psycopg.Error as exc:
        raise HTTPException(503, "tariff_store_unavailable") from exc
    return {"configured": bool(profile), "profile": profile}


@api.put("/sites/{site_id}/tariff-profile")
def update_tariff_profile(site_id: UUID, request: TariffProfile):
    if site_id != SITE_ID:
        raise HTTPException(404, "site_not_found")
    if not settings.database_url:
        raise HTTPException(503, "tariff_store_unavailable")
    try:
        profile = put_tariff(
            settings.database_url, ORG_ID, SITE_ID, request.model_dump(mode="json")
        )
    except psycopg.Error as exc:
        raise HTTPException(503, "tariff_store_unavailable") from exc
    return {"configured": True, "profile": profile}


@api.get("/replay-sessions/{session_id}/dashboard")
def legacy_dashboard(session_id: UUID):
    payload = _snapshot(session_id, "24h")
    payload["alerts"] = payload["anomalies"]
    payload["kpis"]["climate_compliance_pct"] = payload["kpis"]["climate_compliance_24h_pct"]
    return payload


@api.post("/replay-sessions/{session_id}/agent/explain")
def legacy_agent(session_id: UUID, request: AgentQuestion):
    return assistant_message(session_id, request)


app.include_router(api)
