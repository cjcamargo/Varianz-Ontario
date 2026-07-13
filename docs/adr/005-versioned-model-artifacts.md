# ADR-005: Versioned model artifacts for online serving

Status: Accepted — 2026-07-13

## Decision

Train and validate the demo energy baseline offline. Commit its small, immutable artifact under
`services/api/artifacts/energy-baseline/<version>` and load it once into API memory at startup.
The online path selects the latest daily prediction whose `as_of` is not later than the replay
cursor. It does not fit, backtest or promote a model during a dashboard request.

Supabase stores the active artifact registry, audit metadata and effective dates. Git is the
artifact store for this fixed demo dataset; Render is only the execution environment. Future
customer artifacts move to private object storage without changing the registry contract.

Every artifact contains a manifest with data, definition and model versions, source dataset hash,
coverage and file checksums; a model specification/model card; and precomputed walk-forward
predictions. A version mismatch or checksum failure prevents startup. Runtime calculation remains
an explicit local fallback for cursors outside artifact coverage, and is labeled as such.

## Consequences

- Baseline serving is deterministic, auditable and approximately constant time.
- Replay requests preserve point-in-time selection and cannot read a future prediction.
- Retraining becomes a reviewed release action with a model-version bump.
- Git is acceptable only while the artifact is small and contains no customer-sensitive data.
