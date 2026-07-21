import { Snapshot } from "../lib/types";
import { fmt } from "../lib/format";
import { Card, LineChart } from "../components/primitives";
import { ChartDateRange } from "../components/ChartDateRange";

export function ClimateView({data,k}:{data:Snapshot;k:Snapshot["kpis"]}){
  const impact=data.business_impact;
  return <>
    <section className="hero-grid compact">
      <Card label="Indoor temperature" value={data.latest.Tair} unit="°C" meta={`Outdoor ${fmt(data.latest.Tout)} °C`}/>
      <Card label="Relative humidity" value={data.latest.Rhair} unit="%" meta={`${fmt(k.climate_compliance_1h_pct)}% compliance / 1h`}/>
      <Card label="Humidity deficit" value={data.latest.HumDef} unit="g/m³" meta="Observed indoor state"/>
      <Card label="CO₂" value={data.latest.CO2air} unit="ppm" meta="Observed concentration"/>
      <Card label="Climate cost exposure" value={impact.climate_cost_exposure_24h_cad_per_1000m2} unit={`${impact.currency||"CAD"} / 1,000 m²`} meta={`${impact.climate_excursion_intervals_24h} non-compliant five-minute intervals · not avoidable savings`} tone={impact.climate_excursion_intervals_24h>0?"amber":"green"}/>
    </section>
    <ChartDateRange points={data.climate_series}>{filtered=><>
      <article className="panel"><div className="panel-head"><div><span>CONTROL PERFORMANCE</span><h2>Temperature, setpoints and safe band · selected chart range</h2></div></div><LineChart height={430} points={filtered} series={[{key:"Tair",name:"Indoor °C",color:"#63e6a5"},{key:"Tout",name:"Outdoor °C",color:"#70a4ff"},{key:"t_heat_vip",name:"Heat target °C",color:"#f0b45a",dashed:true},{key:"t_ventlee_vip",name:"Vent target °C",color:"#d178ff",dashed:true}]} bands={[18,26]}/></article>
      <section className="two-col"><article className="panel"><div className="panel-head"><div><span>HUMIDITY</span><h2>RH and humidity deficit</h2></div></div><LineChart height={330} points={filtered} series={[{key:"Rhair",name:"RH %",color:"#70a4ff"},{key:"HumDef",name:"Deficit g/m³",color:"#f0b45a",axis:1}]}/></article><article className="panel"><div className="panel-head"><div><span>ACTUATION</span><h2>Screens and vents</h2></div></div><LineChart height={330} points={filtered} series={[{key:"EnScr",name:"Energy screen %",color:"#d178ff"},{key:"VentLee",name:"Leeward vent %",color:"#63e6a5"}]}/></article></section>
    </>}</ChartDateRange>
  </>;
}
