from __future__ import annotations

import argparse
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import psycopg
from psycopg import sql

from varianz.config import settings
from varianz.dataset import load_replay_frame, source_sha256


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "202607110001_initial.sql"
ORG_ID = uuid5(NAMESPACE_URL, "varianz:demo-organization")
SITE_ID = uuid5(NAMESPACE_URL, "varianz:demo-greenhouse")

METRICS = {
    "Tair": ("Indoor air temperature", "temperature", "degC"),
    "Rhair": ("Indoor relative humidity", "relative_humidity", "%"),
    "HumDef": ("Indoor humidity deficit", "humidity_deficit", "g/m3"),
    "CO2air": ("Indoor carbon dioxide", "concentration", "ppm"),
    "AssimLight": ("Assimilation lighting", "control_signal", "%"),
    "EnScr": ("Energy screen position", "control_signal", "%"),
    "PipeLow": ("Lower heating pipe temperature", "temperature", "degC"),
    "t_heat_vip": ("Heating setpoint", "temperature", "degC"),
    "Tout": ("Outdoor temperature", "temperature", "degC"),
    "Rhout": ("Outdoor relative humidity", "relative_humidity", "%"),
    "Iglob": ("Global solar radiation", "irradiance", "W/m2"),
    "Windsp": ("Outdoor wind speed", "speed", "m/s"),
}


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
    migration_sql = MIGRATION.read_text(encoding="utf-8")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select exists(select 1 from information_schema.schemata where schema_name='app')"
        )
        if cur.fetchone()[0]:
            print({"migration": "already_applied"})
            return
        cur.execute(migration_sql)
    print({"migration": MIGRATION.name, "status": "applied"})


def seed() -> None:
    frame = load_replay_frame(settings.dataset_zip)
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
            insert into app.site(id, organization_id, name, timezone, area_m2)
            values (%s, %s, %s, %s, %s)
            on conflict (id) do update set name=excluded.name, timezone=excluded.timezone
            """,
            (SITE_ID, ORG_ID, "Wageningen Reference Greenhouse", "Europe/Amsterdam", None),
        )
        for code, (label, dimension, unit) in METRICS.items():
            cur.execute(
                """
                insert into app.metric_definition(id, code, label, dimension, canonical_unit)
                values (%s, %s, %s, %s, %s)
                on conflict (code) do update
                set label=excluded.label, dimension=excluded.dimension,
                    canonical_unit=excluded.canonical_unit
                """,
                (metric_ids[code], code, label, dimension, unit),
            )

        cur.execute("create temporary table seed_observation (like app.observation including defaults)")
        with cur.copy(
            sql.SQL(
                "copy seed_observation "
                "(organization_id, site_id, metric_id, observed_at, value, quality_state, "
                "source_record_id) from stdin"
            )
        ) as copy:
            for row in frame.itertuples(index=False):
                observed_at = row.observed_at.to_pydatetime()
                source_id = f"wageningen:{dataset_hash[:12]}:{observed_at.isoformat()}"
                for code in METRICS:
                    value = getattr(row, code)
                    if value == value:
                        copy.write_row(
                            (ORG_ID, SITE_ID, metric_ids[code], observed_at, float(value), "valid", source_id)
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
