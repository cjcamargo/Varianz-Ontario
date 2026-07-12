# UX and Replay Specification

## Information architecture

English-only desktop-first shell: Overview, Energy & Resources, Climate, Anomalies, Scenarios, Assistant and Evidence. Header always shows site, historical cursor, `LIVE SIMULATION` badge, data quality and replay controls.

Overview provides five decision cards: current energy/resource state, climate compliance, active anomaly, 24 h forecast and best unconfirmed scenario. Technical pages expose synchronized charts, definitions and evidence drawer. Observed values use solid lines; estimated dotted; forecast shaded intervals; simulated purple; recommendations amber with “operator review required.” Color is never the only distinction.

## Replay behavior

- Create restores a private session at dataset start; play advances virtual time; pause freezes; seek is bounded; step uses one source interval; reset returns to start.
- Changing cursor cancels stale requests and recomputes the entire visible snapshot using `session_id + revision`. Views may not mix revisions.
- End-of-data pauses and explains completion. Refresh restores session. Two tabs use optimistic revision conflict messaging rather than silently overwriting.
- Charts never reveal future observations; forecasts/scenarios may extend beyond cursor and are visually distinct.

## Demo script

1. Open seeded greenhouse and explain the synchronized operation.
2. Advance to a deterministic heat/climate anomaly.
3. Open contributors, data quality and forecast evidence.
4. Ask the assistant to explain it in operator language.
5. Preview a constrained setpoint scenario and compare energy/cost/climate uncertainty.
6. Confirm saving the scenario, not physical execution.
7. Show EnPI/baseline evidence and audit trail.

Accessibility target: WCAG 2.2 AA for keyboard navigation, contrast, focus, chart summaries and reduced motion. Responsive tablet is supported; phone receives read-only summary in MVP.

