create table if not exists analytics.model_artifact (
  id text primary key,
  organization_id uuid not null references app.organization,
  site_id uuid not null references app.site,
  model_version text not null,
  data_version text not null,
  definitions_version text not null,
  artifact_uri text not null,
  manifest_sha256 text not null check(length(manifest_sha256) = 64),
  effective_from timestamptz not null,
  effective_to timestamptz,
  status text not null check(status in ('candidate','active','retired')),
  metadata jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique(site_id, model_version)
);

create unique index if not exists one_active_model_artifact_per_site
  on analytics.model_artifact(site_id) where status = 'active';

alter table analytics.model_artifact enable row level security;
drop policy if exists model_artifact_read on analytics.model_artifact;
create policy model_artifact_read on analytics.model_artifact for select to authenticated
  using(app.is_member(organization_id));
