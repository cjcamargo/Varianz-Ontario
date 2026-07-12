create schema if not exists analytics;

alter table app.site add column if not exists growing_area_m2 numeric check(growing_area_m2 > 0);
alter table app.metric_definition add column if not exists grain text not null default '5min';
alter table app.metric_definition add column if not exists aggregation text not null default 'mean';
alter table app.metric_definition add column if not exists source text not null default 'unknown';
alter table app.metric_definition add column if not exists quality_rule text not null default 'finite';
alter table app.metric_definition add column if not exists owner text not null default 'Varianz Analytics';

create table if not exists analytics.kpi_snapshot (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references app.organization,
  site_id uuid not null references app.site,
  metric_code text not null,
  period_start timestamptz not null,
  period_end timestamptz not null,
  value double precision,
  unit text not null,
  quality text not null,
  definitions_version text not null,
  evidence jsonb not null default '{}',
  calculated_at timestamptz not null default now(),
  unique(site_id, metric_code, period_start, period_end, definitions_version)
);

create table if not exists analytics.baseline_run (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references app.organization,
  site_id uuid not null references app.site,
  cursor_at timestamptz not null,
  model_version text not null,
  selected_model text not null,
  promoted boolean not null,
  metrics jsonb not null,
  prediction jsonb not null,
  evidence jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists analytics.anomaly_event (
  id uuid primary key,
  organization_id uuid not null references app.organization,
  site_id uuid not null references app.site,
  code text not null,
  category text not null,
  severity text not null check(severity in ('low','medium','high','critical')),
  started_at timestamptz not null,
  ended_at timestamptz,
  duration_minutes integer not null,
  observed double precision,
  expected double precision,
  residual double precision,
  confidence text not null,
  contributors jsonb not null default '[]',
  evidence jsonb not null default '{}',
  model_version text not null,
  created_at timestamptz not null default now(),
  unique(site_id, code, started_at, model_version)
);

create table if not exists app.tariff_profile (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references app.organization,
  site_id uuid not null references app.site,
  currency text not null default 'CAD',
  effective_from date not null,
  electricity_peak_per_kwh numeric check(electricity_peak_per_kwh >= 0),
  electricity_offpeak_per_kwh numeric check(electricity_offpeak_per_kwh >= 0),
  heat_per_mj numeric check(heat_per_mj >= 0),
  co2_per_kg numeric check(co2_per_kg >= 0),
  water_per_m3 numeric check(water_per_m3 >= 0),
  source text not null,
  created_by uuid,
  created_at timestamptz not null default now(),
  unique(site_id, effective_from)
);

create index if not exists anomaly_event_lookup
  on analytics.anomaly_event(organization_id, site_id, started_at desc);

alter table analytics.kpi_snapshot enable row level security;
alter table analytics.baseline_run enable row level security;
alter table analytics.anomaly_event enable row level security;
alter table app.tariff_profile enable row level security;

drop policy if exists kpi_read on analytics.kpi_snapshot;
create policy kpi_read on analytics.kpi_snapshot for select to authenticated
  using(app.is_member(organization_id));
drop policy if exists baseline_read on analytics.baseline_run;
create policy baseline_read on analytics.baseline_run for select to authenticated
  using(app.is_member(organization_id));
drop policy if exists anomaly_read on analytics.anomaly_event;
create policy anomaly_read on analytics.anomaly_event for select to authenticated
  using(app.is_member(organization_id));
drop policy if exists tariff_read on app.tariff_profile;
create policy tariff_read on app.tariff_profile for select to authenticated
  using(app.is_member(organization_id));
drop policy if exists tariff_write on app.tariff_profile;
create policy tariff_write on app.tariff_profile for all to authenticated
  using(app.has_role(organization_id,array['admin']))
  with check(app.has_role(organization_id,array['admin']));

