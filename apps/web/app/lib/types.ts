export type View = "overview" | "energy" | "climate" | "anomalies" | "assistant" | "settings";
export type WindowKey = "1h" | "6h" | "24h" | "7d" | "all";
export type Point = Record<string, string | number | null> & { time: string };

export type Anomaly = {
  id: string; code: string; category: string; severity: string; message: string;
  started_at: string; duration_minutes: number; observed: number | null;
  expected: number | null; residual: number | null; confidence: string;
  contributors: string[]; evidence_ids: string[]; active: boolean;
  cost_exposure_cad_per_1000m2?:number|null; cost_exposure_scope?:string;
};

export type Snapshot = {
  session_id: string; revision: number; cursor: string; playing: boolean; speed: number;
  replay:{minimum:string;maximum:string;observations_seen:number;observations_total:number;progress_pct:number};
  window: WindowKey; site: {id:string; name:string; area_m2:number; growing_area_m2:number};
  quality: {state:string;backend:string;future_safe:boolean;data_status:string;validation_scope:string;as_of:string;coverage_start:string;coverage_end:string;data_version:string;definitions_version:string};
  data_version:string; definitions_version:string; model_version:string; evidence_ids:string[];
  kpis: Record<string, number | null>; latest: Record<string, number | null>;
  baseline: Record<string, any>; anomalies: Anomaly[]; climate_series: Point[];
  resource_series: Point[]; tariff:{configured:boolean;currency:string|null;cost_scope?:string};
  business_impact:{
    status:"ready"|"tariff_required"|"baseline_required";
    energy_performance_pct:number|null; performance_state:string; performance_label:string;
    estimated_heat_cost_variance_cad:number|null; current_cost_to_cursor_cad:number|null;
    cumulative_energy_performance_pct:number|null;
    cumulative_estimated_heat_cost_variance_cad:number|null;
    cumulative_cost_state:"saving"|"overconsumption"|"balanced"|"unavailable";
    cumulative_avoided_mj_m2:number|null; cumulative_excess_mj_m2:number|null;
    cumulative_avoided_heat_cost_cad:number|null; cumulative_excess_heat_cost_cad:number|null;
    cumulative_net_heat_cost_cad_per_1000m2:number|null;
    cumulative_avoided_heat_cost_cad_per_1000m2:number|null;
    cumulative_excess_heat_cost_cad_per_1000m2:number|null;
    heat_cost_30d_run_rate_cad_per_1000m2:number|null; evaluation_elapsed_days:number|null;
    remaining_target_potential_mj_m2:number|null; remaining_target_potential_cad:number|null;
    remaining_target_potential_cad_per_1000m2:number|null;
    remaining_target_potential_30d_run_rate_cad_per_1000m2:number|null;
    target_opportunity_cad:number|null; target_opportunity_cad_per_1000m2:number|null;
    target_achieved:boolean|null;
    target_improvement_pct:number; target_version:string; target_status:string; target_source:string;
    actual_to_cursor_mj_m2:number|null; baseline_to_cursor_mj_m2:number|null;
    target_to_cursor_mj_m2:number|null; cumulative_actual_mj_m2:number|null;
    reference_day_fraction:number|null; reference_daily_heat_mj_m2:number|null;
    intraday_baseline_method:string|null;
    cumulative_baseline_mj_m2:number|null; cumulative_target_mj_m2:number|null;
    performance_series:Point[]; evaluation_start:string|null;
    completed_evaluation_days:number; current_day_provisional:boolean;
    calculation_grain_minutes:number; calculation_intervals:number; display_points:number;
    current_cost_to_cursor_cad_per_1000m2:number|null;
    climate_cost_exposure_24h_cad_per_1000m2:number|null;
    climate_excursion_intervals_24h:number; climate_eligible_intervals_24h:number;
    anomaly_cost_exposure_7d_cad_per_1000m2:number|null;
    anomaly_exposure_intervals_7d:number; monetized_anomaly_count:number;
    exposure_definition:string;
    currency:string|null; area_basis_m2:number; source_growing_area_m2:number;
    financial_reference_area_m2:number;
    comparison_as_of:string|null;
    heat_tariff_cad_per_mj:number|null; tariff_source:string|null; monetary_status:string;
    tariff_effective_from:string|null; confidence:string|null; baseline_model:string|null;
    cost_scope:string; comparison_scope:string; disclaimer:string; tariff_application:string; evidence_ids:string[];
  };
  metric_definitions: Record<string,{label:string;unit:string;source:string}>;
  intraday?:{
    grain:"5min"|"1h"; series:Point[];
    reconstruction:{method:string;calibration_days:number;model_version:string;fit_r2:Record<string,number|null>;evidence_ids:string[];serving_source?:string};
    summary:Record<string,any>;serving_source?:string;
    cost_configured:boolean;tou_configured:boolean;currency:string|null;
  };
  efficiency?:Record<string,any>;
};

export type AssistantResult = {
  recommendation:string; answer:string; claims:{text:string;evidence_ids:string[]}[]; confidence:string;
  limitations:string[]; suggested_actions:string[]; model:string; evidence_version:string; language:"en"|"es";
};

export type ChatMessage = {
  id:string; role:"operator"|"assistant"; text:string; result?:AssistantResult;
};

export type SeriesSpec = { key:string; name:string; color:string; axis?:number; dashed?:boolean };
