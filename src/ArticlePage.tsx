import ArticleImagePicker from './ArticleImagePicker';
import ArticleAngles from './ArticleAngles';
import ArticleVersions from './ArticleVersions';
import ArticleFormatField from './ArticleFormatField';
import ArticleRewriteTools,{previewPart,type RewriteTarget} from './ArticleRewriteTools';
import {ArticleStreamPanel,useArticleStream} from './ArticleStreaming';
import {useConfirmation} from './Confirmation';
import ArticleTemplatePicker from './ArticleTemplates';
import ArticlePhonePreview from './ArticlePhonePreview';
import ArticleActivity from './ArticleActivity';
import {useOutcomeNotice} from './Notifications';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowDownToLine, BookOpen, Check, Copy, ImagePlus, LoaderCircle, Plus, Save, Sparkles, Trash2 } from 'lucide-react';
import { api, send } from './api';
import type { Article, ArticleDocument, ArticleOutline, ArticleProfile, ArticleSummary, Asset, IllustrationSettings, Topic } from './types';
import './articles.css';

const labels:Record<string,string>={queued:'排队中',running:'写作中',needs_angle:'选择角度',needs_outline:'确认大纲',needs_review:'待你过目',needs_revision:'需修改',draft:'草稿已修改',failed:'需要处理'};
const blankProfile:ArticleProfile={name:'我的公众号',direction:'',audience:'',style:'清晰自然，有具体解释，避免夸张和套话',length:1500,format:'解读',preferences:''};
const active=(a:Article)=>['queued','running'].includes(a.status);

export default function ArticlePage({topics,health,onError,onNotice,initialTopic='',onTopicsChanged,onUnsavedChange}:{topics:Topic[];health:{ai_ready:boolean};onError:(s:string)=>void;onNotice:(s:string)=>void;initialTopic?:string;onTopicsChanged:()=>Promise<unknown>;onUnsavedChange:(v:boolean)=>void}){
  const confirm=useConfirmation();
  const [profile,setProfile]=useState<ArticleProfile>(blankProfile),[savedProfile,setSavedProfile]=useState<ArticleProfile|null>(null);
  const [mode,setMode]=useState<'original'|'reference'>(initialTopic?'reference':'original'),[brief,setBrief]=useState(''),[notes,setNotes]=useState('');
  const [selected,setSelected]=useState<string[]>(initialTopic?[initialTopic]:[]),[articles,setArticles]=useState<ArticleSummary[]>([]),[current,setCurrent]=useState<Article|null>(null);
  const [editorEpoch,setEditorEpoch]=useState(0);
  const [busy,setBusy]=useState(''),[loaded,setLoaded]=useState(false),[dirty,setDirty]=useState(false),[url,setUrl]=useState(''),[manual,setManual]=useState(false),[title,setTitle]=useState(''),[text,setText]=useState('');
  const requestId=useRef(crypto.randomUUID()),dirtyRef=useRef(false),[filter,setFilter]=useState('');
  const updateDirty=useCallback((v:boolean)=>{dirtyRef.current=v;setDirty(v);onUnsavedChange(v);},[onUnsavedChange]);
  useEffect(()=>{requestId.current=crypto.randomUUID();},[mode,brief,notes,selected]);
  useEffect(()=>()=>onUnsavedChange(false),[onUnsavedChange]);
  useEffect(()=>{let live=true;Promise.all([api<ArticleProfile>('/article-profile'),api<ArticleSummary[]>('/articles')]).then(([p,a])=>{if(live){setProfile(p);setSavedProfile(p);setArticles(a);setLoaded(true);}}).catch(e=>onError(e.message));return()=>{live=false;};},[]);
  useEffect(()=>{if(!current)return;let live=true;const id=current.id;let polling=false;const timer=setInterval(async()=>{if(polling)return;polling=true;try{const [a,list]=await Promise.all([api<Article>(`/articles/${id}`),api<ArticleSummary[]>('/articles')]);if(live){setCurrent(previous=>previous&&previous.id===a.id&&previous.version>a.version?previous:a);setArticles(list);}}catch{/* Keep the saved draft visible during temporary disconnects. */}finally{polling=false;}},3000);return()=>{live=false;clearInterval(timer);};},[current?.id]);
  useEffect(()=>{const handler=(e:BeforeUnloadEvent)=>{if(dirtyRef.current){e.preventDefault();}};window.addEventListener('beforeunload',handler);return()=>window.removeEventListener('beforeunload',handler);},[]);
  const run=async(name:string,fn:()=>Promise<void>)=>{setBusy(name);try{await fn();}catch(e){onError((e as Error).message);}finally{setBusy('');}};
  const refresh=async()=>{if(current)setCurrent(await api<Article>(`/articles/${current.id}`));setArticles(await api<ArticleSummary[]>('/articles'));};
  const leave=async()=>!dirty||await confirm({title:'离开文章编辑？',message:'文章还有未保存的修改。离开后，这些修改将不会保留。',confirmLabel:'放弃修改并离开',cancelLabel:'继续编辑',tone:'discard'});
  const saveProfile=()=>run('profile',async()=>{const p=await api<ArticleProfile>('/article-profile',send('PUT',profile));setSavedProfile(p);onNotice('公众号定位已保存，新文章会使用此定位。');});
  const create=()=>run('create',async()=>{
    if(!brief.trim()&&!profile.direction.trim()&&notes.trim().length<20&&mode==='original')throw new Error('请填写公众号方向、想写的主题，或至少 20 字的笔记。');
    if(mode==='reference'&&!selected.length&&notes.trim().length<20)throw new Error('请选择参考资料，或填写至少 20 字的参考笔记。');
    const p=await api<ArticleProfile>('/article-profile',send('PUT',profile));setSavedProfile(p);
    const a=await api<Article>('/articles',send('POST',{mode,brief,notes,topic_ids:selected,request_id:requestId.current}));
    setCurrent(a);setArticles(await api<ArticleSummary[]>('/articles'));requestId.current=crypto.randomUUID();onNotice('定位和资料已保存，正在生成写作角度。');
  });
  const importSource=()=>run('import',async()=>{
    let id:string;
    if(manual){const r=await api<{topic_id:string}>('/sources/import',send('POST',{url,title,text}));id=r.topic_id;}
    else {const r=await api<Topic>('/article-sources/link',send('POST',{url}));id=r.id;}
    await onTopicsChanged();setSelected(s=>Array.from(new Set([...s,id])).slice(0,5));setUrl('');setTitle('');setText('');onNotice('参考资料已保存并选中。');
  });
  const act=async(action:string,extra:Record<string,unknown>={})=>{if(!current)return;await run(action,async()=>{setCurrent(await api<Article>(`/articles/${current.id}/${action}`,send('POST',{version:current.version,...extra})));await refresh();});};
  return <section className="article-page"><div className="ss-heading"><div><h1>让想法，有自己的声音。</h1><p>确定一个方向，从一个问题或一篇资料出发，写成可以反复打磨的文章。</p></div><button className="ss-btn" disabled={!loaded||!!busy} onClick={async()=>{if(await leave()){setCurrent(null);updateDirty(false);}}}><Plus/>新建文章</button></div>
    {!loaded?<div className="empty"><LoaderCircle className="spin"/><p>正在打开文章工作台…</p></div>:<>
    <div className="article-shelf"><span className="fn-label"><BookOpen/> 我的草稿 · {articles.length}</span><div>{articles.map(a=><button key={a.id} aria-pressed={current?.id===a.id} disabled={!!busy} onClick={async()=>{if(await leave())run('open',async()=>{setCurrent(await api<Article>(`/articles/${a.id}`));setEditorEpoch(n=>n+1);updateDirty(false);});}}><strong>{a.title}</strong><small>{labels[a.status]} · v{a.version}</small></button>)}{!articles.length&&<p>这里将保存你的文章、版本和资料。</p>}</div></div>
    {current?<ArticleWorkspace key={`${current.id}:${editorEpoch}`} article={current} busy={busy} dirty={dirty} onDirty={updateDirty} onAction={act} onRefresh={refresh} onError={onError} onNotice={onNotice}/>:<div className="article-start-grid">
      <section className="connection-card"><div className="connection-heading"><span className="connection-icon"><BookOpen/></span><div><h2>公众号定位</h2></div></div><p className="connection-description">把方向和读者记下来，每次写作都从这里出发。</p>
        <ArticleTemplatePicker value={profile.template_id} onChange={template_id=>setProfile({...profile,template_id})} disabled={!!busy} samplePreview/><fieldset className="article-fields" disabled={!!busy}><label className="field">账号名称<input maxLength={40} value={profile.name} onChange={e=>setProfile({...profile,name:e.target.value})}/></label><label className="field">内容方向<textarea maxLength={500} rows={3} value={profile.direction} onChange={e=>setProfile({...profile,direction:e.target.value})} placeholder="例如：AI 工具与职场效率，用实际操作解决问题"/></label><label className="field">目标读者<input maxLength={300} value={profile.audience} onChange={e=>setProfile({...profile,audience:e.target.value})} placeholder="例如：想尝试 AI 的普通上班族"/></label><div className="article-form-grid"><ArticleFormatField value={profile.format} onChange={format=>setProfile({...profile,format})}/><label className="field">目标字数<input type="number" min={400} max={4000} value={profile.length} onChange={e=>setProfile({...profile,length:Number(e.target.value)})}/></label></div><label className="field">写作风格<textarea maxLength={1000} rows={3} value={profile.style} onChange={e=>setProfile({...profile,style:e.target.value})}/></label><details><summary>更多偏好 · 开头、用词和避开的话题</summary><label className="field">其他偏好<textarea maxLength={2000} rows={3} value={profile.preferences} onChange={e=>setProfile({...profile,preferences:e.target.value})}/></label></details><button className="ss-btn" onClick={saveProfile}><Save/>{JSON.stringify(profile)===JSON.stringify(savedProfile)?'定位已保存':'保存定位'}</button></fieldset>
      </section>
      <section className="connection-card"><div className="connection-heading"><span className="connection-icon"><Sparkles/></span><div><h2>今天，想写些什么？</h2></div></div>
        <fieldset disabled={!!busy} className="article-fields"><div className="article-mode-tabs"><button aria-pressed={mode==='original'} onClick={()=>setMode('original')}>从零构思</button><button aria-pressed={mode==='reference'} onClick={()=>setMode('reference')}>热点 / 资料参考</button></div><p className="inline-hint">{mode==='original'?'按公众号方向推荐选题，也可以输入更具体的主题或个人笔记。':'从参考资料中提炼自己的角度；资料推荐不代表实际热度。'}</p><label className="field">想写什么？<textarea maxLength={2000} rows={3} value={brief} onChange={e=>{setBrief(e.target.value);requestId.current=crypto.randomUUID();}} placeholder={mode==='original'?'可留空，按账号方向推荐。也可以指定：普通人如何建立 AI 工作流？':'例如：从实用角度解释这次更新，读者应该关注什么？'}/></label>
        <details open={mode==='reference'} className="article-import"><summary>参考资料 · 已选 {selected.length}/5</summary><label className="field">查找资料<input value={filter} onChange={e=>setFilter(e.target.value)} placeholder="输入标题关键词"/></label><div className="article-source-picker">{topics.filter(t=>t.title.includes(filter)).map(t=><label key={t.id}><input type="checkbox" checked={selected.includes(t.id)} disabled={selected.length>=5&&!selected.includes(t.id)} onChange={()=>{setSelected(s=>s.includes(t.id)?s.filter(id=>id!==t.id):[...s,t.id]);requestId.current=crypto.randomUUID();}}/><span>{t.title}<small>{t.source} · {t.page_data?.full_text?'正文快照':'摘要'}</small></span></label>)}{!topics.length&&<p className="inline-hint">还没有资料，可在下面导入文章。</p>}</div>
        <label className="field">文章链接<input type="url" value={url} maxLength={2000} onChange={e=>setUrl(e.target.value)} placeholder="粘贴公众号文章或公开网页链接"/></label><label className="article-check-label"><input type="checkbox" checked={manual} onChange={e=>setManual(e.target.checked)}/>网页无法读取时，手动导入正文</label>{manual&&<><label className="field">原文标题<input maxLength={240} value={title} onChange={e=>setTitle(e.target.value)}/></label><label className="field">原文正文<textarea rows={5} minLength={20} maxLength={60000} value={text} onChange={e=>setText(e.target.value)}/></label></>}<button className="ss-btn" disabled={!url.trim()||selected.length>=5} onClick={importSource}>{busy==='import'?<LoaderCircle className="spin"/>:<Plus/>}{manual?'导入正文':'读取并添加资料'}</button></details>
        <label className="field">个人观点与笔记<textarea rows={3} maxLength={20000} value={notes} onChange={e=>{setNotes(e.target.value);requestId.current=crypto.randomUUID();}} placeholder="可以写自己的观点、案例或采访笔记，这些内容也会作为资料保存。"/></label><button className="ss-btn ss-primary" disabled={!health.ai_ready} onClick={create}>{busy==='create'?<LoaderCircle className="spin"/>:<Sparkles/>}保存定位并生成写作角度</button>{!health.ai_ready&&<p className="inline-hint">需要先<a href="#flow">配置 AI 模型</a>。</p>}</fieldset>
      </section>
    </div>}
    </>}
  </section>;
}

export function ArticleWorkspace({article,delivery,illustration,busy,dirty,onDirty,onAction,onRefresh,onError,onNotice}:{article:Article;delivery?:ReactNode;illustration?:IllustrationSettings;busy:string;dirty:boolean;onDirty:(v:boolean)=>void;onAction:(action:string,extra?:Record<string,unknown>)=>Promise<unknown>;onRefresh:()=>Promise<void>;onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const confirm=useConfirmation();
  const {draft:liveDraft,reconnecting}=useArticleStream(article,onRefresh);
  const [activePart,setActivePart]=useState('');const preview=useRef<HTMLDivElement>(null);
  const [submittingRewrite,setSubmittingRewrite]=useState<RewriteTarget|null>(null);
  const selectPart=(target:RewriteTarget)=>{
    const key=previewPart(target);setActivePart(key);
    requestAnimationFrame(()=>{
      const area=preview.current,element=area?.querySelector<HTMLElement>(`[data-preview-part="${key}"]`);
      if(area&&element)area.scrollTo({top:Math.max(0,area.scrollTop+element.getBoundingClientRect().top-area.getBoundingClientRect().top-16),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
    });
  };
  const [doc,setDoc]=useState<ArticleDocument|null>(article.document),[outline,setOutline]=useState<ArticleOutline|null>(article.outline),[saving,setSaving]=useState(false),[assets,setAssets]=useState<Asset[]>([]),[file,setFile]=useState<File|null>(null),[rights,setRights]=useState(''),[credit,setCredit]=useState('');
  const [pictureBusy,setPictureBusy]=useState<Record<string,boolean>>({});
  const pictureSettings=article.input_data._illustration as IllustrationSettings|undefined||illustration;
  const [viewStep,setViewStep]=useState(article.document?3:article.outline?1:0);
  const [stepsOpen,setStepsOpen]=useState(()=>!matchMedia('(max-width:760px)').matches);
  useEffect(()=>{const media=matchMedia('(max-width:760px)'),changed=()=>setStepsOpen(!media.matches);media.addEventListener('change',changed);return()=>media.removeEventListener('change',changed);},[]);
  useOutcomeNotice(article.id,article.status,article.error,article.updated_at,article.note.startsWith('新的写作角度')?'新的写作角度已生成，可编辑或选用后继续。':article.status==='needs_angle'?'写作角度已生成，请选择一个继续。':article.status==='needs_outline'?'文章大纲已生成，可以编辑或返回重新选角度。':'正文与检查已完成，可以继续编辑。');
  const [angleDirty,setAngleDirty]=useState(false);const versionRef=useRef(article.version);const dirtyRef=useRef(false);
  const mark=(v:boolean)=>{dirtyRef.current=v;onDirty(v||angleDirty);};
  const markAngles=(v:boolean)=>{setAngleDirty(v);onDirty(dirtyRef.current||v);};
  useEffect(()=>{if(article.version>versionRef.current&&!dirtyRef.current){if(!!article.document!==!!doc)setViewStep(article.document?3:article.outline?1:0);else if(!article.document&&article.status==='needs_angle')setViewStep(0);else if(!outline&&article.outline)setViewStep(1);setDoc(article.document);setOutline(article.outline);versionRef.current=article.version;}},[article.version,article.document,article.outline]);
  useEffect(()=>{api<Asset[]>('/assets').then(a=>setAssets(a.filter(x=>x.media_type.startsWith('image/')))).catch(e=>onError(e.message));return()=>onDirty(false);},[]);
  useEffect(()=>{api<Asset[]>('/assets').then(a=>setAssets(a.filter(x=>x.media_type.startsWith('image/')))).catch(()=>{});},[article.version]);
  const pictureProcessing=Object.values(pictureBusy).some(Boolean);
  useEffect(()=>{onDirty(dirtyRef.current||angleDirty||pictureProcessing);},[pictureProcessing]);
  const blocked=!!busy||saving||active(article)||pictureProcessing;
  const changeDoc=(value:ArticleDocument)=>{setDoc(value);mark(true);};
  const rewritePart=async(target:RewriteTarget,instruction:string)=>{
    if(!doc||blocked)return false;
    setSubmittingRewrite(target);
    setSaving(true);
    try{
      const document=dirty?{...doc,sections:doc.sections.map(s=>({...s,paragraphs:s.paragraphs.map(p=>p.trim()).filter(Boolean)}))}:undefined;
      let scope=target;
      if(document&&target.target==='paragraph'&&target.section!==undefined&&target.paragraph!==undefined){
        const paragraphs=doc.sections[target.section].paragraphs;
        if(!paragraphs[target.paragraph]?.trim())throw new Error('该段尚无文字，请选择本节全部正文来生成内容。');
        scope={...target,paragraph:paragraphs.slice(0,target.paragraph).filter(p=>p.trim()).length};
      }
      const saved=await api<Article>(`/articles/${article.id}/rewrite`,send('POST',{version:versionRef.current,...scope,instruction,...(document?{document}:{})}));
      setDoc(saved.document);versionRef.current=saved.version;mark(false);await onRefresh();
      onNotice('已开始局部调整，原有版本保留在历史记录中。');return true;
    }catch(e){onError((e as Error).message);return false;}finally{setSaving(false);setSubmittingRewrite(null);}
  };
  const rewriteTarget=submittingRewrite||article.input_data._rewrite as RewriteTarget|undefined;
  const localStream=viewStep===3&&!!rewriteTarget&&(!!submittingRewrite||(active(article)&&(article.stage==='section'||(article.stage==='check'&&article.note.startsWith('局部修改')))));
  const localStatus=submittingRewrite?'正在提交局部调整…':article.status==='queued'?'局部调整已排队，等待模型响应…':article.stage==='check'?'局部修改已保存，正在核对…':'正在调整选中的内容';
  const tools=(label:string,target:RewriteTarget,paragraphs?:string[])=><><ArticleRewriteTools label={label} target={target} paragraphs={paragraphs} disabled={blocked} dirty={dirty} onSelect={selectPart} onRewrite={rewritePart}/>{localStream&&rewriteTarget&&rewriteTarget.section===target.section&&(rewriteTarget.target===target.target||(['paragraph','section'].includes(rewriteTarget.target)&&target.target==='paragraphs'))&&<ArticleStreamPanel draft={submittingRewrite?null:liveDraft} reconnecting={!submittingRewrite&&reconnecting} statusText={localStatus}/>}</>;
  const changeOutline=(value:ArticleOutline)=>{setOutline(value);mark(true);};
  const goStep=(step:number)=>{if(step===viewStep)return;if(dirty){onError(angleDirty?'写作角度有未保存的修改，请先保存角度或取消调整。':'当前步骤有未保存的修改，请先保存，或点击“撤销修改”后返回。');return;}setViewStep(step);};
  const discard=()=>{setDoc(article.document);setOutline(article.outline);versionRef.current=article.version;mark(false);onNotice('已撤销尚未保存的修改。');};
  const chooseAngle=async(choice:number)=>{
    if(outline&&article.input_data.angle_index===choice&&!article.input_data._angle_outline_stale){goStep(1);return;}
    const replace=!!(outline||doc);
    if(replace&&!await confirm({title:'换一个写作角度？',message:'将按新的角度重新生成大纲，后续正文也需要重新生成。',detail:'现有大纲和正文会保留在版本记录中，随时可以恢复。',confirmLabel:'切换并生成大纲',cancelLabel:'保留当前角度'}))return;
    if(await onAction('angle',{choice,replace_existing:replace})!==false)setViewStep(1);
  };
  const generate=async()=>{
    if(doc&&!await confirm({title:'重新生成这篇文章？',message:'将根据当前大纲重新创作完整正文，新内容会替换编辑区中的当前版本。',detail:'当前正文会保留在版本记录中，随时可以恢复。',confirmLabel:'重新生成正文',cancelLabel:'保留当前正文'}))return;
    const previous=viewStep;setViewStep(2);
    if(await onAction('generate',{replace_existing:!!doc})===false)setViewStep(previous);
  };
  const save=async()=>{
    const part=viewStep===1?'outline':'document';
    if(part==='outline'&&doc&&!await confirm({title:'保存新的文章大纲？',message:'大纲调整后，需要重新生成正文，使内容与新的结构保持一致。',detail:'现有正文会保留在版本记录中，随时可以恢复。',confirmLabel:'保存新大纲',cancelLabel:'继续调整'}))return;
    setSaving(true);try{
      const value=part==='document'&&doc?{...doc,sections:doc.sections.map(s=>({...s,paragraphs:s.paragraphs.map(p=>p.trim()).filter(Boolean)}))}:outline;
      const saved=await api<Article>(`/articles/${article.id}/${part}`,send('PUT',{version:versionRef.current,[part]:value,...(part==='outline'?{replace_existing:!!doc}:{})}));
      setDoc(saved.document);setOutline(saved.outline);versionRef.current=saved.version;mark(false);await onRefresh();onNotice(part==='document'?'文章已保存，请重新检查修改后的内容。':'大纲已保存，可以生成正文；历史内容仍可在版本记录恢复。');
    }catch(e){onError((e as Error).message);}finally{setSaving(false);}
  };
  const copy=async()=>{try{const response=await fetch(`/api/articles/${article.id}/export?format=html&wechat=true&version=${article.version}`);if(!response.ok)throw new Error('文章已更新或正在处理，请刷新后复制。');const value=await response.text();if(!navigator.clipboard?.write)throw new Error('当前浏览器不支持复制排版，请下载 HTML。');const plain=doc?[doc.summary,doc.opening,...doc.sections.flatMap(s=>[s.heading,...s.paragraphs]),doc.closing].filter(Boolean).join('\n\n'):'';await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([value],{type:'text/html'}),'text/plain':new Blob([plain],{type:'text/plain'})})]);onNotice('已复制排版文字。粘贴到公众号后检查排版，图片请另行上传。');}catch(e){onError((e as Error).message);}};
  const upload=async()=>{if(!file)return;setSaving(true);try{const form=new FormData();form.append('file',file);form.append('rights',rights);form.append('credit',credit);const asset=await api<Asset>('/assets',{method:'POST',body:form});setAssets(s=>[asset,...s]);setFile(null);onNotice('图片已上传，可在封面或正文配图中选择。');}catch(e){onError((e as Error).message);}finally{setSaving(false);}};
  const imageCard=(label:string,id:string,caption:string,locked:boolean,hint:string,onChange:(id:string,caption:string,locked:boolean)=>void)=><ArticleImagePicker label={label} value={id} caption={caption} locked={locked} hint={hint} settings={pictureSettings} assets={assets} disabled={blocked} onChange={onChange} onAssets={a=>setAssets(v=>[a,...v.filter(x=>x.id!==a.id)])} onBusy={v=>setPictureBusy(old=>old[label]===v?old:{...old,[label]:v})} onError={onError} onNotice={onNotice}/>;
  return <div className="article-workspace"><div className="article-workspace-heading"><div><span className="fn-label">{article.profile.name} · {article.mode==='original'?'原创构思':'资料参考'} · v{article.version}</span><h2>{doc?.title||outline?.title||'为文章寻找一个角度'}</h2></div><div className="article-heading-actions">{delivery}<span className="ss-badge">{dirty?'有未保存修改':labels[article.status]}</span><ArticleVersions article={article} blocked={blocked||dirty} onRestore={version=>onAction('restore',{target_version:version})}/></div></div>
    <ArticleActivity key={article.id} article={article} draft={liveDraft} reconnecting={reconnecting} local={localStream} canRetry={!blocked&&!dirty} onRetry={()=>onAction('retry')}/>
    <div className="article-workspace-layout"><details className="article-flow" open={stepsOpen} onToggle={e=>setStepsOpen(e.currentTarget.open)}><summary>创作流程<span>{['写作角度','文章大纲','撰写正文','编辑与检查'][viewStep]}</span></summary><span className="fn-label">创作流程</span><ol className="article-steps" aria-label="文章创作步骤">{['写作角度','文章大纲','撰写正文','编辑与检查'].map((s,i)=><li key={s} className={viewStep===i?'current':article.progress>=[0,30,50,80][i]?'reached':''}><button disabled={blocked||(i===0&&!article.angles)||(i===1&&!outline)||(i===2&&!outline)||(i===3&&!doc)} aria-current={viewStep===i?'step':undefined} onClick={()=>goStep(i)}><span>0{i+1}</span>{s}</button></li>)}</ol></details><div className="article-workspace-content">
    <div className="article-step-tools">{viewStep>0&&((viewStep===1&&article.angles)||viewStep>1)&&<button className="text-button" disabled={blocked} onClick={()=>goStep(viewStep===3?1:viewStep-1)}>← {viewStep===1?'上一步：写作角度':viewStep===2?'上一步：文章大纲':'返回文章大纲'}</button>}{viewStep===0&&outline&&<button className="text-button" disabled={blocked} onClick={()=>goStep(1)}>返回当前大纲 →</button>}{dirty&&!angleDirty&&<button className="text-button" disabled={blocked} onClick={discard}>撤销修改</button>}</div>
    {viewStep===0&&<ArticleAngles article={article} blocked={blocked} onChoose={chooseAngle} onDirty={markAngles} onRefresh={onRefresh} onError={onError} onNotice={onNotice}/>}
    {viewStep===1&&outline&&<section className="connection-card"><h3>先把结构理顺</h3><p className="inline-hint">确认标题、切入点和各节要点后，再生成正文。</p><fieldset disabled={blocked} className="article-fields"><label className="field">大纲标题<input value={outline.title} maxLength={100} onChange={e=>changeOutline({...outline,title:e.target.value})}/></label><label className="field">切入角度<textarea rows={2} value={outline.angle} maxLength={1000} onChange={e=>changeOutline({...outline,angle:e.target.value})}/></label>{outline.sections.map((s,i)=><div className="article-section-editor" key={i}><label className="field">第 {i+1} 节标题<input maxLength={120} value={s.heading} onChange={e=>changeOutline({...outline,sections:outline.sections.map((x,j)=>i===j?{...x,heading:e.target.value}:x)})}/></label><label className="field">第 {i+1} 节要点<textarea rows={3} maxLength={1800} value={s.points} onChange={e=>changeOutline({...outline,sections:outline.sections.map((x,j)=>i===j?{...x,points:e.target.value}:x)})}/></label><button className="text-button" disabled={outline.sections.length<=1} onClick={()=>changeOutline({...outline,sections:outline.sections.filter((_,j)=>j!==i)})}>删除此节</button></div>)}<button className="ss-btn" disabled={outline.sections.length>=12} onClick={()=>changeOutline({...outline,sections:[...outline.sections,{heading:'新增章节',points:'补充本节要点'}]})}><Plus/>添加章节</button>{outline.source_gaps.length>0&&<div className="article-checks"><strong>资料缺口</strong>{outline.source_gaps.map((s,i)=><p key={i}>{s}</p>)}<p>可先调整大纲，删去缺乏依据的论点；也可在任务工作台的“选题与资料”中补充资料，再重新生成。</p></div>}<div className="article-actions"><button className="ss-btn" disabled={!dirty} onClick={save}><Save/>保存大纲</button><button className="ss-btn ss-primary" disabled={dirty} onClick={generate}><Sparkles/>按大纲生成正文</button></div></fieldset></section>}
    {viewStep===2&&outline&&<section className="connection-card article-generate-panel"><h3>{doc?'按当前大纲重新创作':'准备撰写正文'}</h3><p>《{outline.title}》 · {outline.sections.length} 个章节 · 目标约 {article.profile.length} 字</p><p className="inline-hint">{doc?'重新生成前会保留当前正文版本。':'可返回修改大纲，确认后生成完整正文。'}</p><button className="ss-btn ss-primary" disabled={blocked||dirty} onClick={generate}><Sparkles/>{doc?'按大纲重新生成正文':'开始生成正文'}</button>{doc&&<button className="ss-btn" onClick={()=>goStep(3)}>继续编辑当前正文</button>}</section>}
    {viewStep===3&&doc&&<><ArticleTemplatePicker value={doc.template_id} onChange={template_id=>changeDoc({...doc,template_id})} disabled={blocked}/><div className="article-editor-grid"><details className="article-reference-panel"><summary><BookOpen size={15}/>写作资料与配图<span>{article.source_data.length} 条资料</span></summary><div className="article-reference-content">{article.source_data.map(s=><details key={s.id}><summary>{s.title}</summary><p className="inline-hint">{s.publisher} · {s.full_text?'正文快照':'摘要'}</p>{s.url&&<a href={s.url} target="_blank" rel="noreferrer">打开原文 ↗</a>}<p className="article-source-text">{s.text}</p></details>)}{!article.source_data.length&&<p className="inline-hint">本稿未附资料，具体事实需补充核验。</p>}<details><summary>封面与配图</summary><p className="inline-hint">{doc.cover_hint}</p><fieldset className="article-fields" disabled={blocked}><label className="field">上传图片<input type="file" accept="image/jpeg,image/png,image/webp" onChange={e=>setFile(e.target.files?.[0]||null)}/></label><label className="field">使用权说明<input value={rights} onChange={e=>setRights(e.target.value)} placeholder="例如：本人拍摄，可用于公众号"/></label><label className="field">图片署名<input value={credit} onChange={e=>setCredit(e.target.value)}/></label><button className="ss-btn" disabled={!file||rights.trim().length<4} onClick={upload}><ImagePlus/>上传图片</button></fieldset></details></div></details>
    <div className="article-editor"><fieldset className="article-fields" disabled={blocked}><label className="field">主标题<input onFocus={()=>selectPart({target:'title'})} maxLength={100} value={doc.title} onChange={e=>changeDoc({...doc,title:e.target.value})}/></label>{tools('主标题',{target:'title'})}<details><summary>备选标题</summary>{doc.titles.map((t,i)=><button className="article-title-option" key={i} onClick={()=>changeDoc({...doc,title:t})}>{t}</button>)}</details>{imageCard('封面图片',doc.cover_asset_id,doc.cover_caption||'',!!doc.cover_image_locked,doc.cover_hint||doc.title,(id,caption,locked)=>changeDoc({...doc,cover_asset_id:id,cover_caption:caption,cover_image_locked:locked}))}<label className="field">摘要<textarea onFocus={()=>selectPart({target:'summary'})} rows={3} maxLength={300} value={doc.summary} onChange={e=>changeDoc({...doc,summary:e.target.value})}/></label>{tools('摘要',{target:'summary'})}<label className="field">开头<textarea onFocus={()=>selectPart({target:'opening'})} rows={4} maxLength={3000} value={doc.opening} onChange={e=>changeDoc({...doc,opening:e.target.value})}/></label>{tools('开头',{target:'opening'})}{doc.sections.map((section,i)=><div className="article-section-editor" key={i}><label className="field">第 {i+1} 节小标题<input onFocus={()=>selectPart({target:'heading',section:i})} maxLength={120} value={section.heading} onChange={e=>changeDoc({...doc,sections:doc.sections.map((s,j)=>i===j?{...s,heading:e.target.value}:s)})}/></label>{tools(`第 ${i+1} 节小标题`,{target:'heading',section:i})}<label className="field">第 {i+1} 节正文<textarea onFocus={()=>selectPart({target:'paragraphs',section:i})} rows={9} value={section.paragraphs.join('\n\n')} onChange={e=>changeDoc({...doc,sections:doc.sections.map((s,j)=>i===j?{...s,paragraphs:e.target.value.split(/\n\s*\n/)}:s)})}/></label>{tools(`第 ${i+1} 节正文`,{target:'paragraphs',section:i},section.paragraphs)}<p className="inline-hint">{section.image_hint}</p>{imageCard(`第 ${i+1} 节配图`,section.asset_id,section.caption,!!section.image_locked,section.image_hint||section.heading,(id,caption,locked)=>changeDoc({...doc,sections:doc.sections.map((x,j)=>j===i?{...x,asset_id:id,caption,image_locked:locked}:x)}))}<details><summary>本节依据 · {section.evidence.length} 条</summary>{section.evidence.map((evidence,k)=><div key={k} className="article-evidence"><label className="field">引用来源<select value={evidence.source_id} onChange={e=>changeDoc({...doc,sections:doc.sections.map((s,j)=>i===j?{...s,evidence:s.evidence.map((x,n)=>k===n?{...x,source_id:e.target.value}:x)}:s)})}>{article.source_data.map(s=><option key={s.id} value={s.id}>{s.title}</option>)}</select></label><label className="field">原文引文<textarea value={evidence.quote} onChange={e=>changeDoc({...doc,sections:doc.sections.map((s,j)=>i===j?{...s,evidence:s.evidence.map((x,n)=>k===n?{...x,quote:e.target.value}:x)}:s)})}/></label><button className="text-button" onClick={()=>changeDoc({...doc,sections:doc.sections.map((s,j)=>i===j?{...s,evidence:s.evidence.filter((_,n)=>n!==k)}:s)})}>移除此引用</button></div>)}<button className="text-button" disabled={!article.source_data.length||section.evidence.length>=8} onClick={()=>changeDoc({...doc,sections:doc.sections.map((s,j)=>i===j?{...s,evidence:[...s.evidence,{source_id:article.source_data[0].id,quote:'请填写来源中对应的原文引文'}]}:s)})}>添加引用</button></details><button className="text-button" disabled={doc.sections.length<=1} onClick={()=>changeDoc({...doc,sections:doc.sections.filter((_,j)=>j!==i)})}><Trash2/>删除此节</button></div>)}<button className="ss-btn" disabled={doc.sections.length>=12} onClick={()=>changeDoc({...doc,sections:[...doc.sections,{heading:'新增章节',paragraphs:['填写正文'],evidence:[],image_hint:'',asset_id:'',caption:''}]})}><Plus/>添加章节</button><label className="field">结尾<textarea onFocus={()=>selectPart({target:'closing'})} rows={4} maxLength={3000} value={doc.closing} onChange={e=>changeDoc({...doc,closing:e.target.value})}/></label>{tools('结尾',{target:'closing'})}</fieldset></div>
    <ArticlePhonePreview document={doc} activePart={activePart} readingRef={preview}/></div>
    <div className="article-actions article-savebar">{pictureSettings?.enabled&&<button className="ss-btn" disabled={blocked||dirty} onClick={()=>onAction('illustrate')}><ImagePlus/>按配置补齐配图</button>}<button className="ss-btn ss-primary" onClick={save} disabled={blocked||!dirty}><Save/>{saving?'保存中…':'保存修改'}</button><button className="ss-btn" onClick={()=>onAction('check')} disabled={blocked||dirty}><Check/>重新检查</button><button className="ss-btn" onClick={copy} disabled={blocked||dirty}><Copy/>复制排版文字</button>{!blocked&&!dirty&&(['html','markdown','bundle'] as const).map(format=><a key={format} className="ss-btn" href={`/api/articles/${article.id}/export?format=${format}&version=${article.version}`} download><ArrowDownToLine/>{format==='bundle'?'图文交付包':format.toUpperCase()}</a>)}<span className="inline-hint">{dirty?'先保存修改，再检查或导出。':'HTML / Markdown 为文字版，配图随交付包导出。'}</span></div>
    {article.checks&&!dirty?<div className="article-checks"><strong>检查记录 · v{article.version}</strong><p>{article.checks.note}</p>{article.checks.issues.map((x,i)=><div key={i}><span>{x.severity==='error'?'需处理':'建议'} · {x.section?`第 ${x.section} 节`:'全文'}</span>{x.message}</div>)}<p className="inline-hint">检查用于定位问题，不代表事实或原创性的保证。</p></div>:<p className="inline-hint">{dirty?'当前修改尚未检查。':'尚无当前版本的检查结果，可以点击“重新检查”。'}</p>}
    </>}

  </div></div></div>;
}
