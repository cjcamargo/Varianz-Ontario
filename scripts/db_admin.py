from __future__ import annotations

import argparse
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import psycopg
from psycopg import sql

from varianz.config import settings
from varianz.dataset import load_replay_frame, load_resources, source_sha256
from varianz.metrics import METRICS, OPERATIONAL_CODES, RESOURCE_CODES


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
        if migrated:
            cur.execute("select count(*) from app.observation where site_id=%s", (SITE_ID,))
            observations = cur.fetchone()[0]
        print(
            {
                "authenticated": True,
                "database": database,
                "role": role,
                "migrated": migrated,
                "demo_observations": observations,
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
    print({"seed": "wageningen", "inserted": inserted, "total": total})


def main() -> None:
    parser = argparse.ArgumentParser(description="Varianz database administration")
    parser.add_argument("command", choices=("status", "migrate", "seed"))
    args = parser.parse_args()
    {"status": status, "migrate": migrate, "seed": seed}[args.command]()


if __name__ == "__main__":
    main()
