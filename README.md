# Varianz by Operion — Operational Intelligence 0.2

Operational Intelligence for Controlled Environment Agriculture. Varianz 0.2 delivers point-in-time
diagnosis across energy/resources and climate, with natural anomaly detection and an
evidence-grounded OpenAI interpretation layer.

## Structure

- `apps/web`: Next.js operator/investor dashboard with analyst drill-down.
- `services/api`: FastAPI application and domain logic.
- `supabase/migrations`: PostgreSQL schema and tenant RLS.
- `tests`: dependency-light domain tests.
- `docs`: approved product and architecture baseline.

## Bootstrap

Use Python 3.12 and Node 20+. Copy `.env.example` to `.env`, then install
`pip install -e ".[dev]"` and `pnpm install --dir apps/web`. Run
`uvicorn varianz.main:app --app-dir services/api --reload` and `pnpm --dir apps/web dev`.
Set `DATA_BACKEND=auto` to prefer Supabase with ZIP fallback, `supabase` to fail closed when
PostgreSQL is unavailable, or `zip` for credential-free checks.

Run the credential-free checks with `python -m unittest discover -s tests -v`.

## Intraday energy and operational efficiency

The Energy & Resources module reconstructs five-minute or hourly heat, electricity and CO₂ from
daily authoritative meters. The meter provides mass and equipment telemetry provides shape:
pipe-to-air temperature excess for heat, lamp PAR for electricity and the dosing signal for CO₂.
Completed days conserve each measured total exactly. The incomplete replay day uses a median
calibration factor from up to seven prior completed days and is visibly marked `provisional`; it
never reads the current day's future meter value.

`energy-intraday-1.0.0` also exposes evidence-backed EnPIs and persistent observations for heating
with open vents, supplemental lighting under high daylight, open-screen night heating and tariff
peak concentration. These are diagnostics, not causal or savings claims. Interval cost and peak
share stay hidden until a sourced, effective tariff and ToU schedule are versioned in Settings.

## Private demo authentication

The web app uses Supabase email/password authentication and sends the active access token to
FastAPI on every request. Configure the three `NEXT_PUBLIC_*` variables shown in `.env.example`
and set `AUTH_REQUIRED=true` for public deployments. User registration is intentionally not
exposed; create demo accounts in Supabase Auth. See `docs/12-authentication-deployment.md`.

## Supabase bootstrap

After configuring `DATABASE_URL` with the Supabase session-pooler URI, run:

```bash
python scripts/db_admin.py status
python scripts/db_admin.py migrate
python scripts/db_admin.py seed
```

The migration is transactional. The Wageningen seed uses deterministic identifiers and conflict
handling, so rerunning it does not duplicate observations.

## Varianz 0.2 workflow

The synchronized UI exposes Overview, Energy & Resources, Operational Climate, Anomalies,
Ask Varianz and Ontario Tariff Settings. Every analytical response includes replay revision,
data/definition/model versions, quality state and evidence IDs. Cost remains hidden until an
effective CAD tariff profile is entered. Forecasting and optimization remain outside 0.2; no
result is presented as causal or as guaranteed savings.
