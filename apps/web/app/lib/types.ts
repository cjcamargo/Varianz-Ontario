export type View = "overview" | "energy" | "climate" | "anomalies" | "assistant" | "settings";
export type WindowKey = "1h" | "6h" | "24h" | "7d" | "all";
export type Point = Record<string, string | number | null> & { time: string };

export type Anomaly = {
  id: string; code: string; category: string; severity: string; message: string;
  started_at: string; duration_minutes: number; observed: number | null;
  expected: number | null; residual: number | null; confidence: string;
  contributors: string[]; evidence_ids: string[]; active: boolean;
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
    currency:string|null; area_basis_m2:number; comparison_as_of:string|null;
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
