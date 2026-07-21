import { useEffect, useRef, useState } from "react";
import { ChatMessage, Snapshot } from "../lib/types";
import { date } from "../lib/format";

type AssistantProps = {
  data:Snapshot; question:string; setQuestion:(q:string)=>void;
  messages:ChatMessage[]; asking:boolean; transcribing:boolean;
  ask:(custom?:string,anomalyId?:string)=>void; onVoice:(audio:Blob)=>Promise<void>;
  onSpeak:(text:string,language:"en"|"es")=>Promise<Blob>;
};

function VoiceRecorder({busy,onVoice}:{busy:boolean;onVoice:(audio:Blob)=>Promise<void>}){
  const [recording,setRecording]=useState(false),[error,setError]=useState("");
  const recorderRef=useRef<MediaRecorder|null>(null),streamRef=useRef<MediaStream|null>(null);
  const chunksRef=useRef<Blob[]>([]),timerRef=useRef<ReturnType<typeof setTimeout>|null>(null);
  const startedAtRef=useRef(0);
  const stop=()=>{if(timerRef.current)clearTimeout(timerRef.current);timerRef.current=null;const recorder=recorderRef.current;if(recorder&&recorder.state!=="inactive")recorder.stop()};
  useEffect(()=>()=>{if(timerRef.current)clearTimeout(timerRef.current);const recorder=recorderRef.current;if(recorder&&recorder.state!=="inactive")recorder.stop();streamRef.current?.getTracks().forEach(track=>track.stop())},[]);
  async function toggle(){
    if(recording){stop();return}
    if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==="undefined"){setError("Voice recording is not supported in this browser.");return}
    try{
      setError("");
      const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
      streamRef.current=stream;chunksRef.current=[];
      const candidates=["audio/webm;codecs=opus","audio/mp4;codecs=mp4a.40.2","audio/mp4","audio/ogg;codecs=opus"];
      const mimeType=candidates.find(type=>MediaRecorder.isTypeSupported(type));
      const recorder=new MediaRecorder(stream,mimeType?{mimeType,audioBitsPerSecond:64000}:{audioBitsPerSecond:64000});recorderRef.current=recorder;
      recorder.ondataavailable=event=>{if(event.data.size)chunksRef.current.push(event.data)};
      recorder.onerror=()=>setError("The browser could not encode this recording. Please retry.");
      recorder.onstop=async()=>{
        setRecording(false);stream.getTracks().forEach(track=>track.stop());streamRef.current=null;
        const audio=new Blob(chunksRef.current,{type:recorder.mimeType||"audio/webm"});chunksRef.current=[];
        if(Date.now()-startedAtRef.current<900){setError("Speak for at least one second before stopping.");return}
        if(audio.size)await onVoice(audio);else setError("No audio was captured. Check the microphone and retry.");
      };
      startedAtRef.current=Date.now();recorder.start();setRecording(true);timerRef.current=setTimeout(stop,60000);
    }catch{setError("Microphone access was not granted. Allow it in your browser and try again.")}
  }
  return <div className="voice-control"><button type="button" className={recording?"voice-button recording":"voice-button"} onClick={toggle} disabled={busy&&!recording} aria-label={recording?"Stop and transcribe voice message":"Start voice message"}><span>{recording?"■":"●"}</span>{recording?"Stop":"Talk"}</button><small>{recording?"Listening — tap Stop when finished":busy?"Transcribing voice…":"Ask Varianz by voice · up to 60 seconds"}</small>{error?<em>{error}</em>:null}</div>;
}

export function AssistantView({data,question,setQuestion,messages,asking,transcribing,ask,onVoice,onSpeak}:AssistantProps){
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
            <span>VARIANZ</span>
            {message.result?<>
              <div className="recommendation-first"><small>RECOMMENDED NEXT CHECK</small><strong>{message.result.recommendation}</strong></div>
              <p>{message.result.answer}</p>
              <button type="button" className="listen-button" onClick={()=>void playMessage(message)} disabled={speechBusy===message.id}>{speechBusy===message.id?"Generating voice…":speaking===message.id?"■ Stop":"▶ Listen"} · {(message.result.language||"en").toUpperCase()}</button>
              <div className="answer-meta"><span>{message.result.confidence} confidence</span><span>{message.result.model}</span></div>
              {message.result.suggested_actions.length?<><h3>Then check</h3><ol>{message.result.suggested_actions.map((action,index)=><li key={index}>{action}</li>)}</ol></>:null}
              <details><summary>Evidence and limitations</summary><h3>Evidence-backed claims</h3>{message.result.claims.map((claim,index)=><div className="claim" key={index}><p>{claim.text}</p><div className="chips">{claim.evidence_ids.map(id=><span key={id}>{id}</span>)}</div></div>)}{message.result.limitations.length?<div className="limitations"><b>Limitations</b>{message.result.limitations.map((item,index)=><p key={index}>{item}</p>)}</div>:null}</details>
            </>:<p>{message.text}</p>}
          </div>)}
        {asking?<div className="chat-message varianz thinking"><span>VARIANZ</span><p>Reviewing current evidence…</p></div>:null}
      </div>
      {speechError?<p className="speech-error">{speechError}</p>:null}
      <VoiceRecorder busy={asking||transcribing} onVoice={onVoice}/>
      <form className="chat-composer" onSubmit={event=>{event.preventDefault();ask()}}><textarea value={question} onChange={event=>setQuestion(event.target.value)} placeholder="Ask a follow-up about energy, climate, resources or an anomaly…"/><button className="primary" disabled={asking||transcribing||question.trim().length<3}>{transcribing?"Transcribing…":asking?"Analyzing…":"Send →"}</button></form>
    </article>
    <aside className="panel evidence-drawer"><span>CURRENT EVIDENCE</span><h3>Replay context</h3><p>{date(data.cursor)}</p><h3>Versions</h3><p>{data.data_version}</p><p>{data.model_version}</p><h3>Metric terminology</h3><p>Official Wageningen dataset definitions · {data.definitions_version}</p><h3>Evidence IDs</h3><div className="chips vertical">{data.evidence_ids.map(id=><span key={id}>{id}</span>)}</div></aside>
  </section>;
}
