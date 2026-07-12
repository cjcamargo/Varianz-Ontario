create extension if not exists pgcrypto;
create schema if not exists app;
create schema if not exists audit;

create table app.organization (id uuid primary key default gen_random_uuid(), name text not null, created_at timestamptz not null default now());
create table app.site (id uuid primary key default gen_random_uuid(), organization_id uuid not null references app.organization, name text not null, timezone text not null, area_m2 numeric check(area_m2 > 0));
create table app.membership (organization_id uuid not null references app.organization, user_id uuid not null references auth.users, role text not null check(role in ('viewer','operator','analyst','admin','approver')), primary key(organization_id,user_id));
create table app.metric_definition (id uuid primary key default gen_random_uuid(), code text unique not null, label text not null, dimension text not null, canonical_unit text not null, version integer not null default 1);
create table app.observation (id uuid primary key default gen_random_uuid(), organization_id uuid not null references app.organization, site_id uuid not null references app.site, metric_id uuid not null references app.metric_definition, observed_at timestamptz not null, value double precision, quality_state text not null check(quality_state in ('valid','suspect','invalid','imputed')), source_record_id text not null, recorded_at timestamptz not null default now(), unique(site_id,metric_id,observed_at,source_record_id));
create index observation_lookup on app.observation(organization_id,site_id,metric_id,observed_at desc);
create table app.replay_session (id uuid primary key default gen_random_uuid(), organization_id uuid not null references app.organization, site_id uuid not null references app.site, owner_id uuid not null references auth.users, dataset_version text not null, cursor_at timestamptz not null, minimum_at timestamptz not null, maximum_at timestamptz not null, speed numeric not null default 1, playing boolean not null default false, revision bigint not null default 0, updated_at timestamptz not null default now());
create table audit.event (id uuid primary key default gen_random_uuid(), organization_id uuid not null, actor_id uuid, action text not null, object_type text not null, object_id uuid, request_id uuid, evidence jsonb not null default '{}', occurred_at timestamptz not null default now());

create function app.is_member(org uuid) returns boolean language sql stable security definer set search_path='' as $$ select exists(select 1 from app.membership m where m.organization_id=org and m.user_id=(select auth.uid())) $$;
create function app.has_role(org uuid, roles text[]) returns boolean language sql stable security definer set search_path='' as $$ select exists(select 1 from app.membership m where m.organization_id=org and m.user_id=(select auth.uid()) and m.role=any(roles)) $$;

alter table app.organization enable row level security;
alter table app.site enable row level security;
alter table app.membership enable row level security;
alter table app.observation enable row level security;
alter table app.replay_session enable row level security;
alter table audit.event enable row level security;
create policy organization_read on app.organization for select to authenticated using(app.is_member(id));
create policy site_read on app.site for select to authenticated using(app.is_member(organization_id));
create policy membership_read on app.membership for select to authenticated using(app.is_member(organization_id));
create policy observation_read on app.observation for select to authenticated using(app.is_member(organization_id));
create policy replay_read on app.replay_session for select to authenticated using(app.is_member(organization_id));
create policy replay_insert on app.replay_session for insert to authenticated with check(app.is_member(organization_id) and owner_id=(select auth.uid()));
create policy replay_update on app.replay_session for update to authenticated using(owner_id=(select auth.uid())) with check(owner_id=(select auth.uid()));
create policy audit_read on audit.event for select to authenticated using(app.has_role(organization_id,array['analyst','approver']));

