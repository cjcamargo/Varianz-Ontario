from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pandas as pd
import psycopg
from psycopg import sql

from .config import Settings
from .dataset import load_replay_frame, load_resources
from .metrics import OPERATIONAL_CODES, RESOURCE_CODES


ORG_ID = uuid5(NAMESPACE_URL, "varianz:demo-organization")
SITE_ID = uuid5(NAMESPACE_URL, "varianz:demo-greenhouse")


@dataclass(frozen=True)
class OperationalData:
    operational: pd.DataFrame
    resources: pd.DataFrame
    backend: str
    quality: str


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


@lru_cache(maxsize=2)
def _database_frames(database_url: str, site_id: UUID) -> OperationalData:
    return OperationalData(
        operational=_query_frame(database_url, site_id, OPERATIONAL_CODES),
        resources=_query_frame(database_url, site_id, RESOURCE_CODES),
        backend="supabase",
        quality="validated",
    )


def _zip_frames(path: Path, quality: str = "validated") -> OperationalData:
    return OperationalData(load_replay_frame(path), load_resources(path), "zip", quality)


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
