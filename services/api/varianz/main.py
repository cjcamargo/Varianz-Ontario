from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from threading import Event
from uuid import UUID

import httpx
import pandas as pd
import psycopg
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .agent import AgentUnavailable, explain_operational
from .analytics import operational_snapshot
from .baseline_artifact import BaselineArtifactError, baseline_artifact_status, get_baseline_artifact
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
from .intraday_artifact import get_intraday_artifact, intraday_artifact_status
from .replay import ReplaySession
from .store import ORG_ID, SITE_ID, get_operational_data
from .tariffs import get_tariff, put_tariff
from .voice import SpeechUnavailable, TranscriptionUnavailable, synthesize_speech, transcribe_audio


operational_data_ready = Event()
operational_warmup_error: str | None = None
DEMO_ENERGY_TARGET = {
    "version": "energy-target-demo-1.0.0",
    "improvement_pct": 5.0,
    "status": "provisional_demo_target",
    "source": "Varianz demo management objective",
}
FINANCIAL_REFERENCE_AREA_M2 = 1000.0


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
    get_baseline_artifact()
    get_intraday_artifact()
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
MAX_VOICE_BYTES = 10 * 1024 * 1024
VOICE_CONTENT_TYPES = {
    "audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav",
}


class ReplayMutation(BaseModel):
    action: str
    expected_revision: int
    value: float | datetime | None = None


class AgentQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    anomaly_id: str | None = None


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)
    language: str = Field(pattern="^(en|es)$")


class TouWindow(BaseModel):
    label: str = Field(pattern="^(peak|midpeak|offpeak)$")
    days: str = Field(pattern="^(all|mon-fri|sat-sun|weekend)$")
    start: str = Field(pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    end: str = Field(pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    season: str = Field(default="all", pattern="^(all|summer|winter)$")


class TariffProfile(BaseModel):
    currency: str = Field(default="CAD", pattern="^[A-Z]{3}$")
    effective_from: date
    electricity_peak_per_kwh: float | None = Field(default=None, ge=0)
    electricity_midpeak_per_kwh: float | None = Field(default=None, ge=0)
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
    """Energy and CO2 costs require only rates used by the intraday calculation."""
    scheduled = _schedule_tariff(profile)
    rate_fields = [
        "electricity_peak_per_kwh", "electricity_midpeak_per_kwh",
        "electricity_offpeak_per_kwh", "heat_per_mj", "co2_per_kg",
    ]
    return scheduled if scheduled and all(scheduled.get(field) is not None for field in rate_fields) else None


def _historical_heat_profile(
    daily_frames: dict[pd.Timestamp, pd.DataFrame], day: pd.Timestamp
) -> pd.Series:
    """Return a causal five-minute heat shape from the previous seven complete days."""
    minutes = pd.Index(range(0, 1440, 5), name="minute")
    profiles = []
    for history_day in [item for item in sorted(daily_frames) if item < day][-7:]:
        history = daily_frames[history_day]
        total = float(history.heat_mj_m2.sum())
        if total <= 0:
            continue
        interval = history.groupby("minute").heat_mj_m2.sum().reindex(minutes, fill_value=0)
        profiles.append(interval / total)
    if not profiles:
        return pd.Series(1 / len(minutes), index=minutes, dtype=float)
    profile = pd.concat(profiles, axis=1).median(axis=1).clip(lower=0)
    total = float(profile.sum())
    return profile / total if total > 0 else pd.Series(1 / len(minutes), index=minutes)


def _performance_accounting(
    baseline: dict,
    cursor: datetime,
    intraday: pd.DataFrame,
    target: dict = DEMO_ENERGY_TARGET,
) -> dict:
    """Accumulate reconstructed actual, EnB and target energy at a five-minute grain."""
    timestamp = pd.Timestamp(cursor)
    day_start = timestamp.floor("D")
    target_factor = 1 - float(target["improvement_pct"]) / 100
    frame = intraday.copy()
    if frame.empty:
        return {
            "performance_series": [], "evaluation_start": None,
            "completed_evaluation_days": 0, "current_day_provisional": False,
            "calculation_grain_minutes": 5, "calculation_intervals": 0,
            "target": target,
        }
    frame["time"] = pd.to_datetime(frame.time, utc=True)
    frame = frame[frame.time <= timestamp].sort_values("time")
    frame["time"] = frame.time.dt.floor("5min")
    frame = frame.groupby("time", as_index=False, sort=True).agg(
        heat_mj_m2=("heat_mj_m2", "sum")
    )
    frame["day"] = frame.time.dt.floor("D")
    frame["minute"] = frame.time.dt.hour * 60 + frame.time.dt.minute
    daily_frames = {day: part.copy() for day, part in frame.groupby("day")}
    cumulative_actual = 0.0
    cumulative_baseline = 0.0
    cumulative_avoided = 0.0
    cumulative_excess = 0.0
    ledger: list[dict] = []
    evaluation_start = None
    completed_evaluation_days = 0
    current_actual = None
    current_baseline = None
    current_target = None
    reference_daily_heat = None
    try:
        predictions = get_baseline_artifact().predictions
    except BaselineArtifactError:
        predictions = ()
    baseline_by_day = {
        pd.Timestamp(item["as_of"]).floor("D"): item["baseline"]
        for item in predictions
        if item["baseline"].get("status") == "ready"
    }
    completed_daily_heat = pd.Series({
        day: float(part.heat_mj_m2.sum())
        for day, part in daily_frames.items() if day < day_start
    }).sort_index().tail(7)
    reference_daily_heat = (
        float(completed_daily_heat.median()) if not completed_daily_heat.empty else None
    )
    evaluation_days = [day for day in sorted(baseline_by_day) if day < day_start]
    if baseline.get("status") == "ready" and reference_daily_heat not in {None, 0}:
        evaluation_days.append(day_start)
    for day in evaluation_days:
        actual_day = daily_frames.get(day)
        if actual_day is None or actual_day.empty:
            continue
        if day < day_start:
            expected_daily = baseline_by_day[day].get("expected_mj_m2")
            if expected_daily in {None, 0}:
                continue
            completed_evaluation_days += 1
        else:
            expected_daily = reference_daily_heat
        evaluation_start = evaluation_start or day.isoformat()
        profile = _historical_heat_profile(daily_frames, day)
        day_actual = 0.0
        day_expected = 0.0
        for row in actual_day.itertuples():
            actual_interval = float(row.heat_mj_m2)
            expected_interval = float(expected_daily) * float(profile.loc[row.minute])
            variance = expected_interval - actual_interval
            day_actual += actual_interval
            day_expected += expected_interval
            cumulative_actual += actual_interval
            cumulative_baseline += expected_interval
            cumulative_avoided += max(variance, 0)
            cumulative_excess += max(-variance, 0)
            ledger.append({
                "time": row.time.isoformat(),
                "actual_cumulative_mj_m2": round(cumulative_actual, 4),
                "baseline_cumulative_mj_m2": round(cumulative_baseline, 4),
                "target_cumulative_mj_m2": round(cumulative_baseline * target_factor, 4),
                "net_cumulative_mj_m2": round(cumulative_baseline - cumulative_actual, 4),
            })
        if day == day_start:
            current_actual = day_actual
            current_baseline = day_expected
            current_target = day_expected * target_factor
    cumulative_target = cumulative_baseline * target_factor if cumulative_baseline > 0 else None
    max_display_points = 1200
    stride = max(1, (len(ledger) + max_display_points - 1) // max_display_points)
    series = ledger[::stride]
    if ledger and (not series or series[-1]["time"] != ledger[-1]["time"]):
        series.append(ledger[-1])
    fraction = (
        current_baseline / float(reference_daily_heat)
        if current_baseline is not None and reference_daily_heat not in {None, 0} else None
    )
    return {
        "actual_to_cursor_mj_m2": round(current_actual, 4) if current_actual is not None else None,
        "baseline_to_cursor_mj_m2": round(current_baseline, 4) if current_baseline is not None else None,
        "target_to_cursor_mj_m2": round(current_target, 4) if current_target is not None else None,
        "reference_day_fraction": round(fraction, 4) if fraction is not None else None,
        "reference_daily_heat_mj_m2": round(float(reference_daily_heat), 4) if reference_daily_heat is not None else None,
        "intraday_baseline_method": "daily EnB allocated to five-minute intervals using the median normalized heat shape of the previous seven completed days",
        "cumulative_actual_mj_m2": round(cumulative_actual, 4) if cumulative_baseline > 0 else None,
        "cumulative_baseline_mj_m2": round(cumulative_baseline, 4) if cumulative_baseline > 0 else None,
        "cumulative_target_mj_m2": round(cumulative_target, 4) if cumulative_target is not None else None,
        "cumulative_avoided_mj_m2": round(cumulative_avoided, 4) if cumulative_baseline > 0 else None,
        "cumulative_excess_mj_m2": round(cumulative_excess, 4) if cumulative_baseline > 0 else None,
        "performance_series": series,
        "evaluation_start": evaluation_start,
        "completed_evaluation_days": completed_evaluation_days,
        "current_day_provisional": bool(current_baseline is not None),
        "calculation_grain_minutes": 5,
        "calculation_intervals": len(ledger),
        "display_points": len(series),
        "evaluation_elapsed_days": round(
            max(
                (timestamp - pd.Timestamp(evaluation_start)).total_seconds() / 86400,
                5 / 1440,
            ),
            6,
        ) if evaluation_start else None,
        "target": target,
    }


def _monetized_operational_exposure(
    costed_intraday: pd.DataFrame,
    operational: pd.DataFrame,
    anomalies: list[dict],
    cursor: datetime,
    reference_area_m2: float = FINANCIAL_REFERENCE_AREA_M2,
) -> dict:
    """Price observed operating cost coincident with climate excursions and anomalies.

    Exposure is not an avoidable-cost or causal-savings estimate. Event totals may overlap;
    the aggregate anomaly exposure uses the union of event intervals to prevent double counting.
    """
    empty = {
        "climate_cost_exposure_24h_cad_per_1000m2": None,
        "climate_excursion_intervals_24h": 0,
        "climate_eligible_intervals_24h": 0,
        "anomaly_cost_exposure_7d_cad_per_1000m2": None,
        "anomaly_exposure_intervals_7d": 0,
        "monetized_anomaly_count": 0,
        "anomaly_cost_by_id": {},
        "exposure_definition": "Coincident operating cost; not verified avoidable savings.",
    }
    if costed_intraday.empty or "cost_cad_m2" not in costed_intraday:
        return empty
    costs = costed_intraday.copy()
    costs["time"] = pd.to_datetime(costs.time, utc=True).dt.floor("5min")
    costs = costs.groupby("time", as_index=False, sort=True).agg(
        cost_cad_m2=("cost_cad_m2", "sum")
    )
    costs = costs[costs.cost_cad_m2.notna()]
    if costs.empty:
        return empty

    cursor_ts = pd.Timestamp(cursor)
    climate_start = cursor_ts - pd.Timedelta(hours=24)
    climate_costs = costs[(costs.time >= climate_start) & (costs.time <= cursor_ts)]
    climate = operational.copy()
    climate["time"] = pd.to_datetime(climate.observed_at, utc=True).dt.floor("5min")
    climate = climate[(climate.time >= climate_start) & (climate.time <= cursor_ts)]
    climate = climate.groupby("time", as_index=False, sort=True).agg(
        Tair=("Tair", "last"), Rhair=("Rhair", "last")
    )
    aligned = climate_costs.merge(climate, on="time", how="inner")
    eligible = aligned.Tair.notna() & aligned.Rhair.notna()
    excursion = eligible & (~aligned.Tair.between(18, 26) | ~aligned.Rhair.between(55, 90))
    climate_exposure = float(aligned.loc[excursion, "cost_cad_m2"].sum()) * reference_area_m2

    anomaly_start = cursor_ts - pd.Timedelta(days=7)
    anomaly_costs = costs[(costs.time >= anomaly_start) & (costs.time <= cursor_ts)].copy()
    union_mask = pd.Series(False, index=anomaly_costs.index)
    anomaly_cost_by_id: dict[str, float] = {}
    for event in anomalies:
        started = max(pd.to_datetime(event["started_at"], utc=True), anomaly_start)
        duration = max(int(event.get("duration_minutes") or 0), 5)
        ended = min(
            started + pd.Timedelta(minutes=duration),
            cursor_ts + pd.Timedelta(minutes=5),
        )
        event_mask = (anomaly_costs.time >= started) & (anomaly_costs.time < ended)
        if not bool(event_mask.any()):
            continue
        anomaly_cost_by_id[event["id"]] = round(
            float(anomaly_costs.loc[event_mask, "cost_cad_m2"].sum()) * reference_area_m2,
            2,
        )
        union_mask |= event_mask
    anomaly_exposure = float(anomaly_costs.loc[union_mask, "cost_cad_m2"].sum()) * reference_area_m2
    return {
        "climate_cost_exposure_24h_cad_per_1000m2": round(climate_exposure, 2),
        "climate_excursion_intervals_24h": int(excursion.sum()),
        "climate_eligible_intervals_24h": int(eligible.sum()),
        "anomaly_cost_exposure_7d_cad_per_1000m2": round(anomaly_exposure, 2),
        "anomaly_exposure_intervals_7d": int(union_mask.sum()),
        "monetized_anomaly_count": len(anomaly_cost_by_id),
        "anomaly_cost_by_id": anomaly_cost_by_id,
        "exposure_definition": "Coincident operating cost; not verified avoidable savings.",
    }


def _business_impact(
    baseline: dict,
    tariff: dict | None,
    growing_area_m2: float,
    current_cost_cad_m2: float | None = None,
    performance: dict | None = None,
    operational_exposure: dict | None = None,
) -> dict:
    """Translate analytical evidence into stakeholder-facing, non-causal impact metrics."""
    performance = performance or {}
    operational_exposure = operational_exposure or {}
    actual = performance.get("actual_to_cursor_mj_m2")
    expected = performance.get("baseline_to_cursor_mj_m2")
    if actual is None and baseline.get("status") == "ready":
        actual = baseline.get("actual_mj_m2")
    if expected is None and baseline.get("status") == "ready":
        expected = baseline.get("expected_mj_m2")
    comparable = actual is not None and expected not in {None, 0}
    performance_pct = (
        round((float(expected) - float(actual)) / abs(float(expected)) * 100, 1)
        if comparable else None
    )
    if performance_pct is None:
        performance_state = "not_comparable"
        performance_label = "Baseline not ready"
    elif performance_pct > 5:
        performance_state = "favorable"
        performance_label = "Estimated improvement"
    elif performance_pct < -5:
        performance_state = "unfavorable"
        performance_label = "Estimated excess use"
    else:
        performance_state = "within_expected"
        performance_label = "Within expected range"

    heat_variance_cad = None
    cumulative_heat_variance_cad = None
    cumulative_avoided_heat_cost_cad = None
    cumulative_excess_heat_cost_cad = None
    cumulative_net_heat_cost_cad_per_1000m2 = None
    cumulative_avoided_heat_cost_cad_per_1000m2 = None
    cumulative_excess_heat_cost_cad_per_1000m2 = None
    current_cost_to_cursor_cad_per_1000m2 = None
    remaining_target_potential_cad_per_1000m2 = None
    remaining_target_potential_30d_run_rate_cad_per_1000m2 = None
    target_opportunity_cad_per_1000m2 = None
    heat_cost_30d_run_rate_cad_per_1000m2 = None
    remaining_target_potential_cad = None
    target_opportunity_cad = None
    cumulative_actual = performance.get("cumulative_actual_mj_m2")
    cumulative_expected = performance.get("cumulative_baseline_mj_m2")
    cumulative_target = performance.get("cumulative_target_mj_m2")
    cumulative_avoided = performance.get("cumulative_avoided_mj_m2")
    cumulative_excess = performance.get("cumulative_excess_mj_m2")
    cumulative_comparable = cumulative_actual is not None and cumulative_expected not in {None, 0}
    if tariff and tariff.get("heat_per_mj") is not None:
        heat_rate = float(tariff["heat_per_mj"])
        if comparable:
            heat_variance_cad = round(
                (float(expected) - float(actual))
                * heat_rate
                * FINANCIAL_REFERENCE_AREA_M2,
                2,
            )
        if cumulative_comparable:
            cumulative_heat_variance_cad = round(
                (float(cumulative_expected) - float(cumulative_actual))
                * heat_rate * FINANCIAL_REFERENCE_AREA_M2,
                4,
            )
            cumulative_net_heat_cost_cad_per_1000m2 = round(
                (float(cumulative_expected) - float(cumulative_actual)) * heat_rate * 1000,
                2,
            )
            elapsed_days = performance.get("evaluation_elapsed_days")
            if elapsed_days not in {None, 0}:
                heat_cost_30d_run_rate_cad_per_1000m2 = round(
                    (float(cumulative_expected) - float(cumulative_actual))
                    * heat_rate * FINANCIAL_REFERENCE_AREA_M2
                    / float(elapsed_days) * 30,
                    2,
                )
        if cumulative_avoided is not None:
            cumulative_avoided_heat_cost_cad = round(
                float(cumulative_avoided) * heat_rate * FINANCIAL_REFERENCE_AREA_M2, 4
            )
            cumulative_avoided_heat_cost_cad_per_1000m2 = round(
                float(cumulative_avoided) * heat_rate * 1000, 2
            )
        if cumulative_excess is not None:
            cumulative_excess_heat_cost_cad = round(
                float(cumulative_excess) * heat_rate * FINANCIAL_REFERENCE_AREA_M2, 4
            )
            cumulative_excess_heat_cost_cad_per_1000m2 = round(
                float(cumulative_excess) * heat_rate * 1000, 2
            )
        if cumulative_actual is not None and cumulative_target is not None:
            remaining_target_potential_cad = round(
                max(float(cumulative_actual) - float(cumulative_target), 0)
                * heat_rate * FINANCIAL_REFERENCE_AREA_M2,
                2,
            )
            remaining_target_potential_cad_per_1000m2 = round(
                max(float(cumulative_actual) - float(cumulative_target), 0)
                * heat_rate * FINANCIAL_REFERENCE_AREA_M2,
                2,
            )
            elapsed_days = performance.get("evaluation_elapsed_days")
            if elapsed_days not in {None, 0}:
                remaining_target_potential_30d_run_rate_cad_per_1000m2 = round(
                    max(float(cumulative_actual) - float(cumulative_target), 0)
                    * heat_rate * FINANCIAL_REFERENCE_AREA_M2
                    / float(elapsed_days) * 30,
                    2,
                )
        if cumulative_expected is not None and cumulative_target is not None:
            target_opportunity_cad = round(
                max(float(cumulative_expected) - float(cumulative_target), 0)
                * heat_rate * FINANCIAL_REFERENCE_AREA_M2,
                2,
            )
            target_opportunity_cad_per_1000m2 = round(
                max(float(cumulative_expected) - float(cumulative_target), 0)
                * heat_rate * FINANCIAL_REFERENCE_AREA_M2,
                2,
            )
    current_cost_cad = (
        round(current_cost_cad_m2 * FINANCIAL_REFERENCE_AREA_M2, 2)
        if current_cost_cad_m2 is not None else None
    )
    if current_cost_cad_m2 is not None:
        current_cost_to_cursor_cad_per_1000m2 = round(
            current_cost_cad_m2 * FINANCIAL_REFERENCE_AREA_M2, 2
        )
    status = (
        "baseline_required" if not comparable and not cumulative_comparable
        else "tariff_required" if tariff is None
        else "ready"
    )
    cumulative_performance_pct = (
        round((float(cumulative_expected) - float(cumulative_actual)) / abs(float(cumulative_expected)) * 100, 1)
        if cumulative_actual is not None and cumulative_expected not in {None, 0} else None
    )
    remaining_target_potential_mj_m2 = (
        round(max(float(cumulative_actual) - float(cumulative_target), 0), 3)
        if cumulative_actual is not None and cumulative_target is not None else None
    )
    target_achieved = (
        bool(float(cumulative_actual) <= float(cumulative_target))
        if cumulative_actual is not None and cumulative_target is not None else None
    )
    target = performance.get("target", DEMO_ENERGY_TARGET)
    performance_series = [dict(point) for point in performance.get("performance_series", [])]
    if tariff and tariff.get("heat_per_mj") is not None:
        heat_rate = float(tariff["heat_per_mj"])
        for point in performance_series:
            point["net_cumulative_cad"] = round(
                float(point["net_cumulative_mj_m2"])
                * heat_rate * FINANCIAL_REFERENCE_AREA_M2,
                4,
            )
            point["break_even_cad"] = 0.0
            point["net_cumulative_cad_per_1000m2"] = round(
                float(point["net_cumulative_mj_m2"])
                * heat_rate * FINANCIAL_REFERENCE_AREA_M2,
                4,
            )
            point["break_even_cad_per_1000m2"] = 0.0
    cumulative_cost_state = (
        "saving" if cumulative_heat_variance_cad is not None and cumulative_heat_variance_cad > 0
        else "overconsumption" if cumulative_heat_variance_cad is not None and cumulative_heat_variance_cad < 0
        else "balanced" if cumulative_heat_variance_cad is not None else "unavailable"
    )
    return {
        "status": status,
        "energy_performance_pct": performance_pct,
        "performance_state": performance_state,
        "performance_label": performance_label,
        "estimated_heat_cost_variance_cad": heat_variance_cad,
        "cumulative_energy_performance_pct": cumulative_performance_pct,
        "cumulative_estimated_heat_cost_variance_cad": cumulative_heat_variance_cad,
        "cumulative_cost_state": cumulative_cost_state,
        "cumulative_avoided_mj_m2": performance.get("cumulative_avoided_mj_m2"),
        "cumulative_excess_mj_m2": performance.get("cumulative_excess_mj_m2"),
        "cumulative_avoided_heat_cost_cad": cumulative_avoided_heat_cost_cad,
        "cumulative_excess_heat_cost_cad": cumulative_excess_heat_cost_cad,
        "cumulative_net_heat_cost_cad_per_1000m2": cumulative_net_heat_cost_cad_per_1000m2,
        "cumulative_avoided_heat_cost_cad_per_1000m2": cumulative_avoided_heat_cost_cad_per_1000m2,
        "cumulative_excess_heat_cost_cad_per_1000m2": cumulative_excess_heat_cost_cad_per_1000m2,
        "heat_cost_30d_run_rate_cad_per_1000m2": heat_cost_30d_run_rate_cad_per_1000m2,
        "evaluation_elapsed_days": performance.get("evaluation_elapsed_days"),
        "remaining_target_potential_mj_m2": remaining_target_potential_mj_m2,
        "remaining_target_potential_cad": remaining_target_potential_cad,
        "remaining_target_potential_cad_per_1000m2": remaining_target_potential_cad_per_1000m2,
        "remaining_target_potential_30d_run_rate_cad_per_1000m2": remaining_target_potential_30d_run_rate_cad_per_1000m2,
        "target_opportunity_cad": target_opportunity_cad,
        "target_opportunity_cad_per_1000m2": target_opportunity_cad_per_1000m2,
        "target_achieved": target_achieved,
        "target_improvement_pct": target["improvement_pct"],
        "target_version": target["version"],
        "target_status": target["status"],
        "target_source": target["source"],
        "actual_to_cursor_mj_m2": actual,
        "baseline_to_cursor_mj_m2": expected,
        "target_to_cursor_mj_m2": performance.get("target_to_cursor_mj_m2"),
        "reference_day_fraction": performance.get("reference_day_fraction"),
        "reference_daily_heat_mj_m2": performance.get("reference_daily_heat_mj_m2"),
        "intraday_baseline_method": performance.get("intraday_baseline_method"),
        "cumulative_actual_mj_m2": cumulative_actual,
        "cumulative_baseline_mj_m2": cumulative_expected,
        "cumulative_target_mj_m2": cumulative_target,
        "performance_series": performance_series,
        "evaluation_start": performance.get("evaluation_start"),
        "completed_evaluation_days": performance.get("completed_evaluation_days", 0),
        "current_day_provisional": performance.get("current_day_provisional", False),
        "calculation_grain_minutes": performance.get("calculation_grain_minutes", 5),
        "calculation_intervals": performance.get("calculation_intervals", 0),
        "display_points": performance.get("display_points", 0),
        "current_cost_to_cursor_cad": current_cost_cad,
        "current_cost_to_cursor_cad_per_1000m2": current_cost_to_cursor_cad_per_1000m2,
        "currency": tariff.get("currency") if tariff else None,
        "heat_tariff_cad_per_mj": tariff.get("heat_per_mj") if tariff else None,
        "tariff_source": tariff.get("source") if tariff else None,
        "monetary_status": "configured_scenario" if tariff else "tariff_required",
        "area_basis_m2": FINANCIAL_REFERENCE_AREA_M2,
        "source_growing_area_m2": growing_area_m2,
        "financial_reference_area_m2": FINANCIAL_REFERENCE_AREA_M2,
        "comparison_as_of": baseline.get("artifact_as_of"),
        "tariff_effective_from": tariff.get("effective_from") if tariff else None,
        "confidence": baseline.get("confidence") if comparable else None,
        "baseline_model": baseline.get("selected_model") if comparable else None,
        "cost_scope": "Stakeholder monetary values are normalized to 1,000 m2. Operating cost covers heat, electricity and CO2; performance value covers heat since EnB became available.",
        "comparison_scope": "Point-in-time and cumulative heat intensity versus weather-normalized EnB and provisional management target",
        "disclaimer": "ISO-aligned EnPI/EnB accounting; the 5% demo target is not prescribed by ISO and values are association-based estimates.",
        "tariff_application": "Configured tariff scenario applied to the historical demo replay",
        "evidence_ids": list(dict.fromkeys([
            *baseline.get("evidence_ids", []),
            f"target:{target['version']}",
            *([f"tariff:{tariff['id']}"] if tariff and tariff.get("id") else []),
        ])),
        **{key: value for key, value in operational_exposure.items() if key != "anomaly_cost_by_id"},
    }


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
        tariff_profile = get_tariff(settings.database_url, SITE_ID, date.today())
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
    observed_times = pd.to_datetime(data.operational.observed_at, utc=True)
    observations_seen = int(observed_times.searchsorted(pd.Timestamp(cursor), side="right"))
    observations_total = len(observed_times)
    data_status = (
        "good" if data.quality == "validated" and data.backend == "supabase"
        else "warning" if data.quality in {"validated", "zip_fallback"}
        else "bad"
    )
    snapshot["quality"].update({
        "data_status": data_status,
        "validation_scope": "timestamps, units, duplicates, finite ranges and source reconciliation",
        "as_of": pd.Timestamp(cursor).isoformat(),
        "coverage_start": observed_times.min().isoformat(),
        "coverage_end": observed_times.max().isoformat(),
        "data_version": snapshot["data_version"],
        "definitions_version": snapshot["definitions_version"],
    })
    day_start = pd.Timestamp(cursor).floor("D")
    performance_intraday = intraday_energy_frame(
        data.operational,
        data.resources,
        cursor,
        grain="5min",
        tou_windows=(tariff_profile or {}).get("tou_windows"),
        allocated_cache=data.intraday_cache,
        calibrations=data.energy_calibrations,
        start=pd.to_datetime(data.operational.observed_at, utc=True).min(),
        cache_source=data.intraday_backend,
    )
    current_cost_cad_m2 = None
    costed_intraday = apply_intraday_cost(performance_intraday, tariff)
    if tariff:
        current_day = costed_intraday[
            pd.to_datetime(costed_intraday.time, utc=True).dt.floor("D") == day_start
        ]
        costs = current_day["cost_cad_m2"].dropna()
        current_cost_cad_m2 = float(costs.sum()) if not costs.empty else None
    performance = _performance_accounting(
        snapshot["baseline"], cursor, performance_intraday
    )
    exposure = _monetized_operational_exposure(
        costed_intraday, data.operational, snapshot["anomalies"], cursor
    )
    anomaly_cost_by_id = exposure.get("anomaly_cost_by_id", {})
    for event in snapshot["anomalies"]:
        event["cost_exposure_cad_per_1000m2"] = anomaly_cost_by_id.get(event["id"])
        event["cost_exposure_scope"] = exposure["exposure_definition"]
    snapshot["business_impact"] = _business_impact(
        snapshot["baseline"], tariff, 62.5, current_cost_cad_m2, performance, exposure
    )
    snapshot["evidence_ids"] = list(dict.fromkeys([
        *snapshot["evidence_ids"], *snapshot["business_impact"]["evidence_ids"]
    ]))
    return {
        "session_id": session.id,
        "revision": session.revision,
        "playing": session.playing,
        "speed": session.speed,
        "replay": {
            "minimum": session.minimum.isoformat(),
            "maximum": session.maximum.isoformat(),
            "observations_seen": observations_seen,
            "observations_total": observations_total,
            "progress_pct": round(observations_seen / max(observations_total, 1) * 100, 1),
        },
        "site": {
            "id": SITE_ID,
            "name": "Wageningen Demo Reference Greenhouse",
            "area_m2": 96,
            "growing_area_m2": 62.5,
            "timezone": "Europe/Amsterdam",
        },
        **snapshot,
    }


def _intraday_summary(frame: pd.DataFrame, cursor: pd.Timestamp) -> dict:
    times = pd.to_datetime(frame.time, utc=True)
    current = frame[times.dt.floor("D") == cursor.floor("D")]
    columns = {
        "heat": ("heat_mj_m2", "MJ/m2/h", "MJ/m2"),
        "electricity": ("elec_kwh_m2", "kW/m2", "kWh/m2"),
        "co2": ("co2_kg_m2", "kg/m2/h", "kg/m2"),
    }
    signals = {}
    for name, (column, rate_unit, accumulated_unit) in columns.items():
        values = current[column].dropna() if column in current else pd.Series(dtype=float)
        if values.empty:
            signals[name] = {
                "status": "unavailable", "current_rate": None, "accumulated": None,
                "rate_unit": rate_unit, "accumulated_unit": accumulated_unit,
                "quality": "missing", "is_exact_zero": False, "is_small_nonzero": False,
            }
            continue
        latest = float(values.iloc[-1])
        accumulated = float(values.sum())
        quality = str(current.loc[values.index[-1], "quality"])
        is_zero = latest == 0
        rate = latest * 12  # five-minute energy allocated as an hourly equivalent rate
        signals[name] = {
            "status": (
                "estimated_zero" if is_zero and quality == "provisional"
                else "measured_zero" if is_zero
                else "estimated" if quality == "provisional"
                else "reconciled"
            ),
            "current_rate": round(rate, 8),
            "accumulated": round(accumulated, 8),
            "rate_unit": rate_unit,
            "accumulated_unit": accumulated_unit,
            "quality": quality,
            "is_exact_zero": is_zero,
            "is_small_nonzero": not is_zero and abs(rate) < 0.01,
        }
    electricity = float(current.elec_kwh_m2.sum()) if not current.empty else 0
    signals["tou_shares"] = {
        "peak_pct": None if electricity <= 0 else round(float(current.elec_peak_kwh_m2.sum()) / electricity * 100, 1),
        "midpeak_pct": None if electricity <= 0 else round(float(current.elec_midpeak_kwh_m2.sum()) / electricity * 100, 1),
        "offpeak_pct": None if electricity <= 0 else round(float(current.elec_offpeak_kwh_m2.sum()) / electricity * 100, 1),
    }
    signals["interval_minutes"] = 5
    return signals


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
            "business_impact",
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
        "baseline_artifact": baseline_artifact_status(),
        "intraday_artifact": intraday_artifact_status(),
    }


@api.get("/ready")
def readiness():
    if not _data_is_ready():
        return JSONResponse(
            status_code=503,
            content={"ready": False, "state": "loading_operational_history"},
            headers={"Retry-After": "3"},
        )
    return {
        "ready": True,
        "state": "ready",
        "baseline_artifact": baseline_artifact_status(),
        "intraday_artifact": intraday_artifact_status(),
    }


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
        tariff_profile = get_tariff(settings.database_url, SITE_ID, date.today())
    except psycopg.Error:
        tariff_profile = None
    schedule_tariff = _schedule_tariff(tariff_profile)
    cost_tariff = _cost_tariff(tariff_profile)
    tou_windows = schedule_tariff.get("tou_windows") if schedule_tariff else None
    intraday_start = None if window == "all" else cursor - pd.Timedelta(days=7)
    five_min_intraday = intraday_energy_frame(
        data.operational, data.resources, cursor.to_pydatetime(), grain="5min",
        tou_windows=tou_windows, allocated_cache=data.intraday_cache,
        calibrations=data.energy_calibrations, start=intraday_start,
        cache_source=data.intraday_backend,
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
        data.operational, data.resources, cursor.to_pydatetime(),
        calibrations=data.energy_calibrations,
        cache_source=data.intraday_backend,
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
            "definitions_version", "model_version", "quality", "replay", "evidence_ids", "kpis",
            "baseline", "resource_series", "anomalies", "tariff", "metric_definitions",
            "business_impact",
        ]
    }
    base["evidence_ids"] = list(dict.fromkeys([
        *base["evidence_ids"], *reconstruction["evidence_ids"],
        *(evidence for item in efficiency_anomalies for evidence in item["evidence_ids"]),
    ]))
    base["intraday"] = {
        "grain": grain,
        "series": records,
        "summary": _intraday_summary(five_min_intraday, cursor),
        "reconstruction": reconstruction,
        "serving_source": five_min_intraday.attrs.get("serving_source"),
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
            "definitions_version", "model_version", "quality", "replay", "evidence_ids", "kpis",
            "latest", "climate_series", "anomalies", "metric_definitions", "business_impact",
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
            "model_version", "quality", "replay", "evidence_ids", "anomalies",
            "business_impact",
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
        tariff_profile = get_tariff(settings.database_url, SITE_ID, date.today())
    except psycopg.Error:
        tariff_profile = None
    schedule_tariff = _schedule_tariff(tariff_profile)
    intraday = intraday_energy_frame(
        data.operational, data.resources, cursor.to_pydatetime(), grain="5min",
        tou_windows=schedule_tariff.get("tou_windows") if schedule_tariff else None,
        allocated_cache=data.intraday_cache, calibrations=data.energy_calibrations,
        start=cursor - pd.Timedelta(days=7),
        cache_source=data.intraday_backend,
    )
    snapshot["efficiency"] = efficiency_indicators(
        intraday, data.operational, data.resources, cursor.to_pydatetime(), schedule_tariff,
    )
    snapshot["reconstruction"] = reconstruction_metadata(
        data.operational, data.resources, cursor.to_pydatetime(),
        calibrations=data.energy_calibrations,
        cache_source=data.intraday_backend,
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


@api.post("/replay-sessions/{session_id}/assistant/transcriptions")
async def assistant_transcription(
    session_id: UUID,
    audio: UploadFile = File(...),
    principal: Principal = Depends(current_principal),
):
    _session(session_id, principal)
    content_type = (audio.content_type or "").split(";", 1)[0].lower()
    if content_type not in VOICE_CONTENT_TYPES:
        raise HTTPException(415, "unsupported_audio_format")
    content = await audio.read(MAX_VOICE_BYTES + 1)
    await audio.close()
    if not content:
        raise HTTPException(422, "empty_audio")
    if len(content) > MAX_VOICE_BYTES:
        raise HTTPException(413, "audio_too_large")
    try:
        result = await transcribe_audio(
            content,
            audio.filename or "varianz-voice.webm",
            content_type,
            settings,
        )
    except TranscriptionUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "session_id": session_id,
        "transcript": result["text"],
        "model": result["model"],
        "language": "auto",
    }


@api.post("/replay-sessions/{session_id}/assistant/speech")
async def assistant_speech(
    session_id: UUID,
    request: SpeechRequest,
    principal: Principal = Depends(current_principal),
):
    _session(session_id, principal)
    try:
        result = await synthesize_speech(
            request.text.strip(), request.language, settings
        )
    except SpeechUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(
        content=result["audio"],
        media_type=result["content_type"],
        headers={
            "Cache-Control": "private, no-store",
            "X-Varianz-Speech-Model": result["model"],
            "X-Varianz-Voice": result["voice"],
            "X-Varianz-Language": result["language"],
        },
    )


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
