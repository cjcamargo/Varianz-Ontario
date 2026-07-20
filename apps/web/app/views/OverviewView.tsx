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
    current_cost_to_cursor_cad:null,currency:null,area_basis_m2:data.site.growing_area_m2,
    comparison_as_of:null,tariff_effective_from:null,confidence:null,baseline_model:null,
    cost_scope:"",comparison_scope:"",disclaimer:"Estimated association-based variance; not verified or guaranteed savings.",evidence_ids:[],
  };
  const favorable=impact.energy_performance_pct!=null&&impact.energy_performance_pct>5;
  const unfavorable=impact.energy_performance_pct!=null&&impact.energy_performance_pct<-5;
  const impactTone=unfavorable?"amber":impact.energy_performance_pct==null?"neutral":"green";
  const moneyReady=impact.status==="ready";
  const varianceLabel=impact.estimated_heat_cost_variance_cad!=null&&impact.estimated_heat_cost_variance_cad<0
    ?"Estimated excess heat cost":"Estimated avoided heat cost";
  const direction=favorable?"below":unfavorable?"above":"from";
  const monetaryPhrase=moneyReady&&impact.estimated_heat_cost_variance_cad!=null
    ?`, equivalent to ${currency(Math.abs(impact.estimated_heat_cost_variance_cad),impact.currency)} across the growing area`:"";
  const executiveText=impact.energy_performance_pct==null
    ?"The weather-normalized baseline is not ready for a defensible performance comparison."
    :`${impact.performance_label}: heat intensity is ${fmt(Math.abs(impact.energy_performance_pct))}% ${direction} the weather-normalized expectation${monetaryPhrase}.`;

  return <>
    <section className={`stakeholder-impact ${impactTone}`}>
      <div><span>STAKEHOLDER IMPACT</span><h2>{executiveText}</h2><p>{impact.disclaimer}</p></div>
      <button onClick={()=>setView("energy")}>Review evidence →</button>
    </section>
    <section className="hero-grid stakeholder-kpis">
      <Card label="Energy performance" value={impact.energy_performance_pct==null?null:Math.abs(impact.energy_performance_pct)} unit="% vs baseline" meta={impact.energy_performance_pct==null?"Baseline building — minimum 45 days":`${impact.performance_label} · ${impact.confidence} confidence`} tone={impactTone} badge={favorable?"FAVORABLE":unfavorable?"ATTENTION":"ON TRACK"}/>
      <Card label={varianceLabel} value={impact.estimated_heat_cost_variance_cad==null?null:Math.abs(impact.estimated_heat_cost_variance_cad)} unit={impact.currency||"CAD"} meta={moneyReady?`Weather-normalized heat variance · ${fmt(impact.area_basis_m2)} m² growing area`:"Configure complete Ontario tariffs to enable monetary impact"} tone={impact.estimated_heat_cost_variance_cad!=null&&impact.estimated_heat_cost_variance_cad<0?"amber":"green"} digits={2} badge="ESTIMATED"/>
      <Card label="Operating cost to cursor" value={impact.current_cost_to_cursor_cad} unit={impact.currency||"CAD"} meta={moneyReady?`Heat + electricity + CO₂ · ${fmt(impact.area_basis_m2)} m² growing area`:"Configure complete Ontario tariffs to enable current cost"} tone="neutral" digits={2} badge="TO CURSOR"/>
      <Card label="Total energy" value={k.daily_total_energy_mj_m2} unit="MJ/m²·day" meta={`${fmt(k.daily_heat_mj_m2)} heat · ${fmt(k.daily_electricity_kwh_m2)} kWh electricity`}/>
      <Card label="Climate compliance" value={k.climate_compliance_24h_pct} unit="% / 24h" meta={`${fmt(k.climate_compliance_1h_pct)}% last hour · ${fmt(k.anomaly_minutes,0)} anomaly min`} tone={Number(k.climate_compliance_24h_pct)<90?"amber":"green"}/>
      <Card label="Drain ratio" value={k.drain_ratio_pct} unit="%" meta={`${fmt(k.daily_irrigation_l_m2)} L/m² irrigation · ${fmt(k.daily_drain_l_m2)} L/m² drain`} tone={Number(k.drain_ratio_pct)>80||Number(k.drain_ratio_pct)<10?"amber":"green"}/>
    </section>
    <section className="overview-grid"><article className="panel span-2"><div className="panel-head"><div><span>OPERATIONAL CLIMATE</span><h2>Inside temperature vs targets</h2></div><button onClick={()=>setView("climate")}>Open climate →</button></div><LineChart points={data.climate_series} series={[{key:"Tair",name:"Indoor °C",color:"#63e6a5"},{key:"Tout",name:"Outdoor °C",color:"#70a4ff"},{key:"t_heat_vip",name:"Heat target °C",color:"#f0b45a",dashed:true},{key:"t_ventlee_vip",name:"Vent target °C",color:"#d178ff",dashed:true}]} bands={[18,26]}/></article>
      <article className="panel attention"><div className="panel-head"><div><span>OPERATOR ATTENTION</span><h2>{top?top.message:"Operation within configured review bands"}</h2></div></div>{top?<><div className={`severity ${top.severity}`}>{top.severity} · {top.duration_minutes} min</div><dl><div><dt>Observed</dt><dd>{fmt(top.observed)}</dd></div><div><dt>Expected</dt><dd>{fmt(top.expected)}</dd></div><div><dt>Confidence</dt><dd>{top.confidence}</dd></div></dl><button className="primary" onClick={()=>ask(`Explain anomaly ${top.code}, its operational impact, and the safest next checks.`,top.id)}>✦ Explain with Varianz</button></>:<p>No active anomaly requires intervention at this cursor.</p>}</article>
    </section>
    <section className="model-strip"><div><span>BASELINE STATUS</span><b>{baseline.status==="ready"?(baseline.candidate_promoted?"Elastic Net promoted":"Naive baseline retained"):"Collecting training history"}</b></div><div><span>LOCKED TEST</span><b>{baseline.promotion_gate?`${fmt(baseline.promotion_gate.locked_test_improvement_pct)}% vs naive`:"Not available"}</b></div><div><span>UNCERTAINTY</span><b>{baseline.p10_mj_m2!=null?`${fmt(baseline.p10_mj_m2)}–${fmt(baseline.p90_mj_m2)} MJ/m²`:"Not available"}</b></div><div><span>EVIDENCE</span><b>{data.evidence_ids.length} linked records</b></div></section>
  </>;
}
