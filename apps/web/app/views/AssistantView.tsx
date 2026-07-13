import { ChatMessage, Snapshot } from "../lib/types";
import { date } from "../lib/format";

type AssistantProps = {
  data:Snapshot; question:string; setQuestion:(q:string)=>void;
  messages:ChatMessage[]; asking:boolean; ask:(custom?:string,anomalyId?:string)=>void;
};

export function AssistantView({data,question,setQuestion,messages,asking,ask}:AssistantProps){
  return <section className="assistant-layout">
    <article className="panel assistant-main">
      <div className="assistant-title"><span>✦</span><div><b>VARIANZ AI</b><h2>Operator guidance grounded in current evidence</h2></div></div>
      {!messages.length?<div className="assistant-empty"><b>Start a conversation</b><button onClick={()=>ask("What should the operator check first right now?")}>What should I check first?</button><button onClick={()=>ask("Why is heating energy consumption different from the expected baseline?")}>Why is heating energy different from expected?</button><button onClick={()=>ask("Which climate deviation requires attention now?")}>What climate issue requires attention?</button></div>:null}
      <div className="chat-thread" aria-live="polite">
        {messages.map(message=>message.role==="operator"
          ?<div className="chat-message operator" key={message.id}><span>YOU</span><p>{message.text}</p></div>
          :<div className="chat-message varianz" key={message.id}>
            <span>VARIANZ</span>
            {message.result?<>
              <div className="recommendation-first"><small>RECOMMENDED NEXT CHECK</small><strong>{message.result.recommendation}</strong></div>
              <p>{message.result.answer}</p>
              <div className="answer-meta"><span>{message.result.confidence} confidence</span><span>{message.result.model}</span></div>
              {message.result.suggested_actions.length?<><h3>Then check</h3><ol>{message.result.suggested_actions.map((action,index)=><li key={index}>{action}</li>)}</ol></>:null}
              <details><summary>Evidence and limitations</summary><h3>Evidence-backed claims</h3>{message.result.claims.map((claim,index)=><div className="claim" key={index}><p>{claim.text}</p><div className="chips">{claim.evidence_ids.map(id=><span key={id}>{id}</span>)}</div></div>)}{message.result.limitations.length?<div className="limitations"><b>Limitations</b>{message.result.limitations.map((item,index)=><p key={index}>{item}</p>)}</div>:null}</details>
            </>:<p>{message.text}</p>}
          </div>)}
        {asking?<div className="chat-message varianz thinking"><span>VARIANZ</span><p>Reviewing current evidence…</p></div>:null}
      </div>
      <form className="chat-composer" onSubmit={event=>{event.preventDefault();ask()}}><textarea value={question} onChange={event=>setQuestion(event.target.value)} placeholder="Ask a follow-up about energy, climate, resources or an anomaly…"/><button className="primary" disabled={asking||question.trim().length<3}>{asking?"Analyzing…":"Send →"}</button></form>
    </article>
    <aside className="panel evidence-drawer"><span>CURRENT EVIDENCE</span><h3>Replay context</h3><p>{date(data.cursor)}</p><h3>Versions</h3><p>{data.data_version}</p><p>{data.model_version}</p><h3>Metric terminology</h3><p>Official Wageningen dataset definitions · {data.definitions_version}</p><h3>Evidence IDs</h3><div className="chips vertical">{data.evidence_ids.map(id=><span key={id}>{id}</span>)}</div></aside>
  </section>;
}
