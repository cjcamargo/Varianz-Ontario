# ADR-003: Typed LLM tools and evidence boundary

Status: Accepted | Date: 2026-07-11

## Context and decision

The LLM interprets deterministic analytics through allowlisted typed tools. It has no SQL, web, code or actuator access. Numerical claims require evidence IDs; scenario persistence uses preview plus explicit confirmation.

## Consequences and reversal trigger

This reduces flexibility but makes answers testable, tenant-safe and auditable. Add tools only with schema, authorization, evidence contract, threat review and eval coverage.

