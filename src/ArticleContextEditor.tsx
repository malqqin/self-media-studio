import {useEffect,useState} from 'react';
import {Link,LoaderCircle,Search,Sparkles,Save} from 'lucide-react';
import {api,send} from './api';
import CollectedSources from './CollectedSources';
import type {Article,TaskRun,Topic} from './types';

type Action='save'|'angles'|'outline'|'article';
const actionLabels:Record<Action,string>={save:'保存选题与资料',angles:'重新生成写作角度',outline:'按新选题重建大纲',article:'按新选题重写全文'};
const actionHints:Record<Action,string>={save:'保存本次选题和资料，保留当前大纲与正文。',angles:'生成一组新角度，选好后继续写大纲。原稿保留在历史版本中。',outline:'按新主题重新构思角度和大纲，完成后由你确认再写正文。',article:'按新主题重新构思角度、大纲与全文；生成成功后替换当前稿件，旧稿保留在历史版本中。'};

export default function ArticleContextEditor({article,run,topics,onSaved,onDirty,onBusy,onError,onNotice,blocked}:{article:Article;run:TaskRun;topics?:Topic[];onSaved:(article:Article,generated:boolean)=>void;onDirty:(dirty:boolean)=>void;onBusy:(busy:boolean)=>void;onError:(message:string)=>void;onNotice:(message:string)=>void;blocked:boolean}){
  const input=article.input_data,materials=run.settings.materials,plan=run.settings._editorial_plan;
  const [form,setForm]=useState(()=>({subject:String(input._subject??plan?.subject??''),brief:String(input.brief??run.settings.brief??''),mode:article.mode,notes:String(input.notes||''),topic_ids:(input.topic_ids as string[]||[]),query:String(input.query??plan?.query??materials.query??''),search_scope:String(input.search_scope??materials.search_scope??'wechat'),max_age_days:Number(input.max_age_days??materials.max_age_days??30)}));
  const [initial]=useState(()=>JSON.stringify(form));
  const [action,setAction]=useState<Action>('save'),[available,setAvailable]=useState<Topic[]>(topics||[]),[filter,setFilter]=useState(''),[url,setUrl]=useState(''),[manual,setManual]=useState(false),[sourceTitle,setSourceTitle]=useState(''),[sourceText,setSourceText]=useState(''),[busy,setBusy]=useState(''),[reports,setReports]=useState<TaskRun['reports']>([]);
  const changed=JSON.stringify(form)!==initial||!!url||!!sourceTitle||!!sourceText;
  useEffect(()=>{onDirty(changed);return()=>onDirty(false);},[changed,onDirty]);
  useEffect(()=>{onBusy(!!busy);return()=>onBusy(false);},[busy,onBusy]);
  useEffect(()=>{let live=true;api<Topic[]>('/topics').then(values=>{if(live)setAvailable(old=>[...new Map([...old,...values].map(t=>[t.id,t])).values()]);}).catch(e=>onError(e.message));return()=>{live=false;};},[]);
  const patch=(change:Partial<typeof form>)=>setForm(old=>({...old,...change}));
  const locked=blocked||!!busy;
  const collect=async()=>{setBusy('collect');try{
    const result=await api<{topics:Topic[];reports:TaskRun['reports']}>(`/articles/${article.id}/context/collect`,send('POST',{version:article.version,brief:[form.subject,form.brief].filter(Boolean).join('\n'),query:form.query,search_scope:form.search_scope,max_age_days:form.max_age_days}));
    setAvailable(old=>[...new Map([...result.topics,...old].map(t=>[t.id,t])).values()]);setReports(result.reports);
    const failures=result.reports.filter(r=>r.status==='error');if(failures.length)onError(failures.map(r=>r.message).join('；'));else onNotice(`搜索完成，取得 ${result.topics.length} 篇资料，请勾选本次要使用的文章。`);
  }catch(e){onError((e as Error).message);}finally{setBusy('');}};
  const importSource=async()=>{setBusy('import');try{
    let topic:Topic;
    if(manual){const result=await api<{topic_id:string}>('/sources/import',send('POST',{url,title:sourceTitle,text:sourceText}));const values=await api<Topic[]>('/topics');const imported=values.find(t=>t.id===result.topic_id);if(!imported)throw new Error('资料已导入，请刷新素材列表后选择。');topic=imported;}
    else topic=await api<Topic>('/article-sources/link',send('POST',{url}));
    setAvailable(old=>[topic,...old.filter(t=>t.id!==topic.id)]);patch({topic_ids:[...new Set([...form.topic_ids,topic.id])]});setUrl('');setSourceText('');setSourceTitle('');onNotice('文章已导入并选中，保存后用于本次创作。');
  }catch(e){onError((e as Error).message);}finally{setBusy('');}};
  const save=async()=>{setBusy('save');try{
    const saved=await api<Article>(`/articles/${article.id}/context`,send('PUT',{...form,version:article.version,action}));onDirty(false);onSaved(saved,action!=='save');onNotice(action==='save'?'本次选题与资料已保存，当前正文保留。':'已按新选题开始创作，可在悬浮进度中查看。原稿保留在历史版本中。');
  }catch(e){onError((e as Error).message);}finally{setBusy('');}};
  const choices=[...available].sort((a,b)=>Number(form.topic_ids.includes(b.id))-Number(form.topic_ids.includes(a.id)));
  return <div className="article-context-editor">
    <p className="context-scope-note">只调整这次作品。任务的长期方向、定时计划和已交付的公众号稿件保持原样。</p>
    {blocked&&<p className="context-blocked" role="status">请先保存工作区中的修改，并等待当前创作或公众号交付完成。</p>}
    <fieldset className="article-fields" disabled={locked}>
      <label className="field">本次选题<input maxLength={160} value={form.subject} onChange={e=>patch({subject:e.target.value})} placeholder="例如：从古建筑细节认识平遥"/></label>
      <label className="field">本次写作要求<textarea rows={4} maxLength={2000} value={form.brief} onChange={e=>patch({brief:e.target.value})} placeholder="想表达什么、希望从哪个角度写？"/></label>
      <label className="field">本次创作方式<select aria-label="本次创作方式" value={form.mode} onChange={e=>patch({mode:e.target.value as Article['mode']})}><option value="original">从零构思</option><option value="reference">热点 / 资料参考</option></select></label>
      <label className="field">个人观点与参考笔记<textarea rows={3} maxLength={20000} value={form.notes} onChange={e=>patch({notes:e.target.value})}/></label>
      <details className="context-materials" open><summary>本次参考资料 · 已选 {form.topic_ids.length}/5</summary>
        <label className="field">筛选已有资料<input value={filter} onChange={e=>setFilter(e.target.value)} placeholder="按标题查找"/></label>
        <div className="article-source-picker context-source-picker">{choices.filter(t=>t.title.includes(filter)).map(t=><label key={t.id}><input type="checkbox" checked={form.topic_ids.includes(t.id)} disabled={locked||form.topic_ids.length>=5&&!form.topic_ids.includes(t.id)} onChange={()=>patch({topic_ids:form.topic_ids.includes(t.id)?form.topic_ids.filter(id=>id!==t.id):[...form.topic_ids,t.id]})}/><span>{t.title}<small>{t.source} · {t.page_data?.full_text?'完整正文':'资料摘要'}</small></span></label>)}{form.topic_ids.filter(id=>!available.some(t=>t.id===id)).map(id=><label key={id}><input type="checkbox" checked onChange={()=>patch({topic_ids:form.topic_ids.filter(value=>value!==id)})}/><span>已选资料 {id}<small>资料可能已移除，可取消选用后重新导入</small></span></label>)}{!available.length&&<p className="inline-hint">可以重新搜索或导入文章链接。</p>}</div>
      </details>
      <details className="context-materials"><summary><Search size={14}/>重新联网找资料</summary>
        <label className="field">本次搜索关键词<input value={form.query} maxLength={100} onChange={e=>patch({query:e.target.value})}/></label>
        <div className="context-search-options"><label className="field">资料平台<select aria-label="资料平台" value={form.search_scope} onChange={e=>patch({search_scope:e.target.value})}><option value="wechat">微信公众号</option><option value="web">公开网页</option></select></label><label className="field">发布时间<select aria-label="发布时间" value={form.max_age_days} onChange={e=>patch({max_age_days:Number(e.target.value)})}>{[[0,'不限时间'],[7,'最近 7 天'],[30,'最近 30 天'],[90,'最近 90 天'],[365,'最近一年']].map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label></div>
        <button type="button" className="ss-btn" disabled={locked||form.query.trim().length<2||!form.subject.trim()&&!form.brief.trim()} onClick={collect}>{busy==='collect'?<LoaderCircle className="spin"/>:<Search/>}搜索本次资料</button>
      </details>
      <details className="context-materials"><summary><Link size={14}/>导入新的文章</summary>
        <label className="field">参考文章链接<input type="url" value={url} maxLength={2000} onChange={e=>setUrl(e.target.value)} placeholder="公众号或公开文章链接"/></label>
        <label className="article-check-label"><input type="checkbox" checked={manual} onChange={e=>setManual(e.target.checked)}/>网页无法读取时，粘贴原文</label>
        {manual&&<><label className="field">参考文章标题<input maxLength={240} value={sourceTitle} onChange={e=>setSourceTitle(e.target.value)}/></label><label className="field">参考文章正文<textarea rows={5} maxLength={60000} value={sourceText} onChange={e=>setSourceText(e.target.value)}/></label></>}
        <button type="button" className="ss-btn" disabled={locked||!url.trim()||form.topic_ids.length>=5||manual&&(!sourceTitle.trim()||sourceText.trim().length<20)} onClick={importSource}>{busy==='import'?<LoaderCircle className="spin"/>:<Link/>}导入并选用</button>
      </details>
      {!!reports.length&&<CollectedSources reports={reports} used={form.topic_ids} title="本次重新搜索结果"/>}
      <div className="context-regenerate"><label className="field">保存后做什么<select aria-label="保存后做什么" value={action} onChange={e=>setAction(e.target.value as Action)}><option value="save">仅保存选题与资料</option><option value="angles">重新生成写作角度</option><option value="outline">重新生成文章大纲</option><option value="article">重新生成整篇文章</option></select></label><p>{actionHints[action]}</p><button type="button" className="ss-btn ss-primary" disabled={locked||!form.subject.trim()&&!form.brief.trim()||form.mode==='reference'&&!form.topic_ids.length&&form.notes.trim().length<20} onClick={save}>{busy==='save'?<LoaderCircle className="spin"/>:action==='save'?<Save/>:<Sparkles/>}{actionLabels[action]}</button></div>
    </fieldset>
  </div>;
}
