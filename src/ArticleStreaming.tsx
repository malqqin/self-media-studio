import {useEffect,useRef,useState} from 'react';
import {LoaderCircle,Radio} from 'lucide-react';
import type {Article} from './types';

export interface LiveDraft {kind:string;partial:Record<string,unknown>;revision:number}
export function useArticleStream(article:Article,onRefresh:()=>Promise<void>){
  const [draft,setDraft]=useState<LiveDraft|null>(null),[reconnecting,setReconnecting]=useState(false);
  const refresh=useRef(onRefresh);refresh.current=onRefresh;
  const running=['queued','running'].includes(article.status);
  useEffect(()=>{
    if(!running)return;
    setDraft(null);setReconnecting(false);
    const stream=new EventSource(`/api/articles/${article.id}/events`);
    stream.onopen=()=>setReconnecting(false);
    stream.addEventListener('snapshot',event=>{
      try{const value=JSON.parse((event as MessageEvent).data);if(value&&typeof value.partial==='object'&&value.partial&&!Array.isArray(value.partial)){setDraft(value);setReconnecting(false);}}catch{/* Ignore a malformed event; saved content still arrives through polling. */}
    });
    stream.addEventListener('complete',()=>{stream.close();void refresh.current().catch(()=>{});});
    stream.onerror=()=>setReconnecting(true);
    return()=>stream.close();
  },[article.id,running]);
  return {draft,reconnecting};
}
const text=(value:unknown)=>typeof value==='string'?value:'';
const list=(value:unknown)=>Array.isArray(value)?value:[];
const object=(value:unknown):Record<string,unknown>=>value&&typeof value==='object'?value as Record<string,unknown>:{};

export function ArticleStreamPanel({draft,reconnecting,failed=false,completed=false,statusText}:{draft:LiveDraft|null;reconnecting:boolean;failed?:boolean;completed?:boolean;statusText?:string}){
  const [follow,setFollow]=useState(true),area=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(follow&&area.current)area.current.scrollTop=area.current.scrollHeight;},[draft,follow]);
  const p=draft?.partial||{},kind=draft?.kind||'';
  const label=kind.includes('repair')?'正在调整成品内容':kind==='article_angles'?'构思写作角度':kind==='article_outline'?'整理文章大纲':kind==='article_rewrite'?'调整选中的内容':kind==='article_check'?'核对文章内容':'撰写文章';
  return <section className="article-live" aria-label="实时生成内容">
    <div className="article-live-heading"><span role="status">{failed||completed?<Radio size={16}/>:<LoaderCircle className="spin" size={16}/>}<strong>{failed?'本次未完成 · 临时输出仅供参考':completed?'本次实时输出':statusText||label}</strong></span>{!failed&&!completed&&<label><input type="checkbox" checked={follow} onChange={e=>setFollow(e.target.checked)}/>跟随输出</label>}</div>
    <p className="article-live-hint">{reconnecting?'正在重新连接实时输出，后台创作会继续。':failed?'已保存的内容和历史版本仍然保留。':completed?'处理已结束，保存结果可在工作台查看。':'模型返回的文字会实时显示，完成校验后保存。'}</p>
    <div className="article-live-copy" ref={area} tabIndex={0}>
      {!Object.keys(p).length&&<p className="inline-hint">{failed?'本次没有可展示的实时输出。':completed?'本次没有保留实时输出，请查看工作台中的保存结果。':'等待模型返回文字…'}</p>}
      {text(p.title)&&<h3>{text(p.title)}</h3>}{text(p.summary)&&<p>{text(p.summary)}</p>}{text(p.opening)&&<p>{text(p.opening)}</p>}
      {list(p.choices).map((v,i)=>{const c=object(v);return <div key={i}><h4>{text(c.title)}</h4><p>{text(c.angle)}</p><small>{text(c.reason)}</small></div>;})}
      {text(p.angle)&&<p>{text(p.angle)}</p>}
      {list(p.sections).map((v,i)=>{const s=object(v);return <div key={i}><h4>{text(s.heading)}</h4>{text(s.points)&&<p>{text(s.points)}</p>}{list(s.paragraphs).map((v,j)=><p key={j}>{text(v)}</p>)}</div>;})}
      {text(p.heading)&&<h4>{text(p.heading)}</h4>}{list(p.paragraphs).map((v,i)=><p key={i}>{text(v)}</p>)}
      {text(p.text)&&<p className="live-rewrite-text">{text(p.text)}</p>}{text(p.closing)&&<p>{text(p.closing)}</p>}
      {list(p.issues).map((v,i)=><p key={i}>{text(object(v).message)}</p>)}{text(p.note)&&<p>{text(p.note)}</p>}
    </div>
  </section>;
}
