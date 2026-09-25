import {createPortal} from 'react-dom';
import {useEffect,useRef,useState} from 'react';
import {ChevronLeft,ChevronRight,Crop,Globe,ImagePlus,LoaderCircle,Lock,LockOpen,RefreshCw,Sparkles,Trash2} from 'lucide-react';
import {api,send} from './api';
import WorkspaceDrawer from './WorkspaceDrawer';
import {AssetUpload} from './MaterialsPage';
import type {Asset,IllustrationSettings,PictureCandidate,PictureSearchResult,PictureJob,SavedModel} from './types';
import {defaultIllustration} from './IllustrationConfiguration';
import PictureSources from './PictureSources';
import SearchPicture from './SearchPicture';

export const pictureCaption=(a:Asset)=>a.provenance?.kind==='ai'?'AI 生成示意图':[a.credit,a.provenance?.license].filter(Boolean).join(' · ').slice(0,300);
type Tab='library'|'web'|'ai'|'crop';
export default function ArticleImagePicker({label,value,caption,locked,hint,settings,assets,disabled,onChange,onAssets,onBusy,onError,onNotice}:{label:string;value:string;caption:string;locked:boolean;hint:string;settings?:IllustrationSettings;assets:Asset[];disabled:boolean;onChange:(id:string,caption:string,locked:boolean)=>void;onAssets:(a:Asset)=>void;onBusy:(busy:boolean)=>void;onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const cfg={...defaultIllustration,...settings};
  const [tab,setTab]=useState<Tab|null>(null),[query,setQuery]=useState(''),[results,setResults]=useState<PictureCandidate[]|null>(null),[searching,setSearching]=useState(false),[models,setModels]=useState<SavedModel[]>([]),[model,setModel]=useState(cfg.model_id),[prompt,setPrompt]=useState(hint+'\n'+cfg.style),[ratio,setRatio]=useState(cfg.ratio),[edit,setEdit]=useState(false),[job,setJob]=useState<PictureJob|null>(null),[pending,setPending]=useState(false),[size,setSize]=useState({w:1,h:1}),[cropRatio,setCropRatio]=useState(1.5),[zoom,setZoom]=useState(1),[cx,setCx]=useState(.5),[cy,setCy]=useState(.5);
  const asset=assets.find(a=>a.id===value),working=pending||!!job;
  const [sources,setSources]=useState<string[]>(cfg.web_sources?.length?cfg.web_sources:['bing','360']),[report,setReport]=useState<PictureSearchResult|null>(null),[searchError,setSearchError]=useState('');
  const pages=useRef(new Map<number,PictureSearchResult>()),searchRequest=useRef<AbortController|null>(null),reportNode=useRef<HTMLDivElement>(null);
  const [loadingPage,setLoadingPage]=useState(1),[retryPage,setRetryPage]=useState<number|null>(null);
  const latest=useRef({onChange,onAssets,onError,onNotice,onBusy});latest.current={onChange,onAssets,onError,onNotice,onBusy};
  const completed=useRef('');
  useEffect(()=>()=>searchRequest.current?.abort(),[]);
  useEffect(()=>{if(tab!=='ai')return;api<SavedModel[]>('/models').then(v=>setModels(v.filter(m=>m.protocol==='images'))).catch(e=>latest.current.onError(e.message));},[tab]);
  useEffect(()=>{latest.current.onBusy(working);return()=>latest.current.onBusy(false);},[working]);
  useEffect(()=>{
    if(!job)return;
    let active=true;
    const accept=(result:PictureJob)=>{
      if(!active||!['ready','failed'].includes(result.status)||completed.current===result.id)return;
      completed.current=result.id;setJob(null);
      if(result.asset){latest.current.onAssets(result.asset);latest.current.onChange(result.asset.id,pictureCaption(result.asset),false);setTab(null);latest.current.onNotice('图片已放入当前文章，请保存修改。');}
      else latest.current.onError(result.error||'图片处理未完成。');
    };
    accept(job);
    const timer=setInterval(()=>api<PictureJob>(`/pictures/${job.id}`).then(accept).catch(()=>{}),1500);
    return()=>{active=false;clearInterval(timer);};
  },[job?.id]);
  const resetSearch=()=>{searchRequest.current?.abort();pages.current.clear();setReport(null);setResults(null);setSearchError('');setRetryPage(null);setSearching(false);};
  const showPage=(result:PictureSearchResult)=>{
    setReport(result);setResults(result.items);
    requestAnimationFrame(()=>{reportNode.current?.scrollIntoView({block:'start'});reportNode.current?.focus({preventScroll:true});});
  };
  const search=async(page=1,restart=false)=>{
    if(restart)resetSearch();
    setSearchError('');setRetryPage(null);
    const cached=pages.current.get(page);
    if(cached){showPage(cached);return;}
    searchRequest.current?.abort();
    const controller=new AbortController();searchRequest.current=controller;
    setSearching(true);setLoadingPage(page);
    if(!restart)reportNode.current?.scrollIntoView({block:'start'});
    try{
      const params=new URLSearchParams({query:query.trim(),details:'true',page:String(page)});sources.forEach(s=>params.append('sources',s));
      const result=await api<PictureSearchResult>('/pictures/search?'+params,{signal:controller.signal});
      if(controller.signal.aborted)return;
      result.page=page;
      if(result.providers.length&&result.providers.every(p=>p.status==='error')){
        if(restart||!report)showPage(result);
        const message=`第 ${page} 页查询失败，所选图片来源暂时无法连接，请更换搜索来源或稍后重试。`;
        setSearchError(message+' '+result.providers.map(p=>`${p.name}：${p.message||'暂不可用'}`).join('；'));setRetryPage(page);onError(message);return;
      }
      const seen=new Set([...pages.current.entries()].filter(([n])=>n<page).flatMap(([,r])=>r.items.map(i=>i.url)));
      const items=result.items.filter(i=>!seen.has(i.url));
      const current={...result,items,duplicates:result.items.length-items.length};
      pages.current.set(page,current);showPage(current);
    }catch(e){if(!controller.signal.aborted){setSearchError(`第 ${page} 页查询失败：${(e as Error).message}`);setRetryPage(page);onError((e as Error).message);}}
    finally{if(!controller.signal.aborted)setSearching(false);}
  };
  const pagination=(position:string)=>report&&<nav className="picture-pagination" aria-label={`图片搜索分页${position}`}>
    <button className="ss-btn" disabled={searching||(report.page||1)<=1} onClick={()=>void search((report.page||1)-1)}>{searching&&loadingPage<(report.page||1)?<LoaderCircle className="spin"/>:<ChevronLeft/>}上一页</button>
    <span>第 <strong>{report.page||1}</strong> 页<small>{searching?`正在查询第 ${loadingPage} 页…`:report.has_more?'可继续查找':report.providers.every(p=>p.status==='error')?'来源暂不可用':(report.page||1)>=50?'已到搜索页数上限':'已到当前结果末页'}</small></span>
    <button className="ss-btn" disabled={searching||!report.has_more} onClick={()=>void search((report.page||1)+1)}>下一页{searching&&loadingPage>(report.page||1)?<LoaderCircle className="spin"/>:<ChevronRight/>}</button>
  </nav>;
  const process=async(action:string,extra:Record<string,unknown>)=>{setPending(true);try{setJob(await api<PictureJob>('/pictures',send('POST',{request_id:crypto.randomUUID(),action,...extra})));}catch(e){onError((e as Error).message);}finally{setPending(false);}};
  const choose=(a:Asset)=>{onChange(a.id,pictureCaption(a),false);setTab(null);};
  const open=(next:Tab)=>{setTab(next);if(next==='web'&&!query)setQuery(hint.split(/[，。；\n]/)[0].slice(0,40));};
  const width=Math.min(1,cropRatio/(size.w/size.h))/zoom,height=Math.min(1,(size.w/size.h)/cropRatio)/zoom;
  const crop={x:(1-width)*cx,y:(1-height)*cy,width,height};
  return <section className="article-picture-entry" aria-label={label}>
    <button type="button" className="article-picture-trigger" aria-label={`设置${label}`} aria-haspopup="dialog" disabled={disabled||working} onClick={()=>open('library')}>
      {working?<LoaderCircle className="spin"/>:value?<img src={`/api/assets/${encodeURIComponent(value)}/file`} alt={label}/>:<ImagePlus/>}
      <span>{label}</span><small>{working?'正在处理…':locked?'已锁定':value?'编辑':'添加'}</small>{locked?<Lock className="picture-entry-arrow"/>:<ChevronRight className="picture-entry-arrow"/>}
    </button>
    {tab&&createPortal(<WorkspaceDrawer title={label+' · 配图'} subtitle="图片替换和裁剪会创建新的素材，保存文章后可在版本记录恢复。" onClose={()=>setTab(null)}>
      <section className="picture-drawer-settings">
        <header><strong>{value?'当前图片':'图片设置'}</strong><div><button type="button" className="text-button" disabled={disabled||working||searching} aria-pressed={locked} onClick={()=>onChange(value,caption,!locked)}>{locked?<Lock size={14}/>:<LockOpen size={14}/>} {locked?'已锁定':'锁定位置'}</button>{value&&<button type="button" className="text-button" disabled={disabled||working||locked||searching} aria-label={`移除${label}`} onClick={()=>{onChange('', '',false);if(tab==='crop')setTab('library');}}><Trash2 size={14}/>移除</button>}</div></header>
        {value&&<><div className="article-picture-current"><img src={`/api/assets/${encodeURIComponent(value)}/file`} alt="当前图片"/><div><strong>{asset?.filename||'已选图片'}</strong><small>{asset?.provenance?.kind==='ai'?'AI 生成':asset?.provenance?.kind==='web'?'联网图片':'本地素材'}</small><small>{asset?.credit} {asset?.provenance?.license||asset?.rights}</small>{asset?.source_url&&<a href={asset.source_url} target="_blank" rel="noreferrer">图片来源 ↗</a>}</div></div><label className="field picture-caption">图片说明与署名<input maxLength={300} value={caption} disabled={disabled||working} onChange={e=>onChange(value,e.target.value,locked)}/></label></>}
        {locked&&<p className="inline-hint">{value?'图片位置已锁定，解锁后可换图、裁剪或移除。':'此位置保持无图，解锁后可添加图片。'}</p>}
      </section>
      <fieldset className="picture-drawer-tools" disabled={disabled||locked}>
      <div className="picture-tabs">{([['library','素材库',ImagePlus],['web','联网找图',Globe],['ai','AI 生成 / 调整',Sparkles],['crop','裁剪',Crop]] as const).map(([id,name,Icon])=><button key={id} disabled={working||searching||(id==='crop'&&!value)} aria-pressed={tab===id} onClick={()=>open(id)}><Icon size={14}/>{name}</button>)}</div>
      {working?<div className="picture-processing large" role="status"><LoaderCircle className="spin"/><strong>{job?.status==='queued'?'图片已排队':'正在处理图片'}</strong><p>可收起此窗口，完成后会放入当前编辑位置。请等待处理完成再保存或离开文章。</p></div>:<>
      {tab==='library'&&<><div className="picture-results">{assets.map(a=><button key={a.id} className="picture-result" onClick={()=>choose(a)}><img loading="lazy" src={`/api/assets/${a.id}/file`} alt={a.filename}/><strong>{a.filename}</strong><small>{a.credit||a.rights}</small></button>)}</div>{!assets.length&&<p className="inline-hint">素材库暂无图片，可以上传、联网搜索或让 AI 生成。</p>}<AssetUpload onError={onError} onUploaded={a=>{if(!a.media_type.startsWith('image/')){onError('文章配图请选择图片素材。');return;}onAssets(a);choose(a);}}/></>}
      {tab==='web'&&<>
        <PictureSources value={sources} disabled={searching} onChange={v=>{setSources(v);resetSearch();}}/>
        <p className="inline-hint">同时搜索勾选的网站并合并去重。输入具体主体，例如“AI 大模型”或“平遥古城 城墙”；授权以来源页面为准。</p>
        <label className="field">图片搜索词<input maxLength={160} value={query} disabled={searching} onChange={e=>{setQuery(e.target.value);resetSearch();}} onKeyDown={e=>{if(e.key==='Enter'&&query.trim().length>=2&&sources.length&&!searching){e.preventDefault();void search(1,true);}}} placeholder="例如：AI 大模型 神经网络"/></label>
        <button className="ss-btn ss-primary" disabled={searching||!sources.length||query.trim().length<2} onClick={()=>void search(1,true)}>{searching?<LoaderCircle className="spin"/>:<Globe/>}{searching?'正在找图…':'搜索图片'}</button>
        {searching&&<div className="picture-search-status" role="status"><LoaderCircle className="spin"/>正在查询第 {loadingPage} 页 · {sources.length} 个图片来源，请稍候…</div>}
        {report&&<div ref={reportNode} tabIndex={-1} className="picture-search-report" role="status"><strong>“{report.query}” · 本页找到 {report.items.length} 张图片</strong><div>{report.providers.map(p=><span key={p.name} className={'picture-provider '+p.status}>{p.name} · {p.status==='error'?'暂不可用':p.status==='empty'?'无匹配':`${p.count} 张`}{p.message&&<small> · {p.message}</small>}</span>)}</div>{!!report.duplicates&&<p>已跳过前面页面出现过的 {report.duplicates} 张图片。</p>}</div>}
        {searchError&&<div className="picture-search-error" role="alert">{searchError}{retryPage!==null&&<button className="text-button" disabled={searching} onClick={()=>void search(retryPage)}><RefreshCw size={14}/>重试第 {retryPage} 页</button>}</div>}
        {pagination('顶部')}
        <div className="picture-results" aria-busy={searching}>{results?.map(r=><article className="picture-result" key={r.id}><SearchPicture picture={r}/><strong>{r.title||'网络图片'}</strong><small>{r.provider} · {new URL(r.page_url).hostname}</small>{r.provider==='Unsplash'?<small>摄影：<a href={r.author_url||r.page_url} target="_blank" rel="noreferrer">{r.credit||'摄影师'}</a> / <a href="https://unsplash.com/?utm_source=self_media_studio&utm_medium=referral" target="_blank" rel="noreferrer">Unsplash</a> · <a href={r.license_url} target="_blank" rel="noreferrer">授权说明</a></small>:<small>{[r.credit,r.license].filter(Boolean).join(' · ')}</small>}<a href={r.page_url} target="_blank" rel="noreferrer">查看来源与授权 ↗</a><button className="ss-btn" disabled={searching} onClick={()=>process('import',{candidate_id:r.id})}>使用这张图片</button></article>)}</div>
        {results?.length===0&&!searchError&&<p className="picture-placeholder">{report?.has_more?'本页没有新的匹配图片，可以继续查看下一页。':'未找到更多匹配图片，可以换用其他来源或更具体的关键词。'}</p>}
        {pagination('底部')}
      </>}
      {tab==='ai'&&<><label className="field">图片模型<select aria-label="图片模型" value={model} onChange={e=>setModel(e.target.value)}><option value="">选择已配置的图片模型</option>{models.map(m=><option key={m.id} value={m.id}>{m.name} · {m.model}</option>)}</select></label>{!models.length&&<p className="inline-hint">请先在“我的模型”添加 Images 图片模型。</p>}{value&&<label className="check-line"><input type="checkbox" checked={edit} disabled={!models.find(m=>m.id===model)?.image_edit} onChange={e=>setEdit(e.target.checked)}/>基于当前图片调整（需要模型支持图片编辑）</label>}<label className="field">{edit?'图片修改要求':'画面描述与风格'}<textarea rows={6} value={prompt} maxLength={4000} onChange={e=>setPrompt(e.target.value)} placeholder="描述主体、场景、光线、构图，或说明希望怎样修改当前图片"/></label><label className="field">图片比例<select value={ratio} onChange={e=>setRatio(e.target.value as typeof ratio)}><option value="landscape">横版 3:2</option><option value="square">方形 1:1</option><option value="portrait">竖版 2:3</option></select></label><p className="inline-hint">生成图片会调用所选模型。AI 图片默认标注为示意图，不能替代真实景点或事件的现场记录。</p><button className="ss-btn ss-primary" disabled={!model||!prompt.trim()||(edit&&!models.find(m=>m.id===model)?.image_edit)} onClick={()=>process(edit?'edit':'generate',{model_id:model,prompt,ratio,...(edit?{asset_id:value}:{})})}><Sparkles/>{edit?'按要求调整图片':'生成并使用'}</button></>}
      {tab==='crop'&&value&&<><div className="picture-crop-preview" style={{aspectRatio:size.w/size.h}}><img src={`/api/assets/${value}/file`} alt="原图裁剪预览" onLoad={e=>setSize({w:e.currentTarget.naturalWidth,h:e.currentTarget.naturalHeight})}/><span style={{left:crop.x*100+'%',top:crop.y*100+'%',width:width*100+'%',height:height*100+'%'}}/></div><label className="field">裁剪比例<select value={cropRatio} onChange={e=>setCropRatio(Number(e.target.value))}><option value={1.5}>横版 3:2</option><option value={2.35}>公众号封面 2.35:1</option><option value={1}>方形 1:1</option><option value={2/3}>竖版 2:3</option></select></label><label className="field">放大裁剪范围<input type="range" min={1} max={3} step={.05} value={zoom} onChange={e=>setZoom(Number(e.target.value))}/></label><label className="field">水平位置<input type="range" min={0} max={1} step={.01} value={cx} onChange={e=>setCx(Number(e.target.value))}/></label><label className="field">垂直位置<input type="range" min={0} max={1} step={.01} value={cy} onChange={e=>setCy(Number(e.target.value))}/></label><button className="ss-btn ss-primary" onClick={()=>process('crop',{asset_id:value,...crop})}><Crop/>保存裁剪并使用</button></>}
      </>}
      </fieldset>
    </WorkspaceDrawer>,document.getElementById('science-fieldnotes')||document.body)}
  </section>;
}
