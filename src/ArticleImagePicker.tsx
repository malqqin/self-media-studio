import {createPortal} from 'react-dom';
import {useEffect,useRef,useState} from 'react';
import {Crop,Globe,ImagePlus,LoaderCircle,Lock,LockOpen,Sparkles,Trash2} from 'lucide-react';
import {api,send} from './api';
import WorkspaceDrawer from './WorkspaceDrawer';
import {AssetUpload} from './MaterialsPage';
import type {Asset,IllustrationSettings,PictureCandidate,PictureSearchResult,PictureJob,SavedModel} from './types';
import {defaultIllustration} from './IllustrationConfiguration';

export const pictureCaption=(a:Asset)=>a.provenance?.kind==='ai'?'AI 生成示意图':[a.credit,a.provenance?.license].filter(Boolean).join(' · ').slice(0,300);
type Tab='library'|'web'|'ai'|'crop';
function SearchPicture({picture}:{picture:PictureCandidate}){
  const [failed,setFailed]=useState(false);
  return failed?<div className="picture-preview-missing">预览暂不可用，可查看来源</div>:<img loading="lazy" src={picture.preview_url||picture.url} alt={picture.title} referrerPolicy="no-referrer" onError={()=>setFailed(true)}/>;
}
export default function ArticleImagePicker({label,value,caption,locked,hint,settings,assets,disabled,onChange,onAssets,onBusy,onError,onNotice}:{label:string;value:string;caption:string;locked:boolean;hint:string;settings?:IllustrationSettings;assets:Asset[];disabled:boolean;onChange:(id:string,caption:string,locked:boolean)=>void;onAssets:(a:Asset)=>void;onBusy:(busy:boolean)=>void;onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const cfg={...defaultIllustration,...settings};
  const [tab,setTab]=useState<Tab|null>(null),[query,setQuery]=useState(''),[results,setResults]=useState<PictureCandidate[]|null>(null),[searching,setSearching]=useState(false),[models,setModels]=useState<SavedModel[]>([]),[model,setModel]=useState(cfg.model_id),[prompt,setPrompt]=useState(hint+'\n'+cfg.style),[ratio,setRatio]=useState(cfg.ratio),[edit,setEdit]=useState(false),[job,setJob]=useState<PictureJob|null>(null),[pending,setPending]=useState(false),[size,setSize]=useState({w:1,h:1}),[cropRatio,setCropRatio]=useState(1.5),[zoom,setZoom]=useState(1),[cx,setCx]=useState(.5),[cy,setCy]=useState(.5);
  const asset=assets.find(a=>a.id===value),working=pending||!!job;
  const [source,setSource]=useState<'web'|'licensed'>('web'),[report,setReport]=useState<PictureSearchResult|null>(null),[searchError,setSearchError]=useState('');
  const latest=useRef({onChange,onAssets,onError,onNotice,onBusy});latest.current={onChange,onAssets,onError,onNotice,onBusy};
  const completed=useRef('');
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
  const search=async()=>{
    setSearching(true);setResults(null);setReport(null);setSearchError('');
    try{
      const result=await api<PictureSearchResult>('/pictures/search?'+new URLSearchParams({query:query.trim(),source,details:'true'}));
      setReport(result);setResults(result.items);
      if(result.providers.every(p=>p.status==='error')){
        const message=source==='licensed'?'两个授权图库暂时都无法连接，可切换“必应图片”继续查找。':'图片来源暂时无法连接，请稍后重试，或上传图片、使用 AI 生成。';
        setSearchError(message);onError(message);
      }
    }catch(e){setSearchError((e as Error).message);onError((e as Error).message);}finally{setSearching(false);}
  };
  const process=async(action:string,extra:Record<string,unknown>)=>{setPending(true);try{setJob(await api<PictureJob>('/pictures',send('POST',{request_id:crypto.randomUUID(),action,...extra})));}catch(e){onError((e as Error).message);}finally{setPending(false);}};
  const choose=(a:Asset)=>{onChange(a.id,pictureCaption(a),false);setTab(null);};
  const open=(next:Tab)=>{setTab(next);if(next==='web'&&!query)setQuery(hint.split(/[，。；\n]/)[0].slice(0,40));};
  const width=Math.min(1,cropRatio/(size.w/size.h))/zoom,height=Math.min(1,(size.w/size.h)/cropRatio)/zoom;
  const crop={x:(1-width)*cx,y:(1-height)*cy,width,height};
  return <section className="article-picture-card" aria-label={label}>
    <header><strong><ImagePlus size={15}/>{label}</strong><button type="button" className="text-button" disabled={disabled||working} aria-pressed={locked} onClick={()=>onChange(value,caption,!locked)}>{locked?<Lock size={14}/>:<LockOpen size={14}/>} {locked?'已锁定':'锁定位置'}</button></header>
    {value?<div className="article-picture-current"><img src={`/api/assets/${encodeURIComponent(value)}/file`} alt={label}/><div><strong>{asset?.filename||'已选图片'}</strong><small>{asset?.provenance?.kind==='ai'?'AI 生成':asset?.provenance?.kind==='web'?'联网图片':'本地素材'}</small><small>{asset?.credit} {asset?.provenance?.license||asset?.rights}</small>{asset?.source_url&&<a href={asset.source_url} target="_blank" rel="noreferrer">图片来源 ↗</a>}</div></div>:<p className="picture-placeholder">{locked?'此位置保持无图，解锁后可添加。':'为这一处内容选择一张图片'}</p>}
    {working?<div className="picture-processing" role="status"><LoaderCircle className="spin"/>正在处理这张图片…</div>:<div className="picture-card-actions"><button className="ss-btn" disabled={disabled||locked} onClick={()=>open('library')}><ImagePlus/>{value?'换图':'选择图片'}</button><button className="ss-btn" disabled={disabled||locked} onClick={()=>open('web')}><Globe/>联网找图</button><button className="ss-btn" disabled={disabled||locked} onClick={()=>open('ai')}><Sparkles/>AI 配图</button>{value&&<><button className="ss-btn" disabled={disabled||locked} onClick={()=>open('crop')}><Crop/>裁剪</button><button className="text-button" disabled={disabled||locked} aria-label={`移除${label}`} onClick={()=>onChange('', '',false)}><Trash2/></button></>}</div>}
    {value&&<label className="field picture-caption">图片说明与署名<input maxLength={300} value={caption} disabled={disabled||working} onChange={e=>onChange(value,e.target.value,locked)}/></label>}
    {tab&&createPortal(<WorkspaceDrawer title={label+' · 配图'} subtitle="图片替换和裁剪会创建新的素材，保存文章后可在版本记录恢复。" onClose={()=>setTab(null)}>
      <div className="picture-tabs">{([['library','素材库'],['web','联网找图'],['ai','AI 生成 / 调整'],['crop','裁剪']] as const).map(([id,name])=><button key={id} disabled={working||searching||(id==='crop'&&!value)} aria-pressed={tab===id} onClick={()=>setTab(id)}>{name}</button>)}</div>
      {working?<div className="picture-processing large" role="status"><LoaderCircle className="spin"/><strong>{job?.status==='queued'?'图片已排队':'正在处理图片'}</strong><p>可收起此窗口，完成后会放入当前编辑位置。请等待处理完成再保存或离开文章。</p></div>:<>
      {tab==='library'&&<><div className="picture-results">{assets.map(a=><button key={a.id} className="picture-result" onClick={()=>choose(a)}><img loading="lazy" src={`/api/assets/${a.id}/file`} alt={a.filename}/><strong>{a.filename}</strong><small>{a.credit||a.rights}</small></button>)}</div>{!assets.length&&<p className="inline-hint">素材库暂无图片，可以上传、联网搜索或让 AI 生成。</p>}<AssetUpload onError={onError} onUploaded={a=>{if(!a.media_type.startsWith('image/')){onError('文章配图请选择图片素材。');return;}onAssets(a);choose(a);}}/></>}
      {tab==='web'&&<>
        <label className="field">搜索来源<select value={source} disabled={searching} onChange={e=>{setSource(e.target.value as typeof source);setReport(null);setResults(null);setSearchError('');}}><option value="web">必应图片 · 支持中文搜索</option><option value="licensed">开放授权图库 · Wikimedia / Openverse</option></select></label>
        <p className="inline-hint">{source==='web'?'输入具体地点、人物或物品，例如“平遥古城 城墙”。网络图片保留来源，授权以原页面为准。':'同时查询两个开放授权图库，附作者和授权信息。英文主体名称通常结果更多。'}</p>
        <label className="field">图片搜索词<input maxLength={160} value={query} disabled={searching} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&query.trim().length>=2&&!searching){e.preventDefault();void search();}}} placeholder={source==='web'?'例如：平遥古城 城墙':'例如：Pingyao ancient city'}/></label>
        <button className="ss-btn ss-primary" disabled={searching||query.trim().length<2} onClick={search}>{searching?<LoaderCircle className="spin"/>:<Globe/>}{searching?'正在找图…':'搜索图片'}</button>
        {searching&&<div className="picture-search-status" role="status"><LoaderCircle className="spin"/>正在{source==='web'?'搜索相关图片':'查询两个授权图库'}，请稍候…</div>}
        {report&&<div className="picture-search-report" role="status"><strong>“{report.query}” · 找到 {report.items.length} 张图片</strong><div>{report.providers.map(p=><span key={p.name} className={'picture-provider '+p.status}>{p.name} · {p.status==='error'?'暂不可用':p.status==='empty'?'无匹配':`${p.count} 张`}</span>)}</div></div>}
        {searchError&&<p className="picture-search-error" role="alert">{searchError}</p>}
        <div className="picture-results">{results?.map(r=><article className="picture-result" key={r.id}><SearchPicture picture={r}/><strong>{r.title||'网络图片'}</strong><small>{r.provider} · {new URL(r.page_url).hostname}</small><small>{[r.credit,r.license].filter(Boolean).join(' · ')}</small><a href={r.page_url} target="_blank" rel="noreferrer">查看来源与授权 ↗</a><button className="ss-btn" onClick={()=>process('import',{candidate_id:r.id})}>使用这张图片</button></article>)}</div>
        {results?.length===0&&!searchError&&<p className="picture-placeholder">{source==='web'?'未找到匹配图片，试试具体地点或主体名称，去掉长句和风格描述。':'已连接的图库未找到符合授权条件的图片，可以换用英文关键词，或切换必应图片。'}</p>}
      </>}
      {tab==='ai'&&<><label className="field">图片模型<select aria-label="图片模型" value={model} onChange={e=>setModel(e.target.value)}><option value="">选择已配置的图片模型</option>{models.map(m=><option key={m.id} value={m.id}>{m.name} · {m.model}</option>)}</select></label>{!models.length&&<p className="inline-hint">请先在“我的模型”添加 Images 图片模型。</p>}{value&&<label className="check-line"><input type="checkbox" checked={edit} disabled={!models.find(m=>m.id===model)?.image_edit} onChange={e=>setEdit(e.target.checked)}/>基于当前图片调整（需要模型支持图片编辑）</label>}<label className="field">{edit?'图片修改要求':'画面描述与风格'}<textarea rows={6} value={prompt} maxLength={4000} onChange={e=>setPrompt(e.target.value)} placeholder="描述主体、场景、光线、构图，或说明希望怎样修改当前图片"/></label><label className="field">图片比例<select value={ratio} onChange={e=>setRatio(e.target.value as typeof ratio)}><option value="landscape">横版 3:2</option><option value="square">方形 1:1</option><option value="portrait">竖版 2:3</option></select></label><p className="inline-hint">生成图片会调用所选模型。AI 图片默认标注为示意图，不能替代真实景点或事件的现场记录。</p><button className="ss-btn ss-primary" disabled={!model||!prompt.trim()||(edit&&!models.find(m=>m.id===model)?.image_edit)} onClick={()=>process(edit?'edit':'generate',{model_id:model,prompt,ratio,...(edit?{asset_id:value}:{})})}><Sparkles/>{edit?'按要求调整图片':'生成并使用'}</button></>}
      {tab==='crop'&&value&&<><div className="picture-crop-preview" style={{aspectRatio:size.w/size.h}}><img src={`/api/assets/${value}/file`} alt="原图裁剪预览" onLoad={e=>setSize({w:e.currentTarget.naturalWidth,h:e.currentTarget.naturalHeight})}/><span style={{left:crop.x*100+'%',top:crop.y*100+'%',width:width*100+'%',height:height*100+'%'}}/></div><label className="field">裁剪比例<select value={cropRatio} onChange={e=>setCropRatio(Number(e.target.value))}><option value={1.5}>横版 3:2</option><option value={2.35}>公众号封面 2.35:1</option><option value={1}>方形 1:1</option><option value={2/3}>竖版 2:3</option></select></label><label className="field">放大裁剪范围<input type="range" min={1} max={3} step={.05} value={zoom} onChange={e=>setZoom(Number(e.target.value))}/></label><label className="field">水平位置<input type="range" min={0} max={1} step={.01} value={cx} onChange={e=>setCx(Number(e.target.value))}/></label><label className="field">垂直位置<input type="range" min={0} max={1} step={.01} value={cy} onChange={e=>setCy(Number(e.target.value))}/></label><button className="ss-btn ss-primary" onClick={()=>process('crop',{asset_id:value,...crop})}><Crop/>保存裁剪并使用</button></>}
      </>}
    </WorkspaceDrawer>,document.getElementById('science-fieldnotes')||document.body)}
  </section>;
}
