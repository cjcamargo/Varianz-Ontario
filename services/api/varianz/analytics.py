from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .dataset import load_replay_frame, load_resources
from .baseline_artifact import BaselineArtifactError, get_baseline_artifact
from .metrics import DATA_VERSION, DEFINITIONS_VERSION, METRICS, MODEL_VERSION


WINDOWS = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "all": None,
}


def _finite(value, digits: int = 3):
    return None if pd.isna(value) or not np.isfinite(value) else round(float(value), digits)


def _evidence(code: str, cursor: datetime) -> str:
    token = f"{DEFINITIONS_VERSION}:{pd.Timestamp(cursor).isoformat()}:{code}"
    return "ev_" + hashlib.sha256(token.encode()).hexdigest()[:14]


def _series(frame: pd.DataFrame, columns: list[str], stride: int = 1) -> list[dict]:
    available = [column for column in columns if column in frame.columns]
    return [
        {
            "time": row.observed_at.isoformat(),
            **{column: _finite(getattr(row, column)) for column in available},
        }
        for row in frame.iloc[::stride].itertuples()
    ]


def _daily_features(operational: pd.DataFrame, resources: pd.DataFrame) -> pd.DataFrame:
    frame = operational.copy()
    frame["day"] = frame.observed_at.dt.floor("D")
    heating_reference = frame.get("t_heat_vip", pd.Series(20.0, index=frame.index)).fillna(20)
    frame["heating_degree"] = np.maximum(heating_reference - frame.Tout, 0)
    daily = frame.groupby("day").agg(
        tout_mean=("Tout", "mean"),
        heating_degree_hours=("heating_degree", lambda s: s.sum() * 5 / 60),
        radiation_mean=("Iglob", "mean"),
        lighting_hours=("AssimLight", lambda s: (s > 0).sum() * 5 / 60),
        indoor_temp_mean=("Tair", "mean"),
    )
    daily["crop_age_days"] = (daily.index - daily.index.min()).days
    resource = resources.copy()
    resource["day"] = resource.observed_at.dt.floor("D")
    return resource.merge(daily, left_on="day", right_index=True, how="left").sort_values("day")


def _naive_predictions(values: np.ndarray, indices: np.ndarray) -> np.ndarray:
    predictions = []
    for index in indices:
        history = values[max(0, index - 7) : index]
        predictions.append(float(np.median(history)) if len(history) else float(values[index]))
    return np.asarray(predictions)


class _ElasticNetModel:
    def __init__(self, alpha: float = 0.02, l1_ratio: float = 0.25):
        self.alpha = alpha
        self.l1_ratio = l1_ratio

    def fit(self, X: np.ndarray, y: np.ndarray) -> "_ElasticNetModel":
        self.mean = X.mean(axis=0)
        self.scale = np.where(X.std(axis=0) == 0, 1, X.std(axis=0))
        Z = (X - self.mean) / self.scale
        self.intercept = float(y.mean())
        centered = y - self.intercept
        coef = np.zeros(Z.shape[1])
        l1 = self.alpha * self.l1_ratio
        l2 = self.alpha * (1 - self.l1_ratio)
        for _ in range(2000):
            previous = coef.copy()
            for column in range(Z.shape[1]):
                residual = centered - Z @ coef + Z[:, column] * coef[column]
                rho = float(Z[:, column] @ residual / len(Z))
                coef[column] = np.sign(rho) * max(abs(rho) - l1, 0) / (
                    float(np.mean(Z[:, column] ** 2)) + l2
                )
            if np.max(np.abs(coef - previous)) < 1e-8:
                break
        self.coef = coef
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.intercept + ((X - self.mean) / self.scale) @ self.coef


def _mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def compute_energy_baseline_frames(
    operational: pd.DataFrame, resources: pd.DataFrame, cursor: datetime
) -> dict:
    data = _daily_features(
        operational[operational.observed_at <= pd.Timestamp(cursor)],
        resources[resources.observed_at <= pd.Timestamp(cursor)],
    ).dropna(subset=["Heat_cons", "tout_mean", "heating_degree_hours", "radiation_mean"])
    if len(data) < 45:
        return {
            "status": "insufficient_data",
            "minimum_days": 45,
            "available_days": len(data),
            "model_version": MODEL_VERSION,
            "evidence_ids": [_evidence("heat_baseline", cursor)],
        }

    features = [
        "tout_mean",
        "heating_degree_hours",
        "radiation_mean",
        "lighting_hours",
        "crop_age_days",
    ]
    X = data[features].to_numpy(dtype=float)
    y = data.Heat_cons.to_numpy(dtype=float)
    locked_start = max(35, int(len(data) * 0.8))
    train_end = locked_start
    fold_points = np.linspace(21, train_end, 5, dtype=int)
    fold_scores = []
    residuals = []
    for start, end in zip(fold_points[:-1], fold_points[1:]):
        validation = np.arange(start, end)
        model = _ElasticNetModel().fit(X[:start], y[:start])
        candidate = model.predict(X[validation])
        naive = _naive_predictions(y, validation)
        candidate_mae = _mae(y[validation], candidate)
        naive_mae = _mae(y[validation], naive)
        fold_scores.append(
            {
                "candidate_mae": float(candidate_mae),
                "naive_mae": float(naive_mae),
                "relative_change": float((candidate_mae - naive_mae) / max(naive_mae, 1e-9)),
            }
        )
        residuals.extend((y[validation] - candidate).tolist())

    final_model = _ElasticNetModel().fit(X[:locked_start], y[:locked_start])
    test_index = np.arange(locked_start, len(data))
    candidate_test = final_model.predict(X[test_index])
    naive_test = _naive_predictions(y, test_index)
    candidate_mae = _mae(y[test_index], candidate_test)
    naive_mae = _mae(y[test_index], naive_test)
    improvement = (naive_mae - candidate_mae) / max(naive_mae, 1e-9)
    no_bad_fold = all(score["relative_change"] <= 0.20 for score in fold_scores)
    promoted = bool(improvement >= 0.05 and no_bad_fold)
    selected = "elastic_net" if promoted else "rolling_7d_median"

    current_index = len(data) - 1
    candidate_expected = float(final_model.predict(X[[current_index]])[0])
    naive_expected = float(_naive_predictions(y, np.asarray([current_index]))[0])
    expected = candidate_expected if promoted else naive_expected
    actual = float(y[current_index])
    selected_residuals = np.asarray(residuals if promoted else y[1:locked_start] - _naive_predictions(y, np.arange(1, locked_start)))
    lower_q, upper_q = np.quantile(selected_residuals, [0.10, 0.90])
    median = float(np.median(selected_residuals))
    mad = float(np.median(np.abs(selected_residuals - median)))
    robust_scale = max(1.4826 * mad, 0.15)
    residual = actual - expected
    robust_z = residual / robust_scale
    return {
        "status": "ready",
        "model_version": MODEL_VERSION,
        "selected_model": selected,
        "candidate_promoted": promoted,
        "promotion_gate": {
            "required_improvement_pct": 5,
            "locked_test_improvement_pct": _finite(improvement * 100, 1),
            "no_fold_over_20pct_worse": no_bad_fold,
            "candidate_mae": _finite(candidate_mae),
            "naive_mae": _finite(naive_mae),
            "folds": len(fold_scores),
        },
        "training_days": locked_start,
        "actual_mj_m2": _finite(actual),
        "expected_mj_m2": _finite(expected),
        "p10_mj_m2": _finite(expected + lower_q),
        "p90_mj_m2": _finite(expected + upper_q),
        "residual_mj_m2": _finite(residual),
        "variance_pct": _finite(residual / max(abs(expected), 0.1) * 100, 1),
        "robust_z": _finite(robust_z),
        "anomaly": bool(abs(robust_z) >= 3),
        "confidence": "medium" if len(data) < 90 else "high",
        "contributors": [
            {"metric": "Tout", "value": _finite(data.iloc[-1].tout_mean), "unit": "degC"},
            {
                "metric": "heating_degree_hours",
                "value": _finite(data.iloc[-1].heating_degree_hours),
                "unit": "degC*h",
            },
            {
                "metric": "lighting_hours",
                "value": _finite(data.iloc[-1].lighting_hours),
                "unit": "h",
            },
        ],
        "evidence_ids": [_evidence("heat_baseline", cursor)],
    }


def energy_baseline_frames(
    operational: pd.DataFrame, resources: pd.DataFrame, cursor: datetime
) -> dict:
    """Serve a future-safe precomputed prediction; calculate only as an explicit fallback."""
    try:
        artifact = get_baseline_artifact()
        baseline = artifact.prediction_at(cursor)
    except BaselineArtifactError:
        artifact = None
        baseline = None
    if baseline is None:
        baseline = compute_energy_baseline_frames(operational, resources, cursor)
        baseline["serving_source"] = "runtime_fallback"
        return baseline
    baseline["serving_source"] = "versioned_artifact"
    baseline["artifact_id"] = artifact.artifact_id
    baseline["artifact_as_of"] = max(
        timestamp for timestamp in artifact.timestamps if timestamp <= pd.Timestamp(cursor)
    ).isoformat()
    baseline["evidence_ids"] = [_evidence("heat_baseline", cursor), f"artifact:{artifact.artifact_id}"]
    return baseline


def energy_baseline(path: Path, cursor: datetime) -> dict:
    return energy_baseline_frames(load_replay_frame(path), load_resources(path), cursor)


def _persistent_events(
    frame: pd.DataFrame,
    condition: pd.Series,
    *,
    code: str,
    category: str,
    severity: str,
    message: str,
    observed_column: str,
    expected_column: str | None,
    cursor: datetime,
) -> list[dict]:
    condition = condition.fillna(False)
    groups = (condition != condition.shift()).cumsum()
    events = []
    for _, group in frame[condition].groupby(groups[condition]):
        if len(group) < 3:
            continue
        start = group.observed_at.iloc[0]
        end = group.observed_at.iloc[-1]
        duration = max(15, int((end - start).total_seconds() / 60) + 5)
        observed = float(group[observed_column].iloc[-1])
        expected = (
            float(group[expected_column].iloc[-1])
            if expected_column and pd.notna(group[expected_column].iloc[-1])
            else None
        )
        token = f"{code}:{start.isoformat()}:{MODEL_VERSION}"
        events.append(
            {
                "id": "an_" + hashlib.sha256(token.encode()).hexdigest()[:14],
                "code": code,
                "category": category,
                "severity": severity,
                "message": message,
                "started_at": start.isoformat(),
                "ended_at": end.isoformat(),
                "duration_minutes": duration,
                "observed": _finite(observed),
                "expected": _finite(expected) if expected is not None else None,
                "residual": _finite(observed - expected) if expected is not None else None,
                "confidence": "high",
                "contributors": [observed_column] + ([expected_column] if expected_column else []),
                "evidence_ids": [_evidence(code, cursor)],
                "model_version": MODEL_VERSION,
                "active": bool(end >= pd.Timestamp(cursor) - timedelta(minutes=10)),
            }
        )
    return events


def detect_anomalies(
    operational: pd.DataFrame,
    resources: pd.DataFrame,
    cursor: datetime,
    baseline: dict,
) -> list[dict]:
    start = pd.Timestamp(cursor) - timedelta(days=7)
    frame = operational[
        (operational.observed_at >= start) & (operational.observed_at <= pd.Timestamp(cursor))
    ].copy()
    events = []
    if {"Tair", "t_heat_vip"}.issubset(frame.columns):
        events += _persistent_events(
            frame,
            frame.Tair < frame.t_heat_vip - 2,
            code="temperature_below_heating_target",
            category="climate",
            severity="high",
            message="Indoor temperature remained below the realized heating target.",
            observed_column="Tair",
            expected_column="t_heat_vip",
            cursor=cursor,
        )
    if {"Tair", "t_ventlee_vip"}.issubset(frame.columns):
        events += _persistent_events(
            frame,
            frame.Tair > frame.t_ventlee_vip + 2,
            code="temperature_above_ventilation_target",
            category="climate",
            severity="high",
            message="Indoor temperature remained above the realized ventilation target.",
            observed_column="Tair",
            expected_column="t_ventlee_vip",
            cursor=cursor,
        )
    if "HumDef" in frame:
        events += _persistent_events(
            frame,
            (frame.HumDef < 1) | (frame.HumDef > 8),
            code="humidity_deficit_excursion",
            category="climate",
            severity="medium",
            message="Humidity deficit persisted outside the demo operating band.",
            observed_column="HumDef",
            expected_column="dx_vip" if "dx_vip" in frame else None,
            cursor=cursor,
        )
    if baseline.get("anomaly"):
        events.append(
            {
                "id": "an_" + hashlib.sha256(f"energy:{cursor.date()}".encode()).hexdigest()[:14],
                "code": "heat_baseline_deviation",
                "category": "energy",
                "severity": "high",
                "message": "Daily heat intensity deviates from the promoted baseline.",
                "started_at": pd.Timestamp(cursor).floor("D").isoformat(),
                "ended_at": pd.Timestamp(cursor).isoformat(),
                "duration_minutes": int((pd.Timestamp(cursor) - pd.Timestamp(cursor).floor("D")).total_seconds() / 60),
                "observed": baseline.get("actual_mj_m2"),
                "expected": baseline.get("expected_mj_m2"),
                "residual": baseline.get("residual_mj_m2"),
                "confidence": baseline.get("confidence", "medium"),
                "contributors": [item["metric"] for item in baseline.get("contributors", [])],
                "evidence_ids": baseline.get("evidence_ids", []),
                "model_version": MODEL_VERSION,
                "active": True,
            }
        )
    current_resources = resources[resources.observed_at <= pd.Timestamp(cursor)].tail(1)
    if not current_resources.empty:
        row = current_resources.iloc[0]
        ratio = row.Drain / row.Irr if row.Irr > 0 else np.nan
        if pd.notna(ratio) and row.Irr > 1 and (ratio < 0.10 or ratio > 0.80):
            events.append(
                {
                    "id": "an_" + hashlib.sha256(f"drain:{row.observed_at}".encode()).hexdigest()[:14],
                    "code": "drain_ratio_extreme",
                    "category": "resources",
                    "severity": "medium",
                    "message": "Daily drain ratio is outside the demo review band.",
                    "started_at": row.observed_at.isoformat(),
                    "ended_at": pd.Timestamp(cursor).isoformat(),
                    "duration_minutes": 1440,
                    "observed": _finite(ratio * 100, 1),
                    "expected": None,
                    "residual": None,
                    "confidence": "high",
                    "contributors": ["Drain", "Irr"],
                    "evidence_ids": [_evidence("drain_ratio", cursor)],
                    "model_version": "rules-2.0.0",
                    "active": True,
                }
            )
    return sorted(events, key=lambda item: (not item["active"], item["started_at"]), reverse=False)[:30]


def _compliance(frame: pd.DataFrame, hours: int) -> float | None:
    subset = frame[frame.observed_at >= frame.observed_at.max() - timedelta(hours=hours)]
    if subset.empty:
        return None
    valid = subset.Tair.between(18, 26) & subset.Rhair.between(55, 90)
    return _finite(valid.mean() * 100, 1)


def operational_snapshot(
    operational: pd.DataFrame,
    resources: pd.DataFrame,
    cursor: datetime,
    window: str = "24h",
    *,
    backend: str = "zip",
    quality: str = "validated",
    tariff: dict | None = None,
) -> dict:
    if window not in WINDOWS:
        raise ValueError("invalid_window")
    cursor_ts = pd.Timestamp(cursor)
    visible = operational[operational.observed_at <= cursor_ts]
    delta = WINDOWS[window]
    windowed = visible if delta is None else visible[visible.observed_at >= cursor_ts - delta]
    if window in {"7d", "all"}:
        stride = max(1, len(windowed) // 500)
    else:
        stride = 1
    visible_resources = resources[resources.observed_at <= cursor_ts]
    baseline = energy_baseline_frames(operational, resources, cursor)
    anomalies = detect_anomalies(operational, resources, cursor, baseline)
    latest = visible.iloc[-1] if len(visible) else None
    resource = visible_resources.iloc[-1] if len(visible_resources) else None
    electricity = resource.ElecHigh + resource.ElecLow if resource is not None else np.nan
    total_energy = resource.Heat_cons + 3.6 * electricity if resource is not None else np.nan
    peak_share = resource.ElecHigh / electricity * 100 if resource is not None and electricity else np.nan
    drain_ratio = resource.Drain / resource.Irr * 100 if resource is not None and resource.Irr else np.nan
    cost = None
    if resource is not None and tariff:
        cost = (
            resource.ElecHigh * tariff["electricity_peak_per_kwh"]
            + resource.ElecLow * tariff["electricity_offpeak_per_kwh"]
            + resource.Heat_cons * tariff["heat_per_mj"]
            + resource.CO2_cons * tariff["co2_per_kg"]
            + resource.Irr / 1000 * tariff["water_per_m3"]
        )
    evidence_ids = [
        _evidence(code, cursor)
        for code in ["total_energy", "climate_compliance", "drain_ratio", "anomalies"]
    ]
    return {
        "cursor": cursor_ts.isoformat(),
        "window": window,
        "data_version": DATA_VERSION,
        "definitions_version": DEFINITIONS_VERSION,
        "model_version": MODEL_VERSION,
        "quality": {"state": quality, "backend": backend, "future_safe": True},
        "evidence_ids": evidence_ids,
        "kpis": {
            "daily_heat_mj_m2": _finite(resource.Heat_cons if resource is not None else np.nan),
            "daily_electricity_kwh_m2": _finite(electricity),
            "daily_total_energy_mj_m2": _finite(total_energy),
            "peak_electricity_share_pct": _finite(peak_share, 1),
            "daily_co2_kg_m2": _finite(resource.CO2_cons if resource is not None else np.nan),
            "daily_irrigation_l_m2": _finite(resource.Irr if resource is not None else np.nan),
            "daily_drain_l_m2": _finite(resource.Drain if resource is not None else np.nan),
            "drain_ratio_pct": _finite(drain_ratio, 1),
            "climate_compliance_1h_pct": _compliance(visible, 1) if len(visible) else None,
            "climate_compliance_6h_pct": _compliance(visible, 6) if len(visible) else None,
            "climate_compliance_24h_pct": _compliance(visible, 24) if len(visible) else None,
            "active_anomalies": sum(bool(item["active"]) for item in anomalies),
            "anomaly_minutes": sum(item["duration_minutes"] for item in anomalies if item["active"]),
            "operating_cost_cad_m2": _finite(cost) if cost is not None else None,
        },
        "latest": {}
        if latest is None
        else {
            code: _finite(latest[code])
            for code in ["Tair", "Tout", "Rhair", "HumDef", "CO2air", "Iglob", "EnScr", "VentLee"]
            if code in latest
        },
        "baseline": baseline,
        "anomalies": anomalies,
        "climate_series": _series(
            windowed,
            ["Tair", "Tout", "Rhair", "HumDef", "CO2air", "t_heat_vip", "t_ventlee_vip", "EnScr", "VentLee"],
            stride,
        ),
        "resource_series": _series(
            visible_resources, ["Heat_cons", "ElecHigh", "ElecLow", "CO2_cons", "Irr", "Drain"]
        ),
        "tariff": {"configured": bool(tariff), "currency": tariff.get("currency") if tariff else None},
        "metric_definitions": {
            code: {
                "label": definition.label,
                "unit": definition.unit,
                "grain": definition.grain,
                "aggregation": definition.aggregation,
                "source": definition.source,
            }
            for code, definition in METRICS.items()
        },
    }


def dashboard_snapshot(path: Path, cursor: datetime) -> dict:
    snapshot = operational_snapshot(load_replay_frame(path), load_resources(path), cursor)
    snapshot["alerts"] = snapshot["anomalies"]
    snapshot["kpis"]["climate_compliance_pct"] = snapshot["kpis"]["climate_compliance_24h_pct"]
    return snapshot
