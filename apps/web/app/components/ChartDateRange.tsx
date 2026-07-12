import { ReactNode, useEffect, useMemo, useState } from "react";
import { Point } from "../lib/types";

export function ChartDateRange({points,children}:{
  points:Point[];
  children:(filtered:Point[])=>ReactNode;
}){
  const bounds=useMemo(()=>{
    const dates=points.map(point=>String(point.time).slice(0,10)).filter(Boolean);
    return {from:dates[0]||"",to:dates[dates.length-1]||""};
  },[points]);
  const [from,setFrom]=useState(bounds.from),[to,setTo]=useState(bounds.to);

  useEffect(()=>{setFrom(bounds.from);setTo(bounds.to)},[bounds.from,bounds.to]);

  const filtered=useMemo(()=>points.filter(point=>{
    const day=String(point.time).slice(0,10);
    return (!from||day>=from)&&(!to||day<=to);
  }),[from,points,to]);

  return <>
    <section className="chart-date-filter" aria-label="Chart date range">
      <div><b>CHART DATE RANGE</b><span>Charts only · capped at replay cursor</span></div>
      <label>From<input type="date" min={bounds.from} max={to||bounds.to} value={from} onChange={event=>setFrom(event.target.value)}/></label>
      <label>To<input type="date" min={from||bounds.from} max={bounds.to} value={to} onChange={event=>setTo(event.target.value)}/></label>
      <button onClick={()=>{setFrom(bounds.from);setTo(bounds.to)}} disabled={from===bounds.from&&to===bounds.to}>Reset</button>
      <em>{filtered.length.toLocaleString()} observations</em>
    </section>
    {children(filtered)}
  </>;
}
