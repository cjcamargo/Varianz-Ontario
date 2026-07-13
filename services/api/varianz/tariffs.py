from __future__ import annotations

from datetime import date
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb


FIELDS = (
    "electricity_peak_per_kwh",
    "electricity_offpeak_per_kwh",
    "heat_per_mj",
    "co2_per_kg",
    "water_per_m3",
)


def get_tariff(database_url: str | None, site_id: UUID, cursor_date: date) -> dict | None:
    if not database_url:
        return None
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        row = conn.execute(
            """
            select id, currency, effective_from, electricity_peak_per_kwh,
                   electricity_offpeak_per_kwh, heat_per_mj, co2_per_kg,
                   water_per_m3, source, tou_windows, preset
            from app.tariff_profile
            where site_id=%s and effective_from<=%s
            order by effective_from desc limit 1
            """,
            (site_id, cursor_date),
        ).fetchone()
    if not row:
        return None
    keys = (
        "id", "currency", "effective_from", *FIELDS, "source", "tou_windows", "preset"
    )
    result = dict(zip(keys, row))
    for field in FIELDS:
        result[field] = float(result[field])
    result["id"] = str(result["id"])
    result["effective_from"] = result["effective_from"].isoformat()
    return result


def put_tariff(database_url: str, organization_id: UUID, site_id: UUID, tariff: dict) -> dict:
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        row = conn.execute(
            """
            insert into app.tariff_profile
                (organization_id, site_id, currency, effective_from,
                 electricity_peak_per_kwh, electricity_offpeak_per_kwh,
                 heat_per_mj, co2_per_kg, water_per_m3, source, tou_windows, preset)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict (site_id, effective_from) do update set
                currency=excluded.currency,
                electricity_peak_per_kwh=excluded.electricity_peak_per_kwh,
                electricity_offpeak_per_kwh=excluded.electricity_offpeak_per_kwh,
                heat_per_mj=excluded.heat_per_mj,
                co2_per_kg=excluded.co2_per_kg,
                water_per_m3=excluded.water_per_m3,
                source=excluded.source,
                tou_windows=excluded.tou_windows,
                preset=excluded.preset
            returning id
            """,
            (
                organization_id, site_id, tariff["currency"], tariff["effective_from"],
                tariff["electricity_peak_per_kwh"], tariff["electricity_offpeak_per_kwh"],
                tariff["heat_per_mj"], tariff["co2_per_kg"], tariff["water_per_m3"],
                tariff["source"], Jsonb(tariff["tou_windows"]), tariff.get("preset"),
            ),
        ).fetchone()
    return {"id": str(row[0]), **tariff}
