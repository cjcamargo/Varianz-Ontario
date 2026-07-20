import { Point, SeriesSpec } from "../lib/types";
import { fmt, date } from "../lib/format";

export function Card({label,value,unit,meta,tone="green",digits=1,badge}:{label:string;value:number|null|undefined;unit:string;meta:string;tone?:string;digits?:number;badge?:string}){
  return <article className={`metric-card ${tone}`}><div className="metric-top"><span>{label}</span>{badge?<em>{badge}</em>:<i/>}</div><strong>{fmt(value,digits)} <small>{unit}</small></strong><p>{meta}</p></article>
}

export function LineChart({points,series,bands,height=360,qualityRegions=false}:{points:Point[];series:SeriesSpec[];bands?:[number,number];height?:number;qualityRegions?:boolean}){
  const width=900,pad={left:58,right:58,top:42,bottom:38};
  const values=(axis:number)=>series.filter(s=>(s.axis||0)===axis).flatMap(s=>points.map(p=>p[s.key]).filter((v):v is number=>typeof v==="number"));
  const domain=(axis:number)=>{const v=values(axis);if(!v.length)return [0,1];let lo=Math.min(...v),hi=Math.max(...v);if(axis===0&&bands){lo=Math.min(lo,bands[0]);hi=Math.max(hi,bands[1])}const d=Math.max((hi-lo)*.1,.5);return [lo-d,hi+d]};
  const [lo,hi]=domain(0),[lo2,hi2]=domain(1),innerW=width-pad.left-pad.right,innerH=height-pad.top-pad.bottom;
  const y=(v:number,axis=0)=>pad.top+innerH-(v-(axis?lo2:lo))/Math.max((axis?hi2:hi)- (axis?lo2:lo),.001)*innerH;
  const x=(i:number)=>pad.left+i/Math.max(points.length-1,1)*innerW;
  const ticks=Array.from({length:5},(_,i)=>lo+(hi-lo)*i/4);
  const path=(s:SeriesSpec)=>{let drawing=false;return points.map((p,i)=>{const value=p[s.key];if(typeof value!=="number"){drawing=false;return ""}const command=drawing?"L":"M";drawing=true;return `${command}${x(i).toFixed(1)},${y(value,s.axis||0).toFixed(1)}`}).join(" ")};
  const provisionalIndex=qualityRegions?points.findIndex(point=>point.quality==="provisional"):-1;
  if(!points.length)return <div className="no-data">No observations in this replay window.</div>;
  return <div className="line-chart"><div className="chart-legend">{series.map(s=><span key={s.key}><i style={s.dashed?{borderTop:`2px dashed ${s.color}`,background:"transparent"}:{background:s.color}}/>{s.name}</span>)}</div><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={series.map(s=>s.name).join(" compared with ")}>
    {provisionalIndex>=0?<><rect x={x(provisionalIndex)} y={pad.top} width={Math.max(0,width-pad.right-x(provisionalIndex))} height={innerH} fill="#f0b45a0c"/><line x1={x(provisionalIndex)} x2={x(provisionalIndex)} y1={pad.top} y2={height-pad.bottom} stroke="#f0b45a" strokeDasharray="4 5"/><text x={x(provisionalIndex)+7} y={pad.top+13} fill="#f0b45a">PROVISIONAL</text></>:null}
    {bands?<rect x={pad.left} y={y(bands[1])} width={innerW} height={Math.max(0,y(bands[0])-y(bands[1]))} fill="#63e6a510"/>:null}
    {ticks.map((t,i)=><g key={i}><line x1={pad.left} x2={width-pad.right} y1={y(t)} y2={y(t)} stroke="#1d332b"/><text x={pad.left-8} y={y(t)+4} textAnchor="end">{t.toFixed(1)}</text></g>)}
    <line x1={pad.left} x2={pad.left} y1={pad.top} y2={height-pad.bottom} stroke="#355047"/><line x1={pad.left} x2={width-pad.right} y1={height-pad.bottom} y2={height-pad.bottom} stroke="#355047"/>
    {series.map(s=><path key={s.key} d={path(s)} fill="none" stroke={s.color} strokeWidth="2.2" strokeDasharray={s.dashed?"7 6":undefined}><title>{s.name}</title></path>)}
    <text x={pad.left} y={height-9}>{date(points[0].time)}</text><text x={width-pad.right} y={height-9} textAnchor="end">{date(points[points.length-1].time)}</text>
  </svg></div>
}
