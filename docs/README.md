# Varianz by Operion — MVP Documentation Baseline v0.2

Status: **Review-ready baseline** | Owner: CTO/COO | Product language: English | Updated: 2026-07-11

This package converts the founder inputs in [Strategic Direction](../01_Strategic_Direction_Working_Draft_v0.1.pdf) and [MVP Guidelines](../Platform%20Vision%20and%20MVP%20Guidelines%20v0.1.pdf) into a testable specification. Approval of this baseline is the gate for application implementation.

## Document map

1. [Product requirements](01-product-requirements.md)
2. [Standards and governance](02-standards-governance.md)
3. [Data architecture and contracts](03-data-architecture.md)
4. [Solution architecture](04-solution-architecture.md)
5. [Analytics, ML and optimization](05-analytics-ml.md)
6. [LLM agent](06-llm-agent.md)
7. [UX and replay](07-ux-replay.md)
8. [Verification, delivery and backlog](08-verification-delivery.md)
9. [Non-functional requirements and security](09-nfr-security.md)
10. [Documentation audit and risk register](10-documentation-audit.md)
11. [Architecture decision records](adr/README.md)

## Decisions

- MVP modules: Energy & Resource Intelligence and Operational Climate Intelligence.
- Production, quality and economics are contextual only.
- Advice and simulation only; no physical control.
- English UI, multi-tenant data model, private replay clock per user.
- Next.js + FastAPI modular monolith, Supabase PostgreSQL/Auth/Realtime, Python worker, OpenAI Responses API.
- ISO-aligned evidence model; Varianz does not claim ISO certification.

## Change control

Changes require an issue describing affected requirement IDs, contract/schema impact, migration, tests and approver. Architecture changes also require an ADR under `docs/adr/`. Versions follow `major.minor`: major changes alter scope/contracts; minor changes clarify or add backward-compatible requirements.

## Approval record

Approval requires CTO/COO sign-off for technical feasibility and CEO/CMO sign-off for product scope. Record approver, date, version and conditions in the table below; blank means not approved for build.

| Role | Approver | Date | Decision/conditions |
|---|---|---|---|
| CTO/COO |  |  |  |
| CEO/CMO |  |  |  |
