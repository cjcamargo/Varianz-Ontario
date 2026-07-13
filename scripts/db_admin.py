from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from varianz.baseline_artifact import get_baseline_artifact
from varianz.config import settings
from varianz.dataset import load_replay_frame, load_resources, source_sha256
from varianz.intraday_artifact import get_intraday_artifact
from varianz.metrics import ENERGY_MODEL_VERSION, METRICS, OPERATIONAL_CODES, RESOURCE_CODES


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"
ORG_ID = uuid5(NAMESPACE_URL, "varianz:demo-organization")
SITE_ID = uuid5(NAMESPACE_URL, "varianz:demo-greenhouse")

def connect() -> psycopg.Connection:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(settings.database_url, connect_timeout=15)


def status() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select current_database(), current_user,
                   exists(select 1 from information_schema.schemata where schema_name='app')
            """
        )
        database, role, migrated = cur.fetchone()
        observations = 0
        model_artifacts = 0
        if migrated:
            cur.execute("select count(*) from app.observation where site_id=%s", (SITE_ID,))
            observations = cur.fetchone()[0]
            cur.execute(
                "select exists(select 1 from information_schema.tables "
                "where table_schema='analytics' and table_name='model_artifact')"
            )
            if cur.fetchone()[0]:
                cur.execute(
                    "select count(*) from analytics.model_artifact "
                    "where site_id=%s and status='active'",
                    (SITE_ID,),
                )
                model_artifacts = cur.fetchone()[0]
        print(
            {
                "authenticated": True,
                "database": database,
                "role": role,
                "migrated": migrated,
                "demo_observations": observations,
                "active_model_artifacts": model_artifacts,
            }
        )


def migrate() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("create schema if not exists audit")
        cur.execute(
            """
            create table if not exists audit.schema_migration (
              version text primary key,
              applied_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            "select exists(select 1 from information_schema.schemata where schema_name='app')"
        )
        app_exists = cur.fetchone()[0]
        applied = []
        for migration in sorted(MIGRATIONS.glob("*.sql")):
            cur.execute("select exists(select 1 from audit.schema_migration where version=%s)", (migration.name,))
            if cur.fetchone()[0]:
                continue
            if migration.name == "202607110001_initial.sql" and app_exists:
                cur.execute("insert into audit.schema_migration(version) values (%s)", (migration.name,))
                continue
            cur.execute(migration.read_text(encoding="utf-8"))
            cur.execute("insert into audit.schema_migration(version) values (%s)", (migration.name,))
            applied.append(migration.name)
    print({"migrations_applied": applied, "status": "current"})


def _sync_model_artifact(cur) -> str:
    artifact = get_baseline_artifact()
    manifest_path = artifact.directory / "manifest.json"
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    artifact_uri = f"repo://{artifact.directory.relative_to(ROOT).as_posix()}/manifest.json"
    cur.execute(
        "update analytics.model_artifact set status='retired', effective_to=now() "
        "where site_id=%s and model_family='energy_baseline' and status='active' and id<>%s",
        (SITE_ID, artifact.artifact_id),
    )
    cur.execute(
        """
        insert into analytics.model_artifact
            (id, organization_id, site_id, model_version, data_version,
             definitions_version, artifact_uri, manifest_sha256, effective_from,
             status, metadata, model_family)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, 'energy_baseline')
        on conflict (id) do update set
            status='active', effective_to=null, artifact_uri=excluded.artifact_uri,
            manifest_sha256=excluded.manifest_sha256, metadata=excluded.metadata
        """,
        (
            artifact.artifact_id, ORG_ID, SITE_ID,
            artifact.manifest["model_version"], artifact.manifest["data_version"],
            artifact.manifest["definitions_version"], artifact_uri, manifest_hash,
            artifact.manifest["coverage"]["start"], Jsonb(artifact.manifest),
        ),
    )
    return artifact.artifact_id


def sync_artifacts() -> None:
    with connect() as conn, conn.cursor() as cur:
        artifact_id = _sync_model_artifact(cur)
    print({"active_model_artifact": artifact_id, "status": "current"})


def sync_energy_cache() -> None:
    artifact = get_intraday_artifact()
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "delete from analytics.intraday_energy where site_id=%s and model_version=%s",
            (SITE_ID, ENERGY_MODEL_VERSION),
        )
        with cur.copy(
            "copy analytics.intraday_energy "
            "(organization_id, site_id, observed_at, heat_mj_m2, electricity_kwh_m2, "
            "co2_kg_m2, quality, model_version) from stdin"
        ) as copy:
            for row in artifact.allocated.itertuples(index=False):
                copy.write_row((
                    ORG_ID, SITE_ID, row.time.to_pydatetime(warn=False),
                    float(row.heat_mj_m2), float(row.elec_kwh_m2), float(row.co2_kg_m2),
                    row.quality, ENERGY_MODEL_VERSION,
                ))
        cur.execute(
            "delete from analytics.energy_allocation_calibration "
            "where site_id=%s and model_version=%s",
            (SITE_ID, ENERGY_MODEL_VERSION),
        )
        with cur.copy(
            "copy analytics.energy_allocation_calibration "
            "(organization_id, site_id, as_of_day, training_days, factors, fit_r2, "
            "model_version) from stdin"
        ) as copy:
            for day, calibration in artifact.calibrations.items():
                copy.write_row((
                    ORG_ID, SITE_ID, day, calibration["training_days"],
                    Jsonb(calibration["factors"]), Jsonb(calibration["fit_r2"]),
                    ENERGY_MODEL_VERSION,
                ))
        manifest_path = artifact.directory / "manifest.json"
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        artifact_uri = f"repo://{artifact.directory.relative_to(ROOT).as_posix()}/manifest.json"
        cur.execute(
            "update analytics.model_artifact set status='retired', effective_to=now() "
            "where site_id=%s and model_family='intraday_energy' and status='active' and id<>%s",
            (SITE_ID, artifact.artifact_id),
        )
        cur.execute(
            """
            insert into analytics.model_artifact
                (id, organization_id, site_id, model_version, data_version,
                 definitions_version, artifact_uri, manifest_sha256, effective_from,
                 status, metadata, model_family)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, 'intraday_energy')
            on conflict (id) do update set
                status='active', effective_to=null, artifact_uri=excluded.artifact_uri,
                manifest_sha256=excluded.manifest_sha256, metadata=excluded.metadata
            """,
            (
                artifact.artifact_id, ORG_ID, SITE_ID,
                artifact.manifest["model_version"], artifact.manifest["data_version"],
                artifact.manifest["definitions_version"], artifact_uri, manifest_hash,
                artifact.manifest["coverage"]["start"], Jsonb(artifact.manifest),
            ),
        )
    print({
        "active_intraday_artifact": artifact.artifact_id,
        "allocated_observations": len(artifact.allocated),
        "calibration_days": len(artifact.calibrations),
    })


def seed() -> None:
    frame = load_replay_frame(settings.dataset_zip)
    resources = load_resources(settings.dataset_zip)
    dataset_hash = source_sha256(settings.dataset_zip)
    metric_ids = {code: uuid5(NAMESPACE_URL, f"varianz:metric:{code}") for code in METRICS}
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into app.organization(id, name) values (%s, %s)
            on conflict (id) do update set name=excluded.name
            """,
            (ORG_ID, "Varianz Demo Organization"),
        )
        cur.execute(
            """
            insert into app.site(id, organization_id, name, timezone, area_m2, growing_area_m2)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (id) do update
            set name=excluded.name, timezone=excluded.timezone,
                area_m2=excluded.area_m2, growing_area_m2=excluded.growing_area_m2
            """,
            (SITE_ID, ORG_ID, "Wageningen Reference Greenhouse", "Europe/Amsterdam", 96, 62.5),
        )
        for code, definition in METRICS.items():
            cur.execute(
                """
                insert into app.metric_definition
                    (id, code, label, dimension, canonical_unit, version, grain,
                     aggregation, source, quality_rule, owner)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (code) do update
                set label=excluded.label, dimension=excluded.dimension,
                    canonical_unit=excluded.canonical_unit, version=excluded.version,
                    grain=excluded.grain, aggregation=excluded.aggregation,
                    source=excluded.source, quality_rule=excluded.quality_rule,
                    owner=excluded.owner
                """,
                (
                    metric_ids[code], code, definition.label, definition.dimension,
                    definition.unit, 3, definition.grain, definition.aggregation,
                    definition.source, definition.quality_rule, "Varianz Analytics",
                ),
            )

        cur.execute("create temporary table seed_observation (like app.observation including defaults)")
        with cur.copy(
            sql.SQL(
                "copy seed_observation "
                "(organization_id, site_id, metric_id, observed_at, value, quality_state, "
                "source_record_id) from stdin"
            )
        ) as copy:
            for source_name, source_frame, codes in [
                ("operational", frame, OPERATIONAL_CODES),
                ("resources", resources, RESOURCE_CODES),
            ]:
                for row in source_frame.itertuples(index=False):
                    observed_at = row.observed_at.to_pydatetime(warn=False)
                    source_id = (
                        f"wageningen:{dataset_hash[:12]}:{observed_at.isoformat()}"
                        if source_name == "operational"
                        else f"wageningen:{source_name}:{dataset_hash[:12]}:{observed_at.isoformat()}"
                    )
                    for code in codes:
                        if not hasattr(row, code):
                            continue
                        value = getattr(row, code)
                        if value == value:
                            copy.write_row(
                                (
                                    ORG_ID, SITE_ID, metric_ids[code], observed_at,
                                    float(value), "valid", source_id,
                                )
                            )
        cur.execute(
            """
            insert into app.observation
                (organization_id, site_id, metric_id, observed_at, value, quality_state,
                 source_record_id)
            select organization_id, site_id, metric_id, observed_at, value, quality_state,
                   source_record_id
            from seed_observation
            on conflict (site_id, metric_id, observed_at, source_record_id) do nothing
            """
        )
        inserted = cur.rowcount
        cur.execute("select count(*) from app.observation where site_id=%s", (SITE_ID,))
        total = cur.fetchone()[0]
        _sync_model_artifact(cur)
    print({"seed": "wageningen", "inserted": inserted, "total": total})


def main() -> None:
    parser = argparse.ArgumentParser(description="Varianz database administration")
    parser.add_argument(
        "command",
        choices=("status", "migrate", "seed", "sync-artifacts", "sync-energy-cache"),
    )
    args = parser.parse_args()
    {
        "status": status,
        "migrate": migrate,
        "seed": seed,
        "sync-artifacts": sync_artifacts,
        "sync-energy-cache": sync_energy_cache,
    }[args.command]()


if __name__ == "__main__":
    main()
