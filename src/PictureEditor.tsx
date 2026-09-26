import {useEffect,useRef,useState} from 'react';
import {Check,Crop,Eraser,Eye,ImageUp,LoaderCircle,Pencil,Redo2,RotateCcw,Sparkles,Undo2} from 'lucide-react';
import {api,send} from './api';
import WorkspaceDrawer from './WorkspaceDrawer';
import SearchPicture from './SearchPicture';
import type {Asset,PictureCandidate,PictureJob,SavedModel} from './types';
import './picture-editor.css';

export type PictureEditorSource={asset:Asset;candidate?:never}|{candidate:PictureCandidate;asset?:never};
type Tool='enhance'|'remove_watermark'|'crop'|'edit';
const tools=[['enhance','变清晰',ImageUp],['remove_watermark','去水印',Eraser],['crop','裁剪',Crop],['edit','AI 调整',Sparkles]] as const;
const operationNames:Record<string,string>={enhance:'变清晰',remove_watermark:'去水印',crop:'裁剪',edit:'AI 调整',generate:'AI 生成'};
const operationName=(a:Asset)=>operationNames[a.provenance?.operation||'']||'图片版本';
const assetUrl=(a:Asset)=>`/api/assets/${encodeURIComponent(a.id)}/file`;

// Asset derivatives retain a parent pointer, so undo also works after reopening.
function lineage(source:Asset|undefined,assets:Asset[]){
  const items:Asset[]=[],seen=new Set<string>();let current=source;
  while(current&&!seen.has(current.id)&&items.length<50){items.unshift(current);seen.add(current.id);current=assets.find(a=>a.id===current?.provenance?.parent_asset_id);}
  return {items,index:items.length-1};
}

export default function PictureEditor({source,assets,initialMode='preview',initialTool='enhance',defaultModel='',readOnly=false,onClose,onUse,onAssets,onBusy,onError,onNotice}:{source:PictureEditorSource;assets:Asset[];initialMode?:'preview'|'edit';initialTool?:Tool;defaultModel?:string;readOnly?:boolean;onClose:()=>void;onUse:(a:Asset)=>void;onAssets:(a:Asset)=>void;onBusy:(busy:boolean)=>void;onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const [history,setHistory]=useState(()=>lineage(source.asset,assets)),[mode,setMode]=useState(initialMode),[tool,setTool]=useState<Tool>(initialTool);
  const [models,setModels]=useState<SavedModel[]>([]),[model,setModel]=useState(defaultModel),[modelsLoading,setModelsLoading]=useState(false),[modelError,setModelError]=useState('');
  const [prompt,setPrompt]=useState(''),[watermark,setWatermark]=useState(''),[strength,setStrength]=useState(1.5),[scale,setScale]=useState(2);
  const [size,setSize]=useState({w:1,h:1}),[cropRatio,setCropRatio]=useState(1.5),[zoom,setZoom]=useState(1),[cx,setCx]=useState(.5),[cy,setCy]=useState(.5);
  const [compare,setCompare]=useState(false),[displayZoom,setDisplayZoom]=useState(1),[loaded,setLoaded]=useState(false),[loadError,setLoadError]=useState(false);
  const [pending,setPending]=useState(''),[job,setJob]=useState<{value:PictureJob;label:string;apply:boolean}|null>(null),[pollError,setPollError]=useState(''),[pollRetry,setPollRetry]=useState(0);
  const stage=useRef<HTMLDivElement>(null),[viewport,setViewport]=useState({w:600,h:420});
  const busy=!!pending||!!job,original=history.items[0],current=history.items[history.index],shown=compare?original:current;
  const latest=useRef({onUse,onAssets,onBusy,onError,onNotice});latest.current={onUse,onAssets,onBusy,onError,onNotice};
  const done=useRef(new Set<string>()),started=useRef(false),submitting=useRef(false);
  useEffect(()=>{const node=stage.current!;const observer=new ResizeObserver(()=>setViewport({w:node.clientWidth,h:node.clientHeight}));observer.observe(node);return()=>observer.disconnect();},[]);
  useEffect(()=>{latest.current.onBusy(busy);return()=>latest.current.onBusy(false);},[busy]);
  useEffect(()=>{setLoaded(false);setLoadError(false);setDisplayZoom(1);},[shown?.id]);
  useEffect(()=>{setZoom(1);setCx(.5);setCy(.5);setCompare(false);},[current?.id]);
  useEffect(()=>{
    if(mode!=='edit')return;
    let active=true;setModelsLoading(true);
    api<SavedModel[]>('/models').then(values=>{if(!active)return;const capable=values.filter(m=>m.protocol==='images'&&m.image_edit);setModels(capable);setModel(v=>capable.some(m=>m.id===v)?v:capable[0]?.id||'');}).catch(e=>{if(active)setModelError(e.message);}).finally(()=>{if(active)setModelsLoading(false);});
    return()=>{active=false;};
  },[mode]);
  const process=async(action:string,label:string,extra:Record<string,unknown>={},apply=false)=>{
    if(submitting.current||job||readOnly)return;
    submitting.current=true;setPending(label);setCompare(false);setPollError('');
    try{const value=await api<PictureJob>('/pictures',send('POST',{request_id:crypto.randomUUID(),action,...extra}));setJob({value,label,apply});}
    catch(e){latest.current.onError((e as Error).message);}
    finally{submitting.current=false;setPending('');}
  };
  useEffect(()=>{
    if(initialMode==='edit'&&source.candidate&&!started.current){started.current=true;void process('import','载入原图',{candidate_id:source.candidate.id});}
  },[]);
  useEffect(()=>{
    if(!job)return;
    let active=true,timer:ReturnType<typeof setTimeout>,failures=0;
    const accept=(value:PictureJob)=>{
      if(!active)return true;
      if(!['ready','failed'].includes(value.status))return false;
      if(done.current.has(value.id))return true;
      done.current.add(value.id);setJob(null);setPollError('');
      if(value.status==='ready'&&value.asset){
        const next=value.asset;latest.current.onAssets(next);
        setHistory(h=>h.items[h.index]?.id===next.id?h:({items:[...h.items.slice(0,h.index+1),next],index:h.index+1}));
        if(job.apply)latest.current.onUse(next);
        else if(job.label!=='载入原图')latest.current.onNotice(job.label+'已完成，可对比或撤回；点击“用此图”后替换文章图片。');
      }else latest.current.onError(value.error||'图片处理未完成，当前图片已保留。');
      return true;
    };
    const poll=async()=>{
      try{const value=await api<PictureJob>(`/pictures/${job.value.id}`);if(!active)return;failures=0;setPollError('');if(accept(value))return;}
      catch{if(!active)return;if(++failures>=3){setPollError('暂时无法获取处理结果，重试查询不会重复处理图片。');return;}}
      timer=setTimeout(poll,1500);
    };
    if(!accept(job.value))timer=setTimeout(poll,1000);
    return()=>{active=false;clearTimeout(timer);};
  },[job,pollRetry]);
  const startEdit=()=>{setMode('edit');if(!current&&source.candidate)void process('import','载入原图',{candidate_id:source.candidate.id});};
  const useImage=()=>{if(current)onUse(current);else if(source.candidate)void process('import','载入原图',{candidate_id:source.candidate.id},true);};
  const width=Math.min(1,cropRatio/(size.w/size.h))/zoom,height=Math.min(1,(size.w/size.h)/cropRatio)/zoom;
  const crop={x:(1-width)*cx,y:(1-height)*cy,width,height};
  const ai=tool==='edit'||tool==='remove_watermark',canEdit=!!current&&!busy&&loaded&&!loadError&&!readOnly&&!compare;
  const runTool=()=>void process(tool,tools.find(t=>t[0]===tool)![1],{asset_id:current.id,...(tool==='crop'?crop:tool==='enhance'?{strength,scale}:{model_id:model,prompt:tool==='edit'?prompt:watermark,ratio:size.w/size.h>1.15?'landscape':size.h/size.w>1.15?'portrait':'square'})});
  return <WorkspaceDrawer title={mode==='edit'?'图片编辑器':'图片预览'} subtitle="编辑保留每一步原图，选好后点击「用此图」替换文章中的图片。" placement="center" className="picture-editor-dialog" onClose={onClose} closeDisabled={busy}
    footer={<><span className="picture-editor-footer-note">{busy?'正在处理，请稍候…':readOnly?'图片位置已锁定，解锁后可编辑或换图。':history.index>0?`当前：${operationName(current)} · 更改尚未应用到文章`:'原图保留在素材库'}</span><div className="picture-editor-footer-actions"><button className="ss-btn" disabled={busy} onClick={onClose}>返回</button>{mode==='preview'&&<button className="ss-btn" disabled={busy||readOnly} onClick={startEdit}><Pencil/>编辑</button>}<button className="ss-btn ss-primary" disabled={busy||readOnly} onClick={useImage}><Check/>用此图</button></div></>}>
    <div className="picture-editor-toolbar"><div><button className="ss-btn" aria-label="撤回" disabled={busy||history.index<=0||readOnly} onClick={()=>setHistory(h=>({...h,index:h.index-1}))}><Undo2/>撤回</button><button className="ss-btn" aria-label="重做" disabled={busy||history.index>=history.items.length-1||readOnly} onClick={()=>setHistory(h=>({...h,index:h.index+1}))}><Redo2/>重做</button><button className="text-button" disabled={busy||history.index<=0||readOnly} onClick={()=>setHistory(h=>({...h,index:0}))}><RotateCcw size={14}/>恢复原图</button></div><button className="ss-btn" aria-pressed={compare} disabled={busy||history.index<=0} onClick={()=>setCompare(v=>!v)}><Eye/>{compare?'查看当前效果':'对比原图'}</button></div>
    <div className={'picture-editor-layout'+(mode==='preview'?' is-preview':'')}>
      <section className="picture-editor-canvas" aria-label="图片画布" aria-busy={busy}>
        <div ref={stage} className="picture-editor-stage" style={{height:mode==='preview'?480:420}}>
          {shown?<div className="picture-editor-image" style={{width:Math.min(viewport.w,viewport.h*size.w/size.h)*displayZoom}}><img src={assetUrl(shown)} alt={compare?'编辑前原图':'当前编辑图片'} onLoad={e=>{setSize({w:e.currentTarget.naturalWidth,h:e.currentTarget.naturalHeight});setLoaded(true);}} onError={()=>{setLoadError(true);setLoaded(false);}}/>{mode==='edit'&&tool==='crop'&&!compare&&loaded&&<span className="picture-editor-crop" style={{left:crop.x*100+'%',top:crop.y*100+'%',width:crop.width*100+'%',height:crop.height*100+'%'}}/>}</div>:source.candidate&&<SearchPicture picture={source.candidate} fullSize/>}
          {shown&&!loaded&&!loadError&&!busy&&<span className="picture-editor-image-loading"><LoaderCircle className="spin"/>正在加载图片…</span>}
          {loadError&&<p className="picture-editor-image-loading">图片预览加载失败，请返回后重新打开。</p>}
          {busy&&<div className="picture-editor-busy" role="status"><LoaderCircle className="spin"/><strong>正在{pending||job?.label}…</strong><p>{ai?'模型正在处理图片，完成后会显示对比效果。':'处理完成后会显示在画布中。'}</p>{pollError&&<><p>{pollError}</p><button className="ss-btn" onClick={()=>{setPollError('');setPollRetry(v=>v+1);}}>重试查询</button></>}</div>}
        </div>
        <div className="picture-editor-viewbar"><span>{compare?'原图':history.index>0?operationName(current):'原图'}{loaded&&` · ${size.w} × ${size.h}`}</span>{current&&<label>预览缩放<select aria-label="预览缩放" value={displayZoom} disabled={busy||(mode==='edit'&&tool==='crop')} onChange={e=>setDisplayZoom(Number(e.target.value))}><option value={1}>适应画布</option><option value={1.5}>150%</option><option value={2}>200%</option></select></label>}</div>
        {!!history.items.length&&<div className="picture-editor-history" aria-label="编辑记录">{history.items.map((a,i)=><button key={i+':'+a.id} aria-label={`编辑记录：${i===0?'原图':operationName(a)} ${i}`} aria-pressed={i===history.index} disabled={busy||readOnly} onClick={()=>setHistory(h=>({...h,index:i}))}><img src={assetUrl(a)} alt=""/><span>{i===0?'原图':operationName(a)}</span></button>)}</div>}
      </section>
      {mode==='edit'&&<aside className="picture-editor-controls"><div className="picture-editor-tools">{tools.map(([id,name,Icon])=><button key={id} aria-pressed={tool===id} disabled={busy||readOnly} onClick={()=>{setTool(id);setCompare(false);setDisplayZoom(1);}}><Icon/>{name}</button>)}</div>
        {tool==='enhance'&&<><h3>让画面更清楚</h3><p className="inline-hint">改善锐度与轻微灰雾，可放大至 2 倍。严重模糊的细节无法凭空还原。</p><label className="field">清晰强度<input type="range" min={.5} max={3} step={.1} value={strength} disabled={busy} onChange={e=>setStrength(Number(e.target.value))}/><small>{strength.toFixed(1)} · {strength<1.2?'柔和':strength<2?'自然':'较强'}</small></label><label className="field">输出尺寸<select value={scale} disabled={busy} onChange={e=>setScale(Number(e.target.value))}><option value={2}>放大 2 倍（最长边 3840 像素）</option><option value={1}>保持原尺寸</option></select></label></>}
        {tool==='crop'&&<><h3>调整画面构图</h3><label className="field">裁剪比例<select value={cropRatio} disabled={busy} onChange={e=>setCropRatio(Number(e.target.value))}><option value={1.5}>横版 3:2</option><option value={2.35}>公众号封面 2.35:1</option><option value={1}>方形 1:1</option><option value={2/3}>竖版 2:3</option></select></label><label className="field">裁剪放大<input type="range" min={1} max={3} step={.05} value={zoom} disabled={busy} onChange={e=>setZoom(Number(e.target.value))}/></label><label className="field">水平位置<input type="range" min={0} max={1} step={.01} value={cx} disabled={busy} onChange={e=>setCx(Number(e.target.value))}/></label><label className="field">垂直位置<input type="range" min={0} max={1} step={.01} value={cy} disabled={busy} onChange={e=>setCy(Number(e.target.value))}/></label></>}
        {ai&&<><h3>{tool==='remove_watermark'?'移除叠加水印':'按你的要求调整'}</h3><label className="field">图片编辑模型<select value={model} disabled={busy||modelsLoading} onChange={e=>setModel(e.target.value)}><option value="">{modelsLoading?'正在加载模型…':'选择图片编辑模型'}</option>{models.map(m=><option key={m.id} value={m.id}>{m.name} · {m.model}</option>)}</select></label>{!modelsLoading&&!models.length&&<p className="inline-hint">{modelError||'请在“我的模型”添加并启用支持图片编辑的模型。变清晰和裁剪无需配置模型。'}</p>}
        {tool==='remove_watermark'?<label className="field">水印位置或补充要求（可选）<textarea rows={4} maxLength={4000} value={watermark} disabled={busy} onChange={e=>setWatermark(e.target.value)} placeholder="例如：去掉右下角的半透明水印，保留路牌文字"/></label>:<label className="field">图片修改要求<textarea rows={5} maxLength={4000} value={prompt} disabled={busy} onChange={e=>setPrompt(e.target.value)} placeholder="例如：保留建筑细节，将光线调整为温暖的日落"/></label>}<p className="inline-hint">会调用所选模型；处理后先预览，满意再使用。</p></>}
        {!current&&!busy?<button className="ss-btn ss-primary" onClick={startEdit}>重新载入原图</button>:<button className="ss-btn ss-primary picture-editor-apply" disabled={!canEdit||(ai&&!models.some(m=>m.id===model))||(tool==='edit'&&!prompt.trim())} onClick={runTool}>{busy?<LoaderCircle className="spin"/>:<Sparkles/>}{busy?'正在处理…':tool==='enhance'?'开始变清晰':tool==='remove_watermark'?'开始去水印':tool==='crop'?'应用裁剪':'开始调整'}</button>}
      </aside>}
    </div>
  </WorkspaceDrawer>;
}
