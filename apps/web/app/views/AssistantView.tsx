import { useCallback, useEffect, useRef, useState } from "react";
import { ChatMessage, Snapshot } from "../lib/types";
import { date } from "../lib/format";

type AssistantProps = {
  data:Snapshot; question:string; setQuestion:(q:string)=>void;
  messages:ChatMessage[]; asking:boolean;
  ask:(custom?:string,anomalyId?:string)=>void; onLiveConnect:(offerSdp:string)=>Promise<string>;
  onSpeak:(text:string,language:"en"|"es")=>Promise<Blob>;
};

type LiveTurn={id:string;role:"operator"|"varianz";text:string};
type LiveState="idle"|"connecting"|"live"|"error";

function waitForIceGathering(pc:RTCPeerConnection){
  if(pc.iceGatheringState==="complete")return Promise.resolve();
  return new Promise<void>(resolve=>{
    const done=()=>{clearTimeout(timer);pc.removeEventListener("icegatheringstatechange",check);resolve()};
    const check=()=>{if(pc.iceGatheringState==="complete")done()};
    const timer=setTimeout(done,2500);
    pc.addEventListener("icegatheringstatechange",check);
  });
}

function LiveVoice({onConnect}:{onConnect:(offerSdp:string)=>Promise<string>}){
  const [state,setState]=useState<LiveState>("idle"),[error,setError]=useState(""),[muted,setMuted]=useState(false),[turns,setTurns]=useState<LiveTurn[]>([]);
  const pcRef=useRef<RTCPeerConnection|null>(null),streamRef=useRef<MediaStream|null>(null),audioRef=useRef<HTMLAudioElement|null>(null),attemptRef=useRef(0);
  // Invalidates any in-flight connection attempt and releases the microphone; safe to call on unmount.
  const teardown=useCallback(()=>{
    attemptRef.current++;
    pcRef.current?.close();pcRef.current=null;
    streamRef.current?.getTracks().forEach(track=>track.stop());streamRef.current=null;
    if(audioRef.current)audioRef.current.srcObject=null;
  },[]);
  useEffect(()=>teardown,[teardown]);
  const append=(role:LiveTurn["role"],delta:string)=>{if(!delta)return;setTurns(current=>{const last=current[current.length-1];if(last?.role===role)return [...current.slice(0,-1),{...last,text:last.text+delta}];return [...current,{id:crypto.randomUUID(),role,text:delta.trimStart()}].slice(-8)})};
  async function start(){
    if(!navigator.mediaDevices?.getUserMedia||typeof RTCPeerConnection==="undefined"){setState("error");setError("Live voice is not supported in this browser.");return}
    const attempt=++attemptRef.current;
    setError("");setTurns([]);setMuted(false);setState("connecting");
    try{
      const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
      if(attempt!==attemptRef.current){stream.getTracks().forEach(track=>track.stop());return}
      streamRef.current=stream;
      const pc=new RTCPeerConnection();pcRef.current=pc;
      pc.ontrack=event=>{const audio=audioRef.current;if(audio){audio.srcObject=event.streams[0];void audio.play().catch(()=>{})}};
      stream.getTracks().forEach(track=>pc.addTrack(track,stream));
      pc.onconnectionstatechange=()=>{
        if(attempt!==attemptRef.current)return;
        if(pc.connectionState==="connected")setState("live");
        if(pc.connectionState==="failed"||pc.connectionState==="disconnected"){teardown();setState("error");setError("The voice connection dropped. Start the conversation again.")}
      };
      const channel=pc.createDataChannel("oai-events");
      channel.onmessage=message=>{
        if(attempt!==attemptRef.current)return;
        let event:{type?:string;delta?:string};
        try{event=JSON.parse(message.data)}catch{return}
        if(event.type==="session.started")setState("live");
        else if(event.type==="session.input_transcript.delta")append("operator",event.delta||"");
        else if(event.type==="session.output_transcript.delta")append("varianz",event.delta||"");
        else if(event.type==="session.closed"){teardown();setState("idle")}
        else if(event.type==="error")setError("Varianz AI hit a problem answering. Keep talking or restart the conversation.");
      };
      await pc.setLocalDescription(await pc.createOffer());
      await waitForIceGathering(pc);
      const answer=await onConnect(pc.localDescription?.sdp||"");
      if(attempt!==attemptRef.current)return;
      await pc.setRemoteDescription({type:"answer",sdp:answer});
    }catch(event){
      if(attempt!==attemptRef.current)return;
      teardown();setState("error");
      setError(event instanceof DOMException&&event.name==="NotAllowedError"?"Microphone access was not granted. Allow it in your browser and try again.":event instanceof Error?event.message:"Varianz AI voice could not connect.");
    }
  }
  function stop(){teardown();setState("idle");setMuted(false)}
  function toggleMute(){const next=!muted;streamRef.current?.getAudioTracks().forEach(track=>{track.enabled=!next});setMuted(next)}
  const active=state==="live"||state==="connecting";
  const status=state==="connecting"?"Connecting to Varianz AI…":state==="live"?(muted?"Microphone muted":"Live — just talk, you can interrupt anytime"):"Talk with Varianz AI in real time";
  return <div className="voice-control live-voice">
    <div className="live-voice-bar">
      <button type="button" className={active?"voice-button recording":"voice-button"} onClick={active?stop:()=>void start()} aria-label={active?"End live conversation with Varianz AI":"Start live conversation with Varianz AI"}><span>{active?"■":"●"}</span>{active?"End":"Talk live"}</button>
      {state==="live"?<button type="button" className="voice-button" onClick={toggleMute} aria-pressed={muted}>{muted?"Unmute":"Mute"}</button>:null}
      <small aria-live="polite">{status}</small>
      {error?<em role="alert">{error}</em>:null}
    </div>
    {turns.length?<div className="live-transcript" aria-live="polite">{turns.map(turn=><p key={turn.id} className={turn.role}><b>{turn.role==="operator"?"YOU":"VARIANZ AI"}</b>{turn.text}</p>)}</div>:null}
    <audio ref={audioRef} autoPlay hidden/>
  </div>;
}

export function AssistantView({data,question,setQuestion,messages,asking,ask,onLiveConnect,onSpeak}:AssistantProps){
  const [voiceReplies,setVoiceReplies]=useState(true),[speechBusy,setSpeechBusy]=useState<string|null>(null),[speaking,setSpeaking]=useState<string|null>(null),[speechError,setSpeechError]=useState("");
  const audioRef=useRef<HTMLAudioElement|null>(null),audioUrls=useRef<Map<string,string>>(new Map()),lastAutoSpoken=useRef<string|null>(null);
  async function playMessage(message:ChatMessage){
    if(!message.result)return;
    if(speaking===message.id&&audioRef.current){audioRef.current.pause();audioRef.current.currentTime=0;setSpeaking(null);return}
    audioRef.current?.pause();setSpeechError("");setSpeechBusy(message.id);
    try{
      let url=audioUrls.current.get(message.id);
      if(!url){const text=`${message.result.recommendation}. ${message.result.answer}`.slice(0,3000);const blob=await onSpeak(text,message.result.language||"en");url=URL.createObjectURL(blob);audioUrls.current.set(message.id,url)}
      const audio=new Audio(url);audioRef.current=audio;audio.onended=()=>setSpeaking(null);audio.onerror=()=>{setSpeaking(null);setSpeechError("The voice reply could not be played.")};setSpeaking(message.id);await audio.play();
    }catch{setSpeaking(null);setSpeechError("Tap Listen to play the voice reply.")}
    finally{setSpeechBusy(null)}
  }
  useEffect(()=>{const last=messages[messages.length-1];if(voiceReplies&&last?.role==="assistant"&&last.result&&lastAutoSpoken.current!==last.id){lastAutoSpoken.current=last.id;void playMessage(last)}},[messages,voiceReplies]);
  useEffect(()=>()=>{audioRef.current?.pause();audioUrls.current.forEach(url=>URL.revokeObjectURL(url));audioUrls.current.clear()},[]);
  function toggleVoiceReplies(){setVoiceReplies(current=>{if(current){audioRef.current?.pause();setSpeaking(null)}return !current})}
  return <section className="assistant-layout">
    <article className="panel assistant-main">
      <div className="assistant-title"><span>✦</span><div><b>VARIANZ AI</b><h2>Operator guidance grounded in current evidence</h2></div><button type="button" className={voiceReplies?"voice-toggle active":"voice-toggle"} onClick={toggleVoiceReplies}>{voiceReplies?"🔊 AI voice on":"🔇 AI voice off"}</button></div>
      {!messages.length?<div className="assistant-empty"><b>Start a conversation</b><button onClick={()=>ask("What should the operator check first right now?")}>What should I check first?</button><button onClick={()=>ask("Why is heating energy consumption different from the expected baseline?")}>Why is heating energy different from expected?</button><button onClick={()=>ask("Which climate deviation requires attention now?")}>What climate issue requires attention?</button></div>:null}
      <div className="chat-thread" aria-live="polite">
        {messages.map(message=>message.role==="operator"
          ?<div className="chat-message operator" key={message.id}><span>YOU</span><p>{message.text}</p></div>
          :<div className="chat-message varianz" key={message.id}>
            <span>VARIANZ AI</span>
            {message.result?<>
              <div className="recommendation-first"><small>RECOMMENDED NEXT CHECK</small><strong>{message.result.recommendation}</strong></div>
              <p>{message.result.answer}</p>
              <button type="button" className="listen-button" onClick={()=>void playMessage(message)} disabled={speechBusy===message.id}>{speechBusy===message.id?"Generating voice…":speaking===message.id?"■ Stop":"▶ Listen"} · {(message.result.language||"en").toUpperCase()}</button>
              <div className="answer-meta"><span>{message.result.confidence} confidence</span><span>{message.result.model}</span></div>
              {message.result.suggested_actions.length?<><h3>Then check</h3><ol>{message.result.suggested_actions.map((action,index)=><li key={index}>{action}</li>)}</ol></>:null}
              <details><summary>Evidence and limitations</summary><h3>Evidence-backed claims</h3>{message.result.claims.map((claim,index)=><div className="claim" key={index}><p>{claim.text}</p><div className="chips">{claim.evidence_ids.map(id=><span key={id}>{id}</span>)}</div></div>)}{message.result.limitations.length?<div className="limitations"><b>Limitations</b>{message.result.limitations.map((item,index)=><p key={index}>{item}</p>)}</div>:null}</details>
            </>:<p>{message.text}</p>}
          </div>)}
        {asking?<div className="chat-message varianz thinking"><span>VARIANZ AI</span><p>Reviewing current evidence…</p></div>:null}
      </div>
      {speechError?<p className="speech-error">{speechError}</p>:null}
      <LiveVoice onConnect={onLiveConnect}/>
      <form className="chat-composer" onSubmit={event=>{event.preventDefault();ask()}}><textarea value={question} onChange={event=>setQuestion(event.target.value)} placeholder="Ask a follow-up about energy, climate, resources or an anomaly…"/><button className="primary" disabled={asking||question.trim().length<3}>{asking?"Analyzing…":"Send →"}</button></form>
    </article>
    <aside className="panel evidence-drawer"><span>CURRENT EVIDENCE</span><h3>Replay context</h3><p>{date(data.cursor)}</p><h3>Versions</h3><p>{data.data_version}</p><p>{data.model_version}</p><h3>Metric terminology</h3><p>Official Wageningen dataset definitions · {data.definitions_version}</p><h3>Evidence IDs</h3><div className="chips vertical">{data.evidence_ids.map(id=><span key={id}>{id}</span>)}</div></aside>
  </section>;
}
