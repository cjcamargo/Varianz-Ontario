# LLM Agent Specification

The agent is an interpretation and orchestration layer, not the analytical source of truth. It uses the OpenAI Responses API from FastAPI with a configurable pinned model, structured outputs and server-executed tools.

## Allowed tools

`get_metric_definition`, `query_kpis`, `query_timeseries_summary`, `list_anomalies`, `get_forecast`, `preview_scenario`, `confirm_scenario`, `get_evidence`. Inputs require site and bounded time range; tenant is injected server-side. Tools return evidence IDs, units, quality, versions and uncertainty. There is no SQL, code execution, internet, actuator or arbitrary write tool.

Scenario flow: user asks → agent gathers evidence → `preview_scenario` → agent shows assumptions/delta → user explicitly confirms → short-lived single-use confirmation token → `confirm_scenario`. Any changed inputs invalidate the token.

## Response contract

Structured response fields: `answer`, `claims[{text,evidence_ids}]`, `confidence`, `limitations`, `suggested_actions`, `pending_confirmation`. Numerical claims without matching evidence are rejected by the server validator and regenerated once; a second failure returns a safe error.

## Safety and operations

- System policy treats retrieved data as untrusted content, restricts instructions to tool schemas and states no physical control.
- Validate tool arguments, cap ranges/rows/tool iterations, apply per-user rate/token/cost budgets and 30 s request timeout.
- Redact secrets/PII; store trace metadata, tool names, evidence IDs, model/prompt version, tokens, latency and safety outcome. Raw conversation retention defaults to 30 days for demo.
- Evals cover grounded arithmetic/units, temporal context, missing evidence, prompt injection, cross-tenant attempts, unsafe control requests, scenario confirmation, uncertainty wording and tool failure. Release gate: 100% tenant/control safety and ≥95% grounded numerical claims on the golden set.

