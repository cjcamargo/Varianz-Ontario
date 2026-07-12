# ADR-004: No physical control in MVP

Status: Accepted | Date: 2026-07-11

## Context and decision

Historical data and an offline surrogate do not justify autonomous greenhouse control. The MVP may recommend, simulate and save scenarios, but cannot emit actuator commands or present execution language.

## Consequences and reversal trigger

Operators remain accountable and all UI/exports carry the decision-support label. Physical control requires a separate safety case, live validation, fail-safe integration, regulatory review and new ADR.

