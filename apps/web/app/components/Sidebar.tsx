import { Snapshot, View } from "../lib/types";
import { views } from "../lib/nav";

export function Sidebar({view,setView,k,userEmail,onSignOut}:{view:View;setView:(v:View)=>void;k:Snapshot["kpis"];userEmail:string;onSignOut:()=>void}){
  return <aside className="sidebar"><div className="logo"><span>V</span><div><b>VARIANZ</b><small>Operational Intelligence</small></div></div><nav>{views.map(item=><button key={item.id} className={view===item.id?"active":""} onClick={()=>setView(item.id)}><i>{item.icon}</i>{item.label}{item.id==="anomalies"&&Number(k.active_anomalies)>0?<em>{k.active_anomalies}</em>:null}</button>)}</nav><div className="side-foot"><span className="status-dot"/>Supabase connected<small>{userEmail}</small><button className="sign-out" onClick={onSignOut}>Sign out</button></div></aside>
}
