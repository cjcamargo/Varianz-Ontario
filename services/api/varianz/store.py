from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pandas as pd
import psycopg
from psycopg import sql

from .config import Settings
from .dataset import load_replay_frame, load_resources
from .intraday_artifact import get_intraday_artifact
from .metrics import ENERGY_MODEL_VERSION, OPERATIONAL_CODES, RESOURCE_CODES


ORG_ID = uuid5(NAMESPACE_URL, "varianz:demo-organization")
SITE_ID = uuid5(NAMESPACE_URL, "varianz:demo-greenhouse")


@dataclass(frozen=True)
class OperationalData:
    operational: pd.DataFrame
    resources: pd.DataFrame
    backend: str
    quality: str
    intraday_cache: pd.DataFrame
    energy_calibrations: dict[str, dict]
    intraday_backend: str


def _query_frame(database_url: str, site_id: UUID, codes: tuple[str, ...]) -> pd.DataFrame:
    # Aggregate to the canonical wide shape inside PostgreSQL. Fetching the long
    # observation table and pivoting it in pandas temporarily held every metric
    # row twice and exceeded the 512 MB memory limit of the demo runtime.
    value_columns = sql.SQL(", ").join(
        sql.SQL("max(o.value) filter (where m.code = {}) as {}").format(
            sql.Literal(code), sql.Identifier(code)
        )
        for code in codes
    )
    query = sql.SQL(
        """
        select o.observed_at, {value_columns}
        from app.observation o
        join app.metric_definition m on m.id=o.metric_id
        where o.site_id=%s and m.code=any(%s)
        group by o.observed_at
        order by o.observed_at
        """
    ).format(value_columns=value_columns)
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        rows = conn.execute(query, (site_id, list(codes))).fetchall()
    if not rows:
        raise RuntimeError("Supabase contains no operational observations")
    return pd.DataFrame(rows, columns=["observed_at", *codes])


def _query_intraday_cache(database_url: str, site_id: UUID) -> pd.DataFrame:
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        rows = conn.execute(
            """
            select observed_at, heat_mj_m2, electricity_kwh_m2, co2_kg_m2, quality
            from analytics.intraday_energy
            where site_id=%s and model_version=%s
            order by observed_at
            """,
            (site_id, ENERGY_MODEL_VERSION),
        ).fetchall()
    if not rows:
        raise RuntimeError("Supabase contains no intraday energy cache")
    return pd.DataFrame(
        rows,
        columns=["time", "heat_mj_m2", "elec_kwh_m2", "co2_kg_m2", "quality"],
    )


def _query_energy_calibrations(database_url: str, site_id: UUID) -> dict[str, dict]:
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        rows = conn.execute(
            """
            select as_of_day, training_days, factors, fit_r2
            from analytics.energy_allocation_calibration
            where site_id=%s and model_version=%s
            order by as_of_day
            """,
            (site_id, ENERGY_MODEL_VERSION),
        ).fetchall()
    if not rows:
        raise RuntimeError("Supabase contains no energy allocation calibrations")
    return {
        day.isoformat(): {
            "as_of": day.isoformat(),
            "training_days": training_days,
            "factors": factors,
            "fit_r2": fit_r2,
        }
        for day, training_days, factors, fit_r2 in rows
    }


@lru_cache(maxsize=2)
def _database_frames(database_url: str, site_id: UUID) -> OperationalData:
    # These independent read models are loaded once. Parallel I/O keeps Render's
    # cold-start warmup from serially waiting on four Supabase round trips.
    with ThreadPoolExecutor(max_workers=4) as pool:
        operational = pool.submit(_query_frame, database_url, site_id, OPERATIONAL_CODES)
        resources = pool.submit(_query_frame, database_url, site_id, RESOURCE_CODES)
        intraday = pool.submit(_query_intraday_cache, database_url, site_id)
        calibrations = pool.submit(_query_energy_calibrations, database_url, site_id)
    return OperationalData(
        operational=operational.result(),
        resources=resources.result(),
        backend="supabase",
        quality="validated",
        intraday_cache=intraday.result(),
        energy_calibrations=calibrations.result(),
        intraday_backend="supabase_cache",
    )


def _zip_frames(path: Path, quality: str = "validated") -> OperationalData:
    artifact = get_intraday_artifact()
    return OperationalData(
        load_replay_frame(path), load_resources(path), "zip", quality,
        artifact.allocated, artifact.calibrations, "versioned_artifact",
    )


def get_operational_data(settings: Settings) -> OperationalData:
    if settings.data_backend == "zip":
        return _zip_frames(settings.dataset_zip)
    if settings.database_url:
        try:
            return _database_frames(settings.database_url, SITE_ID)
        except (psycopg.Error, RuntimeError):
            if settings.data_backend == "supabase":
                raise
            return _zip_frames(settings.dataset_zip, "zip_fallback")
    if settings.data_backend == "supabase":
        raise RuntimeError("DATABASE_URL is required when DATA_BACKEND=supabase")
    return _zip_frames(settings.dataset_zip, "zip_fallback")


def clear_data_cache() -> None:
    _database_frames.cache_clear()
