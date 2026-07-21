import { Anomaly, Snapshot, View } from "../lib/types";
import { fmt } from "../lib/format";
import { Card, LineChart } from "../components/primitives";

type OverviewProps = {
  data:Snapshot; k:Snapshot["kpis"]; baseline:Record<string,any>; top:Anomaly|undefined;
  setView:(v:View)=>void; ask:(custom?:string,anomalyId?:string)=>void;
};

function currency(value:number,currency:string|null){
  return value.toLocaleString("en-CA",{style:"currency",currency:currency||"CAD"});
}

export function OverviewView({data,k,baseline,top,setView,ask}:OverviewProps){
  const impact=data.business_impact||{
    status:"baseline_required",energy_performance_pct:null,performance_state:"not_comparable",
    performance_label:"Baseline not ready",estimated_heat_cost_variance_cad:null,
    cumulative_energy_performance_pct:null,cumulative_estimated_heat_cost_variance_cad:null,
    cumulative_cost_state:"unavailable",
    cumulative_avoided_mj_m2:null,cumulative_excess_mj_m2:null,
    cumulative_avoided_heat_cost_cad:null,cumulative_excess_heat_cost_cad:null,
    cumulative_net_heat_cost_cad_per_1000m2:null,cumulative_avoided_heat_cost_cad_per_1000m2:null,
    cumulative_excess_heat_cost_cad_per_1000m2:null,
    heat_cost_30d_run_rate_cad_per_1000m2:null,evaluation_elapsed_days:null,
    remaining_target_potential_mj_m2:null,remaining_target_potential_cad:null,
    remaining_target_potential_cad_per_1000m2:null,target_opportunity_cad:null,
    remaining_target_potential_30d_run_rate_cad_per_1000m2:null,
    target_opportunity_cad_per_1000m2:null,
    target_achieved:null,target_improvement_pct:5,target_version:"energy-target-demo-1.0.0",
    target_status:"provisional_demo_target",target_source:"Varianz demo management objective",
    actual_to_cursor_mj_m2:null,baseline_to_cursor_mj_m2:null,target_to_cursor_mj_m2:null,
    reference_day_fraction:null,reference_daily_heat_mj_m2:null,intraday_baseline_method:null,
    cumulative_actual_mj_m2:null,cumulative_baseline_mj_m2:null,cumulative_target_mj_m2:null,
    performance_series:[],evaluation_start:null,completed_evaluation_days:0,current_day_provisional:false,
    calculation_grain_minutes:5,calculation_intervals:0,display_points:0,
    current_cost_to_cursor_cad:null,current_cost_to_cursor_cad_per_1000m2:null,
    climate_cost_exposure_24h_cad_per_1000m2:null,climate_excursion_intervals_24h:0,
    climate_eligible_intervals_24h:0,anomaly_cost_exposure_7d_cad_per_1000m2:null,
    anomaly_exposure_intervals_7d:0,monetized_anomaly_count:0,
    exposure_definition:"Coincident operating cost; not verified avoidable savings.",
    currency:null,area_basis_m2:1000,source_growing_area_m2:data.site.growing_area_m2,
    financial_reference_area_m2:1000,
    heat_tariff_cad_per_mj:null,tariff_source:null,monetary_status:"tariff_required",
    comparison_as_of:null,tariff_effective_from:null,confidence:null,baseline_model:null,
    cost_scope:"",comparison_scope:"",disclaimer:"Estimated association-based variance.",tariff_application:"",evidence_ids:[],
  };
  const favorable=impact.energy_performance_pct!=null&&impact.energy_performance_pct>5;
  const unfavorable=impact.energy_performance_pct!=null&&impact.energy_performance_pct<-5;
  const impactTone=unfavorable?"amber":impact.energy_performance_pct==null?"neutral":"green";
  const moneyReady=impact.monetary_status==="configured_scenario";
  const avoidedValue=impact.cumulative_avoided_heat_cost_cad_per_1000m2;
  const excessValue=impact.cumulative_excess_heat_cost_cad_per_1000m2;
  const netValue=impact.cumulative_net_heat_cost_cad_per_1000m2;
  const netSaving=impact.cumulative_cost_state==="saving";
  const netExcess=impact.cumulative_cost_state==="overconsumption";
  const netTone=netSaving?"green":netExcess?"amber":"neutral";
  const netBadge=netSaving?"NET SAVING":netExcess?"OVERCONSUMPTION":"BALANCED";
  const direction=favorable?"below":unfavorable?"above":"from";
  const monetaryPhrase=moneyReady&&netValue!=null
    ?`; the five-minute cumulative balance is ${currency(Math.abs(netValue),impact.currency)} ${netSaving?"net saving":netExcess?"net overconsumption":"from break-even"} per 1,000 m²`:"";
  const executiveText=impact.energy_performance_pct==null
    ?"The weather-normalized baseline is not ready for a defensible performance comparison."
    :`${impact.performance_label}: heat to this cursor is ${fmt(Math.abs(impact.energy_performance_pct))}% ${direction} the weather-normalized baseline${monetaryPhrase}.`;

  return <>
    <section className={`stakeholder-impact ${impactTone}`}>
      <div><span>ENERGY IMPACT</span><h2>{executiveText}</h2><p>{impact.disclaimer}</p></div>
      <button onClick={()=>setView("energy")}>Review evidence →</button>
    </section>
    <section className="hero-grid stakeholder-kpis">
      <Card label="Current heat variance" value={impact.energy_performance_pct==null?null:Math.abs(impact.energy_performance_pct)} unit="% vs EnB" meta={impact.energy_performance_pct==null?"Baseline building — minimum 45 days":`${fmt(impact.actual_to_cursor_mj_m2,3)} actual vs ${fmt(impact.baseline_to_cursor_mj_m2,3)} EnB MJ/m²`} tone={impactTone} badge={favorable?"LOWER USE":unfavorable?"OVERCONSUMPTION":"ON TRACK"}/>
      <Card label="Cumulative heat cost balance" value={netValue==null?null:Math.abs(netValue)} unit={`${impact.currency||"CAD"} / 1,000 m²`} meta={moneyReady?`${currency(avoidedValue||0,impact.currency)} saving − ${currency(excessValue||0,impact.currency)} excess · ${impact.calculation_intervals.toLocaleString()} five-minute intervals`:"Configure complete Ontario tariffs"} tone={netTone} digits={2} badge={netBadge}/>
      <Card label="30-day heat cost run rate" value={impact.heat_cost_30d_run_rate_cad_per_1000m2==null?null:Math.abs(impact.heat_cost_30d_run_rate_cad_per_1000m2)} unit={`${impact.currency||"CAD"} / 1,000 m²`} meta={impact.evaluation_elapsed_days?`Extrapolated from ${fmt(impact.evaluation_elapsed_days,1)} evaluated days · not a forecast`:"Waiting for an evaluable EnB period"} tone={netTone} digits={2} badge={netSaving?"RUN-RATE SAVING":netExcess?"RUN-RATE EXCESS":"RUN RATE"}/>
      <Card label="30-day target cost gap" value={impact.remaining_target_potential_30d_run_rate_cad_per_1000m2} unit={`${impact.currency||"CAD"} / 1,000 m²`} meta={moneyReady&&impact.evaluation_elapsed_days?`${fmt(impact.remaining_target_potential_mj_m2,3)} MJ/m² accumulated gap · extrapolated from ${fmt(impact.evaluation_elapsed_days,1)} evaluated days`:"Configure tariffs and wait for an evaluable EnB period"} tone={impact.target_achieved?"green":"amber"} digits={2} badge={impact.target_achieved?"TARGET MET":"RUN-RATE GAP"}/>
      <Card label="Operating cost today" value={impact.current_cost_to_cursor_cad_per_1000m2} unit={`${impact.currency||"CAD"} / 1,000 m²`} meta={moneyReady?"Heat + electricity + CO₂ · start of day to cursor":"Configure electricity, heat and CO₂ tariffs to enable current cost"} tone="neutral" digits={2} badge="TO CURSOR"/>
      <Card label="Climate cost exposure" value={impact.climate_cost_exposure_24h_cad_per_1000m2} unit={`${impact.currency||"CAD"} / 1,000 m²`} meta={`${impact.climate_excursion_intervals_24h} non-compliant five-minute intervals · last 24h`} tone={impact.climate_excursion_intervals_24h>0?"amber":"green"} digits={2} badge="EXPOSURE · 24H"/>
      <Card label="Anomaly-linked cost exposure" value={impact.anomaly_cost_exposure_7d_cad_per_1000m2} unit={`${impact.currency||"CAD"} / 1,000 m²`} meta={`${impact.monetized_anomaly_count} events · ${impact.anomaly_exposure_intervals_7d} unique five-minute intervals`} tone={impact.anomaly_exposure_intervals_7d>0?"amber":"green"} digits={2} badge="EXPOSURE · 7D"/>
      <Card label="Climate compliance" value={k.climate_compliance_24h_pct} unit="% / 24h" meta={`${fmt(k.climate_compliance_1h_pct)}% last hour · ${fmt(k.anomaly_minutes,0)} anomaly min`} tone={Number(k.climate_compliance_24h_pct)<90?"amber":"green"}/>
      <Card label="Drain ratio" value={k.drain_ratio_pct} unit="%" meta={`${fmt(k.daily_irrigation_l_m2)} L/m² irrigation · ${fmt(k.daily_drain_l_m2)} L/m² drain`} tone={Number(k.drain_ratio_pct)>80||Number(k.drain_ratio_pct)<10?"amber":"green"}/>
    </section>
    <section className="overview-grid"><article className="panel span-2"><div className="panel-head"><div><span>FIVE-MINUTE COST LEDGER · 1,000 M²</span><h2>Cumulative net heat cost: saving above zero, overconsumption below zero</h2></div></div><LineChart height={280} points={impact.performance_series||[]} series={[{key:"net_cumulative_cad_per_1000m2",name:"Cumulative net CAD / 1,000 m²",color:"#d178ff"},{key:"break_even_cad_per_1000m2",name:"Break-even",color:"#8da198",dashed:true}]}/></article>
      <article className="panel baseline-card"><span>CUMULATIVE INTERPRETATION · 1,000 M²</span><h2>{netSaving?"Net saving":netExcess?"Net overconsumption":"At break-even"}</h2><p>{currency(avoidedValue||0,impact.currency)} gross saving − {currency(excessValue||0,impact.currency)} gross excess = {currency(Math.abs(netValue||0),impact.currency)} {netSaving?"favorable":netExcess?"unfavorable":"balanced"} balance.</p><p>Calculated over <b>{impact.calculation_intervals.toLocaleString()} intervals of {impact.calculation_grain_minutes} minutes</b>; chart reduced to {impact.display_points.toLocaleString()} display points.</p><p>Heat uses the meter-conserving intraday reconstruction; completed daily totals remain conserved.</p><p>Climate and anomaly values are coincident operating-cost exposure, not verified avoidable savings.</p></article>
    </section>
    <section className="overview-grid"><article className="panel span-2"><div className="panel-head"><div><span>ISO-ALIGNED ENERGY PERFORMANCE</span><h2>Cumulative actual vs weather-normalized EnB and management target</h2></div><button onClick={()=>setView("energy")}>Open energy →</button></div><LineChart height={300} points={impact.performance_series||[]} series={[{key:"actual_cumulative_mj_m2",name:"Actual cumulative MJ/m²",color:"#f0b45a"},{key:"baseline_cumulative_mj_m2",name:"Energy baseline (EnB)",color:"#70a4ff",dashed:true},{key:"target_cumulative_mj_m2",name:"Provisional target line",color:"#63e6a5",dashed:true}]}/></article>
      <article className="panel baseline-card"><span>PROVISIONAL MANAGEMENT TARGET</span><h2>{fmt(impact.target_improvement_pct)}% below the weather-normalized EnB</h2><p>{impact.target_achieved?"Current cumulative performance meets the target line.":`${fmt(impact.remaining_target_potential_mj_m2)} MJ/m² remains between actual performance and the target line.`}</p><p>Evaluation coverage: <b>{impact.completed_evaluation_days} completed EnB days + live provisional edge</b>.</p><p>Live edge: previous seven completed days; no future observations.</p><p>Money basis: {fmt(impact.financial_reference_area_m2)} m² × {fmt(impact.heat_tariff_cad_per_mj,4)} CAD/MJ.</p><p>Tariff evidence: <b>{impact.tariff_source||"Not configured"}</b></p><p>Version: <b>{impact.target_version}</b></p><p>ISO 50001/50006 aligned structure; organization approval is required for a pilot target.</p></article>
    </section>
    <section className="overview-grid"><article className="panel span-2"><div className="panel-head"><div><span>OPERATIONAL CLIMATE</span><h2>Inside temperature vs targets</h2></div><button onClick={()=>setView("climate")}>Open climate →</button></div><LineChart points={data.climate_series} series={[{key:"Tair",name:"Indoor °C",color:"#63e6a5"},{key:"Tout",name:"Outdoor °C",color:"#70a4ff"},{key:"t_heat_vip",name:"Heat target °C",color:"#f0b45a",dashed:true},{key:"t_ventlee_vip",name:"Vent target °C",color:"#d178ff",dashed:true}]} bands={[18,26]}/></article>
      <article className="panel attention"><div className="panel-head"><div><span>OPERATOR ATTENTION</span><h2>{top?top.message:"Operation within configured review bands"}</h2></div></div>{top?<><div className={`severity ${top.severity}`}>{top.severity} · {top.duration_minutes} min</div><dl><div><dt>Observed</dt><dd>{fmt(top.observed)}</dd></div><div><dt>Expected</dt><dd>{fmt(top.expected)}</dd></div><div><dt>Confidence</dt><dd>{top.confidence}</dd></div></dl><button className="primary" onClick={()=>ask(`Explain anomaly ${top.code}, its operational impact, and the safest next checks.`,top.id)}>✦ Explain with Varianz</button></>:<p>No active anomaly requires intervention at this cursor.</p>}</article>
    </section>
    <section className="model-strip"><div><span>BASELINE STATUS</span><b>{baseline.status==="ready"?(baseline.candidate_promoted?"Elastic Net promoted":"Naive baseline retained"):"Collecting training history"}</b></div><div><span>LOCKED TEST</span><b>{baseline.promotion_gate?`${fmt(baseline.promotion_gate.locked_test_improvement_pct)}% vs naive`:"Not available"}</b></div><div><span>UNCERTAINTY</span><b>{baseline.p10_mj_m2!=null?`${fmt(baseline.p10_mj_m2)}–${fmt(baseline.p90_mj_m2)} MJ/m²`:"Not available"}</b></div><div><span>EVIDENCE</span><b>{data.evidence_ids.length} linked records</b></div></section>
  </>;
}
