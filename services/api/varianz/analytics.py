from __future__ import annotations
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from .dataset import load_replay_frame, load_resources


def _finite(v):
    return None if pd.isna(v) or not np.isfinite(v) else round(float(v), 3)


def _series(df, columns):
    return [
        {"time": r.observed_at.isoformat(), **{c: _finite(getattr(r, c)) for c in columns}}
        for r in df.itertuples()
    ]


def energy_baseline(path: Path, cursor: datetime) -> dict:
    resources = load_resources(path)
    resources = resources[resources.observed_at <= pd.Timestamp(cursor)]
    replay = load_replay_frame(path)
    replay = replay[replay.observed_at <= pd.Timestamp(cursor)].copy()
    replay["day"] = replay.observed_at.dt.floor("D")
    features = replay.groupby("day").agg(
        Tout=("Tout", "mean"), Iglob=("Iglob", "mean"), light=("AssimLight", "mean")
    )
    data = (
        resources.assign(day=resources.observed_at.dt.floor("D"))
        .merge(features, left_on="day", right_index=True)
        .dropna(subset=["Heat_cons", "Tout", "Iglob", "light"])
    )
    if len(data) < 30:
        return {"status": "insufficient_data", "minimum_days": 30, "available_days": len(data)}
    train = data.iloc[:-1]
    current = data.iloc[-1]
    X = train[["Tout", "Iglob", "light"]].to_numpy()
    y = train.Heat_cons.to_numpy()
    mu = X.mean(0)
    sd = np.where(X.std(0) == 0, 1, X.std(0))
    Z = (X - mu) / sd
    design = np.column_stack([np.ones(len(Z)), Z])
    penalty = np.eye(4) * 0.1
    penalty[0, 0] = 0
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    predicted = float(np.r_[1, (current[["Tout", "Iglob", "light"]].to_numpy() - mu) / sd] @ beta)
    residual = float(current.Heat_cons - predicted)
    fitted = design @ beta
    train_res = y - fitted
    mad = float(np.median(np.abs(train_res - np.median(train_res))))
    scale = max(1.4826 * mad, 0.05)
    z = residual / scale
    return {
        "status": "ready",
        "model": "ridge-v1",
        "training_days": len(train),
        "actual_mj_m2": _finite(current.Heat_cons),
        "expected_mj_m2": _finite(predicted),
        "residual_mj_m2": _finite(residual),
        "robust_z": _finite(z),
        "anomaly": abs(z) >= 3,
        "confidence": "medium" if len(train) < 90 else "high",
    }


def dashboard_snapshot(path: Path, cursor: datetime) -> dict:
    replay = load_replay_frame(path)
    visible = replay[replay.observed_at <= pd.Timestamp(cursor)]
    recent = visible[visible.observed_at >= pd.Timestamp(cursor) - timedelta(hours=24)].iloc[::3]
    resources = load_resources(path)
    resources = resources[resources.observed_at <= pd.Timestamp(cursor)]
    baseline = energy_baseline(path, cursor)
    latest = visible.iloc[-1] if len(visible) else None
    r = resources.iloc[-1] if len(resources) else None
    compliance = (
        ((recent.Tair.between(18, 26)) & (recent.Rhair.between(55, 90))).mean() * 100
        if len(recent)
        else np.nan
    )
    alerts = []
    if latest is not None:
        for code, label, value, low, high in [
            ("temperature", "Air temperature", latest.Tair, 16, 28),
            ("humidity", "Relative humidity", latest.Rhair, 50, 95),
            ("co2", "CO2", latest.CO2air, 300, 1200),
        ]:
            if pd.notna(value) and not low <= value <= high:
                alerts.append(
                    {
                        "code": code,
                        "severity": "high",
                        "message": f"{label} outside demo operating range",
                        "value": _finite(value),
                    }
                )
    if baseline.get("anomaly"):
        alerts.append(
            {
                "code": "heat_baseline",
                "severity": "medium",
                "message": "Daily heat use deviates from weather-normalized baseline",
                "value": baseline["robust_z"],
            }
        )
    electricity = (r.ElecHigh + r.ElecLow) if r is not None else np.nan
    total = (r.Heat_cons + 3.6 * electricity) if r is not None else np.nan
    return {
        "cursor": pd.Timestamp(cursor).isoformat(),
        "kpis": {
            "daily_total_energy_mj_m2": _finite(total),
            "daily_heat_mj_m2": _finite(r.Heat_cons if r is not None else np.nan),
            "daily_electricity_kwh_m2": _finite(electricity),
            "climate_compliance_pct": _finite(compliance),
            "active_anomalies": len(alerts),
        },
        "latest": {}
        if latest is None
        else {c: _finite(latest[c]) for c in ["Tair", "Tout", "Rhair", "CO2air", "Iglob"]},
        "baseline": baseline,
        "alerts": alerts,
        "climate_series": _series(recent, ["Tair", "Tout", "Rhair"]),
        "resource_series": _series(
            resources.tail(30), ["Heat_cons", "ElecHigh", "ElecLow", "Irr", "Drain"]
        ),
        "definitions_version": "1.0.0",
    }
