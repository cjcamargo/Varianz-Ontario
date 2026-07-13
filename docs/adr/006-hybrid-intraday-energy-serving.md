# ADR-006: Hybrid intraday energy serving

Status: Accepted — 2026-07-13

## Decision

Materialize five-minute heat, electricity and carbon-dioxide allocations for completed days. Store
the production serving copy and daily calibration records in Supabase, and commit a compressed,
checksummed artifact to GitHub as the reproducible demo seed.

At request time the API reads completed allocations, applies the configured tariff schedule, and
transforms only intervals without an authoritative completed-day meter. Normally this is the
current replay day. Provisional values use conversion factors trained exclusively on the previous
seven completed days. When the daily meter becomes available, the worker replaces provisional
values with meter-conserving allocations.

Non-`all` dashboard requests load at most seven days of intraday evidence because the operational
EnPIs use a seven-day reference. The complete-period view remains available explicitly. Supabase
read models load once during API warmup and are reused across sessions; replay sessions only filter
by cursor and never duplicate historical data.

## Consequences

- Historical disaggregation and fit diagnostics are removed from the online request path.
- The realtime transformation remains causal and incremental.
- Tariff changes do not require rebuilding the energy artifact.
- Every completed day must reconcile to authoritative daily meters before publication.
