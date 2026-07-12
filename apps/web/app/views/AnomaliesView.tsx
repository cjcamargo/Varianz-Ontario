import { Snapshot } from "../lib/types";
import { fmt, date } from "../lib/format";

type AnomaliesProps = {
  data:Snapshot; focus:string|null; setFocus:(id:string|null)=>void;
  ask:(custom?:string,anomalyId?:string)=>void;
};

export function AnomaliesView({data,focus,setFocus,ask}:AnomaliesProps){
  return <section className="anomaly-layout"><article className="panel"><div className="panel-head"><div><span>NATURAL EVENTS ONLY</span><h2>Operational deviations · last 7 days</h2></div><b>{data.anomalies.length} events</b></div><div className="anomaly-list">{data.anomalies.length?data.anomalies.map(a=><button key={a.id} onClick={()=>setFocus(a.id)} className={focus===a.id?"selected":""}><i className={`severity-dot ${a.severity}`}/><div><b>{a.message}</b><span>{date(a.started_at)} · {a.duration_minutes} min · {a.category}</span></div><em>{a.active?"ACTIVE":"CLOSED"}</em></button>):<p>No natural deviations detected in this window.</p>}</div></article><article className="panel detail">{(()=>{const a=data.anomalies.find(x=>x.id===focus)||data.anomalies[0];return a?<><span>ANOMALY EVIDENCE</span><h2>{a.code.replaceAll("_"," ")}</h2><div className={`severity ${a.severity}`}>{a.severity} severity</div><dl><div><dt>Duration</dt><dd>{a.duration_minutes} min</dd></div><div><dt>Observed</dt><dd>{fmt(a.observed)}</dd></div><div><dt>Expected</dt><dd>{fmt(a.expected)}</dd></div><div><dt>Confidence</dt><dd>{a.confidence}</dd></div></dl><h3>Contributing signals</h3><div className="chips">{a.contributors.map(c=><span key={c}>{c}</span>)}</div><button className="primary" onClick={()=>ask(`Explain ${a.code}, quantify the deviation, and recommend operator checks without claiming causality.`,a.id)}>✦ Explain this deviation</button></>:<><h2>No event selected</h2><p>Advance the replay or widen the window to inspect natural deviations.</p></>})()}</article></section>
}
