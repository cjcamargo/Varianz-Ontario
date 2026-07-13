alter table analytics.model_artifact
  add column if not exists model_family text not null default 'energy_baseline';

drop index if exists analytics.one_active_model_artifact_per_site;
create unique index if not exists one_active_model_artifact_per_site_family
  on analytics.model_artifact(site_id, model_family) where status = 'active';

create table if not exists analytics.intraday_energy (
  organization_id uuid not null references app.organization,
  site_id uuid not null references app.site,
  observed_at timestamptz not null,
  heat_mj_m2 double precision not null,
  electricity_kwh_m2 double precision not null,
  co2_kg_m2 double precision not null,
  quality text not null check(quality in ('allocated','imputed')),
  model_version text not null,
  created_at timestamptz not null default now(),
  primary key(site_id, observed_at, model_version)
);

create table if not exists analytics.energy_allocation_calibration (
  organization_id uuid not null references app.organization,
  site_id uuid not null references app.site,
  as_of_day date not null,
  training_days integer not null check(training_days > 0),
  factors jsonb not null,
  fit_r2 jsonb not null,
  model_version text not null,
  created_at timestamptz not null default now(),
  primary key(site_id, as_of_day, model_version)
);

create index if not exists intraday_energy_cursor_lookup
  on analytics.intraday_energy(site_id, observed_at);

alter table analytics.intraday_energy enable row level security;
alter table analytics.energy_allocation_calibration enable row level security;

drop policy if exists intraday_energy_read on analytics.intraday_energy;
create policy intraday_energy_read on analytics.intraday_energy for select to authenticated
  using(app.is_member(organization_id));
drop policy if exists energy_calibration_read on analytics.energy_allocation_calibration;
create policy energy_calibration_read on analytics.energy_allocation_calibration for select to authenticated
  using(app.is_member(organization_id));
