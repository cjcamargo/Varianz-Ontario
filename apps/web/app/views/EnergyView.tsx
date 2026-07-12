import { Snapshot } from "../lib/types";
import { fmt } from "../lib/format";
import { Card, LineChart } from "../components/primitives";

type EnergyProps = {
  data:Snapshot; k:Snapshot["kpis"]; baseline:Record<string,any>;
  ask:(custom?:string,anomalyId?:string)=>void;
};

export function EnergyView({data,k,baseline,ask}:EnergyProps){
  return <><section className="hero-grid compact"><Card label="Heat" value={k.daily_heat_mj_m2} unit="MJ/m²·day" meta="Observed daily resource total"/><Card label="Electricity" value={k.daily_electricity_kwh_m2} unit="kWh/m²·day" meta={`${fmt(k.peak_electricity_share_pct)}% peak share`}/><Card label="CO₂" value={k.daily_co2_kg_m2} unit="kg/m²·day" meta="Observed resource intensity"/><Card label="Water" value={k.daily_irrigation_l_m2} unit="L/m²·day" meta={`${fmt(k.drain_ratio_pct)}% drain ratio`}/></section><section className="two-col"><article className="panel"><div className="panel-head"><div><span>ENERGY INTENSITY</span><h2>Heat and electricity — last 30 days</h2></div></div><LineChart height={390} points={data.resource_series} series={[{key:"Heat_cons",name:"Heat MJ/m²",color:"#f0b45a"},{key:"ElecHigh",name:"Peak kWh/m²",color:"#63e6a5",axis:1},{key:"ElecLow",name:"Off-peak kWh/m²",color:"#70a4ff",axis:1}]}/></article><article className="panel baseline-card"><span>WEATHER-NORMALIZED BASELINE</span><h2>{baseline.status==="ready"?`${fmt(baseline.actual_mj_m2)} actual vs ${fmt(baseline.expected_mj_m2)} expected`:"Insufficient history at cursor"}</h2><div className="baseline-bar"><i style={{width:`${Math.min(100,Math.max(0,(baseline.actual_mj_m2||0)/Math.max(baseline.p90_mj_m2||6,1)*100))}%`}}/></div><p>Selected: <b>{baseline.selected_model||"pending"}</b></p><p>Promotion: <b>{baseline.candidate_promoted?"passed":"candidate not promoted"}</b></p><p>Confidence: <b>{baseline.confidence||"not available"}</b></p><button className="primary" onClick={()=>ask("Explain today's energy intensity, the baseline result, uncertainty, and likely operational drivers.")}>✦ Explain energy status</button></article></section><article className="panel"><div className="panel-head"><div><span>WATER BALANCE</span><h2>Irrigation and drain</h2></div></div><LineChart height={310} points={data.resource_series} series={[{key:"Irr",name:"Irrigation L/m²",color:"#70a4ff"},{key:"Drain",name:"Drain L/m²",color:"#63e6a5"}]}/></article></>
}
