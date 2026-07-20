from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from .intraday_artifact import IntradayArtifactError, get_intraday_artifact
from .metrics import ENERGY_MODEL_VERSION

DEFAULT_TOU_WINDOWS: list[dict] = []
QUALITY_ORDER = {"allocated": 0, "measured": 0, "provisional": 1, "imputed": 2}


def _evidence(name: str, cursor: datetime) -> str:
    token = hashlib.sha256(f"{name}:{cursor.isoformat()}:{ENERGY_MODEL_VERSION}".encode()).hexdigest()[:14]
    return f"ev_{token}"


def _proxy_frame(operational: pd.DataFrame) -> pd.DataFrame:
    frame = operational.copy()
    for code in ["PipeLow", "PipeGrow", "Tair", "Tot_PAR_Lamps", "AssimLight", "co2_dos"]:
        if code not in frame:
            frame[code] = np.nan
    frame["heat_proxy"] = (
        (frame.PipeLow - frame.Tair).clip(lower=0).fillna(0)
        + (frame.PipeGrow - frame.Tair).clip(lower=0).fillna(0)
    )
    lamp = frame.Tot_PAR_Lamps.clip(lower=0)
    frame["elec_proxy"] = lamp.where(lamp.notna(), frame.AssimLight.clip(lower=0)).fillna(0)
    frame["co2_proxy"] = frame.co2_dos.clip(lower=0).fillna(0)
    return frame


def _day_key(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True).dt.floor("D")


def _day_matches(day_index: pd.DatetimeIndex, rule: str) -> np.ndarray:
    rule = rule.lower()
    if rule == "mon-fri":
        return np.asarray(day_index.dayofweek < 5)
    if rule in {"sat-sun", "weekend"}:
        return np.asarray(day_index.dayofweek >= 5)
    return np.ones(len(day_index), dtype=bool)


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (occurrence - 1))


def _easter_sunday(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    weekday_correction = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday_correction) // 451
    month = (h + weekday_correction - 7 * m + 114) // 31
    day = (h + weekday_correction - 7 * m + 114) % 31 + 1
    return date(year, month, day)


@lru_cache(maxsize=32)
def ontario_tou_holidays(year: int) -> frozenset[date]:
    holidays = {
        date(year, 1, 1),
        _nth_weekday(year, 2, 0, 3),  # Family Day
        _easter_sunday(year) - timedelta(days=2),
        date(year, 5, 25) - timedelta(
            days=((date(year, 5, 25).weekday() - 0) % 7 or 7)
        ),
        date(year, 7, 1),
        _nth_weekday(year, 8, 0, 1),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    observed = set(holidays)
    occupied = set(holidays)
    for holiday in sorted(holidays):
        if holiday.weekday() < 5:
            continue
        candidate = holiday + timedelta(days=1)
        while candidate.weekday() >= 5 or candidate in occupied:
            candidate += timedelta(days=1)
        observed.add(candidate)
        occupied.add(candidate)
    return frozenset(observed)


def tou_period_masks(
    times: pd.Series,
    windows: list[dict] | None = None,
    timezone: str = "America/Toronto",
) -> dict[str, np.ndarray]:
    local = pd.DatetimeIndex(pd.to_datetime(times, utc=True)).tz_convert(timezone)
    minutes = local.hour * 60 + local.minute
    periods = np.full(len(local), "offpeak", dtype=object)
    holidays = np.asarray([
        timestamp.date() in ontario_tou_holidays(timestamp.year) for timestamp in local
    ])
    summer = np.asarray((local.month >= 5) & (local.month <= 10))
    for window in windows or DEFAULT_TOU_WINDOWS:
        label = str(window.get("label", "")).lower()
        if label not in {"peak", "midpeak", "offpeak"}:
            continue
        start_h, start_m = map(int, str(window["start"]).split(":"))
        end_h, end_m = map(int, str(window["end"]).split(":"))
        start, end = start_h * 60 + start_m, end_h * 60 + end_m
        clock = (minutes >= start) & (minutes < end) if start < end else (minutes >= start) | (minutes < end)
        season = str(window.get("season", "all")).lower()
        season_match = summer if season == "summer" else ~summer if season == "winter" else True
        match = clock & _day_matches(local, str(window.get("days", "all"))) & season_match
        if label != "offpeak":
            match &= ~holidays
        periods[match] = label
    return {label: np.asarray(periods == label) for label in ("peak", "midpeak", "offpeak")}


def tou_peak_mask(
    times: pd.Series,
    windows: list[dict] | None = None,
    timezone: str = "America/Toronto",
) -> np.ndarray:
    return tou_period_masks(times, windows, timezone)["peak"]


def _rolling_factor(
    proxy_daily: pd.Series,
    meter_daily: pd.Series,
    before: pd.Timestamp,
    calibration_days: int,
) -> float:
    joined = pd.concat([proxy_daily.rename("proxy"), meter_daily.rename("meter")], axis=1).dropna()
    joined = joined[(joined.index < before) & (joined.proxy > 0)].tail(calibration_days)
    if len(joined) < 3:
        return 0.0
    return float((joined.meter / joined.proxy).median())


def aggregate_intraday(intraday: pd.DataFrame, grain: str) -> pd.DataFrame:
    if grain == "5min" or intraday.empty:
        return intraday.reset_index(drop=True)
    if grain != "1h":
        raise ValueError("invalid_energy_grain")
    sums = [
        "heat_mj_m2", "elec_kwh_m2", "co2_kg_m2",
        "elec_peak_kwh_m2", "elec_midpeak_kwh_m2", "elec_offpeak_kwh_m2",
        "cost_cad_m2",
    ]
    hourly = intraday.set_index("time").resample("1h").agg(
        {**{column: "sum" for column in sums}, "quality": lambda values: max(values, key=lambda x: QUALITY_ORDER[x])}
    )
    return hourly.reset_index()


def compute_intraday_energy_frame(
    operational: pd.DataFrame,
    resources: pd.DataFrame,
    cursor: datetime,
    *,
    grain: str = "5min",
    calibration_days: int = 7,
    tou_windows: list[dict] | None = None,
) -> pd.DataFrame:
    """Meter-conserving disaggregation; the incomplete current day uses past calibration only."""
    if grain not in {"5min", "1h"}:
        raise ValueError("invalid_energy_grain")
    cursor_ts = pd.Timestamp(cursor)
    if cursor_ts.tzinfo is None:
        cursor_ts = cursor_ts.tz_localize("UTC")
    visible = operational[pd.to_datetime(operational.observed_at, utc=True) <= cursor_ts].copy()
    if visible.empty:
        return pd.DataFrame(columns=[
            "time", "heat_mj_m2", "elec_kwh_m2", "co2_kg_m2",
            "elec_peak_kwh_m2", "elec_midpeak_kwh_m2", "elec_offpeak_kwh_m2",
            "cost_cad_m2", "quality",
        ])
    frame = _proxy_frame(visible).sort_values("observed_at").reset_index(drop=True)
    frame["day"] = _day_key(frame.observed_at)
    current_day = cursor_ts.floor("D")

    meters = resources.copy()
    meters["day"] = _day_key(meters.observed_at)
    meters = meters[meters.day < current_day].drop_duplicates("day", keep="last").set_index("day")
    meters["elec_total"] = meters.ElecHigh.fillna(0) + meters.ElecLow.fillna(0)
    proxy_daily = frame.groupby("day")[["heat_proxy", "elec_proxy", "co2_proxy"]].sum()
    meter_columns = {
        "heat": ("heat_proxy", "Heat_cons"),
        "elec": ("elec_proxy", "elec_total"),
        "co2": ("co2_proxy", "CO2_cons"),
    }
    frame["quality"] = "allocated"
    for channel, (proxy_code, meter_code) in meter_columns.items():
        output = f"{channel}_{'kwh_m2' if channel == 'elec' else 'kg_m2' if channel == 'co2' else 'mj_m2'}"
        frame[output] = 0.0
        factor = _rolling_factor(
            proxy_daily[proxy_code], meters[meter_code] if meter_code in meters else pd.Series(dtype=float),
            current_day, calibration_days,
        )
        for day, indexes in frame.groupby("day").groups.items():
            proxy = frame.loc[indexes, proxy_code].astype(float)
            if day < current_day and day in meters.index:
                total = float(meters.loc[day, meter_code])
                denominator = float(proxy.sum())
                if denominator > 0:
                    frame.loc[indexes, output] = total * proxy / denominator
                else:
                    frame.loc[indexes, output] = total / len(indexes)
                    frame.loc[indexes, "quality"] = "imputed"
            else:
                frame.loc[indexes, output] = factor * proxy
                frame.loc[indexes, "quality"] = "provisional"

    periods = tou_period_masks(frame.observed_at, tou_windows)
    frame["elec_peak_kwh_m2"] = frame.elec_kwh_m2.where(periods["peak"], 0.0)
    frame["elec_midpeak_kwh_m2"] = frame.elec_kwh_m2.where(periods["midpeak"], 0.0)
    frame["elec_offpeak_kwh_m2"] = frame.elec_kwh_m2.where(periods["offpeak"], 0.0)
    frame["cost_cad_m2"] = np.nan
    result = frame.rename(columns={"observed_at": "time"})[[
        "time", "heat_mj_m2", "elec_kwh_m2", "co2_kg_m2",
        "elec_peak_kwh_m2", "elec_midpeak_kwh_m2", "elec_offpeak_kwh_m2",
        "cost_cad_m2", "quality",
    ]]
    return aggregate_intraday(result, grain)


def build_intraday_materialization(
    operational: pd.DataFrame,
    resources: pd.DataFrame,
    calibration_days: int = 7,
) -> tuple[pd.DataFrame, dict[str, dict]]:
    """Build immutable completed-day allocations and causal factors for every replay day."""
    end = pd.to_datetime(operational.observed_at, utc=True).max() + pd.Timedelta(days=1)
    complete = compute_intraday_energy_frame(
        operational, resources, end.to_pydatetime(), grain="5min",
        calibration_days=calibration_days,
    )
    allocated = complete[complete.quality != "provisional"].reset_index(drop=True)
    allocated = allocated[[
        "time", "heat_mj_m2", "elec_kwh_m2", "co2_kg_m2", "quality",
    ]]

    proxy = _proxy_frame(operational.copy())
    proxy["day"] = _day_key(proxy.observed_at)
    proxy_daily = proxy.groupby("day")[["heat_proxy", "elec_proxy", "co2_proxy"]].sum()
    meters = resources.copy()
    meters["day"] = _day_key(meters.observed_at)
    meters = meters.drop_duplicates("day", keep="last").set_index("day")
    meters["elec_total"] = meters.ElecHigh.fillna(0) + meters.ElecLow.fillna(0)
    channels = {
        "heat": ("heat_proxy", "Heat_cons"),
        "elec": ("elec_proxy", "elec_total"),
        "co2": ("co2_proxy", "CO2_cons"),
    }
    calibrations: dict[str, dict] = {}
    for day in sorted(proxy.day.unique()):
        factors = {
            channel: _rolling_factor(
                proxy_daily[proxy_code], meters[meter_code], day, calibration_days,
            )
            for channel, (proxy_code, meter_code) in channels.items()
        }
        calibrations[pd.Timestamp(day).date().isoformat()] = {
            "as_of": pd.Timestamp(day).isoformat(),
            "training_days": calibration_days,
            "factors": factors,
            "fit_r2": reconstruction_fit(operational, resources, pd.Timestamp(day).to_pydatetime()),
        }
    return allocated, calibrations


def intraday_energy_frame(
    operational: pd.DataFrame,
    resources: pd.DataFrame,
    cursor: datetime,
    *,
    grain: str = "5min",
    calibration_days: int = 7,
    tou_windows: list[dict] | None = None,
    allocated_cache: pd.DataFrame | None = None,
    calibrations: dict[str, dict] | None = None,
    start: datetime | pd.Timestamp | None = None,
    cache_source: str | None = None,
) -> pd.DataFrame:
    """Read completed allocations and transform only intervals without an official meter."""
    artifact_id = None
    if allocated_cache is None or calibrations is None:
        try:
            artifact = get_intraday_artifact()
            allocated_cache = artifact.allocated
            calibrations = artifact.calibrations
            artifact_id = artifact.artifact_id
        except IntradayArtifactError:
            result = compute_intraday_energy_frame(
                operational, resources, cursor, grain=grain,
                calibration_days=calibration_days, tou_windows=tou_windows,
            )
            if start is not None:
                result = result[pd.to_datetime(result.time, utc=True) >= pd.Timestamp(start)]
            result.attrs["serving_source"] = "runtime_fallback"
            return result

    cursor_ts = pd.Timestamp(cursor)
    if cursor_ts.tzinfo is None:
        cursor_ts = cursor_ts.tz_localize("UTC")
    current_day = cursor_ts.floor("D")
    cache = allocated_cache
    cache_times = pd.to_datetime(cache.time, utc=True)
    history_mask = (cache_times <= cursor_ts) & (cache_times < current_day)
    if start is not None:
        history_mask &= cache_times >= pd.Timestamp(start)
    history = cache.loc[history_mask].copy()
    cached_days = set(_day_key(history.time).unique())

    operational_times = pd.to_datetime(operational.observed_at, utc=True)
    visible_mask = operational_times <= cursor_ts
    if start is not None:
        visible_mask &= operational_times >= pd.Timestamp(start)
    visible = operational.loc[visible_mask].copy()
    visible["day"] = _day_key(visible.observed_at)
    unresolved = visible[(visible.day >= current_day) | (~visible.day.isin(cached_days))]
    provisional_parts = []
    if not unresolved.empty:
        proxy = _proxy_frame(unresolved).sort_values("observed_at")
        for day, part in proxy.groupby("day"):
            calibration = calibrations.get(pd.Timestamp(day).date().isoformat())
            if calibration is None:
                fallback = compute_intraday_energy_frame(
                    operational, resources, cursor, grain=grain,
                    calibration_days=calibration_days, tou_windows=tou_windows,
                )
                if start is not None:
                    fallback = fallback[
                        pd.to_datetime(fallback.time, utc=True) >= pd.Timestamp(start)
                    ]
                fallback.attrs["serving_source"] = "runtime_fallback"
                return fallback
            provisional_parts.append(pd.DataFrame({
                "time": pd.to_datetime(part.observed_at, utc=True),
                "heat_mj_m2": calibration["factors"]["heat"] * part.heat_proxy,
                "elec_kwh_m2": calibration["factors"]["elec"] * part.elec_proxy,
                "co2_kg_m2": calibration["factors"]["co2"] * part.co2_proxy,
                "quality": "provisional",
            }))
    result = pd.concat([history, *provisional_parts], ignore_index=True).sort_values("time")
    periods = tou_period_masks(result.time, tou_windows)
    result["elec_peak_kwh_m2"] = result.elec_kwh_m2.where(periods["peak"], 0.0)
    result["elec_midpeak_kwh_m2"] = result.elec_kwh_m2.where(periods["midpeak"], 0.0)
    result["elec_offpeak_kwh_m2"] = result.elec_kwh_m2.where(periods["offpeak"], 0.0)
    result["cost_cad_m2"] = np.nan
    result = aggregate_intraday(result, grain)
    result.attrs["serving_source"] = cache_source or (
        "materialized_cache" if artifact_id is None else "versioned_artifact"
    )
    result.attrs["artifact_id"] = artifact_id
    return result


def apply_intraday_cost(intraday: pd.DataFrame, tariff: dict | None) -> pd.DataFrame:
    result = intraday.copy()
    if not tariff or result.empty:
        result["cost_cad_m2"] = np.nan
        return result
    result["cost_cad_m2"] = (
        result.elec_peak_kwh_m2 * tariff["electricity_peak_per_kwh"]
        + result.elec_midpeak_kwh_m2 * tariff["electricity_midpeak_per_kwh"]
        + result.elec_offpeak_kwh_m2 * tariff["electricity_offpeak_per_kwh"]
        + result.heat_mj_m2 * tariff["heat_per_mj"]
        + result.co2_kg_m2 * tariff["co2_per_kg"]
    )
    return result


def reconstruction_fit(
    operational: pd.DataFrame, resources: pd.DataFrame, cursor: datetime
) -> dict[str, float | None]:
    cursor_day = pd.Timestamp(cursor).floor("D")
    proxy = _proxy_frame(operational.copy())
    proxy["day"] = _day_key(proxy.observed_at)
    daily = proxy[proxy.day < cursor_day].groupby("day")[["heat_proxy", "elec_proxy", "co2_proxy"]].sum()
    meter = resources.copy()
    meter["day"] = _day_key(meter.observed_at)
    meter = meter[meter.day < cursor_day].set_index("day")
    meter["elec_total"] = meter.ElecHigh.fillna(0) + meter.ElecLow.fillna(0)
    output = {}
    for channel, left, right in [
        ("heat", "heat_proxy", "Heat_cons"), ("elec", "elec_proxy", "elec_total"), ("co2", "co2_proxy", "CO2_cons")
    ]:
        joined = pd.concat([daily[left], meter[right]], axis=1).dropna()
        if len(joined) < 3 or joined.iloc[:, 0].std() == 0 or joined.iloc[:, 1].std() == 0:
            output[channel] = None
        else:
            output[channel] = round(float(np.corrcoef(joined.iloc[:, 0], joined.iloc[:, 1])[0, 1] ** 2), 3)
    return output


def reconstruction_metadata(
    operational: pd.DataFrame,
    resources: pd.DataFrame,
    cursor: datetime,
    calibration_days: int = 7,
    calibrations: dict[str, dict] | None = None,
    cache_source: str | None = None,
) -> dict:
    artifact_id = None
    if calibrations is None:
        try:
            artifact = get_intraday_artifact()
            calibrations = artifact.calibrations
            artifact_id = artifact.artifact_id
        except IntradayArtifactError:
            calibrations = {}
    calibration = calibrations.get(pd.Timestamp(cursor).date().isoformat())
    return {
        "method": "meter-conserving disaggregation",
        "calibration_days": calibration_days,
        "model_version": ENERGY_MODEL_VERSION,
        "fit_r2": calibration["fit_r2"] if calibration else reconstruction_fit(operational, resources, cursor),
        "serving_source": (cache_source or "materialized_cache") if calibration and artifact_id is None else (
            "versioned_artifact" if calibration else "runtime_fallback"
        ),
        "artifact_id": artifact_id,
        "evidence_ids": [
            _evidence("intraday:heat", cursor),
            _evidence("intraday:electricity", cursor),
            _evidence("intraday:co2", cursor),
        ],
    }


def _indicator(
    value: float | None,
    unit: str,
    cursor: datetime,
    relevant_variables: list[str],
    *,
    expected: float | None = None,
    confidence: str = "medium",
    unavailable_reason: str | None = None,
    direction: str = "lower_is_better",
    tolerance_pct: float = 5,
) -> dict:
    variance = None if value is None or expected in {None, 0} else round((value - expected) / expected * 100, 1)
    if variance is None:
        performance_status = "not_comparable"
        interpretation = "No validated expectation is available for this replay cursor."
    elif abs(variance) <= tolerance_pct:
        performance_status = "within_expected"
        interpretation = "Within the expected operating range."
    elif (variance < 0 and direction == "lower_is_better") or (
        variance > 0 and direction == "higher_is_better"
    ):
        performance_status = "favorable"
        interpretation = "Favorable versus expected; confirm climate and production guardrails."
    else:
        performance_status = "unfavorable"
        interpretation = "Unfavorable versus expected; review the contributing operating signals."
    numeric = None if value is None else float(value)
    return {
        "status": "ready" if value is not None else "insufficient_data",
        "value": None if numeric is None else round(numeric, 6),
        "unit": unit,
        "expected": None if expected is None else round(float(expected), 6),
        "variance_pct": variance,
        "direction": direction,
        "performance_status": performance_status,
        "interpretation": interpretation,
        "display_precision": 4 if numeric is not None and abs(numeric) < 0.1 else 2,
        "comparison_basis": "Current day to replay cursor vs median of previous seven completed days",
        "stability": "provisional_intraday",
        "confidence": confidence,
        "unavailable_reason": unavailable_reason if value is None else None,
        "relevant_variables": relevant_variables,
        "evidence_ids": [_evidence("enpi:" + ":".join(relevant_variables), cursor)],
    }


def efficiency_indicators(
    intraday: pd.DataFrame,
    operational: pd.DataFrame,
    resources: pd.DataFrame,
    cursor: datetime,
    tariff: dict | None,
) -> dict:
    if intraday.empty:
        empty = _indicator(None, "not available", cursor, [])
        return {"lighting_efficacy": empty, "heat_degree_intensity": empty, "peak_share": empty, "simultaneity_index": empty}
    current_day = pd.Timestamp(cursor).floor("D")
    day_energy = intraday[_day_key(intraday.time) == current_day]
    operational_times = pd.to_datetime(operational.observed_at, utc=True)
    history_start = current_day - pd.Timedelta(days=8)
    op = operational[
        (operational_times <= pd.Timestamp(cursor)) & (operational_times >= history_start)
    ].copy()
    op["day"] = _day_key(op.observed_at)
    op_day = op[_day_key(op.observed_at) == current_day]
    step_hours = 5 / 60
    lamp_mol = float(op_day.get("Tot_PAR_Lamps", pd.Series(dtype=float)).clip(lower=0).fillna(0).sum() * 300 / 1e6)
    lighting = None if lamp_mol <= 0 else float(day_energy.elec_kwh_m2.sum() / lamp_mol)
    degree_hours = float((op_day.get("t_heat_vip", 0) - op_day.get("Tout", 0)).clip(lower=0).fillna(0).sum() * step_hours)
    heat_degree = None if degree_hours <= 0 else float(day_energy.heat_mj_m2.sum() / degree_hours)
    electricity = float(day_energy.elec_kwh_m2.sum())
    peak_share = None if not tariff or electricity <= 0 else float(day_energy.elec_peak_kwh_m2.sum() / electricity * 100)

    daily_op = op[op.day < current_day].groupby("day").agg(
        lamp_mol=("Tot_PAR_Lamps", lambda values: values.clip(lower=0).fillna(0).sum() * 300 / 1e6),
        degree_hours=("t_heat_vip", lambda values: 0.0),
    )
    degree_steps = (op.t_heat_vip - op.Tout).clip(lower=0).fillna(0) * step_hours
    daily_op["degree_hours"] = degree_steps.groupby(op.day).sum().reindex(daily_op.index)
    meter = resources.copy()
    meter["day"] = _day_key(meter.observed_at)
    meter = meter[meter.day < current_day].drop_duplicates("day", keep="last").set_index("day")
    meter["elec_total"] = meter.ElecHigh.fillna(0) + meter.ElecLow.fillna(0)
    history = daily_op.join(meter[["Heat_cons", "elec_total"]], how="inner").tail(7)
    lighting_history = (history.elec_total / history.lamp_mol.where(history.lamp_mol > 0)).dropna()
    heat_history = (history.Heat_cons / history.degree_hours.where(history.degree_hours > 0)).dropna()
    lighting_expected = float(lighting_history.median()) if len(lighting_history) >= 3 else None
    heat_expected = float(heat_history.median()) if len(heat_history) >= 3 else None
    peak_history = intraday[_day_key(intraday.time) < current_day].copy()
    if tariff and not peak_history.empty:
        peak_daily = peak_history.groupby(_day_key(peak_history.time)).agg(
            peak=("elec_peak_kwh_m2", "sum"), total=("elec_kwh_m2", "sum")
        )
        shares = (peak_daily.peak / peak_daily.total.where(peak_daily.total > 0) * 100).dropna().tail(7)
        peak_expected = float(shares.median()) if len(shares) >= 3 else None
    else:
        peak_expected = None

    aligned = day_energy.copy().set_index(pd.to_datetime(day_energy.time, utc=True))
    states = op_day.copy().set_index(pd.to_datetime(op_day.observed_at, utc=True)).reindex(aligned.index, method="nearest", tolerance=pd.Timedelta(minutes=3))
    heat_total, light_total = float(aligned.heat_mj_m2.sum()), float(aligned.elec_kwh_m2.sum())
    heat_fraction = 0 if heat_total <= 0 else float(aligned.heat_mj_m2.where(states.VentLee.fillna(0) > 10, 0).sum() / heat_total)
    light_fraction = 0 if light_total <= 0 else float(aligned.elec_kwh_m2.where(states.Iglob.fillna(0) > 300, 0).sum() / light_total)
    simultaneity = (heat_fraction + light_fraction) / 2 * 100
    return {
        "model_version": ENERGY_MODEL_VERSION,
        "lighting_efficacy": _indicator(lighting, "kWh/mol PAR", cursor, ["Lamp PAR contribution", "Electricity consumption"], expected=lighting_expected),
        "heat_degree_intensity": _indicator(heat_degree, "MJ/m2 per degC-hour", cursor, ["Heating energy", "Realized heating setpoint", "Outside temperature"], expected=heat_expected),
        "peak_share": _indicator(
            peak_share, "%", cursor,
            ["Electricity consumption", "Ontario time-of-use schedule"],
            expected=peak_expected, confidence="high",
            unavailable_reason="Configure a sourced Ontario time-of-use schedule in Settings.",
        ),
        "simultaneity_index": _indicator(simultaneity, "% observed in counterproductive states", cursor, ["Heating energy", "Leeward vents opening", "Lamp PAR contribution", "Solar radiation"]),
    }


def _events_from_mask(
    frame: pd.DataFrame,
    mask: pd.Series,
    code: str,
    message: str,
    cursor: datetime,
    contributors: list[str],
) -> list[dict]:
    selected = frame[mask.fillna(False)].copy()
    if selected.empty:
        return []
    selected["group"] = (selected.time.diff() > pd.Timedelta(minutes=10)).cumsum()
    events = []
    for _, group in selected.groupby("group"):
        if len(group) < 3:
            continue
        started, ended = group.time.iloc[0], group.time.iloc[-1]
        events.append({
            "id": hashlib.sha256(f"{code}:{started}".encode()).hexdigest()[:16],
            "code": code, "category": "efficiency", "severity": "medium",
            "message": message, "started_at": started.isoformat(),
            "duration_minutes": int((ended - started).total_seconds() / 60) + 5,
            "observed": None, "expected": None, "residual": None, "confidence": "medium",
            "contributors": contributors, "evidence_ids": [_evidence(code, cursor)],
            "model_version": ENERGY_MODEL_VERSION, "active": ended >= pd.Timestamp(cursor) - pd.Timedelta(minutes=10),
        })
    return events


def efficiency_events(
    operational: pd.DataFrame,
    cursor: datetime,
    tou_windows: list[dict] | None = None,
) -> list[dict]:
    frame = _proxy_frame(operational[pd.to_datetime(operational.observed_at, utc=True) <= pd.Timestamp(cursor)].copy())
    frame = frame.rename(columns={"observed_at": "time"})
    recent = frame[frame.time >= pd.Timestamp(cursor) - pd.Timedelta(days=7)].copy()
    if recent.empty:
        return []
    pipe_threshold = max(2.0, float(recent.heat_proxy[recent.heat_proxy > 0].quantile(0.75)))
    events = []
    events += _events_from_mask(recent, (recent.heat_proxy >= pipe_threshold) & (recent.VentLee > 10), "heating_against_ventilation", "Heat was delivered while leeward vents were open.", cursor, ["Rail and crop pipe temperatures", "Greenhouse air temperature", "Leeward vents opening"])
    events += _events_from_mask(recent, (recent.elec_proxy > 0) & (recent.Iglob > 300), "lighting_under_daylight", "Supplemental lighting ran while outside radiation was high.", cursor, ["Lamp PAR contribution", "Solar radiation"])
    events += _events_from_mask(recent, (recent.Iglob < 20) & (recent.Tout < 10) & (recent.EnScr < 20) & (recent.heat_proxy > 0), "screen_open_heat_loss", "Energy screen was retracted during active night heating.", cursor, ["Energy curtain opening", "Outside temperature", "Rail and crop pipe temperatures"])
    if tou_windows:
        recent["peak"] = tou_peak_mask(recent.time, tou_windows)
        recent["day"] = _day_key(recent.time)
        daily = recent.groupby("day").apply(
            lambda day: pd.Series({
                "share": float(day.elec_proxy.where(day.peak, 0).sum() / day.elec_proxy.sum() * 100)
                if day.elec_proxy.sum() > 0 else np.nan,
                "started_at": day.time.min(), "ended_at": day.time.max(),
            }),
            include_groups=False,
        ).dropna(subset=["share"])
        reference = daily[daily.index < pd.Timestamp(cursor).floor("D")].share
        threshold = float(reference.quantile(0.9)) if len(reference) >= 3 else None
        if threshold is not None:
            for day, row in daily[daily.share > threshold].iterrows():
                events.append({
                    "id": hashlib.sha256(f"peak_window_energy:{day}".encode()).hexdigest()[:16],
                    "code": "peak_window_energy", "category": "efficiency", "severity": "low",
                    "message": "Electricity use was concentrated in configured tariff peak windows.",
                    "started_at": row.started_at.isoformat(),
                    "duration_minutes": int((row.ended_at - row.started_at).total_seconds() / 60) + 5,
                    "observed": round(float(row.share), 2), "expected": round(threshold, 2),
                    "residual": round(float(row.share - threshold), 2), "confidence": "medium",
                    "contributors": ["Lamp PAR contribution", "Ontario time-of-use schedule"],
                    "evidence_ids": [_evidence("peak_window_energy", cursor)],
                    "model_version": ENERGY_MODEL_VERSION,
                    "active": row.ended_at >= pd.Timestamp(cursor) - pd.Timedelta(minutes=10),
                })
    return sorted(events, key=lambda item: item["started_at"], reverse=True)[:30]
