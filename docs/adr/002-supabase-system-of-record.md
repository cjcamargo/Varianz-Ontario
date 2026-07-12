# ADR-002: Supabase PostgreSQL as system of record

Status: Accepted | Date: 2026-07-11

## Context and decision

Use managed Supabase PostgreSQL for durable operational/analytical state, Auth for identity and Realtime for authorized invalidation/session events. API reads remain authoritative; WebSocket events do not contain analytical truth.

## Consequences and reversal trigger

RLS, migrations, restore tests and plan/region review are mandatory. Reconsider if pilot residency, recovery, time-series scale or commercial constraints cannot be satisfied.

