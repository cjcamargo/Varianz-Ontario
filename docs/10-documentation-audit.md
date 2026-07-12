# Documentation Audit and Risk Register

Audit date: 2026-07-11 | Baseline reviewed: v0.1 | Result: **v0.2 review-ready, pending founder approval**

## Findings and remediation

| Finding | Severity | v0.2 remediation |
|---|---|---|
| No measurable NFR, recovery or privacy contract | High | Added NFR-01–12, RPO/RTO, retention and restore gate |
| API named endpoints but not payload/concurrency semantics | High | Added envelopes, errors, idempotency, revision and scenario contract |
| RLS intent lacked role matrix/threat tests | High | Added permission matrix, tenant guard and adversarial cases |
| LLM safety lacked structured threat model | High | Added injection, output, agency, cost and evidence controls aligned to OWASP GenAI risks |
| Data entities lacked relationships/quality thresholds | Medium | Added ERD, identifiers, reconciliation and migration policy |
| ML promotion criteria were qualitative | Medium | Added explicit model gates and fallback behavior in analytics spec |
| ADRs referenced but absent | Medium | Materialized ADR index and four accepted decisions |
| Traceability grouped requirements too broadly | Medium | Expanded verification matrix and named release evidence |
| Commercial claims could overstate dataset evidence | High | Added research-data limitation and required economic/causal labels |

## Residual product and delivery risks

| ID | Risk | Likelihood/impact | Mitigation and trigger | Owner |
|---|---|---|---|---|
| R-01 | One compartment/six months fails to generalize to Ontario sites | High/High | Treat as demo; collect ≥1 Ontario pilot; no savings guarantee | CEO + CTO |
| R-02 | Only 166 daily resource points weaken daily EnB | Medium/High | Prefer interpretable baseline, bootstrap intervals, retain naive model if gate fails | CTO |
| R-03 | Production/quality sparsity invites unsupported ROI narrative | High/High | Context-only labels; exclude from optimizer objective | CEO + CTO |
| R-04 | Surrogate optimizer recommends unsafe extrapolation | Medium/High | historical bounds, constraint margin, extrapolation block, operator review | CTO/COO |
| R-05 | Agent invents explanation or leaks tenant data | Medium/High | typed tools, evidence validation, RLS evals, kill switch | CTO |
| R-06 | Two-person team overbuilds platform foundations | High/Medium | modular monolith; vertical slice E1–E4 before advanced ML | CTO/COO |
| R-07 | ISO-aligned language interpreted as certification | Medium/High | approved wording and disclaimer on UI/exports/sales material | CEO/CMO |
| R-08 | Supabase tier lacks required recovery/region capability | Medium/High | verify plan/region before staging gate; tested logical backup fallback | CTO |
| R-09 | Demo anomaly is not compelling/reproducible | Medium/Medium | deterministic seed fixture and seven-minute rehearsal | COO |

## Approval blockers

Before build, founders must fill the approval record in [README](README.md) and accept: two-module scope, English-only UI, no physical control, context-only production, default retention, demo SLOs and research-data disclaimer. Before pilot, replace demo tariff/constraints, confirm data residency/privacy terms, define customer RACI and execute restore plus tenant-isolation tests.

