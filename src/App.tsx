import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, ArrowUpRight, Bird, Check, CircleAlert, Clapperboard, Clock3, LoaderCircle, Settings2, ShieldCheck, X } from 'lucide-react';
import { api, dateText, send } from './api';
import type { Health, Job, Page, Settings, Topic } from './types';
import PelicanScene from './PelicanScene';
import ReviewPage from './ReviewPage';
import SettingsPage from './SettingsPage';
import {SourceSettings} from './ConnectionSettings';

export const statuses={queued:'等待制作',running:'制作中',needs_review:'待审核',approved:'已通过',failed:'需要处理',changes_requested:'待修改',draft:'文案已更新'};
const pages: {id:Page;name:string}[]=[{id:'home',name:'今日漫游'},{id:'topics',name:'每日选题'},{id:'review',name:'成片审核'},{id:'flow',name:'每日路线'}];

export default function App(){
  const [page,setPage]=useState<Page>(()=>pages.some(p=>p.id===location.hash.slice(1))?location.hash.slice(1) as Page:'home');
  const [topics,setTopics]=useState<Topic[]>([]),[jobs,setJobs]=useState<Job[]>([]),[health,setHealth]=useState<Health|null>(null),[settings,setSettings]=useState<Settings|null>(null);
  const [selected,setSelected]=useState(''),[jobId,setJobId]=useState('');
  const [loading,setLoading]=useState(true),[error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState('');
  const refresh=useCallback(async()=>{
    const [h,t,j,s]=await Promise.all([api<Health>('/health'),api<Topic[]>('/topics'),api<Job[]>('/jobs'),api<Settings>('/settings')]);
    setHealth(h);setTopics(t);setJobs(j);setSettings(s);setError('');return j;
  },[]);
  useEffect(()=>{refresh().catch(e=>setError(e.message)).finally(()=>setLoading(false));},[refresh]);
  useEffect(()=>{const timer=setInterval(()=>{api<Job[]>('/jobs').then(setJobs).catch(()=>{});},3500);return()=>clearInterval(timer);},[]);
  useEffect(()=>{const onHash=()=>{const next=location.hash.slice(1);if(pages.some(p=>p.id===next))setPage(next as Page);};addEventListener('hashchange',onHash);return()=>removeEventListener('hashchange',onHash);},[]);
  const navigate=(next:Page)=>{setPage(next);location.hash=next;window.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'});};
  const tell=(text:string)=>setNotice(text);
  const choose=(id:string)=>{setSelected(id);navigate('topics');};
  const run=async(topic:Topic)=>{
    setBusy('create');setError('');
    try{const job=await api<Job>('/jobs',send('POST',{topic_id:topic.id,mode:'ai',request_id:crypto.randomUUID()}));setJobId(job.id);await refresh();navigate('review');tell('制作任务已加入队列，进度会自动更新。');}catch(e){setError((e as Error).message);}finally{setBusy('');}
  };
  const curate=async()=>{setBusy('curate');setError('');try{const result=await api<{selected:number;note:string}>('/curate',send('POST'));await refresh();tell(`已推荐 ${result.selected} 个选题。${result.note}`);}catch(e){setError((e as Error).message);}finally{setBusy('');}};
  const selectedTopic=topics.find(t=>t.id===selected)||topics[0];
  const pending=jobs.filter(j=>j.status==='needs_review').length;
  return <div id="science-fieldnotes">
    <a className="skip-link" href="#main">跳到主要内容</a>
    <header className="fn-header"><button className="fn-brand" onClick={()=>navigate('home')} aria-label="知序，回到首页"><span className="fn-brand-mark"><Bird/></span><span><strong>{settings?.account_name||'知序'} · 科学漫游编辑部</strong><small>THE LITTLE SCIENCE CLUB</small></span></button>
      <nav className="fn-navigation" aria-label="主导航">{pages.map(p=><button key={p.id} className="fn-nav" aria-label={p.name} aria-current={page===p.id?'page':undefined} aria-selected={page===p.id} onClick={()=>navigate(p.id)}>{p.name}{p.id==='review'&&pending>0&&<span className="nav-count" aria-hidden="true">{pending}</span>}</button>)}</nav>
      <span className="fn-edition"><span className="fn-dot"/>本地工作台 / V. 0.1</span>
    </header>
    {error&&<div className="message error" role="alert"><CircleAlert/><span>{error}</span><button onClick={()=>setError('')} aria-label="关闭错误"><X/></button></div>}
    {notice&&<div className="message" role="status"><Check/><span>{notice}</span><button onClick={()=>setNotice('')} aria-label="关闭提示"><X/></button></div>}
    <main id="main">
      {loading?<div className="empty"><LoaderCircle className="spin"/><h2>正在翻开工作手记…</h2></div>:!health?<div className="empty"><CircleAlert/><h2>工作台暂时未连接</h2><p>请启动后端服务，再重新连接。</p><button className="ss-btn" onClick={()=>refresh().catch(e=>setError(e.message))}>重新连接</button></div>:<>
        {page==='home'&&<><PelicanScene onExplore={()=>navigate('topics')}/>
          <div className="fn-notes-heading"><div><span className="fn-label">THE FIELD NOTES / 今日手记</span><h2>先从一个好问题出发。</h2></div><button className="fn-text-action" onClick={()=>navigate('topics')}>翻阅选题 <ArrowRight/></button></div>
          {!topics.length?<div className="empty home-empty"><Bird/><h3>还没有选题，先配置采集网址。</h3><p>从你关注的网站，收集第一条创作线索。</p><button className="ss-btn ss-primary" onClick={()=>navigate('topics')}>配置采集数据 <ArrowRight/></button></div>:<div className="fn-notes-grid">{topics.slice(0,3).map((topic,i)=><button key={topic.id} className="fn-note" onClick={()=>choose(topic.id)}><span className="fn-note-top"><span>0{i+1} / 网页资料</span><span>{topic.source}</span></span><h3>{topic.title}</h3><span className="fn-note-bottom">网络采集 · 查看资料<ArrowUpRight/></span></button>)}</div>}
          <div className="fn-daily"><span><span className="fn-dot"/>{settings?.schedule_enabled?`${settings.schedule_time} 自动出发`:'每日计划待启用'}</span><p>收集灵感 <span>—</span> 写短标题 <span>—</span> 剪成短片 <span>—</span> 等你过目</p><span className="fn-daily-end">a little science, a little joy.</span></div>
          {jobs.length>0&&<button className="latest-job" onClick={()=>{setJobId(jobs[0].id);navigate('review');}}><Clapperboard/><span><strong>{jobs[0].script?.title||topics.find(t=>t.id===jobs[0].topic_id)?.title||'最新制作任务'}</strong><small>{statuses[jobs[0].status]} · {dateText(jobs[0].created_at)}</small></span><ArrowRight/></button>}
        </>}
        {page==='topics'&&settings&&<TopicsPage topics={topics} topic={selectedTopic} onSelect={setSelected} onCreate={run} onCollected={refresh} onSaved={setSettings} onCurate={curate} busy={busy} health={health} settings={settings} jobs={jobs} onOpenJob={id=>{setJobId(id);navigate('review');}}/>}
        {page==='review'&&<ReviewPage jobs={jobs} selectedId={jobId} onSelect={setJobId} onRefresh={refresh} onError={setError} onNotice={tell} onExplore={()=>navigate('topics')}/>}
        {page==='flow'&&settings&&<SettingsPage onConnectionChanged={refresh} settings={settings} health={health} onSaved={s=>{setSettings(s);refresh().catch(()=>{});}} onError={setError} onNotice={tell}/>}
      </>}
    </main>
    <footer className="ss-footer"><span>知序 · 科学漫游编辑部</span><span>{health?.ai_ready?`AI 已配置 · ${health.model}`:'10 秒无配音短片 · AI 服务待配置'}　/　人工审核后手动发布</span></footer>
  </div>;
}

function TopicsPage({topics,topic,onSelect,onCreate,onCollected,onSaved,onCurate,busy,health,settings,jobs,onOpenJob}:{topics:Topic[];topic:Topic|undefined;onSelect:(id:string)=>void;onCreate:(t:Topic)=>void;onCollected:()=>Promise<unknown>;onSaved:(s:Settings)=>void;onCurate:()=>void;busy:string;health:Health;settings:Settings;jobs:Job[];onOpenJob:(id:string)=>void}){
  const current=topic||topics[0];
  const related=jobs.find(j=>j.topic_id===current?.id);
  const configured=settings.sources.length>0||settings.custom_sources.some(s=>s.enabled);
  return <section><div className="ss-heading"><div><div className="ss-eyebrow">FIELD NOTES / 每日采风</div><h1>捡起一个好问题。</h1><p>配置采集网址，把网络上的发现变成今天的创作手记。</p></div></div>
    <SourceSettings settings={settings} onSaved={onSaved} onCollected={onCollected}/>
    <div className="ss-plan"><div className="ss-plan-left"><Clock3/><span>{settings.schedule_enabled?`每日 ${settings.schedule_time} · 北京时间`:'定时计划未启用'}</span></div><div className="ss-plan-flow"><b>按需制作</b><span>→</span><b>10 秒图集 / 视频</b><span>→</span><b>你审核</b></div></div>
    <div className="topic-results-heading"><div><h2>采集到的选题 <span className="ss-badge">{topics.length}</span></h2><p>读取原文、匹配画面，再生成简短标题。</p></div><button className="ss-btn" disabled={!!busy||!health.ai_ready||!topics.length} onClick={onCurate}>{busy==='curate'?<LoaderCircle className="spin"/>:<Bird/>}{busy==='curate'?'正在筛选…':'AI 推荐最多 5 题'}</button></div>
    {!current?<div className="empty"><Bird/><h2>今天的手记还是空白。</h2><p>{configured?'点击上方“保存并采集”获取资料，支持任意领域的公开网页。':'还没有配置采集源。请在上方输入网址，点击“保存并采集”。'}</p></div>:<div className="ss-board"><div><div className="ss-section-label">选题候选 <span>{topics.length} 个问题，等你探索</span></div><div className="ss-topics">{topics.map((t,i)=><button key={t.id} className="ss-topic" onClick={()=>onSelect(t.id)} aria-pressed={t.id===current.id}><span className="ss-topic-meta"><span className="ss-num">{String(i+1).padStart(2,'0')}</span>{t.source}</span><strong className="ss-topic-title">{t.title}</strong><span className="ss-topic-bottom"><span>{dateText(t.published_at)}</span><span>原文待核验</span></span></button>)}</div></div>
      <article className="ss-detail"><div className="ss-cover"><span className="ss-cover-tag">网页资料线索</span><div className="ss-cover-label"><span>A LITTLE WONDER</span><strong>网页观察手记</strong></div></div><div className="ss-detail-body"><span className="ss-badge ss-green">网络采集</span> <span className="ss-badge ss-amber">需人工核验</span><h2>{current.title}</h2>{current.page_data&&<p className="inline-hint">{({browser:'浏览器加载',http:'网页直读',rss:'订阅摘要',manual:'手动导入'} as Record<string,string>)[current.page_data.method]||'网页采集'} · {current.page_data.full_text?'已保存正文':'页面摘要'} · {current.page_data.images.length} 张图片线索</p>}<div className="ss-field"><div className="ss-field-label">来源摘要</div><p>{current.angle}</p></div><div className="ss-field"><div className="ss-field-label">依据与素材</div><p>{current.rights}</p>{current.sources.map(s=><a key={s.id} className="source-link" href={s.url} target="_blank" rel="noreferrer">{s.publisher} · 查看原文<ArrowUpRight/></a>)}</div>
      <details className="script-peek"><summary>查看已采集正文与链接</summary><p className="captured-text">{current.sources[0]?.text}</p>{current.page_data?.links.map(link=><a className="source-link" key={link.url} href={link.url} target="_blank" rel="noreferrer">{link.title}<ArrowUpRight/></a>)}</details>
      {current.curation&&<div className="ss-field"><div className="ss-field-label">AI 推荐理由 · {dateText(current.curation.at)}</div><p>{current.curation.reason}</p></div>}
      {!health.ai_ready&&<p className="inline-hint"><Settings2/>制作成片需要 AI。<a href="#flow">前往每日路线配置模型</a></p>}
      <div className="ss-detail-footer"><span className="ss-small">无配音 · 9:16 · 10 秒</span><button className="ss-btn ss-primary" disabled={!!busy||!health.ai_ready} onClick={()=>onCreate(current)}>{busy==='create'?<LoaderCircle className="spin"/>:<Clapperboard/>}制作这一题</button></div>
      {related&&<button className="related-job" onClick={()=>onOpenJob(related.id)}>{statuses[related.status]} · 查看已有任务 <ArrowRight/></button>}
      </div></article></div>}
    <div className="ss-bottomline"><ShieldCheck/><span>用相关图片或视频，搭配一两句短标题。可在“编辑文案与画面”上传素材并调整顺序。</span></div>
  </section>;
}
