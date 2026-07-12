# Product Requirements Document

## Product outcome

Varianz turns fragmented greenhouse operating data into traceable decisions. The MVP must convincingly show an operator and a commercial stakeholder what happened, what is likely next, what is abnormal, and what safe scenario may reduce resources while maintaining climate constraints.

### Users and journeys

| Persona | Primary job | Successful journey |
|---|---|---|
| Operator | Maintain stable climate with efficient inputs | Replay shift → see alert → inspect drivers → compare scenario → acknowledge |
| Energy/data analyst | Validate performance and models | Select period → inspect EnPI/baseline → view uncertainty/evidence → export result |
| Demo visitor | Understand value quickly | Guided story → anomaly → quantified scenario → grounded agent explanation |
| Org admin | Protect tenant data | Invite user → assign site role → review audit events |

## Scope

In scope: historical ingestion, canonical data, session replay, dashboards, EnPIs/baselines, forecasts, anomaly detection, constrained scenarios, LLM interpretation, authentication, tenant isolation, audit and reproducible demo seed.

Out: equipment write/control, causal claims, production/quality ML, billing, mobile native app, certification workflow, live vendor connector, autonomous agent, custom customer model training.

### Product assumptions and constraints

- Demo data represents one research greenhouse compartment and does not establish Ontario commercial savings.
- The operator remains accountable for action; the product supplies decision support and evidence.
- “Real time” in the MVP means replayed historical observations on a virtual clock, not live telemetry.
- Economic results use the dataset's challenge assumptions unless a versioned Ontario tariff is configured, and must be labelled accordingly.
- Browser support: latest two stable versions of Chrome, Edge and Safari; desktop and tablet are primary.

## Functional requirements

| ID | Requirement | Acceptance summary |
|---|---|---|
| FR-01 | Authenticate and authorize users by organization, site and role | Cross-tenant access tests fail closed |
| FR-02 | Import Wageningen sources through versioned CSV adapters | Counts, hashes, units and rejects reconcile |
| FR-03 | Expose synchronized historical and derived time series | Queries use explicit site, metric, interval and time range |
| FR-04 | Create an independent replay session per user | Play/pause/seek/step/speed/reset never affects another user |
| FR-05 | Present executive and technical dashboards | Both share replay cursor and metric definitions |
| FR-06 | Calculate versioned EnPIs and energy baselines | Result records period, variables, data/model version and uncertainty |
| FR-07 | Generate forecasts and anomaly events | Each output includes horizon/severity, confidence and contributors |
| FR-08 | Create and compare constrained scenarios | Baseline delta covers energy, cost, climate and uncertainty |
| FR-09 | Explain evidence and draft scenarios through an LLM | Claims cite internal evidence IDs; persistence requires confirmation |
| FR-10 | Record immutable audit evidence | Actor, tenant, time, action, input/output IDs and versions retained |
| FR-11 | Export a human-readable evidence report | Export matches dashboard values for the same snapshot |
| FR-12 | Run a deterministic guided demo | Fresh seed completes the documented story without manual repair |

Detailed performance, resilience, privacy and security acceptance criteria are normative in [NFR and Security](09-nfr-security.md). Requirement priority uses MoSCoW: FR-01 through FR-10 and FR-12 are Must; FR-11 is Should.

## Primary use-case acceptance

**UC-01 Investigate anomaly:** Given an authorized operator at a replay cursor with a seeded anomaly, when they open the event, then the system shows affected metrics, start/duration/severity, quality status, top contributing signals, forecast residual and evidence IDs without exposing future observations.

**UC-02 Compare scenario:** Given an approved constraint/model version, when an analyst previews modified setpoints, then the system returns a feasible or rejected result with baseline/candidate values, energy and cost deltas, climate margins, uncertainty, extrapolation score and versions; no equipment command is produced.

**UC-03 Ask Varianz:** Given a question about the visible period, when the agent answers, then every numerical claim references authorized tool evidence and uses the session revision; saving a scenario requires explicit, single-use confirmation.

## Success metrics

- 100% of displayed official metrics resolve to a versioned definition and source records.
- Zero cross-tenant findings in automated authorization tests.
- Replay controls acknowledge within 300 ms; dashboard refresh p95 under 2 s for demo load.
- Forecast promoted only when it beats the declared naive baseline under walk-forward evaluation.
- At least 90% of seeded anomalies detected with under 5% alerting on labelled normal windows.
- 100% of sampled agent numerical claims match tool evidence; zero unconfirmed scenario writes.
- Guided demo completes in under 7 minutes.
