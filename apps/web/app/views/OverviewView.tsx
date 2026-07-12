import { Anomaly, Snapshot, View } from "../lib/types";
import { fmt } from "../lib/format";
import { Card, LineChart } from "../components/primitives";

type OverviewProps = {
  data:Snapshot; k:Snapshot["kpis"]; baseline:Record<string,any>; top:Anomaly|undefined;
  setView:(v:View)=>void; ask:(custom?:string,anomalyId?:string)=>void;
};

export function OverviewView({data,k,baseline,top,setView,ask}:OverviewProps){
  return <>
    <section className="hero-grid">
      <Card label="Total energy" value={k.daily_total_energy_mj_m2} unit="MJ/m²·day" meta={`${fmt(k.daily_heat_mj_m2)} heat · ${fmt(k.daily_electricity_kwh_m2)} kWh electricity`}/>
      <Card label="Heat vs expected" value={baseline.residual_mj_m2} unit="MJ/m²" meta={baseline.status==="ready"?`${baseline.variance_pct>0?"Above":"Below"} ${baseline.selected_model} baseline · ${baseline.confidence} confidence`:"Baseline building — minimum 45 days"} tone={baseline.anomaly?"amber":"green"}/>
      <Card label="Climate compliance" value={k.climate_compliance_24h_pct} unit="% / 24h" meta={`${fmt(k.climate_compliance_1h_pct)}% last hour · ${fmt(k.anomaly_minutes,0)} anomaly min`} tone={Number(k.climate_compliance_24h_pct)<90?"amber":"green"}/>
      <Card label="Drain ratio" value={k.drain_ratio_pct} unit="%" meta={`${fmt(k.daily_irrigation_l_m2)} L/m² irrigation · ${fmt(k.daily_drain_l_m2)} L/m² drain`} tone={Number(k.drain_ratio_pct)>80||Number(k.drain_ratio_pct)<10?"amber":"green"}/>
      <Card label="Operating cost" value={k.operating_cost_cad_m2} unit="CAD/m²·day" meta={data.tariff.configured?"Ontario tariff profile applied":"Configure Ontario tariffs to enable cost"} tone="neutral"/>
    </section>
    <section className="overview-grid"><article className="panel span-2"><div className="panel-head"><div><span>OPERATIONAL CLIMATE</span><h2>Inside temperature vs targets</h2></div><button onClick={()=>setView("climate")}>Open climate →</button></div><LineChart points={data.climate_series} series={[{key:"Tair",name:"Indoor °C",color:"#63e6a5"},{key:"Tout",name:"Outdoor °C",color:"#70a4ff"},{key:"t_heat_vip",name:"Heat target °C",color:"#f0b45a",dashed:true},{key:"t_ventlee_vip",name:"Vent target °C",color:"#d178ff",dashed:true}]} bands={[18,26]}/></article>
      <article className="panel attention"><div className="panel-head"><div><span>OPERATOR ATTENTION</span><h2>{top?top.message:"Operation within configured review bands"}</h2></div></div>{top?<><div className={`severity ${top.severity}`}>{top.severity} · {top.duration_minutes} min</div><dl><div><dt>Observed</dt><dd>{fmt(top.observed)}</dd></div><div><dt>Expected</dt><dd>{fmt(top.expected)}</dd></div><div><dt>Confidence</dt><dd>{top.confidence}</dd></div></dl><button className="primary" onClick={()=>ask(`Explain anomaly ${top.code}, its operational impact, and the safest next checks.`,top.id)}>✦ Explain with Varianz</button></>:<p>No active anomaly requires intervention at this cursor.</p>}</article>
    </section>
    <section className="model-strip"><div><span>BASELINE STATUS</span><b>{baseline.status==="ready"?(baseline.candidate_promoted?"Elastic Net promoted":"Naive baseline retained"):"Collecting training history"}</b></div><div><span>LOCKED TEST</span><b>{baseline.promotion_gate?`${fmt(baseline.promotion_gate.locked_test_improvement_pct)}% vs naive`:"Not available"}</b></div><div><span>UNCERTAINTY</span><b>{baseline.p10_mj_m2!=null?`${fmt(baseline.p10_mj_m2)}–${fmt(baseline.p90_mj_m2)} MJ/m²`:"Not available"}</b></div><div><span>EVIDENCE</span><b>{data.evidence_ids.length} linked records</b></div></section>
  </>
}
