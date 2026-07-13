from __future__ import annotations

import hashlib
from datetime import datetime

import numpy as np
import pandas as pd


ENERGY_MODEL_VERSION = "energy-intraday-1.0.0"
DEFAULT_TOU_WINDOWS = [
    {"label": "peak", "days": "all", "start": "07:00", "end": "23:00"}
]
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


def tou_peak_mask(
    times: pd.Series,
    windows: list[dict] | None = None,
    timezone: str = "Europe/Amsterdam",
) -> np.ndarray:
    local = pd.DatetimeIndex(pd.to_datetime(times, utc=True)).tz_convert(timezone)
    minutes = local.hour * 60 + local.minute
    peak = np.zeros(len(local), dtype=bool)
    for window in windows or DEFAULT_TOU_WINDOWS:
        if str(window.get("label", "")).lower() != "peak":
            continue
        start_h, start_m = map(int, str(window["start"]).split(":"))
        end_h, end_m = map(int, str(window["end"]).split(":"))
        start, end = start_h * 60 + start_m, end_h * 60 + end_m
        clock = (minutes >= start) & (minutes < end) if start < end else (minutes >= start) | (minutes < end)
        peak |= clock & _day_matches(local, str(window.get("days", "all")))
    return peak


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
        "elec_peak_kwh_m2", "elec_offpeak_kwh_m2", "cost_cad_m2",
    ]
    hourly = intraday.set_index("time").resample("1h").agg(
        {**{column: "sum" for column in sums}, "quality": lambda values: max(values, key=lambda x: QUALITY_ORDER[x])}
    )
    return hourly.reset_index()


def intraday_energy_frame(
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
            "elec_peak_kwh_m2", "elec_offpeak_kwh_m2", "cost_cad_m2", "quality",
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

    peak = tou_peak_mask(frame.observed_at, tou_windows)
    frame["elec_peak_kwh_m2"] = frame.elec_kwh_m2.where(peak, 0.0)
    frame["elec_offpeak_kwh_m2"] = frame.elec_kwh_m2.where(~peak, 0.0)
    frame["cost_cad_m2"] = np.nan
    result = frame.rename(columns={"observed_at": "time"})[[
        "time", "heat_mj_m2", "elec_kwh_m2", "co2_kg_m2",
        "elec_peak_kwh_m2", "elec_offpeak_kwh_m2", "cost_cad_m2", "quality",
    ]]
    return aggregate_intraday(result, grain)


def apply_intraday_cost(intraday: pd.DataFrame, tariff: dict | None) -> pd.DataFrame:
    result = intraday.copy()
    if not tariff or result.empty:
        result["cost_cad_m2"] = np.nan
        return result
    result["cost_cad_m2"] = (
        result.elec_peak_kwh_m2 * tariff["electricity_peak_per_kwh"]
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
) -> dict:
    return {
        "method": "meter-conserving disaggregation",
        "calibration_days": calibration_days,
        "model_version": ENERGY_MODEL_VERSION,
        "fit_r2": reconstruction_fit(operational, resources, cursor),
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
) -> dict:
    variance = None if value is None or expected in {None, 0} else round((value - expected) / expected * 100, 1)
    return {
        "status": "ready" if value is not None else "insufficient_data",
        "value": None if value is None else round(float(value), 4),
        "unit": unit,
        "expected": None if expected is None else round(float(expected), 4),
        "variance_pct": variance,
        "confidence": confidence,
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
    op = operational[pd.to_datetime(operational.observed_at, utc=True) <= pd.Timestamp(cursor)].copy()
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
        "peak_share": _indicator(peak_share, "%", cursor, ["Electricity consumption", "Ontario time-of-use schedule"], expected=peak_expected, confidence="high"),
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
