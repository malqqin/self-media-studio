import {useEffect,useState} from 'react';
import {Pencil,Save,Sparkles,LoaderCircle} from 'lucide-react';
import {api,send} from './api';
import type {Article,ArticleAngle} from './types';

export default function ArticleAngles({article,blocked,onChoose,onDirty,onRefresh,onError,onNotice}:{article:Article;blocked:boolean;onChoose:(index:number)=>void;onDirty:(value:boolean)=>void;onRefresh:()=>Promise<void>;onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const [editing,setEditing]=useState<number|null>(null),[form,setForm]=useState<ArticleAngle|null>(null),[target,setTarget]=useState<number|'all'|null>(null),[instruction,setInstruction]=useState(''),[saving,setSaving]=useState(false),[baseVersion,setBaseVersion]=useState(article.version);
  const choices=article.angles?.choices||[];
  const changed=editing!==null&&JSON.stringify(form)!==JSON.stringify(choices[editing])||!!instruction.trim();
  useEffect(()=>{onDirty(changed);},[changed]);
  useEffect(()=>()=>onDirty(false),[]);
  const locked=blocked||saving;
  const save=async()=>{setSaving(true);try{await api(`/articles/${article.id}/angles`,send('PUT',{version:baseVersion,choice:editing,angle:form}));setEditing(null);setForm(null);onDirty(false);await onRefresh();onNotice('写作角度已保存。选用它可重新生成大纲。');}catch(e){onError((e as Error).message);}finally{setSaving(false);}};
  const regenerate=async()=>{setSaving(true);try{await api(`/articles/${article.id}/angles/regenerate`,send('POST',{version:baseVersion,choice:target==='all'?null:target,instruction}));setTarget(null);setInstruction('');onDirty(false);await onRefresh();onNotice('正在重新生成写作角度，现有大纲和正文保留。');}catch(e){onError((e as Error).message);}finally{setSaving(false);}};
  return <section className="angle-workspace"><div className="angle-toolbar"><p>先选一个切入点，也可以编辑或让 AI 换个思路。</p><button className="ss-btn" disabled={locked||editing!==null||target!==null} onClick={()=>{setBaseVersion(article.version);setTarget('all');}}><Sparkles/>重新生成一组角度</button></div>
    {target!==null&&<div className="angle-ai-form"><label className="field">{target==='all'?'整组角度调整要求':`第 ${target+1} 个角度调整要求`}<textarea aria-label="角度调整要求" rows={3} maxLength={2000} disabled={locked} value={instruction} onChange={e=>setInstruction(e.target.value)} placeholder="例如：从普通人的真实疑问切入，标题直白一些"/></label><p className="inline-hint">生成完成后再选用；当前大纲与正文会保留。</p><div className="article-actions"><button className="ss-btn ss-primary" disabled={locked} onClick={regenerate}>{saving?<LoaderCircle className="spin"/>:<Sparkles/>}开始重新生成</button><button className="ss-btn" disabled={locked} onClick={()=>{setTarget(null);setInstruction('');}}>取消调整</button></div></div>}
    <div className="angle-grid">{choices.map((angle,index)=><article className={'angle-item'+(article.input_data.angle_index===index?' is-selected':'')} key={index}>
      {editing===index&&form?<div className="angle-edit-form"><fieldset className="article-fields" disabled={locked}><label className="field">角度标题<input maxLength={100} value={form.title} onChange={e=>setForm({...form,title:e.target.value})}/></label><label className="field">切入思路<textarea rows={4} maxLength={600} value={form.angle} onChange={e=>setForm({...form,angle:e.target.value})}/></label><label className="field">读者价值<textarea rows={3} maxLength={600} value={form.reason} onChange={e=>setForm({...form,reason:e.target.value})}/></label><div className="article-actions"><button className="ss-btn ss-primary" disabled={!form.title.trim()||form.angle.trim().length<5||form.reason.trim().length<5} onClick={save}><Save/>保存角度</button><button className="ss-btn" onClick={()=>{setEditing(null);setForm(null);}}>取消编辑</button></div></fieldset></div>:<>
        <button className="angle-card" disabled={locked||editing!==null||target!==null} aria-pressed={article.input_data.angle_index===index} onClick={()=>onChoose(index)}><span className="fn-label">ANGLE 0{index+1}</span><strong>{angle.title}</strong><p>{angle.angle}</p><small>{angle.reason}</small><span className="angle-action">{article.outline&&article.input_data.angle_index===index&&!article.input_data._angle_outline_stale?'已选角度 · 返回当前大纲 →':article.outline?'选用并重新生成大纲 →':'用这个角度写大纲 →'}</span></button>
        <div className="angle-item-actions"><button className="text-button" disabled={locked||editing!==null||target!==null} onClick={()=>{setBaseVersion(article.version);setEditing(index);setForm({...angle});}}><Pencil size={14}/>编辑角度 {index+1}</button><button className="text-button" disabled={locked||editing!==null||target!==null} onClick={()=>{setBaseVersion(article.version);setTarget(index);}}><Sparkles size={14}/>AI 重生成角度 {index+1}</button></div>
      </>}
    </article>)}</div>
  </section>;
}
