import { Snapshot } from "../lib/types";
import { fmt } from "../lib/format";
import { Card, LineChart } from "../components/primitives";
import { ChartDateRange } from "../components/ChartDateRange";

type EnergyProps = {
  data:Snapshot; k:Snapshot["kpis"]; baseline:Record<string,any>;
  ask:(custom?:string,anomalyId?:string)=>void;
  grain:"5min"|"1h"; setGrain:(grain:"5min"|"1h")=>void;
  openSettings:()=>void;
};

const indicatorNames:Record<string,string>={
  lighting_efficacy:"Lighting energy per delivered PAR",
  heat_degree_intensity:"Heating intensity per degree-hour",
  peak_share:"Electricity in configured peak periods",
  simultaneity_index:"Counterproductive operating states",
};

export function EnergyView({data,k,baseline,ask,grain,setGrain,openSettings}:EnergyProps){
  const intraday=data.intraday;
  const efficiency=data.efficiency||{};
  const points=(intraday?.series||[]).map(point=>({
    ...point,
    heat_allocated:point.quality==="provisional"?null:point.heat_mj_m2,
    heat_provisional:point.quality==="provisional"?point.heat_mj_m2:null,
    elec_allocated:point.quality==="provisional"?null:point.elec_kwh_m2,
    elec_provisional:point.quality==="provisional"?point.elec_kwh_m2:null,
    co2_allocated:point.quality==="provisional"?null:point.co2_kg_m2,
    co2_provisional:point.quality==="provisional"?point.co2_kg_m2:null,
    cost_visible:intraday?.cost_configured?point.cost_cad_m2:null,
  }));
  const efficiencyEvents=(data.anomalies||[]).filter(item=>item.category==="efficiency");
  return <>
    <section className="hero-grid compact">
      <Card label="Heat" value={k.daily_heat_mj_m2} unit="MJ/m²·day" meta="Observed daily resource total"/>
      <Card label="Electricity" value={k.daily_electricity_kwh_m2} unit="kWh/m²·day" meta={intraday?.tou_configured?`${fmt((efficiency.peak_share as any)?.value)}% configured peak share`:"Configure a ToU schedule for peak share"}/>
      <Card label="CO₂" value={k.daily_co2_kg_m2} unit="kg/m²·day" meta="Observed resource intensity"/>
      <Card label="Water" value={k.daily_irrigation_l_m2} unit="L/m²·day" meta={`${fmt(k.drain_ratio_pct)}% drain ratio`}/>
    </section>
    <section className="panel intraday-panel">
      <div className="panel-head"><div><span>INTRADAY ENERGY RECONSTRUCTION</span><h2>Meter-conserving operational profile</h2></div><div className="grain-picker"><button className={grain==="5min"?"active":""} onClick={()=>setGrain("5min")}>5 min</button><button className={grain==="1h"?"active":""} onClick={()=>setGrain("1h")}>1 hour</button></div></div>
      <p className="method-note">Daily meters are allocated with equipment telemetry. The incomplete day is provisional and uses only the previous seven completed days.</p>
      <ChartDateRange points={points}>{filtered=><LineChart height={390} points={filtered} series={[
        {key:"heat_allocated",name:"Heat · allocated MJ/m²",color:"#f0b45a"},
        {key:"heat_provisional",name:"Heat · provisional MJ/m²",color:"#f0b45a",dashed:true},
        {key:"elec_allocated",name:"Electricity · allocated kWh/m²",color:"#63e6a5",axis:1},
        {key:"elec_provisional",name:"Electricity · provisional kWh/m²",color:"#63e6a5",axis:1,dashed:true},
        {key:"co2_allocated",name:"CO₂ · allocated kg/m²",color:"#70a4ff",axis:1},
        {key:"co2_provisional",name:"CO₂ · provisional kg/m²",color:"#70a4ff",axis:1,dashed:true},
      ]}/>}</ChartDateRange>
      <div className="model-strip reconstruction-strip"><div><span>METHOD</span><b>{intraday?.reconstruction.method||"Loading"}</b></div><div><span>CALIBRATION</span><b>{intraday?.reconstruction.calibration_days||0} completed days</b></div><div><span>QUALITY</span><b>Solid allocated · dashed provisional</b></div><div><span>MODEL</span><b>{intraday?.reconstruction.model_version||"—"}</b></div></div>
    </section>
    <section className="efficiency-grid">
      {Object.entries(indicatorNames).map(([code,label])=>{const item=efficiency[code] as any;return <article className="panel enpi-card" key={code}><span>OPERATIONAL ENPI</span><h2>{label}</h2><strong>{item?.value==null?(code==="peak_share"?"ToU schedule required":"Not available"):`${fmt(item.value)} ${item.unit}`}</strong><p>{item?.value==null?(item?.unavailable_reason||"Insufficient evidence at this replay cursor."):item?.expected==null?"Observed diagnostic; no validated expectation yet.":`${fmt(item.variance_pct)}% versus expected`}</p><small>Confidence: {item?.confidence||"not available"}</small>{code==="peak_share"&&item?.value==null?<button className="enpi-action" onClick={openSettings}>Configure ToU schedule</button>:null}</article>})}
    </section>
    <section className="two-col efficiency-section">
      <article className="panel"><div className="panel-head"><div><span>EFFICIENCY EVENTS</span><h2>Prioritized operational conflicts</h2></div></div>{efficiencyEvents.length?<div className="efficiency-events">{efficiencyEvents.slice(0,6).map(event=><div key={event.id}><i className={`severity-dot ${event.severity}`}/><p><b>{event.message}</b><span>{event.duration_minutes} min · {event.confidence} confidence</span></p><button onClick={()=>ask(`Explain this efficiency event and give the operator one direct next action.`,event.id)}>Explain</button></div>)}</div>:<div className="no-data compact-empty">No persistent efficiency conflict in the visible evidence.</div>}</article>
      <article className="panel cost-card"><span>INTRADAY OPERATING COST</span>{intraday?.cost_configured?<><h2>Configured tariff applied</h2><LineChart height={240} points={points} series={[{key:"cost_visible",name:`Cost ${intraday.currency||"CAD"}/m²`,color:"#d178ff"}]}/></>:<><h2>Configure Ontario tariffs</h2><p>Cost remains hidden until rates, schedule, effective date, and source are reviewed and versioned.</p></>}</article>
    </section>
    <ChartDateRange points={data.resource_series}>{filtered=><>
      <section className="two-col">
        <article className="panel"><div className="panel-head"><div><span>ENERGY INTENSITY</span><h2>Heat and electricity · selected chart range</h2></div></div><LineChart height={390} points={filtered} series={[{key:"Heat_cons",name:"Heat MJ/m²",color:"#f0b45a"},{key:"ElecHigh",name:"Peak kWh/m²",color:"#63e6a5",axis:1},{key:"ElecLow",name:"Off-peak kWh/m²",color:"#70a4ff",axis:1}]}/></article>
        <article className="panel baseline-card"><span>WEATHER-NORMALIZED BASELINE</span><h2>{baseline.status==="ready"?`${fmt(baseline.actual_mj_m2)} actual vs ${fmt(baseline.expected_mj_m2)} expected`:"Insufficient history at cursor"}</h2><div className="baseline-bar"><i style={{width:`${Math.min(100,Math.max(0,(baseline.actual_mj_m2||0)/Math.max(baseline.p90_mj_m2||6,1)*100))}%`}}/></div><p>Selected: <b>{baseline.selected_model||"pending"}</b></p><p>Promotion: <b>{baseline.candidate_promoted?"passed":"candidate not promoted"}</b></p><p>Confidence: <b>{baseline.confidence||"not available"}</b></p><button className="primary" onClick={()=>ask("Explain today's energy intensity, the baseline result, uncertainty, and likely operational drivers.")}>✦ Explain energy status</button></article>
      </section>
      <article className="panel"><div className="panel-head"><div><span>WATER BALANCE</span><h2>Irrigation and drain · selected chart range</h2></div></div><LineChart height={310} points={filtered} series={[{key:"Irr",name:"Irrigation L/m²",color:"#70a4ff"},{key:"Drain",name:"Drain L/m²",color:"#63e6a5"}]}/></article>
    </>}</ChartDateRange>
  </>;
}
