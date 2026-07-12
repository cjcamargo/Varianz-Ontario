import { Snapshot, View, WindowKey } from "../lib/types";
import { views } from "../lib/nav";
import { date } from "../lib/format";

type TopbarProps={view:View;data:Snapshot|null;windowKey:WindowKey;mutate:(action:string,value?:number|string)=>void;changeWindow:(next:WindowKey)=>void};

export function Topbar({view,data,windowKey,mutate,changeWindow}:TopbarProps){
  return <>
    <header className="topbar"><div><span className="eyebrow">WAGENINGEN REFERENCE · GREENHOUSE 01</span><h1>{views.find(item=>item.id===view)?.label}</h1></div><div className="replay"><div><b>LIVE SIMULATION</b><span>{data?date(data.cursor):"Loading…"}</span></div><button aria-label="Play replay" onClick={()=>mutate("play")} className={data?.playing?"selected":""}>▶</button><button aria-label="Pause replay" onClick={()=>mutate("pause")}>Ⅱ</button><select aria-label="Replay speed" value={data?.speed||1} onChange={e=>mutate("speed",Number(e.target.value))}><option value="1">1×</option><option value="5">5×</option><option value="20">20×</option><option value="60">60×</option></select><button className="event-jump" onClick={()=>mutate("seek","2020-05-20T12:00:00Z")}>Natural event</button><button aria-label="Reset replay" onClick={()=>mutate("reset")}>↺</button></div></header>
    <section className="context-bar"><div><span className={`quality ${data?.quality.state}`}>{data?.quality.state||"loading"}</span><span>Source: {data?.quality.backend||"—"}</span><span>Model: {data?.model_version||"—"}</span></div><div className="window-picker">{(["1h","6h","24h","7d","all"] as WindowKey[]).map(item=><button key={item} className={windowKey===item?"active":""} onClick={()=>changeWindow(item)}>{item}</button>)}</div></section>
  </>
}
