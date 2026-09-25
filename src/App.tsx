import CreationRecords,{TaskRecordsButton} from './CreationRecords';
import {useCallback,useEffect,useRef,useState} from 'react';
import {ArrowRight,Bird,Clapperboard,FileText,Image,LoaderCircle,Plus,X} from 'lucide-react';
import {api,dateText,send} from './api';
import type {CreationKind,CreationTask,Settings,Topic} from './types';
import ModelsPage from './ModelsPage';
import WeChatAccountsPage from './WeChatAccountsPage';
import TaskDelete from './TaskDelete';
import TaskWorkbench from './TaskWorkbench';
import MaterialsPage from './MaterialsPage';
import './connections.css';
import './articles.css';
import {NotificationProvider,useNotifications,useNotificationHost} from './Notifications';
import {ConfirmationProvider,useConfirmation} from './Confirmation';

export const statuses={queued:'等待制作',running:'制作中',needs_review:'待审核',approved:'已通过',failed:'需要处理',changes_requested:'待修改',draft:'文案已更新'};
export const kindNames={video:'视频',article:'公众号文章',image:'图片'};
export const kindIcons={video:Clapperboard,article:FileText,image:Image};
export const runLabels:Record<string,string>={...statuses,publishing:'微信发布中',published:'已发布',wechat_draft:'微信草稿',awaiting_publish:'待你发布',ready:'已完成',needs_revision:'待修订',needs_angle:'待选角度',needs_outline:'待确认大纲',draft:'可编辑'};
const pages=[{id:'home',name:'首页'},{id:'tasks',name:'任务列表'},{id:'materials',name:'素材库'},{id:'models',name:'我的模型'},{id:'accounts',name:'发布账号'}];
const route=()=>{const value=location.hash.slice(1);return pages.some(p=>p.id===value)||value==='records'||value.startsWith('tasks?')||value.startsWith('task/')?value:'home';};
export default function App(){return <NotificationProvider><ConfirmationProvider><StudioApp/></ConfirmationProvider></NotificationProvider>;}
function StudioApp(){
  const [page,setPage]=useState(route),[tasks,setTasks]=useState<CreationTask[]>([]),[topics,setTopics]=useState<Topic[]>([]),[settings,setSettings]=useState<Settings|null>(null);
  const [loading,setLoading]=useState(true),[creating,setCreating]=useState(false);const dirty=useRef(false),navigating=useRef(false);const confirm=useConfirmation();
  const {error:setError,success:setNotice}=useNotifications();
  const refresh=useCallback(async()=>{const [t,p,s]=await Promise.all([api<CreationTask[]>('/tasks'),api<Topic[]>('/topics'),api<Settings>('/settings')]);setTasks(t);setTopics(p);setSettings(s);},[]);
  useEffect(()=>{refresh().catch(e=>setError(e.message)).finally(()=>setLoading(false));},[refresh]);
  useEffect(()=>{const timer=setInterval(()=>api<CreationTask[]>('/tasks').then(setTasks).catch(()=>{}),4000);return()=>clearInterval(timer);},[]);
  useEffect(()=>{const changed=async()=>{
    const next=route();if(next===page)return;
    if(navigating.current){history.replaceState(null,'','#'+page);return;}
    if(dirty.current){
      history.replaceState(null,'','#'+page);navigating.current=true;
      const leave=await confirm({title:'离开当前编辑？',message:'当前页面还有未保存的修改。离开后，这些修改将不会保留。',confirmLabel:'放弃修改并离开',cancelLabel:'继续编辑',tone:'discard'});
      navigating.current=false;if(!leave)return;history.replaceState(null,'','#'+next);
    }
    dirty.current=false;setPage(next);window.scrollTo(0,0);
  };addEventListener('hashchange',changed);return()=>removeEventListener('hashchange',changed);},[page,confirm]);
  useEffect(()=>{const leave=(e:BeforeUnloadEvent)=>{if(dirty.current){e.preventDefault();e.returnValue='';}};addEventListener('beforeunload',leave);return()=>removeEventListener('beforeunload',leave);},[]);
  const navigate=(next:string)=>{location.hash=next;};const openTask=(id:string,runId?:string)=>navigate('task/'+id+(runId?'?run='+encodeURIComponent(runId):''));const mark=useCallback((v:boolean)=>{dirty.current=v;},[]);const newTask=()=>setCreating(true);
  const removed=(id:string)=>{dirty.current=false;setTasks(current=>current.filter(t=>t.id!==id));if(page.split('?')[0]==='task/'+id){history.replaceState(null,'','#tasks');setPage('tasks');window.scrollTo(0,0);}};
  return <div id="science-fieldnotes" className={'creation-platform'+(page.startsWith('task/')?' task-detail-page':'')}><a className="skip-link" href="#main">跳到主要内容</a>
    {!page.startsWith('task/')&&<header className="fn-header"><button className="fn-brand" onClick={()=>navigate('home')} aria-label="知序，回到首页"><span className="fn-brand-mark"><Bird/></span><span><strong>知序 · 创作空间</strong><small>SELF MEDIA STUDIO</small></span></button><nav className="fn-navigation" aria-label="主导航">{pages.map(p=><button key={p.id} className="fn-nav" aria-current={(page===p.id||(p.id==='tasks'&&(page.startsWith('task')||page==='records')))?'page':undefined} onClick={()=>navigate(p.id)}>{p.name}</button>)}</nav><button className="ss-btn ss-primary" onClick={newTask}><Plus/>新建任务</button></header>}
    <main id="main">{loading?<div className="empty"><LoaderCircle className="spin"/><h2>正在打开创作空间…</h2></div>:!settings?<div className="empty"><h2>暂时未连接工作台</h2><button className="ss-btn" onClick={()=>refresh().catch(e=>setError(e.message))}>重新连接</button></div>:<>
      {page==='home'&&<Home tasks={tasks} onOpen={openTask} onNew={newTask} onAll={()=>navigate('tasks')} onNavigate={navigate} onDeleted={removed}/>}
      {(page==='tasks'||page.startsWith('tasks?'))&&<TaskList key={page} initialExecution={new URLSearchParams(page.split('?')[1]||'').get('execution')||'all'} tasks={tasks} onOpen={openTask} onNew={newTask} onDeleted={removed} onRefresh={refresh}/>}
      {page==='records'&&<CreationRecords onOpen={openTask}/>}
      {page==='materials'&&<MaterialsPage settings={settings} topics={topics} onSaved={setSettings} onRefresh={refresh} onError={setError} onNotice={setNotice}/>}
      {page==='models'&&<ModelsPage onError={setError} onNotice={setNotice}/>}
      {page==='accounts'&&<WeChatAccountsPage onError={setError} onNotice={setNotice}/>}
      {page.startsWith('task/')&&<TaskWorkbench onDeleted={removed} key={page} id={page.slice(5).split('?')[0]} initialRun={new URLSearchParams(page.split('?')[1]||'').get('run')||undefined} topics={topics} onRefresh={refresh} onDirty={mark} onError={setError} onNotice={setNotice}/>}
    </>}</main><footer className="ss-footer"><span>知序 · 自媒体创作平台</span><span>本地保存 · 北京时间 · 定时执行需保持服务运行</span></footer>
    {creating&&<NewTask onClose={()=>setCreating(false)} onCreated={async task=>{setCreating(false);await refresh();navigate('task/'+task.id);setNotice('任务已创建，可以开始配置。');}}/>}
  </div>;
}
function Home({tasks,onOpen,onNew,onAll,onDeleted,onNavigate}:{tasks:CreationTask[];onOpen:(id:string,runId?:string)=>void;onNew:()=>void;onAll:()=>void;onNavigate:(page:string)=>void;onDeleted:(id:string)=>void}){
  const active=tasks.filter(t=>!t.archived),scheduled=active.filter(t=>t.settings.execution==='automatic');
  return <><section className="studio-welcome"><div><span className="fn-label">YOUR IDEAS, TAKING SHAPE</span><h1>让每一个想法，<br/>有自己的创作空间。</h1><p>写一篇文章，制作一支短片，或者一组图文。<br/>亲手打磨，也可以设定时间，让灵感持续生长。</p><button className="ss-btn ss-primary" onClick={onNew}>开始新的创作 <ArrowRight/></button></div><div className="studio-collage" aria-hidden="true"><div className="collage-card collage-video"><Clapperboard/><span>10 SEC / VIDEO</span><div className="mini-landscape"><i/><b/></div></div><div className="collage-card collage-article"><FileText/><span>WORDS / IDEAS</span><strong>一个好故事，<br/>从这里开始。</strong><i/><i/><i/></div><div className="collage-card collage-image"><Image/><span>IMAGE / MOMENTS</span><b>记录<br/>每一份灵感</b></div></div></section>
    <div className="studio-stats"><button onClick={onAll}><strong>{tasks.length}</strong><span>全部任务<small>包含手动、定时与归档</small></span><ArrowRight/></button><button onClick={()=>onNavigate('tasks?execution=automatic')}><strong>{scheduled.length}</strong><span>其中定时任务<small>已启用定时执行</small></span><ArrowRight/></button><button onClick={()=>onNavigate('records')}><strong>{tasks.reduce((n,t)=>n+(t.run_count||0),0)}</strong><span>创作记录<small>累计执行次数</small></span><ArrowRight/></button></div>
    <div className="section-title"><div><span className="fn-label">RECENT PROJECTS</span><h2>最近的创作任务</h2></div><button className="fn-text-action" onClick={onAll}>查看全部 <ArrowRight/></button></div>{active.length?<div className="task-grid">{active.slice(0,6).map(t=><TaskCard key={t.id} task={t} onOpen={onOpen} onDeleted={onDeleted}/>)}</div>:<div className="empty platform-empty"><Bird/><h2>给第一个想法起个名字。</h2><p>创建任务后，再选择方向、模型和创作方式。</p><button className="ss-btn" onClick={onNew}><Plus/>创建第一个任务</button></div>}</>;
}
function TaskCard({task:t,onOpen,onDeleted}:{task:CreationTask;onOpen:(id:string,runId?:string)=>void;onDeleted:(id:string)=>void}){
  const Icon=kindIcons[t.kind];
  return <article className={'task-card task-'+t.kind}><button className="task-card-open" onClick={()=>onOpen(t.id)}>
    <span className="task-card-top"><span className="task-type"><Icon/>{kindNames[t.kind]}</span><span className="ss-badge">{t.archived?'已归档':t.latest_run?runLabels[t.latest_run.status]||t.latest_run.status:'待配置'}</span></span>
    <strong>{t.name}</strong><p>{t.settings.brief||(t.kind==='article'?t.settings.article.direction:'')||'打开工作台，配置你的创作方向。'}</p>
    <span className="task-card-bottom"><span>{t.archived?'定时执行已暂停':t.settings.execution==='automatic'?`${t.settings.schedule.time} · 定时执行`:'手动创作'}<small>{dateText(t.created_at)} 创建</small></span><ArrowRight/></span>
    </button><div className="task-card-actions"><TaskRecordsButton task={t} onOpen={onOpen}/><TaskDelete task={t} onDeleted={onDeleted} compact/></div></article>;
}
function TaskList({tasks,onOpen,onNew,onDeleted,onRefresh,initialExecution}:{tasks:CreationTask[];onOpen:(id:string,runId?:string)=>void;onNew:()=>void;onDeleted:(id:string)=>void;onRefresh:()=>Promise<unknown>;initialExecution:string}){
  const [execution,setExecution]=useState(initialExecution);
  const [kind,setKind]=useState('all'),[query,setQuery]=useState(''),[archived,setArchived]=useState(false),[trash,setTrash]=useState(false),[deleted,setDeleted]=useState<CreationTask[]>([]),[loadingTrash,setLoadingTrash]=useState(false),[restoring,setRestoring]=useState('');
  const {error,success}=useNotifications();
  useEffect(()=>{if(!trash)return;let live=true;setLoadingTrash(true);api<CreationTask[]>('/tasks?deleted=true').then(v=>{if(live)setDeleted(v);}).catch(e=>{if(live)error(e.message);}).finally(()=>{if(live)setLoadingTrash(false);});return()=>{live=false;};},[trash]);
  const restore=async(t:CreationTask)=>{setRestoring(t.id);try{await api(`/tasks/${t.id}/restore`,send('POST',{version:t.version}));setDeleted(v=>v.filter(x=>x.id!==t.id));await onRefresh();success('任务已恢复到“已归档”，打开任务并点击“恢复任务”后才会重新启用定时执行。');}catch(e){error((e as Error).message);}finally{setRestoring('');}};
  const list=(trash?deleted:tasks.filter(t=>(!archived||t.archived)&&(execution==='all'||!t.archived&&t.settings.execution===execution))).filter(t=>(kind==='all'||kind===t.kind)&&t.name.toLowerCase().includes(query.toLowerCase()));
  return <section><div className="platform-heading"><div><span className="fn-label">ALL PROJECTS</span><h1>{trash?'任务回收站':'任务列表'}</h1><p>{trash?'删除的任务保留作品与记录，恢复后先放入已归档，定时执行保持暂停。':'每个任务都有独立配置，点击卡片上的创作记录，可以打开之前的作品。'}</p></div><span className="ss-badge">{list.length} 个任务</span></div>
    <div className="task-filters"><div className="segmented" aria-label="任务类型">{[['all','全部'],['video','视频'],['article','文章'],['image','图片']].map(([v,l])=><button key={v} aria-pressed={kind===v} onClick={()=>setKind(v)}>{l}</button>)}</div><select aria-label="执行方式筛选" value={execution} onChange={e=>setExecution(e.target.value)}><option value="all">全部执行方式</option><option value="automatic">定时任务（已启用）</option><option value="manual">手动任务</option></select><input aria-label="搜索任务" placeholder="搜索任务名称…" value={query} onChange={e=>setQuery(e.target.value)}/>{!trash&&<label className="check-line"><input type="checkbox" checked={archived} onChange={e=>{setArchived(e.target.checked);if(e.target.checked)setExecution('all');}}/>已归档</label>}<button className="ss-btn" aria-pressed={trash} onClick={()=>setTrash(v=>!v)}>{trash?'返回任务列表':'回收站'}</button></div>
    {loadingTrash&&trash?<p className="inline-hint">正在读取回收站…</p>:list.length?<div className="task-grid">{list.map(t=>trash?<article className="task-card trash-task-card" key={t.id}><span className="task-type">{kindNames[t.kind]} · 已删除</span><strong>{t.name}</strong><p>{dateText(t.deleted_at||null)} 删除 · {t.run_count||0} 次创作</p><button className="ss-btn" disabled={!!restoring} onClick={()=>restore(t)}>{restoring===t.id?'恢复中…':'从回收站恢复'}</button></article>:<TaskCard key={t.id} task={t} onOpen={onOpen} onDeleted={onDeleted}/>)}</div>:<div className="empty platform-empty"><h2>{trash?'回收站中没有符合条件的任务':query||kind!=='all'||archived?'没有符合条件的任务':'还没有创作任务'}</h2>{!trash&&<button className="ss-btn" onClick={onNew}><Plus/>创建任务</button>}</div>}
  </section>;
}
function NewTask({onClose,onCreated}:{onClose:()=>void;onCreated:(t:CreationTask)=>Promise<void>}){
  const [name,setName]=useState(''),[kind,setKind]=useState<CreationKind>('article'),[busy,setBusy]=useState(false);const {error:setError}=useNotifications(),setNotificationHost=useNotificationHost();const dialog=useRef<HTMLDialogElement>(null),request=useRef(crypto.randomUUID());useEffect(()=>{dialog.current?.showModal();setNotificationHost(dialog.current);return()=>setNotificationHost(null);},[setNotificationHost]);
  const create=async()=>{setBusy(true);try{await onCreated(await api<CreationTask>('/tasks',send('POST',{name,kind,request_id:request.current})));}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
  return <dialog className="new-task-dialog" ref={dialog} onCancel={e=>{e.preventDefault();if(!busy)onClose();}} aria-labelledby="new-task-title"><form onSubmit={e=>{e.preventDefault();create();}}><div className="section-title"><span className="fn-label">A NEW BEGINNING</span><button type="button" className="icon-button" aria-label="关闭新建任务" disabled={busy} onClick={onClose}><X/></button></div><h2 id="new-task-title">新建创作任务</h2><p>先起个名字，再进入专属工作台。</p><fieldset disabled={busy}><label className="field">任务名称<input autoFocus required maxLength={80} value={name} onChange={e=>{setName(e.target.value);request.current=crypto.randomUUID();}} placeholder="例如：每天一个 AI 实用技巧"/></label><span className="field-label">任务类型</span><div className="creation-types">{(['video','article','image'] as const).map(v=>{const Icon=kindIcons[v];return <button type="button" key={v} aria-pressed={kind===v} onClick={()=>{setKind(v);request.current=crypto.randomUUID();}}><Icon/><strong>{kindNames[v]}</strong><small>{v==='video'?'短片 · 图集视频':v==='article'?'构思 · 长文写作':'海报 · 图文卡片'}</small></button>;})}</div><button className="ss-btn ss-primary create-submit" type="submit" disabled={!name.trim()}>{busy?<LoaderCircle className="spin"/>:<ArrowRight/>}创建并进入工作台</button></fieldset></form></dialog>;
}
