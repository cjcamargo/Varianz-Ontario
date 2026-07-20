# Standards and Governance Specification

## Position

Varianz is designed to support an energy management process aligned with [ISO 50001:2018](https://www.iso.org/standard/69426.html), its 2024 climate-action amendment, and [ISO 50006:2023](https://www.iso.org/standard/79367.html). It is neither a certification body nor proof of customer certification.

| Standard intent | Varianz evidence | Requirement |
|---|---|---|
| Energy review and significant energy uses (SEU) | Versioned SEU register: heat and artificial lighting initially | GOV-01 |
| EnPI and energy baseline (EnB) | Definition, owner, unit, boundary, period, relevant variables and model artifact | GOV-02 |
| Operational planning/control | Approved constraints and scenario evidence; no actuator writes | GOV-03 |
| Monitoring and measurement | Quality status, lineage, EnPI trend and baseline residuals | GOV-04 |
| Demonstrate improvement | Frozen comparison snapshot with normalized delta and uncertainty | GOV-05 |
| Continual improvement | Review/approval history and superseded versions preserved | GOV-06 |
| Climate-change consideration | Governance review field records whether climate conditions affect context/interested parties | GOV-07 |

## Governed objects

Every KPI/EnPI/EnB/model/scenario/recommendation has UUID, semantic version, status (`draft|validated|approved|retired`), owner, tenant/site boundary, effective dates, formula/code artifact, input dataset version, assumptions, uncertainty method, approval and immutable evidence hash. Approved records are never overwritten; a successor supersedes them.

Initial EnPIs are daily heat MJ/m², electricity kWh/m², electricity converted to MJ/m², and total delivered energy MJ/m². Weather-normalized indicators are approved only after relevant-variable and residual reviews. Production normalization is labelled contextual until sample sufficiency is established.

The demo also maintains a distinct energy target line at 5% below the weather-normalized heat EnB (`energy-target-demo-1.0.0`). This is a provisional Varianz management objective used to demonstrate baseline-to-target accounting; ISO 50001 does not prescribe the percentage. A pilot must replace it with an organization-approved, versioned objective recording owner, boundary, period, rationale, relevant variables, approval and effective dates. Actual, EnB and target remain separate series, and monetary values are labelled association-based estimates rather than guaranteed savings.

## Controls

- Data quality states: `valid`, `suspect`, `invalid`, `imputed`; official results exclude invalid data and disclose suspect/imputed share.
- Recommendations expire at the replay cursor plus their horizon, require model/constraint versions, and state that operator review is required.
- Roles: Viewer (read), Operator (acknowledge/run), Analyst (draft/validate), Admin (membership), Approver (approve/retire). No role can rewrite audit history.
- Retain demo audit/evidence for one year; secrets and raw prompts are excluded or redacted. Customer policy will override retention later.
- Quarterly governance review covers drift, false alerts, model promotion, metric definitions, access and climate-context field.

## EnPI and EnB lifecycle

1. Define energy boundary, SEU, accountable owner and intended decision.
2. Select a representative baseline period and document exclusions.
3. Identify relevant variables using domain rationale plus statistical evidence; do not select solely by correlation.
4. Fit and validate the baseline using the locked temporal procedure in the ML specification.
5. Freeze formula/model, coefficients, data version, uncertainty and applicability conditions.
6. Compare reporting periods only inside applicability; disclose invalid/suspect/imputed coverage.
7. Review after material process/asset/boundary/tariff change, sustained drift or at least annually; recalculation creates a new version and preserves the old basis.

Minimum improvement evidence contains baseline/reporting periods, boundary, actual and normalized consumption, relevant-variable values, adjustment method, absolute/relative delta, uncertainty, exclusions, reviewer and evidence hash. This supports an EnMS process but does not by itself establish conformity with every ISO clause.
