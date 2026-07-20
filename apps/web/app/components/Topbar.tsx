import { Snapshot, View, WindowKey } from "../lib/types";
import { views } from "../lib/nav";
import { date } from "../lib/format";

type TopbarProps={view:View;data:Snapshot|null;windowKey:WindowKey;mutate:(action:string,value?:number|string)=>void;changeWindow:(next:WindowKey)=>void};

export function Topbar({view,data,windowKey,mutate,changeWindow}:TopbarProps){
  const quality=data?.quality;
  const validationNote=quality?`Validated scope: ${quality.validation_scope}. Visible as of ${date(quality.as_of)}. Coverage ${date(quality.coverage_start)} to ${date(quality.coverage_end)}. Data ${quality.data_version}; definitions ${quality.definitions_version}.`:"Validation metadata is loading.";
  return <>
    <header className="topbar"><div><span className="eyebrow">WAGENINGEN DEMO REFERENCE · GREENHOUSE 01</span><h1>{views.find(item=>item.id===view)?.label}</h1></div><div className="replay"><div className="replay-clock"><b>LIVE SIMULATION</b><span>{data?date(data.cursor):"Loading…"}</span><div className="replay-progress" aria-label={`${data?.replay.progress_pct||0}% of demo data replayed`}><i style={{width:`${data?.replay.progress_pct||0}%`}}/></div><small>{data?`${data.replay.observations_seen.toLocaleString()} / ${data.replay.observations_total.toLocaleString()} observations · ${data.replay.progress_pct}%`:"Preparing data range"}</small></div><button aria-label="Play replay" onClick={()=>mutate("play")} className={data?.playing?"selected":""}>▶</button><button aria-label="Pause replay" onClick={()=>mutate("pause")}>Ⅱ</button><select aria-label="Replay speed" value={data?.speed||1} onChange={e=>mutate("speed",Number(e.target.value))}><option value="1">1×</option><option value="5">5×</option><option value="20">20×</option><option value="60">60×</option></select><button className="event-jump" onClick={()=>mutate("seek","2020-05-20T12:00:00Z")}>Natural event</button><button aria-label="Reset replay" onClick={()=>mutate("reset")}>↺</button></div></header>
    <section className="context-bar"><div><span className={`quality-info ${quality?.state||"loading"}`} tabIndex={0} title={validationNote}><b>{quality?.state||"loading"}</b><span className="quality-tooltip">{validationNote}</span></span><span className={`data-status ${quality?.data_status||"loading"}`}><i/>Data status: <b>{quality?.data_status||"loading"}</b></span><span>Model: {data?.model_version||"—"}</span></div><div className="window-picker">{(["1h","6h","24h","7d","all"] as WindowKey[]).map(item=><button key={item} className={windowKey===item?"active":""} onClick={()=>changeWindow(item)}>{item}</button>)}</div></section>
  </>
}
