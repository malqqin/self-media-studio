import {useOutcomeNotice,useNotifications} from './Notifications';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, CheckCircle2, Clapperboard, Download, ExternalLink, FilePenLine, LoaderCircle, Play, RotateCcw, Save, Upload, X } from 'lucide-react';
import { api, dateText, fileUrl, send, timeText } from './api';
import type { Asset, Job, Script } from './types';
import { statuses } from './App';

interface Props {jobs:Job[];selectedId:string;onSelect:(id:string)=>void;onRefresh:()=>Promise<unknown>;onError:(e:string)=>void;onNotice:(e:string)=>void;onExplore:()=>void;onDirty?:(v:boolean)=>void}
export default function ReviewPage({jobs,selectedId,onSelect,onRefresh,onError,onNotice,onExplore,onDirty}:Props){
  const active=jobs.find(j=>j.id===selectedId)||jobs[0];
  const [detail,setDetail]=useState<Job|null>(null),[busy,setBusy]=useState(false),[editing,setEditing]=useState(false);
  const [facts,setFacts]=useState(false),[rights,setRights]=useState(false),[note,setNote]=useState(''),[scene,setScene]=useState(0);
  useEffect(()=>{onDirty?.(editing);return()=>onDirty?.(false);},[editing,onDirty]);
  const player=useRef<HTMLVideoElement>(null);
  const load=async()=>{if(active){const value=await api<Job>(`/jobs/${active.id}`);setDetail(value);return value;}};
  useEffect(()=>{let valid=true;if(active)api<Job>(`/jobs/${active.id}`).then(d=>{if(valid)setDetail(d);}).catch(e=>onError(e.message));else setDetail(null);return()=>{valid=false;};},[active?.id,active?.updated_at]);
  useEffect(()=>{setFacts(false);setRights(false);setNote('');setScene(0);setEditing(false);},[active?.id,active?.version]);
  const job=detail?.id===active?.id?detail:active;
  const act=async(path:string,body?:unknown)=>{setBusy(true);try{await api(`/jobs/${job.id}/${path}`,send('POST',body));await onRefresh();await load();onNotice(path==='review'?'审核结果已保存。':'任务已加入制作队列。');}catch(e){onError((e as Error).message);}finally{setBusy(false);}};
  const seek=(index:number)=>{setScene(index);const start=job.manifest?.timeline[index]?.start;if(player.current&&start!==undefined){player.current.currentTime=start;}};
  const showOutcomeError=useOutcomeNotice(job?.id||'',job?.status,job?.error,job?.updated_at,'视频已生成，可以预览与审核。');
  const playing=job?.status==='running'||job?.status==='queued';
  const canReview=job?.status==='needs_review'||job?.status==='approved';
  return <section><div className="ss-heading"><div><h1>故事成片，等你过目。</h1><p>十秒画面，一两句标题。检查内容与出处，再把成片带走。</p></div><span className="ss-badge">{jobs.length} 个制作任务</span></div>
    {!job?<div className="empty"><Clapperboard/><h2>第一场放映，从一个选题开始。</h2><p>图片或视频组成的 10 秒短片，会在这里等你。</p><button className="ss-btn ss-primary" onClick={onExplore}>去选一题 <ArrowRight/></button></div>:<>
      <div className="job-picker"><label htmlFor="job-select">制作手记</label><select id="job-select" value={job.id} onChange={e=>onSelect(e.target.value)}>{jobs.map(j=><option key={j.id} value={j.id}>{j.script?.title||j.topic_id} · {statuses[j.status]}</option>)}</select><span>第 {job.version} 版</span></div>
      {playing&&<div className="production-progress" role="status"><div><LoaderCircle className="spin"/><strong>{job.note||'准备开始制作…'}</strong><span>{job.progress}%</span></div><progress value={job.progress} max="100"/><p>可切换到其他页面；任务在本地后台执行。</p></div>}
      {job.error&&<button className="text-button error-detail-button" onClick={showOutcomeError}>查看视频制作失败原因</button>}
      <div className="ss-review"><div className="ss-review-player">{job.artifacts?.video?<video ref={player} key={`${job.id}-${job.version}`} className="real-video" controls preload="metadata" poster={fileUrl(job.id,'cover',job.version)} src={fileUrl(job.id,'video',job.version)} onTimeUpdate={()=>{const time=player.current?.currentTime||0;const index=job.manifest?.timeline.findIndex(t=>time>=t.start&&time<t.end);if(index!==undefined&&index>=0)setScene(index);}}/>:<div className="video-empty"><BirdMark/><span>{playing?'好故事，正在路上。':'还没有这一版的成片。'}</span><small>9:16 · 10 秒 · 无配音</small></div>}
        <div className="video-meta"><span>{job.qa?timeText(job.qa.duration_seconds):'10 秒'}</span><span>{job.settings.resolution} · 竖屏</span></div>
        {job.artifacts&&<div className="file-links">{job.artifacts.subtitle&&<a href={fileUrl(job.id,'subtitle',job.version)}><Download/>旧版字幕</a>}<a href={fileUrl(job.id,'script',job.version)}><Download/>文案</a><a href={fileUrl(job.id,'manifest',job.version)}><ExternalLink/>出处清单</a></div>}
      </div><div className="ss-review-content"><span className={`ss-badge ${job.status==='approved'?'ss-green':'ss-amber'}`}>{statuses[job.status]}</span><h2>{job.script?.title||'正在准备短标题'}</h2>
        {job.script&&<>{job.script.title_lines&&<div className="short-title-preview">{job.script.title_lines.map((line,i)=><p key={i}>{line}</p>)}</div>}<div className="ss-section-label">画面与依据 <button className="text-button" disabled={playing} onClick={()=>setEditing(true)}><FilePenLine/>编辑文案与画面</button></div><div className="ss-shots">{job.script.scenes.map((shot,i)=><div key={i}><button className="ss-shot" onClick={()=>seek(i)} aria-pressed={scene===i}><time>{timeText(job.manifest?.timeline[i]?.start||0)}</time><span><strong>{shot.heading}</strong><small>{job.manifest?.timeline[i]?`${timeText(job.manifest.timeline[i].start)} — ${timeText(job.manifest.timeline[i].end)}`:'平均分配时长'} · {shot.asset_id?'相关图片 / 视频':'原创示意'}</small></span><Play className="shot-play"/></button>{scene===i&&<div className="evidence"><span>对应原文</span><blockquote>{shot.evidence}</blockquote>{job.source_data?.filter(s=>s.id===shot.source_id).map(s=><a key={s.id} href={s.url} target="_blank" rel="noreferrer">{s.publisher} · {s.title}<ExternalLink/></a>)}</div>}</div>)}</div></>}
        {job.qa&&<div className="quality-summary"><CheckCircle2/><span>{job.qa.passed?'技术质检通过':'技术质检需要处理'} · {job.qa.duration_seconds.toFixed(1)} 秒 · {job.qa.audio_present?'旧版有音轨':'静音 · 无配音'} · {job.qa.black_frames} 处黑帧</span></div>}
        {canReview&&job.status!=='approved'&&<><div className="ss-review-checks"><label className="ss-check"><input type="checkbox" checked={facts} onChange={e=>setFacts(e.target.checked)}/>标题文案与原始资料一致</label><label className="ss-check"><input type="checkbox" checked={rights} onChange={e=>setRights(e.target.checked)}/>素材使用权、署名与画面含义已核对</label></div><label className="field">修改意见 <textarea value={note} onChange={e=>setNote(e.target.value)} placeholder="需要修改的标题、素材或画面顺序…" rows={2} maxLength={2000}/></label><div className="ss-actions"><button className="ss-btn" disabled={busy||!note.trim()} onClick={()=>act('review',{decision:'revise',version:job.version,facts_checked:facts,rights_checked:rights,note})}>退回修改</button><button className="ss-btn ss-primary" disabled={busy||!facts||!rights} onClick={()=>act('review',{decision:'approve',version:job.version,facts_checked:facts,rights_checked:rights,note})}>通过审核</button></div></>}
        {job.status==='approved'&&<div className="approved"><CheckCircle2/><p>这一版已通过审核，可以带走成片了。</p><a className="ss-btn ss-primary" href={fileUrl(job.id,'bundle',job.version)}><Download/>下载成片包</a></div>}
        {['failed','draft','changes_requested'].includes(job.status)&&<div className="ss-actions"><button className="ss-btn ss-primary" disabled={busy} onClick={()=>act('retry')}><RotateCcw/>{job.script?'用当前文案与画面重新制作':'重试制作'}</button></div>}
      </div></div>
      <details className="task-log"><summary>查看制作过程 · {dateText(job.created_at)}</summary>{job.events?.map(event=><div key={event.id}><time>{dateText(event.at)}</time><span>{event.message}</span></div>)}</details>
      {editing&&job.script&&<ScriptEditor job={job} onClose={()=>setEditing(false)} onSaved={async()=>{await onRefresh();await load();setEditing(false);onNotice('文案与画面已保存，请重新制作 10 秒短片。');}} onError={onError}/>}
    </>}
  </section>;
}
function BirdMark(){return <span className="bird-mark">知</span>;}

function ScriptEditor({job,onClose,onSaved,onError}:{job:Job;onClose:()=>void;onSaved:()=>Promise<void>;onError:(s:string)=>void}){
  const [script,setScript]=useState<Script>(()=>({...structuredClone(job.script!),title_lines:job.script!.title_lines||[job.script!.title.slice(0,28)],scenes:job.script!.scenes.slice(0,5).map(s=>({...s,clip_start:s.clip_start||0}))}));
  const [assets,setAssets]=useState<Asset[]>([]),[busy,setBusy]=useState(false);const {error:setError}=useNotifications();
  const [rights,setRights]=useState(''),[credit,setCredit]=useState('');
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    const dialog=document.querySelector<HTMLElement>('.editor')!;
    dialog.querySelector<HTMLElement>('button,input')?.focus();
    const key=(event:KeyboardEvent)=>{
      if(event.key==='Escape'&&!busy){onClose();return;}
      if(event.key==='Tab'){
        const items=[...dialog.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea,select,summary,a[href]')].filter(el=>el.getClientRects().length);
        const first=items[0],last=items[items.length-1];
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
      }
    };
    document.addEventListener('keydown',key);const old=document.body.style.overflow;document.body.style.overflow='hidden';
    return()=>{document.removeEventListener('keydown',key);document.body.style.overflow=old;previous?.focus();};
  },[busy]);
  useEffect(()=>{api<Asset[]>('/assets').then(setAssets).catch(e=>setError(e.message));},[]);
  const save=async()=>{setBusy(true);setError('');try{await api(`/jobs/${job.id}/script`,send('PUT',{version:job.version,script}));await onSaved();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  const upload=async(file:File)=>{setBusy(true);setError('');try{const form=new FormData();form.set('file',file);form.set('rights',rights);form.set('credit',credit);await api('/assets',{method:'POST',body:form});setAssets(await api<Asset[]>('/assets'));}catch(e){setError((e as Error).message);onError((e as Error).message);}finally{setBusy(false);}};
  const patch=(index:number,field:string,value:string|number)=>setScript(s=>({...s,scenes:s.scenes.map((scene,i)=>i===index?{...scene,[field]:value}:scene)}));
  const move=(i:number,delta:number)=>setScript(s=>{const scenes=[...s.scenes];[scenes[i],scenes[i+delta]]=[scenes[i+delta],scenes[i]];return {...s,scenes};});
  return <div className="editor-overlay"><section className="editor" role="dialog" aria-modal="true" aria-labelledby="editor-title"><div className="editor-heading"><div><h2 id="editor-title">十秒，也可以很精彩。</h2></div><button className="icon-button" onClick={onClose} aria-label="关闭编辑" disabled={busy}><X/></button></div>
    <p className="inline-hint">1–2 句短标题贯穿全片，1–5 个画面平分 10 秒，不生成配音。保存会生成新版本，需重新制作和审核。</p>
    <label className="field">视频标题<input value={script.title} maxLength={60} onChange={e=>setScript(s=>({...s,title:e.target.value}))}/></label>
    <div className="title-editor">{script.title_lines.map((line,i)=><label className="field" key={i}>画面标题 {i+1}<div className="title-input"><input value={line} maxLength={28} onChange={e=>setScript(s=>({...s,title_lines:s.title_lines.map((v,n)=>n===i?e.target.value:v)}))}/>{i===1&&<button className="text-button" onClick={()=>setScript(s=>({...s,title_lines:s.title_lines.slice(0,1)}))}>移除</button>}</div><small>{line.length} / 28 字</small></label>)}{script.title_lines.length===1&&<button className="text-button" onClick={()=>setScript(s=>({...s,title_lines:[...s.title_lines,'']}))}>+ 添加第二句标题</button>}</div>
    {script.scenes.map((scene,i)=>{const asset=assets.find(a=>a.id===scene.asset_id);return <fieldset className="scene-editor" key={i}><legend>画面 {i+1} · 约 {(10/script.scenes.length).toFixed(1)} 秒</legend><div className="scene-tools"><button className="text-button" disabled={i===0} onClick={()=>move(i,-1)}>上移</button><button className="text-button" disabled={i===script.scenes.length-1} onClick={()=>move(i,1)}>下移</button><button className="text-button" disabled={script.scenes.length===1} onClick={()=>setScript(s=>({...s,scenes:s.scenes.filter((_,n)=>n!==i)}))}>删除画面</button></div>
      <label className="field">画面备注（不叠加到成片）<input value={scene.heading} maxLength={32} onChange={e=>patch(i,'heading',e.target.value)}/></label>
      <label className="field">图片或视频<select value={scene.asset_id} onChange={e=>patch(i,'asset_id',e.target.value)}><option value="">{job.mode==='sample'?'内置画面 / 原创示意':'自动匹配来源图片'}</option>{assets.map(a=><option key={a.id} value={a.id}>{a.media_type.startsWith('video/')?'视频':'图片'} · {a.filename}</option>)}</select></label>
      {asset&&<div className="asset-preview">{asset.media_type.startsWith('video/')?<video controls muted preload="metadata" src={`/api/assets/${asset.id}/file`}/>:<img src={`/api/assets/${asset.id}/file`} alt={asset.filename}/>}<small>{asset.credit} · {asset.rights}</small></div>}
      {asset?.media_type.startsWith('video/')&&<label className="field">视频截取起点（秒）<input type="number" min={0} max={600} step={0.1} value={scene.clip_start} onChange={e=>patch(i,'clip_start',Number(e.target.value))}/><small>去掉原声；剩余片段太短时，定格最后一帧补足时长。</small></label>}
      {!scene.asset_id&&<label className="field">示意模板<select value={scene.visual} onChange={e=>patch(i,'visual',e.target.value)}><option value="orbit">轨道</option><option value="spectrum">波段</option><option value="particle">粒子</option><option value="question">通用科学</option></select></label>}
      <details><summary>文案依据</summary><label className="field">资料来源<select value={scene.source_id} onChange={e=>patch(i,'source_id',e.target.value)}>{job.source_data.map(s=><option key={s.id} value={s.id}>{s.publisher} · {s.title}</option>)}</select></label><label className="field">原文引文<textarea rows={2} value={scene.evidence} onChange={e=>patch(i,'evidence',e.target.value)}/></label></details>
    </fieldset>;})}
    {script.scenes.length<5&&<button className="ss-btn" onClick={()=>setScript(s=>({...s,scenes:[...s.scenes,{...s.scenes[s.scenes.length-1],heading:'新画面',asset_id:'',clip_start:0}]}))}>+ 添加画面</button>}
    <details className="upload-area"><summary><Upload/>添加图片或视频素材</summary><div className="field-pair"><label className="field">使用权来源<input value={rights} onChange={e=>setRights(e.target.value)} placeholder="如：本人拍摄，允许本账号使用"/></label><label className="field">画面署名<input value={credit} maxLength={120} onChange={e=>setCredit(e.target.value)} placeholder="作者 / 机构"/></label></div><label className="field">选择素材（图片 ≤20 MB，视频 ≤100 MB）<input type="file" accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm,.mov" disabled={busy||rights.trim().length<4} onChange={e=>{if(e.target.files?.[0])upload(e.target.files[0]);}}/></label><p className="inline-hint">支持 MP4、MOV、WebM，最长 10 分钟。上传后在上方选择；图片和视频均保留完整比例。</p></details>
    <div className="editor-actions"><button className="ss-btn" onClick={onClose} disabled={busy}>取消</button><button className="ss-btn ss-primary" onClick={save} disabled={busy||script.title_lines.some(l=>!l.trim())}>{busy?<LoaderCircle className="spin"/>:<Save/>}保存新版本</button></div>
  </section></div>;
}
