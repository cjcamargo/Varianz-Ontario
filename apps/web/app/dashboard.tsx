"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AssistantResult, ChatMessage, Snapshot, View, WindowKey } from "./lib/types";
import { API } from "./lib/format";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { OverviewView } from "./views/OverviewView";
import { EnergyView } from "./views/EnergyView";
import { ClimateView } from "./views/ClimateView";
import { AnomaliesView } from "./views/AnomaliesView";
import { AssistantView } from "./views/AssistantView";
import { SettingsView } from "./views/SettingsView";

type DashboardProps={accessToken:string;userEmail:string;onSignOut:()=>void};

export default function Dashboard({accessToken,userEmail,onSignOut}:DashboardProps){
  const [view,setView]=useState<View>("overview"),[windowKey,setWindowKey]=useState<WindowKey>("24h");
  const [data,setData]=useState<Snapshot|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(true);
  const [startupMessage,setStartupMessage]=useState("Connecting to the analytics endpoint…");
  const [energyData,setEnergyData]=useState<Snapshot|null>(null),[energyGrain,setEnergyGrain]=useState<"5min"|"1h">("1h");
  const [question,setQuestion]=useState("What requires operator attention at this replay cursor?");
  const [messages,setMessages]=useState<ChatMessage[]>([]),[asking,setAsking]=useState(false),[transcribing,setTranscribing]=useState(false),[focus,setFocus]=useState<string|null>(null);
  const requestRef=useRef<AbortController|null>(null);
  const initializedTokenRef=useRef<string|null>(null);
  const mutationInFlightRef=useRef(false);

  const apiFetch=useCallback((path:string,init:RequestInit={})=>{
    const headers=new Headers(init.headers);
    headers.set("Authorization",`Bearer ${accessToken}`);
    return fetch(`${API}${path}`,{...init,headers});
  },[accessToken]);

  const refresh=useCallback(async(id:string,windowValue:WindowKey=windowKey,allowRecreate=true):Promise<void>=>{
    requestRef.current?.abort();const controller=new AbortController();requestRef.current=controller;
    let response:Response;
    try{response=await apiFetch(`/replay-sessions/${id}/overview?window=${windowValue}`,{signal:controller.signal})}
    catch(e){if(controller.signal.aborted||(e instanceof DOMException&&e.name==="AbortError"))return;throw e}
    if(response.status===401){await onSignOut();return}
    if(response.status===404&&allowRecreate){const created=await apiFetch("/replay-sessions",{method:"POST"});if(!created.ok)throw new Error("Could not restore the replay session.");const session=await created.json();return refresh(session.id,windowValue,false)}
    if(!response.ok)throw new Error("Analytics API unavailable");
    const next:Snapshot=await response.json();
    setData(current=>!current||next.revision>=current.revision?next:current);setError("");setLoading(false);
  },[apiFetch,onSignOut,windowKey]);

  const waitForApiReady=useCallback(async()=>{
    const delays=[1000,1500,2500,4000,6000,8000,8000,8000,8000,8000];
    for(let attempt=0;attempt<delays.length;attempt++){
      setStartupMessage(attempt<2?"Waking the analytics endpoint…":"Loading operational history from Supabase…");
      const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),12000);
      try{
        const response=await apiFetch("/ready",{signal:controller.signal,cache:"no-store"});
        const contentType=response.headers.get("content-type")||"";
        if(contentType.includes("application/json")){
          const payload=await response.json();
          if(response.ok&&payload.ready)return;
        }
      }catch{ /* Render cold starts and request timeouts are retried below. */ }
      finally{clearTimeout(timeout)}
      await new Promise(resolve=>setTimeout(resolve,delays[attempt]));
    }
    throw new Error("The analytics endpoint is taking longer than expected. Please retry in one minute.");
  },[apiFetch]);

  const create=useCallback(async()=>{try{setLoading(true);setError("");await waitForApiReady();setStartupMessage("Preparing your replay session…");const response=await apiFetch("/replay-sessions",{method:"POST"});if(response.status===401){await onSignOut();return}const contentType=response.headers.get("content-type")||"";if(!response.ok||!contentType.includes("application/json"))throw new Error("Analytics API unavailable");const session=await response.json();if(!session.id)throw new Error("Invalid replay session response");await refresh(session.id)}catch(e){setError(e instanceof Error?e.message:"API unavailable");setLoading(false)}},[apiFetch,onSignOut,refresh,waitForApiReady]);

  useEffect(()=>{
    if(initializedTokenRef.current===accessToken)return;
    initializedTokenRef.current=accessToken;
    void create();
  },[accessToken,create]);
  useEffect(()=>{if(!data?.playing)return;const timer=setInterval(()=>refresh(data.session_id),2000);return()=>clearInterval(timer)},[data?.playing,data?.session_id,refresh]);
  useEffect(()=>{
    if(view!=="energy"||!data)return;
    let active=true,inFlight=false;
    const loadEnergy=async()=>{
      if(inFlight)return;inFlight=true;
      try{
        const response=await apiFetch(`/replay-sessions/${data.session_id}/energy-resources?window=${windowKey}&grain=${energyGrain}`);
        if(response.status===401){await onSignOut();return}
        if(!response.ok)throw new Error("Energy analytics unavailable");
        const next:Snapshot=await response.json();
        if(active){setEnergyData(next);setError("")}
      }catch(event){if(active)setError(event instanceof Error?event.message:"Energy analytics unavailable")}
      finally{inFlight=false}
    };
    void loadEnergy();
    const timer=data.playing?setInterval(()=>void loadEnergy(),5000):undefined;
    return()=>{active=false;if(timer)clearInterval(timer)};
  },[apiFetch,data?.playing,data?.revision,data?.session_id,energyGrain,onSignOut,view,windowKey]);

  async function mutate(action:string,value?:number|string){
    if(!data||mutationInFlightRef.current)return;
    mutationInFlightRef.current=true;setError("");
    const send=(revision:number)=>apiFetch(`/replay-sessions/${data.session_id}`,{
      method:"PATCH",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({action,expected_revision:revision,value}),
    });
    try{
      let response=await send(data.revision);
      if(response.status===409){
        const synchronized=await apiFetch(`/replay-sessions/${data.session_id}/overview?window=${windowKey}`);
        if(!synchronized.ok)throw new Error("Replay state could not be synchronized.");
        const latest:Snapshot=await synchronized.json();setData(latest);
        response=await send(latest.revision);
      }
      if(response.status===401){await onSignOut();return}
      if(response.status===404){await create();return}
      if(!response.ok)throw new Error("Replay control could not be applied. Please retry.");
      const session=await response.json();await refresh(session.id);
    }catch(e){setError(e instanceof Error?e.message:"Replay control unavailable")}
    finally{mutationInFlightRef.current=false}
  }
  async function changeWindow(next:WindowKey){setWindowKey(next);if(data)try{await refresh(data.session_id,next)}catch(e){setError(e instanceof Error?e.message:"Analytics API unavailable")}}
  async function ask(custom?:string,anomalyId?:string){
    if(!data)return;const prompt=(custom||question).trim();setView("assistant");setFocus(anomalyId||null);
    if(prompt.length<3){setError("Enter a question with at least 3 characters.");return}
    setError("");setAsking(true);setQuestion("");
    setMessages(current=>[...current,{id:crypto.randomUUID(),role:"operator",text:prompt}]);
    const send=(id:string)=>apiFetch(`/replay-sessions/${id}/assistant/messages`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:prompt,anomaly_id:anomalyId})});
    try{
      let result=await send(data.session_id);
      if(result.status===401){await onSignOut();return}
      if(result.status===404){const created=await apiFetch("/replay-sessions",{method:"POST"});if(!created.ok)throw new Error("Could not restore the replay session.");const session=await created.json();await refresh(session.id);result=await send(session.id)}
      if(!result.ok){const message=result.status===422?"Please enter a clear question (3–1000 characters).":result.status===503?"Varianz AI is unavailable right now — please retry.":result.status===502?"The interpretation model returned an error. Please retry.":"Varianz AI could not complete the explanation";throw new Error(message)}
      const answer:AssistantResult=await result.json();
      setMessages(current=>[...current,{id:crypto.randomUUID(),role:"assistant",text:answer.answer,result:answer}]);setError("");
    }catch(e){setError(e instanceof Error?e.message:"Assistant unavailable")}finally{setAsking(false)}
  }
  async function transcribeVoice(audio:Blob){
    if(!data)return;
    setError("");setTranscribing(true);
    const extension=audio.type.includes("mp4")?"mp4":audio.type.includes("ogg")?"ogg":"webm";
    const body=new FormData();body.append("audio",audio,`varianz-voice.${extension}`);
    try{
      const response=await apiFetch(`/replay-sessions/${data.session_id}/assistant/transcriptions`,{method:"POST",body});
      if(response.status===401){await onSignOut();return}
      if(!response.ok){
        const message=response.status===413?"Voice message is too large. Keep recordings under one minute.":response.status===415?"This browser audio format is not supported.":"Varianz could not transcribe the voice message.";
        throw new Error(message);
      }
      const result:{transcript:string}=await response.json();
      const transcript=result.transcript.trim();
      if(transcript.length<3)throw new Error("No clear speech was detected. Please try again.");
      setQuestion(transcript);
      await ask(transcript);
    }catch(event){setError(event instanceof Error?event.message:"Voice transcription unavailable")}
    finally{setTranscribing(false)}
  }
  async function synthesizeVoice(text:string,language:"en"|"es"){
    if(!data)throw new Error("Replay session unavailable");
    const response=await apiFetch(`/replay-sessions/${data.session_id}/assistant/speech`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text,language})});
    if(response.status===401){await onSignOut();throw new Error("Session expired")}
    if(!response.ok)throw new Error("Varianz voice reply is unavailable right now.");
    return response.blob();
  }

  const k=data?.kpis||{},baseline=data?.baseline||{},top=data?.anomalies?.[0];
  const visibleEnergy=energyData?.session_id===data?.session_id?energyData:null;
  return <div className="app-shell">
    <Sidebar view={view} setView={setView} k={k} userEmail={userEmail} onSignOut={onSignOut}/>
    <main className="workspace">
      <Topbar view={view} data={data} windowKey={windowKey} mutate={mutate} changeWindow={changeWindow}/>
      {error?<section className="error-banner">{error}<button onClick={()=>setError("")}>×</button></section>:null}
      {loading&&!data?<div className="loading"><span/>{startupMessage}</div>:null}
      {data&&view==="overview"?<OverviewView data={data} k={k} baseline={baseline} top={top} setView={setView} ask={ask}/>:null}
      {data&&view==="energy"?(visibleEnergy?<EnergyView data={visibleEnergy} k={visibleEnergy.kpis} baseline={visibleEnergy.baseline} ask={ask} grain={energyGrain} setGrain={setEnergyGrain} openSettings={()=>setView("settings")}/>:<div className="loading"><span/>Loading energy analytics…</div>):null}
      {data&&view==="climate"?<ClimateView data={data} k={k}/>:null}
      {data&&view==="anomalies"?<AnomaliesView data={data} focus={focus} setFocus={setFocus} ask={ask}/>:null}
      {data&&view==="assistant"?<AssistantView data={data} question={question} setQuestion={setQuestion} messages={messages} asking={asking} transcribing={transcribing} ask={ask} onVoice={transcribeVoice} onSpeak={synthesizeVoice}/>:null}
      {data&&view==="settings"?<SettingsView siteId={data.site.id} apiFetch={apiFetch} onSaved={async()=>{setEnergyData(null);await refresh(data.session_id)}}/>:null}
    </main>
  </div>
}
