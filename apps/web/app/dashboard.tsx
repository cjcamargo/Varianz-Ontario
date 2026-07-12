"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AssistantResult, Snapshot, View, WindowKey } from "./lib/types";
import { API } from "./lib/format";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { OverviewView } from "./views/OverviewView";
import { EnergyView } from "./views/EnergyView";
import { ClimateView } from "./views/ClimateView";
import { AnomaliesView } from "./views/AnomaliesView";
import { AssistantView } from "./views/AssistantView";
import { SettingsView } from "./views/SettingsView";

export default function Dashboard(){
  const [view,setView]=useState<View>("overview"),[windowKey,setWindowKey]=useState<WindowKey>("24h");
  const [data,setData]=useState<Snapshot|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(true);
  const [question,setQuestion]=useState("What requires operator attention at this replay cursor?");
  const [assistant,setAssistant]=useState<AssistantResult|null>(null),[asking,setAsking]=useState(false),[focus,setFocus]=useState<string|null>(null);
  const requestRef=useRef<AbortController|null>(null);

  const refresh=useCallback(async(id:string,windowValue:WindowKey=windowKey,allowRecreate=true):Promise<void>=>{
    requestRef.current?.abort(); const controller=new AbortController(); requestRef.current=controller;
    let res:Response;
    try{
      res=await fetch(`${API}/replay-sessions/${id}/overview?window=${windowValue}`,{signal:controller.signal});
    }catch(e){
      if(controller.signal.aborted||(e instanceof DOMException&&e.name==="AbortError"))return; // superseded by a newer request
      throw e;
    }
    if(res.status===404&&allowRecreate){const s=await fetch(`${API}/replay-sessions`,{method:"POST"}).then(r=>r.json());return refresh(s.id,windowValue,false);}
    if(!res.ok)throw new Error("Analytics API unavailable");
    const next:Snapshot=await res.json();
    setData(current=>!current||next.revision>=current.revision?next:current); setError(""); setLoading(false);
  },[windowKey]);
  const create=useCallback(async()=>{try{setLoading(true);const s=await fetch(`${API}/replay-sessions`,{method:"POST"}).then(r=>r.json());await refresh(s.id)}catch(e){setError(e instanceof Error?e.message:"API unavailable");setLoading(false)}},[refresh]);
  useEffect(()=>{create()},[]);
  useEffect(()=>{if(!data?.playing)return;const timer=setInterval(()=>refresh(data.session_id),2000);return()=>clearInterval(timer)},[data?.playing,data?.session_id,refresh]);
  async function mutate(action:string,value?:number|string){if(!data)return;const res=await fetch(`${API}/replay-sessions/${data.session_id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,expected_revision:data.revision,value})});if(res.status===404){await create();return}if(!res.ok)throw new Error("Replay revision conflict");const s=await res.json();await refresh(s.id)}
  async function changeWindow(next:WindowKey){setWindowKey(next);if(data)try{await refresh(data.session_id,next)}catch(e){setError(e instanceof Error?e.message:"Analytics API unavailable")}}
  async function ask(custom?:string,anomalyId?:string){if(!data)return;const prompt=(custom||question).trim();setView("assistant");setFocus(anomalyId||null);setQuestion(prompt);if(prompt.length<3){setError("Enter a question with at least 3 characters.");return}setError("");setAsking(true);const send=(sid:string)=>fetch(`${API}/replay-sessions/${sid}/assistant/messages`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:prompt,anomaly_id:anomalyId})});try{let result=await send(data.session_id);if(result.status===404){const s=await fetch(`${API}/replay-sessions`,{method:"POST"}).then(r=>r.json());await refresh(s.id);result=await send(s.id)}if(!result.ok){const msg=result.status===422?"Please enter a clear question (3–1000 characters).":result.status===503?"Varianz AI is unavailable right now — the interpretation service returned no answer. Please retry.":result.status===502?"The interpretation model returned an error. Please retry.":"Varianz AI could not complete the explanation";throw new Error(msg)}setAssistant(await result.json());setError("")}catch(e){setError(e instanceof Error?e.message:"Assistant unavailable")}finally{setAsking(false)}}
  const k=data?.kpis||{}; const baseline=data?.baseline||{}; const top=data?.anomalies?.[0];

  return <div className="app-shell">
    <Sidebar view={view} setView={setView} k={k}/>
    <main className="workspace">
      <Topbar view={view} data={data} windowKey={windowKey} mutate={mutate} changeWindow={changeWindow}/>
      {error?<section className="error-banner">{error}<button onClick={()=>setError("")}>×</button></section>:null}
      {loading?<div className="loading"><span/>Building point-in-time analytics…</div>:null}
      {!loading&&data&&view==="overview"?<OverviewView data={data} k={k} baseline={baseline} top={top} setView={setView} ask={ask}/>:null}
      {!loading&&data&&view==="energy"?<EnergyView data={data} k={k} baseline={baseline} ask={ask}/>:null}
      {!loading&&data&&view==="climate"?<ClimateView data={data} k={k}/>:null}
      {!loading&&data&&view==="anomalies"?<AnomaliesView data={data} focus={focus} setFocus={setFocus} ask={ask}/>:null}
      {!loading&&data&&view==="assistant"?<AssistantView data={data} question={question} setQuestion={setQuestion} assistant={assistant} asking={asking} ask={ask}/>:null}
      {!loading&&data&&view==="settings"?<SettingsView siteId={data.site.id} onSaved={()=>refresh(data.session_id)}/>:null}
    </main>
  </div>
}
