from __future__ import annotations
import hashlib
import io
import zipfile
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
import pandas as pd

EXCEL_ORIGIN = "1899-12-30"
PREFIX = "Wageningen MVP Dataset/"
SOURCES = (
    "Reference/CropParameters.csv",
    "Reference/GreenhouseClimate.csv",
    "Reference/GrodanSens.csv",
    "Reference/LabAnalysis.csv",
    "Reference/Production.csv",
    "Reference/Resources.csv",
    "Reference/TomQuality.csv",
    "Weather/Weather.csv",
)


@dataclass(frozen=True)
class SourceProfile:
    name: str
    rows: int
    columns: int
    start: str | None
    end: str | None
    duplicate_timestamps: int
    missing_fraction: float
    status: str
    issues: tuple[str, ...]


def source_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _number(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.strip().str.rstrip(","), errors="coerce")


@lru_cache(maxsize=16)
def read_source(path: Path, member: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        raw = z.read(PREFIX + member)
    kwargs = {"sep": "\t"} if member.endswith("TomQuality.csv") else {"sep": ","}
    df = pd.read_csv(io.BytesIO(raw), skipinitialspace=True, **kwargs)
    df.columns = [c.strip().strip(",") for c in df.columns]
    time = df.columns[0]
    serial = _number(df[time])
    df = df.drop(columns=time)
    for c in df.columns:
        df[c] = _number(df[c])
    df.insert(0, "observed_at", pd.to_datetime(serial, unit="D", origin=EXCEL_ORIGIN, utc=True))
    return df


def profile_source(path: Path, member: str) -> SourceProfile:
    df = read_source(path, member)
    t = df.observed_at
    values = df.drop(columns="observed_at")
    issues = []
    if t.isna().any():
        issues.append(f"{int(t.isna().sum())} invalid timestamps")
    duplicates = int(t.duplicated().sum())
    if duplicates:
        issues.append(f"{duplicates} duplicate timestamps")
    if member.endswith("Production.csv") and (t < pd.Timestamp("2019-12-16", tz="UTC")).any():
        issues.append("pre-operation production record quarantined")
    all_null = [c for c in values if values[c].isna().all()]
    if all_null:
        issues.append("all-null columns: " + ", ".join(all_null))
    missing = float(values.isna().sum().sum() / values.size) if values.size else 0
    return SourceProfile(
        member,
        len(df),
        len(values.columns),
        t.min().isoformat(),
        t.max().isoformat(),
        duplicates,
        round(missing, 6),
        "warning" if issues else "valid",
        tuple(issues),
    )


def quality_report(path: Path) -> dict:
    profiles = [profile_source(path, m) for m in SOURCES]
    return {
        "dataset_sha256": source_sha256(path),
        "contract_version": "1.0.0",
        "sources": [asdict(p) for p in profiles],
        "totals": {
            "sources": len(profiles),
            "rows": sum(p.rows for p in profiles),
            "warnings": sum(p.status == "warning" for p in profiles),
        },
    }


@lru_cache(maxsize=2)
def load_replay_frame(path: Path) -> pd.DataFrame:
    climate = read_source(path, "Reference/GreenhouseClimate.csv")
    weather = read_source(path, "Weather/Weather.csv")
    cc = [
        "observed_at",
        "Tair",
        "Rhair",
        "HumDef",
        "CO2air",
        "AssimLight",
        "EnScr",
        "PipeLow",
        "t_heat_vip",
    ]
    wc = ["observed_at", "Tout", "Rhout", "Iglob", "Windsp"]
    return (
        climate[cc]
        .merge(weather[wc], on="observed_at", how="inner")
        .sort_values("observed_at")
        .reset_index(drop=True)
    )


@lru_cache(maxsize=2)
def load_resources(path: Path) -> pd.DataFrame:
    return (
        read_source(path, "Reference/Resources.csv")
        .sort_values("observed_at")
        .reset_index(drop=True)
    )
