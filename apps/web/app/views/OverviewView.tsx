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
    remaining_target_potential_mj_m2:null,remaining_target_potential_cad:null,target_opportunity_cad:null,
    target_achieved:null,target_improvement_pct:5,target_version:"energy-target-demo-1.0.0",
    target_status:"provisional_demo_target",target_source:"Varianz demo management objective",
    actual_to_cursor_mj_m2:null,baseline_to_cursor_mj_m2:null,target_to_cursor_mj_m2:null,
    reference_day_fraction:null,reference_daily_heat_mj_m2:null,intraday_baseline_method:null,
    cumulative_actual_mj_m2:null,cumulative_baseline_mj_m2:null,cumulative_target_mj_m2:null,
    performance_series:[],evaluation_start:null,
    current_cost_to_cursor_cad:null,currency:null,area_basis_m2:data.site.growing_area_m2,
    comparison_as_of:null,tariff_effective_from:null,confidence:null,baseline_model:null,
    cost_scope:"",comparison_scope:"",disclaimer:"Estimated association-based variance.",tariff_application:"",evidence_ids:[],
  };
  const favorable=impact.energy_performance_pct!=null&&impact.energy_performance_pct>5;
  const unfavorable=impact.energy_performance_pct!=null&&impact.energy_performance_pct<-5;
  const impactTone=unfavorable?"amber":impact.energy_performance_pct==null?"neutral":"green";
  const moneyReady=impact.status==="ready";
  const cumulativeValue=impact.cumulative_estimated_heat_cost_variance_cad;
  const cumulativeLabel=cumulativeValue!=null&&cumulativeValue<0
    ?"Cumulative excess heat cost":"Cumulative avoided heat cost";
  const direction=favorable?"below":unfavorable?"above":"from";
  const monetaryPhrase=moneyReady&&cumulativeValue!=null
    ?`; cumulative heat value is ${currency(Math.abs(cumulativeValue),impact.currency)}`:"";
  const executiveText=impact.energy_performance_pct==null
    ?"The weather-normalized baseline is not ready for a defensible performance comparison."
    :`${impact.performance_label}: heat to this cursor is ${fmt(Math.abs(impact.energy_performance_pct))}% ${direction} the weather-normalized baseline${monetaryPhrase}.`;

  return <>
    <section className={`stakeholder-impact ${impactTone}`}>
      <div><span>ENERGY IMPACT</span><h2>{executiveText}</h2><p>{impact.disclaimer}</p></div>
      <button onClick={()=>setView("energy")}>Review evidence →</button>
    </section>
    <section className="hero-grid stakeholder-kpis">
      <Card label="Current energy impact" value={impact.energy_performance_pct==null?null:Math.abs(impact.energy_performance_pct)} unit="% vs EnB" meta={impact.energy_performance_pct==null?"Baseline building — minimum 45 days":`${impact.performance_label} · cumulative ${fmt(impact.cumulative_energy_performance_pct==null?null:Math.abs(impact.cumulative_energy_performance_pct))}%`} tone={impactTone} badge={favorable?"FAVORABLE":unfavorable?"ATTENTION":"ON TRACK"}/>
      <Card label={cumulativeLabel} value={cumulativeValue==null?null:Math.abs(cumulativeValue)} unit={impact.currency||"CAD"} meta={moneyReady?`Since ${impact.evaluation_start?new Date(impact.evaluation_start).toLocaleDateString("en-CA"):"EnB activation"} · heat only`:"Configure complete Ontario tariffs to enable monetary impact"} tone={cumulativeValue!=null&&cumulativeValue<0?"amber":"green"} digits={2} badge="CUMULATIVE"/>
      <Card label="Remaining target potential" value={impact.remaining_target_potential_cad} unit={impact.currency||"CAD"} meta={moneyReady?`${fmt(impact.remaining_target_potential_mj_m2)} MJ/m² to provisional ${fmt(impact.target_improvement_pct)}% target`:"Configure complete Ontario tariffs; energy potential remains available"} tone={impact.target_achieved?"green":"amber"} digits={2} badge={impact.target_achieved?"TARGET MET":"ESTIMATED"}/>
      <Card label="Operating cost today" value={impact.current_cost_to_cursor_cad} unit={impact.currency||"CAD"} meta={moneyReady?"Heat + electricity + CO₂ · start of day to cursor":"Configure electricity, heat and CO₂ tariffs to enable current cost"} tone="neutral" digits={2} badge="TO CURSOR"/>
      <Card label="Climate compliance" value={k.climate_compliance_24h_pct} unit="% / 24h" meta={`${fmt(k.climate_compliance_1h_pct)}% last hour · ${fmt(k.anomaly_minutes,0)} anomaly min`} tone={Number(k.climate_compliance_24h_pct)<90?"amber":"green"}/>
      <Card label="Drain ratio" value={k.drain_ratio_pct} unit="%" meta={`${fmt(k.daily_irrigation_l_m2)} L/m² irrigation · ${fmt(k.daily_drain_l_m2)} L/m² drain`} tone={Number(k.drain_ratio_pct)>80||Number(k.drain_ratio_pct)<10?"amber":"green"}/>
    </section>
    <section className="overview-grid"><article className="panel span-2"><div className="panel-head"><div><span>ISO-ALIGNED ENERGY PERFORMANCE</span><h2>Cumulative actual vs weather-normalized EnB and management target</h2></div><button onClick={()=>setView("energy")}>Open energy →</button></div><LineChart height={300} points={impact.performance_series||[]} series={[{key:"actual_cumulative_mj_m2",name:"Actual cumulative MJ/m²",color:"#f0b45a"},{key:"baseline_cumulative_mj_m2",name:"Energy baseline (EnB)",color:"#70a4ff",dashed:true},{key:"target_cumulative_mj_m2",name:"Provisional target line",color:"#63e6a5",dashed:true}]}/></article>
      <article className="panel baseline-card"><span>PROVISIONAL MANAGEMENT TARGET</span><h2>{fmt(impact.target_improvement_pct)}% below the weather-normalized EnB</h2><p>{impact.target_achieved?"Current cumulative performance meets the target line.":`${fmt(impact.remaining_target_potential_mj_m2)} MJ/m² remains between actual performance and the target line.`}</p><p>Live edge: previous seven completed days; no future observations.</p><p>Version: <b>{impact.target_version}</b></p><p>ISO 50001/50006 aligned structure; organization approval is required for a pilot target.</p></article>
    </section>
    <section className="overview-grid"><article className="panel span-2"><div className="panel-head"><div><span>OPERATIONAL CLIMATE</span><h2>Inside temperature vs targets</h2></div><button onClick={()=>setView("climate")}>Open climate →</button></div><LineChart points={data.climate_series} series={[{key:"Tair",name:"Indoor °C",color:"#63e6a5"},{key:"Tout",name:"Outdoor °C",color:"#70a4ff"},{key:"t_heat_vip",name:"Heat target °C",color:"#f0b45a",dashed:true},{key:"t_ventlee_vip",name:"Vent target °C",color:"#d178ff",dashed:true}]} bands={[18,26]}/></article>
      <article className="panel attention"><div className="panel-head"><div><span>OPERATOR ATTENTION</span><h2>{top?top.message:"Operation within configured review bands"}</h2></div></div>{top?<><div className={`severity ${top.severity}`}>{top.severity} · {top.duration_minutes} min</div><dl><div><dt>Observed</dt><dd>{fmt(top.observed)}</dd></div><div><dt>Expected</dt><dd>{fmt(top.expected)}</dd></div><div><dt>Confidence</dt><dd>{top.confidence}</dd></div></dl><button className="primary" onClick={()=>ask(`Explain anomaly ${top.code}, its operational impact, and the safest next checks.`,top.id)}>✦ Explain with Varianz</button></>:<p>No active anomaly requires intervention at this cursor.</p>}</article>
    </section>
    <section className="model-strip"><div><span>BASELINE STATUS</span><b>{baseline.status==="ready"?(baseline.candidate_promoted?"Elastic Net promoted":"Naive baseline retained"):"Collecting training history"}</b></div><div><span>LOCKED TEST</span><b>{baseline.promotion_gate?`${fmt(baseline.promotion_gate.locked_test_improvement_pct)}% vs naive`:"Not available"}</b></div><div><span>UNCERTAINTY</span><b>{baseline.p10_mj_m2!=null?`${fmt(baseline.p10_mj_m2)}–${fmt(baseline.p90_mj_m2)} MJ/m²`:"Not available"}</b></div><div><span>EVIDENCE</span><b>{data.evidence_ids.length} linked records</b></div></section>
  </>;
}
