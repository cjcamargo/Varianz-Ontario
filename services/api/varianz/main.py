from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from threading import Event
from uuid import UUID

import httpx
import pandas as pd
import psycopg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .agent import AgentUnavailable, explain_operational
from .analytics import operational_snapshot
from .auth import Principal, current_principal
from .config import settings
from .dataset import quality_report
from .energy import (
    aggregate_intraday,
    apply_intraday_cost,
    efficiency_events,
    efficiency_indicators,
    intraday_energy_frame,
    reconstruction_metadata,
)
from .replay import ReplaySession
from .store import ORG_ID, SITE_ID, get_operational_data
from .tariffs import get_tariff, put_tariff


operational_data_ready = Event()
operational_warmup_error: str | None = None


async def _warm_operational_data() -> None:
    global operational_warmup_error
    delay = 0
    while not operational_data_ready.is_set():
        if delay:
            await asyncio.sleep(delay)
        try:
            await asyncio.to_thread(get_operational_data, settings)
            operational_warmup_error = None
            operational_data_ready.set()
            return
        except (psycopg.Error, RuntimeError) as exc:
            operational_warmup_error = type(exc).__name__
            delay = min(60, max(2, delay * 2))


def _data_is_ready() -> bool:
    return settings.data_backend != "supabase" or operational_data_ready.is_set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Accept health/readiness traffic immediately while the immutable Supabase
    # demo history is loaded in the background. This removes the cold-start
    # deadlock between Render's health check and the first authenticated request.
    warmup = asyncio.create_task(_warm_operational_data())
    yield
    if not warmup.done():
        warmup.cancel()


app = FastAPI(
    title="Varianz Operational Intelligence API",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
api = APIRouter(prefix="/api/v1")
sessions: dict[UUID, ReplaySession] = {}
assistant_histories: dict[UUID, list[dict[str, str]]] = {}


class ReplayMutation(BaseModel):
    action: str
    expected_revision: int
    value: float | datetime | None = None


class AgentQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    anomaly_id: str | None = None


class TouWindow(BaseModel):
    label: str = Field(pattern="^(peak|offpeak)$")
    days: str = Field(pattern="^(all|mon-fri|sat-sun|weekend)$")
    start: str = Field(pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    end: str = Field(pattern="^([01]\\d|2[0-3]):[0-5]\\d$")


class TariffProfile(BaseModel):
    currency: str = Field(default="CAD", pattern="^[A-Z]{3}$")
    effective_from: date
    electricity_peak_per_kwh: float | None = Field(default=None, ge=0)
    electricity_offpeak_per_kwh: float | None = Field(default=None, ge=0)
    heat_per_mj: float | None = Field(default=None, ge=0)
    co2_per_kg: float | None = Field(default=None, ge=0)
    water_per_m3: float | None = Field(default=None, ge=0)
    source: str = Field(min_length=3, max_length=300)
    tou_windows: list[TouWindow] = Field(default_factory=list, min_length=1)
    preset: str | None = Field(default=None, max_length=80)


def _data():
    if not _data_is_ready():
        detail = "operational_data_unavailable" if operational_warmup_error else "operational_data_warming"
        raise HTTPException(503, detail, headers={"Retry-After": "3"})
    try:
        return get_operational_data(settings)
    except (psycopg.Error, RuntimeError) as exc:
        raise HTTPException(503, "operational_data_unavailable") from exc


def _schedule_tariff(profile: dict | None) -> dict | None:
    """Peak-period analytics require a sourced and reviewed ToU schedule."""
    return profile if profile and profile.get("tou_windows") else None


def _cost_tariff(profile: dict | None) -> dict | None:
    """Costs additionally require every applicable rate."""
    scheduled = _schedule_tariff(profile)
    rate_fields = [
        "electricity_peak_per_kwh", "electricity_offpeak_per_kwh", "heat_per_mj",
        "co2_per_kg", "water_per_m3",
    ]
    return scheduled if scheduled and all(scheduled.get(field) is not None for field in rate_fields) else None


def _session(session_id: UUID, principal: Principal) -> ReplaySession:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "replay_session_not_found")
    if session.owner_id != principal.user_id:
        raise HTTPException(403, "replay_session_forbidden")
    return session


def _snapshot(session_id: UUID, window: str, principal: Principal) -> dict:
    session = _session(session_id, principal)
    data = _data()
    cursor = session.effective_cursor()
    try:
        tariff_profile = get_tariff(settings.database_url, SITE_ID, cursor.date())
    except psycopg.Error:
        tariff_profile = None
    tariff = _cost_tariff(tariff_profile)
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
    operational_events = efficiency_events(
        data.operational, cursor,
        tariff_profile.get("tou_windows") if _schedule_tariff(tariff_profile) else None,
    )
    snapshot["anomalies"] = sorted(
        [*snapshot["anomalies"], *operational_events],
        key=lambda item: (not item.get("active", False), item["started_at"]),
    )[:40]
    snapshot["evidence_ids"] = list(dict.fromkeys([
        *snapshot["evidence_ids"],
        *(evidence for item in operational_events for evidence in item["evidence_ids"]),
    ]))
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


def _agent_evidence(snapshot: dict, anomaly_id: str | None = None) -> dict:
    """Build the small, typed evidence bundle the LLM is allowed to interpret."""
    focus = next(
        (item for item in snapshot["anomalies"] if item["id"] == anomaly_id), None
    )
    selected_anomalies = [item for item in snapshot["anomalies"] if item.get("active")][:5]
    if focus and all(item["id"] != focus["id"] for item in selected_anomalies):
        selected_anomalies.insert(0, focus)
    bundle = {
        key: snapshot[key]
        for key in [
            "session_id",
            "revision",
            "cursor",
            "window",
            "site",
            "data_version",
            "definitions_version",
            "model_version",
            "quality",
            "evidence_ids",
            "kpis",
            "latest",
            "baseline",
            "tariff",
            "metric_definitions",
        ]
    } | {
        "anomalies": selected_anomalies,
        "focus_anomaly": focus,
        "terminology": {
            code: {
                "official_name": definition["label"],
                "unit": definition["unit"],
                "source": definition["source"],
            }
            for code, definition in snapshot["metric_definitions"].items()
        },
    }
    for optional in ["efficiency", "reconstruction"]:
        if optional in snapshot:
            bundle[optional] = snapshot[optional]
    return bundle


@api.get("/health")
def health():
    return {
        "status": "ok", "environment": settings.environment, "version": "0.2.0",
        "data_ready": _data_is_ready(),
    }


@api.get("/ready")
def readiness():
    if not _data_is_ready():
        return JSONResponse(
            status_code=503,
            content={"ready": False, "state": "loading_operational_history"},
            headers={"Retry-After": "3"},
        )
    return {"ready": True, "state": "ready"}


@api.get("/demo/profile")
def demo_profile():
    return quality_report(settings.dataset_zip)


@api.post("/replay-sessions")
def create_replay_session(principal: Principal = Depends(current_principal)):
    data = _data()
    minimum = data.operational.observed_at.min().to_pydatetime(warn=False)
    maximum = data.operational.observed_at.max().to_pydatetime(warn=False)
    session = ReplaySession.create(
        principal.user_id,
        minimum,
        maximum,
        initial_cursor=min(minimum + timedelta(days=45), maximum),
    )
    sessions[session.id] = session
    return session


@api.patch("/replay-sessions/{session_id}")
def update_replay_session(
    session_id: UUID,
    mutation: ReplayMutation,
    principal: Principal = Depends(current_principal),
):
    session = _session(session_id, principal)
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
def replay_snapshot(session_id: UUID, principal: Principal = Depends(current_principal)):
    payload = _snapshot(session_id, "1h", principal)
    return {
        key: payload[key]
        for key in ["session_id", "revision", "cursor", "latest", "quality", "data_version"]
    }


@api.get("/replay-sessions/{session_id}/overview")
def overview(
    session_id: UUID,
    window: str = Query("24h", pattern="^(1h|6h|24h|7d|all)$"),
    principal: Principal = Depends(current_principal),
):
    return _snapshot(session_id, window, principal)


@api.get("/replay-sessions/{session_id}/energy-resources")
def energy_resources(
    session_id: UUID,
    window: str = Query("7d", pattern="^(1h|6h|24h|7d|all)$"),
    grain: str = Query("1h", pattern="^(5min|1h)$"),
    principal: Principal = Depends(current_principal),
):
    payload = _snapshot(session_id, window, principal)
    data = _data()
    cursor = pd.Timestamp(payload["cursor"])
    try:
        tariff_profile = get_tariff(settings.database_url, SITE_ID, cursor.date())
    except psycopg.Error:
        tariff_profile = None
    schedule_tariff = _schedule_tariff(tariff_profile)
    cost_tariff = _cost_tariff(tariff_profile)
    tou_windows = schedule_tariff.get("tou_windows") if schedule_tariff else None
    five_min_intraday = intraday_energy_frame(
        data.operational, data.resources, cursor.to_pydatetime(), grain="5min",
        tou_windows=tou_windows,
    )
    intraday = aggregate_intraday(five_min_intraday, grain)
    intraday = apply_intraday_cost(intraday, cost_tariff)
    deltas = {
        "1h": pd.Timedelta(hours=1), "6h": pd.Timedelta(hours=6),
        "24h": pd.Timedelta(hours=24), "7d": pd.Timedelta(days=7),
    }
    if window in deltas:
        intraday = intraday[pd.to_datetime(intraday.time, utc=True) >= cursor - deltas[window]]
    if len(intraday) > 2500:
        intraday = intraday.iloc[:: max(1, len(intraday) // 2500)]
    records = intraday.astype(object).where(pd.notna(intraday), None).to_dict("records")
    reconstruction = reconstruction_metadata(
        data.operational, data.resources, cursor.to_pydatetime()
    )
    efficiency = efficiency_indicators(
        five_min_intraday,
        data.operational, data.resources, cursor.to_pydatetime(), schedule_tariff,
    )
    efficiency_anomalies = [
        item for item in payload["anomalies"] if item.get("category") == "efficiency"
    ]
    base = {
        key: payload[key]
        for key in [
            "session_id", "revision", "cursor", "window", "site", "data_version",
            "definitions_version", "model_version", "quality", "evidence_ids", "kpis",
            "baseline", "resource_series", "anomalies", "tariff", "metric_definitions",
        ]
    }
    base["evidence_ids"] = list(dict.fromkeys([
        *base["evidence_ids"], *reconstruction["evidence_ids"],
        *(evidence for item in efficiency_anomalies for evidence in item["evidence_ids"]),
    ]))
    base["intraday"] = {
        "grain": grain,
        "series": records,
        "reconstruction": reconstruction,
        "cost_configured": bool(cost_tariff),
        "tou_configured": bool(schedule_tariff),
        "currency": tariff_profile.get("currency") if tariff_profile else None,
    }
    base["efficiency"] = efficiency
    return base


@api.get("/replay-sessions/{session_id}/climate")
def climate(
    session_id: UUID,
    window: str = Query("24h", pattern="^(1h|6h|24h|7d|all)$"),
    principal: Principal = Depends(current_principal),
):
    payload = _snapshot(session_id, window, principal)
    return {
        key: payload[key]
        for key in [
            "session_id", "revision", "cursor", "window", "site", "data_version",
            "definitions_version", "model_version", "quality", "evidence_ids", "kpis",
            "latest", "climate_series", "anomalies", "metric_definitions",
        ]
    }


@api.get("/replay-sessions/{session_id}/anomalies")
def anomalies(
    session_id: UUID,
    window: str = Query("7d", pattern="^(1h|6h|24h|7d|all)$"),
    principal: Principal = Depends(current_principal),
):
    payload = _snapshot(session_id, window, principal)
    return {
        key: payload[key]
        for key in [
            "session_id", "revision", "cursor", "data_version", "definitions_version",
            "model_version", "quality", "evidence_ids", "anomalies",
        ]
    }


@api.get("/anomalies/{anomaly_id}")
def anomaly_detail(
    anomaly_id: str,
    session_id: UUID,
    principal: Principal = Depends(current_principal),
):
    payload = _snapshot(session_id, "7d", principal)
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
def assistant_message(
    session_id: UUID,
    request: AgentQuestion,
    principal: Principal = Depends(current_principal),
):
    snapshot = _snapshot(session_id, "24h", principal)
    data = _data()
    cursor = pd.Timestamp(snapshot["cursor"])
    try:
        tariff_profile = get_tariff(settings.database_url, SITE_ID, cursor.date())
    except psycopg.Error:
        tariff_profile = None
    schedule_tariff = _schedule_tariff(tariff_profile)
    intraday = intraday_energy_frame(
        data.operational, data.resources, cursor.to_pydatetime(), grain="5min",
        tou_windows=schedule_tariff.get("tou_windows") if schedule_tariff else None,
    )
    snapshot["efficiency"] = efficiency_indicators(
        intraday, data.operational, data.resources, cursor.to_pydatetime(), schedule_tariff,
    )
    snapshot["reconstruction"] = reconstruction_metadata(
        data.operational, data.resources, cursor.to_pydatetime()
    )
    evidence = _agent_evidence(snapshot, request.anomaly_id)
    history = assistant_histories.setdefault(session_id, [])
    try:
        question = request.question.strip()
        result = explain_operational(question, evidence, settings, history)
        history.extend(
            [
                {"role": "operator", "content": question},
                {
                    "role": "varianz",
                    "content": f"Recommendation: {result.recommendation}\nExplanation: {result.answer}",
                },
            ]
        )
        assistant_histories[session_id] = history[-12:]
        return result
    except AgentUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, "openai_upstream_error") from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, "openai_connection_unavailable") from exc


@api.get("/sites/{site_id}/tariff-profile")
def tariff_profile(
    site_id: UUID,
    effective_on: date | None = None,
    principal: Principal = Depends(current_principal),
):
    if site_id != SITE_ID:
        raise HTTPException(404, "site_not_found")
    try:
        profile = get_tariff(settings.database_url, site_id, effective_on or date.today())
    except psycopg.Error as exc:
        raise HTTPException(503, "tariff_store_unavailable") from exc
    return {"configured": bool(profile), "profile": profile}


@api.put("/sites/{site_id}/tariff-profile")
def update_tariff_profile(
    site_id: UUID,
    request: TariffProfile,
    principal: Principal = Depends(current_principal),
):
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
def legacy_dashboard(session_id: UUID, principal: Principal = Depends(current_principal)):
    payload = _snapshot(session_id, "24h", principal)
    payload["alerts"] = payload["anomalies"]
    payload["kpis"]["climate_compliance_pct"] = payload["kpis"]["climate_compliance_24h_pct"]
    return payload


@api.post("/replay-sessions/{session_id}/agent/explain")
def legacy_agent(
    session_id: UUID,
    request: AgentQuestion,
    principal: Principal = Depends(current_principal),
):
    return assistant_message(session_id, request, principal)


app.include_router(api)
