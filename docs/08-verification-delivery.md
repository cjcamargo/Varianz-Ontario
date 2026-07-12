# Verification, Delivery and Backlog

## Traceability and acceptance

| Requirement group | Design evidence | Verification |
|---|---|---|
| FR-01, GOV roles | RLS/JWT architecture | tenant matrix and privilege tests |
| FR-02, DATA-01/02 | adapters and layered pipeline | fixture, checksum, reject and reconciliation tests |
| FR-03–05 | APIs, replay revision, UX | contract, concurrency and end-to-end tests |
| FR-06/07, GOV-01–06 | metric registry/model artifacts | formula fixtures, walk-forward and reproducibility tests |
| FR-08 | constrained optimizer | bounds, infeasible, extrapolation and uncertainty tests |
| FR-09 | typed tools/confirmation | golden eval, injection and unauthorized-write tests |
| FR-10/11 | evidence/audit | immutability and dashboard/export parity tests |
| FR-12 | seed and script | clean-environment demo rehearsal |

### Requirement-level evidence

| ID | Test ID | Required artifact |
|---|---|---|
| FR-01 | SEC-E2E-01 | two-tenant role-matrix report |
| FR-02 | DATA-REC-01 | signed reconciliation JSON |
| FR-03 | API-CON-01 | OpenAPI contract and point-in-time query tests |
| FR-04 | RPL-E2E-01 | two-user/two-tab replay concurrency recording |
| FR-05 | UX-E2E-01 | synchronized dashboard snapshot tests |
| FR-06 | ANA-REP-01 | reproducible EnPI/EnB fixture and model card |
| FR-07 | ML-BT-01 | locked-test forecast/anomaly report |
| FR-08 | OPT-SAFE-01 | constraint, infeasible and extrapolation report |
| FR-09 | LLM-EVAL-01 | golden-set evidence/safety report |
| FR-10 | AUD-IMM-01 | append-only/permission test report |
| FR-11 | EXP-PAR-01 | export/dashboard parity hashes |
| FR-12 | DEMO-E2E-01 | clean-seed seven-minute rehearsal |
| GOV-01–07 | GOV-REV-01 | approved governance-object sample and ISO mapping review |
| DATA-01–02 | DATA-REC-01 | source hash, quarantine and adapter report |
| ML-01 | ML-BT-01 | leakage checklist, folds and promotion decision |
| NFR-01–12 | NFR-GATE-01 | performance, restore, accessibility, security and cost bundle |

## Delivery sequence

| Epic | Outcome | Depends on |
|---|---|---|
| E1 Foundation | monorepo, CI, environments, migrations, Auth/RLS | approved docs |
| E2 Data | adapters, canonical store, reconciliation, seed | E1 |
| E3 Replay/API | private clock, time-series and snapshot contracts | E2 |
| E4 Dashboards | Overview, Energy, Climate, evidence UI | E3 |
| E5 Analytics | KPI registry, EnB, forecasts, anomalies, registry | E2–E4 |
| E6 Scenarios | constraints, optimizer, comparison and audit | E5 |
| E7 Agent | tools, structured response, confirmation, evals | E4–E6 |
| E8 Hardening | exports, observability, accessibility, demo rehearsal | all |

Priority is E1→E4 for a vertical slice, then E5→E7. Each epic is releasable behind feature flags. No production connector or actuator work enters this backlog.

## Definition of Ready

Requirement has owner, acceptance criteria, UX/API/data contract, security classification, dependencies, test approach and sample evidence. ML work additionally has target, decision horizon, naive baseline and leakage-safe split. Agent work has tool schema and golden eval cases.

## Definition of Done

Code reviewed; types/lint/tests pass; migrations reset and seed cleanly; RLS and audit verified; docs/contracts updated; monitoring added; accessibility checked; no critical security findings; relevant model/agent thresholds pass; staging evidence linked; product owner accepts the story.

## Release gates

1. Architecture baseline approval.
2. Data reconciliation report approval.
3. Vertical replay/dashboard demo.
4. Model cards and offline evaluation approval.
5. Agent safety/evidence evaluation approval.
6. Full seven-minute demo, rollback and recovery rehearsal.

Each gate produces an immutable release-evidence manifest containing commit/build ID, dataset/schema/model/prompt versions, environment, test artifact links, approver, decision and timestamp. A failed Must requirement blocks the release; exceptions require a time-bounded written risk acceptance by both founders and may never waive tenant isolation, secret protection or the no-control boundary.

## Architecture decisions

See the normative [ADR index](adr/README.md) for ADR-001 through ADR-004.
