# Non-Functional Requirements and Security

These requirements are release gates, not aspirations. Demo load is 25 concurrent authenticated users, one greenhouse, 50 metrics, and the full source history.

## Service levels

| ID | Requirement | Verification |
|---|---|---|
| NFR-01 | Read API p95 ≤750 ms and p99 ≤1.5 s; dashboard usable p95 ≤2 s | staged load test with warm cache |
| NFR-02 | Replay mutation p95 ≤300 ms; event delivered p95 ≤1 s | API/WebSocket timing test |
| NFR-03 | Monthly demo availability target 99.5%, excluding announced maintenance | synthetic monitor |
| NFR-04 | API/worker RPO ≤24 h and RTO ≤4 h; configuration/code RPO 0 through version control | quarterly restore exercise |
| NFR-05 | One failed worker job cannot publish a partial dataset/model/scenario | fault-injection and transaction tests |
| NFR-06 | 100% tenant tables have RLS; anon has no operational data access | catalog policy test and adversarial matrix |
| NFR-07 | Encrypt in transit and at rest through managed platform controls; secrets never enter client bundles/logs | config and bundle scan |
| NFR-08 | WCAG 2.2 AA on critical journeys | automated plus keyboard/manual audit |
| NFR-09 | API changes are OpenAPI-diff compatible within `/v1` | CI contract gate |
| NFR-10 | Cost budgets and alerts exist for database, compute and OpenAI; agent hard-stops at configured per-request limit | budget/failure tests |
| NFR-11 | Logs contain request/session/revision and versions, but no secrets or raw tenant payloads by default | logging assertions |
| NFR-12 | Dependency/license inventory and critical vulnerability scan pass before release | SBOM and CI scan |

Backups are plan-dependent: demo must use a Supabase tier with daily backups or run a daily encrypted off-platform logical dump. PITR is enabled if the selected tier supports it. Restore tests, not provider claims, determine compliance with NFR-04.

## Authorization matrix

| Capability | Viewer | Operator | Analyst | Admin | Approver |
|---|---:|---:|---:|---:|---:|
| View dashboards/evidence | ✓ | ✓ | ✓ | ✓ | ✓ |
| Control own replay | ✓ | ✓ | ✓ | ✓ | ✓ |
| Acknowledge anomaly |  | ✓ | ✓ |  | ✓ |
| Preview/save scenario |  | ✓ | ✓ |  | ✓ |
| Draft metric/model/constraint |  |  | ✓ |  | ✓ |
| Approve/retire governed object |  |  |  |  | ✓ |
| Manage membership/roles |  |  |  | ✓ |  |
| Read another tenant |  |  |  |  |  |

RLS derives membership from server-verifiable identity, never user-supplied `organization_id`. Service-role operations require a server-side tenant guard and emit an audit event. Exposed views use security-invoker behavior or remain in a non-exposed schema.

## Threat model

| Threat | Control | Test |
|---|---|---|
| Cross-tenant IDOR/RLS bypass | tenant from JWT, deny-by-default RLS, opaque UUIDs, server authorization | swap every object ID across two seeded tenants |
| Prompt injection from user/data | untrusted-content boundaries, fixed tool allowlist, no SQL/web/control tools | direct/indirect injection golden suite |
| Excessive agency | preview/confirm split, one-use token, least privilege, no actuator interface | attempt writes without/after token expiry |
| Insecure LLM output | structured schema, evidence validator, UI escaping, no output execution | malformed HTML/JSON/tool output tests |
| Denial of wallet/service | rate, token, time, tool-call and date-range caps; circuit breaker | concurrency and runaway-loop tests |
| Data/model poisoning | immutable source hash, quality gate, artifact approval, lineage | altered file/model signature test |
| Secret leakage | secret manager, redaction, client bundle/trace scan, rotation playbook | seeded canary secret test |
| Replay race/stale decision | optimistic revision and preview hash | two-tab concurrency test |

Security incidents follow detect → contain → revoke/rotate → preserve evidence → recover → review. A critical tenant isolation, secret exposure or unauthorized scenario-write finding blocks release.

## Privacy and retention

The demo dataset is non-personal operational data. User identity, chat text and audit actors are personal data: collect only account identifiers required for access/evidence, provide deletion/export workflow, and document hosting region before pilot onboarding. Raw agent conversations default to 30 days; tool/evidence metadata to one year; source/metric/model evidence to one year for demo. Legal/customer requirements supersede these defaults through an approved retention policy.

