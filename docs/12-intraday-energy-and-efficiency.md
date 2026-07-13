# Spec 12 — Intraday Energy Reconstruction & Energy-Efficiency Analysis

**Owner:** CTO/COO  ·  **Status:** implemented and verified  ·  **Target:** Varianz 0.3
**Prereq reading:** `05-analytics-ml.md`, `03-data-architecture.md`, `services/api/varianz/{dataset,analytics,metrics,store}.py`

---

## 1. Goal

The demo dataset records **energy only at daily granularity** (`Resources.csv`: `Heat_cons`,
`ElecHigh`, `ElecLow`, `CO2_cons` — 166 rows) while the **physical drivers of that energy are
recorded every 5 minutes** in the climate telemetry. Deliver two capabilities:

- **A. Intraday energy** — a 5-min / hourly reconstruction of heat, electricity and CO₂ energy,
  shown as time series in the Energy view.
- **B. Energy-efficiency analysis** — ISO 50006-style efficiency indicators (EnPIs) and
  detectable inefficiency events computed on that intraday energy.

### Validation evidence (already measured — use as acceptance targets)
Daily aggregates of the proposed 5-min proxies reconstruct the *measured* daily totals with:

| Channel | Proxy (5-min) | R² vs measured daily |
|---|---|---|
| `Heat_cons` | `max(PipeLow−Tair,0) + max(PipeGrow−Tair,0)` (pipe degree-excess) | **0.93** |
| Electricity (`ElecHigh+ElecLow`) | `Tot_PAR_Lamps` (lamp PAR) | **1.00** |
| Electricity (fallback) | `AssimLight` % | 0.97 |
| `CO2_cons` | `co2_dos` (dosing signal) | **1.00** |

Electricity is ~entirely lighting and CO₂ consumption *is* the dosing signal integrated, so those
two channels are near-exactly recoverable; heating is strong but imperfect (pipe heat also depends
on flow/surface area).

---

## 2. Non-negotiable constraints (inherit from the platform)

1. **Point-in-time / future-safe.** No reconstructed value at time *t* may use any measurement
   after the replay cursor. See §4.3 for the partial-current-day rule — this is the trickiest part.
2. **Mass-from-meter, shape-from-telemetry.** The measured daily total is authoritative. The
   telemetry only distributes it in time. Never *invent* energy — reconstruction is a
   **disaggregation**, not a new measurement. Label it as such.
3. **Evidence + versioning.** Every returned figure carries evidence IDs, `data_version`,
   `definitions_version`, and a new `model_version = "energy-intraday-1.0.0"`. Each 5-min point
   carries a `quality` tag (see §4.4).
4. **No causal claims, no savings claims.** Efficiency findings are *observations of state*
   ("heat delivered while vents were open"), never "you would save X by…". Cost stays hidden until
   a reviewed tariff profile exists (existing guardrail).
5. **ISO 50006 framing.** Efficiency indicators are EnPIs normalized against relevant variables;
   report actual vs expected + uncertainty, not verdicts.

---

## 3. Data availability & required ingestion changes

`load_replay_frame()` (`dataset.py`) keeps only columns in `OPERATIONAL_CODES` (`metrics.py`).
Currently available at 5-min: `Tair, PipeLow, PipeGrow, AssimLight, Tot_PAR, EnScr, VentLee,
Ventwind, Iglob, Tout, t_heat_vip, t_ventlee_vip, …`

**Missing from the registry (needed for best-fidelity proxies):** `Tot_PAR_Lamps`, `co2_dos`.

**Task 3.1** — Register both as 5-min metrics in `metrics.py` (`grain="5min"`), e.g.:
- `Tot_PAR_Lamps` — "Lamp PAR contribution", `umol/m2/s`, source `GreenhouseClimate`.
- `co2_dos` — "CO2 dosing rate", control signal, source `GreenhouseClimate`.
This automatically flows them into `OPERATIONAL_CODES` → `load_replay_frame` → the store query.

**Task 3.2 (Supabase path)** — the Supabase seed loads only registered metric codes
(`store.py::OPERATIONAL_CODES`). Update `supabase/migrations` + `scripts/db_admin.py seed` to
insert the two new metric definitions and their observations, then re-seed. The ZIP backend
(`DATA_BACKEND=zip`) needs no migration — it reads columns directly.

**Fallbacks if 3.1/3.2 are deferred:** electricity → `AssimLight` (already available, R²0.97);
CO₂ → allocate uniformly across the day (flag `quality="imputed"`), since `co2_dos` is otherwise
unavailable and CO₂ is a minor energy channel.

---

## 4. Part A — Intraday energy reconstruction

### 4.1 New module `services/api/varianz/energy.py`

```python
def intraday_energy_frame(
    operational: pd.DataFrame,   # 5-min climate+weather (load_replay_frame output), <= cursor
    resources:   pd.DataFrame,   # daily Resources, <= cursor
    cursor:      datetime,
    *, grain: str = "5min",      # "5min" | "1h"
) -> pd.DataFrame:
    """Return per-interval energy: columns
       time, heat_mj_m2, elec_kwh_m2, co2_kg_m2,
       elec_peak_kwh_m2, elec_offpeak_kwh_m2,   # split by tariff ToU windows (§B cost)
       quality  ('measured'|'allocated'|'provisional'|'imputed')
    Sums of completed days equal the measured daily Resources totals exactly."""
```

### 4.2 Reconstruction algorithm (per channel c ∈ {heat, elec, co2})

For step *i* in day *d* (steps restricted to `time <= cursor`):

- `proxy_i` — heat: `max(PipeLow−Tair,0)+max(PipeGrow−Tair,0)`; elec: `Tot_PAR_Lamps`
  (fallback `AssimLight`); co2: `co2_dos`. Clip negatives to 0.
- **Completed day** (`d < cursor.date()`), meter total `M_d` known:
  `energy_i = M_d · proxy_i / Σ_{j∈d} proxy_j`  → conserves `M_d` exactly.
  If `Σ proxy = 0`: distribute `M_d` uniformly; `quality="imputed"`.
- Aggregate to `grain` (`1h` = sum of 5-min energies in the hour).

### 4.3 Partial current day — the point-in-time rule (do not skip)

For the **current, incomplete** day the full-day meter reading is a *future* fact and must not be
used. Instead:
- Maintain a **rolling calibration factor** `k_c = median` over the last *K* completed days of
  `M_{c,d} / Σ proxy_{c,d}` (full-day proxy sum). Default `K = 7`, min 3.
- Current-day intraday energy: `energy_i = k_c · proxy_i`, tagged `quality="provisional"`.
- Never back-fill the current day with `M_d`. When the day completes it is re-computed exactly on
  the next cursor advance.

This is analogous to how `energy_baseline_frames` already treats the locked hold-out — reuse the
"only data ≤ cursor" discipline.

### 4.4 Quality tags
`measured`→completed day, proxy-allocated; `provisional`→current day via rolling k; `imputed`→zero
proxy fallback; propagate any upstream `suspect/invalid` sensor state if present.

### 4.5 API

Extend `GET /replay-sessions/{id}/energy-resources` payload with:
```jsonc
"intraday": {
  "grain": "5min",
  "series": [ {"time": "...", "heat_mj_m2": .., "elec_kwh_m2": .., "co2_kg_m2": ..,
               "elec_peak_kwh_m2": .., "elec_offpeak_kwh_m2": .., "quality": "measured"} ],
  "reconstruction": { "method": "meter-conserving disaggregation",
                      "calibration_days": 7, "model_version": "energy-intraday-1.0.0",
                      "fit_r2": {"heat": .., "elec": .., "co2": ..},   // rolling, informational
                      "evidence_ids": [...] }
}
```
Add `grain` query param (`5min|1h`, default `1h`). **Bound payload size** with striding like the
existing `_series()` for `7d`/`all` windows.

### 4.6 Frontend (EnergyView.tsx)

- New panel **"Intraday energy · selected chart range"** using the existing `ChartDateRange` +
  `LineChart`. Multi-line (heat MJ/m², electricity kWh/m², CO₂ kg/m²) with a **5min/1h grain
  toggle**. Style `provisional` points distinctly (dashed / lighter) and show a "provisional —
  current day" caption.
- Keep the existing daily cards; add a small note that intraday is a telemetry-based
  disaggregation of the measured daily totals.

### 4.7 Tests (`tests/test_core.py`)
- **Conservation:** for every completed day, `Σ intraday_channel ≈ measured daily total` (rtol 1e-6).
- **Future-safe:** with cursor mid-day, no `time > cursor`; current-day rows are `provisional` and
  independent of that day's final meter (assert reconstruction unchanged if a synthetic future
  meter is altered).
- **Fidelity:** rolling daily-aggregate vs measured `R² ≥ 0.90 heat / 0.97 elec / 0.99 co2`.
- **Grain:** hourly sums equal the constituent 5-min sums.

---

## 5. Part B — Energy-efficiency analysis

### 5.1 EnPIs (ISO 50006, computed on the intraday series up to the cursor)

Add to `energy.py::efficiency_indicators(intraday, operational, resources, cursor, tariff)`.
Each EnPI returns `{value, unit, expected, variance_pct, confidence, relevant_variables,
evidence_ids}` (mirror the `energy_baseline_frames` output shape).

1. **Lighting efficacy** — `elec_kwh / mol_PAR_delivered` where `mol_PAR = Σ Tot_PAR_Lamps·Δt/1e6`.
   Relevant variables: lamp channel mix. Lower is better.
2. **Weather-normalized heat intensity** — reuse `energy_baseline_frames` (already an EnPI); add an
   intraday variant: heat per heating-degree `Σheat / Σmax(t_heat_vip−Tout,0)·Δt`.
3. **Peak-energy share** — `elec_peak / (elec_peak+elec_offpeak)` under the tariff's ToU windows.
   Cost-efficiency indicator shown once a sourced ToU schedule is configured; rates are not needed.
4. **Simultaneity waste index** — fraction of *heat energy* delivered while `VentLee > θ_vent`
   (heating against open vents) + fraction of *lighting energy* while `Iglob > θ_solar`
   (supplementing abundant daylight). Report as an observed % of energy in counterproductive states
   — **not** as recoverable savings.

### 5.2 Efficiency events (reuse `analytics.py::_persistent_events`)

Persistent (≥3 steps), evidence-backed, non-causal. Feed into the existing `anomalies` array /
Operator-Attention panel with `category:"efficiency"`.

| Code | Condition (5-min) | Message (non-causal) |
|---|---|---|
| `heating_against_ventilation` | `pipe_excess > θp` AND `VentLee > θv` | "Heat was delivered while leeward vents were open." |
| `lighting_under_daylight` | `Tot_PAR_Lamps > 0` AND `Iglob > θi` | "Supplemental lighting ran while outside radiation was high." |
| `screen_open_heat_loss` | night AND `Tout < θt` AND `EnScr < θs` AND `pipe_excess > 0` | "Energy screen was retracted during active night heating." |
| `peak_window_energy` | day-level: peak share above rolling p90 | "Electricity use was concentrated in tariff peak windows." (informational) |

Thresholds are demo-tunable constants; document defaults and expose no prescriptive action.

### 5.3 Tariff / ToU extension (needed for cost + peak share)

`TariffProfile` (main.py) currently has flat peak/off-peak rates. Add **ToU window schedule** so
5-min steps can be classified by site-local clock:
```jsonc
"tou_windows": [ {"label":"peak","days":"mon-fri","start":"07:00","end":"19:00"}, ... ]
```
Provide a named **Ontario ToU preset** (winter/summer) selectable in `SettingsView`. Cost per
interval = `elec_peak·peak_rate + elec_offpeak·offpeak_rate + heat·heat_rate + co2·co2_rate`;
aggregate to the intraday cost series. A sourced schedule enables peak share independently. Keep the
"cost hidden until all rates are fully configured & sourced"
guardrail. Validate: reconstructed peak share under the *dataset's original* windows should
approximate measured `ElecHigh/(ElecHigh+ElecLow)` (≈1.37 ratio) — log as a sanity check.

### 5.4 Frontend
- **Efficiency panel** in EnergyView: EnPI cards (lighting efficacy, weather-normalized heat,
  peak share) with actual vs expected + confidence, and an **efficiency-events list** reusing the
  anomaly item component. Wire the existing `ask()` "✦ Explain with Varianz" so the assistant can
  interpret an EnPI or event (evidence-grounded).
- Intraday **cost curve** shown only when a tariff profile is configured.

### 5.5 Tests
- Each EnPI returns finite value + unit + evidence IDs; degrades to `status:"insufficient_data"`
  when history < threshold.
- Efficiency events fire on hand-constructed windows (e.g. pipe hot + vent open) and stay silent
  otherwise; wording contains no "save/savings/reduce cost by" (assert via a copy lint).
- Cost is `None` until all rates are configured; ToU classification and peak share require only a sourced schedule and match window boundaries.

---

## 6. Deliverables checklist

- [x] `metrics.py`: register `Tot_PAR_Lamps`, `co2_dos` (Task 3.1).
- [x] `supabase/migrations` + `scripts/db_admin.py`: seed new metrics; re-seed (Task 3.2).
- [x] `energy.py`: `intraday_energy_frame`, `efficiency_indicators`, efficiency-event detectors.
- [x] Expose intraday + efficiency through the dedicated `energy-resources` orchestration, keeping
      the Overview payload bounded; reconstruction outputs carry their own model version.
- [x] `main.py`: `grain` param + `intraday`/`efficiency` in `energy-resources`; extend
      `TariffProfile` with ToU windows + Ontario preset.
- [x] `apps/web/app/views/EnergyView.tsx` (+ `lib/types.ts`): intraday chart w/ grain toggle,
      efficiency panel, cost curve; `SettingsView.tsx`: ToU preset.
- [x] `tests/test_core.py`: conservation, future-safe, fidelity R², grain, EnPI, events, cost.
- [x] Update `README.md` + `docs/05-analytics-ml.md` with the disaggregation method & versions.

## 7. Out of scope
Forecasting/optimization; HVAC control; independent (non-meter-derived) energy metering;
savings/ROI claims; sub-metering per equipment beyond the heat/elec/CO₂ split.

## 8. Acceptance criteria
1. Intraday series sum to measured daily totals for completed days (rtol 1e-6) and never use
   future data; current day is `provisional`.
2. Fidelity R² ≥ 0.90 / 0.97 / 0.99 (heat / elec / co2).
3. EnPIs + ≥3 efficiency-event types render in the Energy view with evidence IDs and versions.
4. All new copy passes the no-causal / no-savings language check.
5. Peak share appears with a sourced Ontario ToU schedule; cost additionally requires all rates.
