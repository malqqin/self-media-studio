import {useEffect,useState} from 'react';
import {createPortal} from 'react-dom';
import {Bot,Check,ChevronRight,FlaskConical,Image,KeyRound,LoaderCircle,Plus,RefreshCw,Save,Search,Settings2,ShieldCheck,Type,Video} from 'lucide-react';
import {api,send} from './api';
import type {DirectoryModel,ModelKind,SavedModel} from './types';
import WorkspaceDrawer from './WorkspaceDrawer';
import providers from '../shared/model-providers.json';
import './models.css';

const kinds:Record<ModelKind,string>={text:'文本模型',image:'生图模型',video:'视频模型',audio:'音频模型',embedding:'向量 / 排序',unknown:'待确认类型'};
const blank:SavedModel={id:'',name:'',provider:'deepseek',base_url:providers[0].url,model:'',protocol:'chat_completions',model_type:'text',output_mode:'json_object',key_configured:false,ready:false,origin:'library'};
const kindOf=(m:SavedModel):ModelKind=>m.model_type||(m.protocol==='images'?'image':m.protocol==='catalog'?'unknown':'text');
function providerOf(m:Pick<SavedModel,'base_url'|'provider'>){return providers.find(p=>p.id===m.provider)||providers.find(p=>p.url&&m.base_url.startsWith(p.url))||providers[providers.length-1];}
function providerFromUrl(url:string){try{return providers.find(p=>p.url&&new URL(p.url).hostname===new URL(url).hostname)?.id||'custom';}catch{return 'custom';}}
function brandOf(model:string,provider:string){
  const id=model.toLowerCase();
  if(/deepseek/.test(id))return 'deepseek';
  if(/doubao|seedream|seedance/.test(id))return 'doubao';
  if(/qwen|qwq|qvq|(?:^|\/)wan[\d.-]/.test(id))return 'qwen';
  if(/glm|cogview|cogvideo/.test(id))return 'zhipu';
  if(/kimi|moonshot/.test(id))return 'kimi';
  if(/minimax/.test(id))return 'minimax';
  if(/^(gpt-|chatgpt|dall-e|sora|o[134](?:-|$))/.test(id))return 'openai';
  return provider;
}
function Brand({brand}:{brand:string}){return <span className={`model-brand brand-${brand}`}>{brand==='custom'?<Bot aria-hidden="true"/>:<img src={`/model-providers/${brand}.svg`} alt={`${providers.find(p=>p.id===brand)?.name||brand} 图标`}/>}</span>;}
function KindBadge({kind}:{kind:ModelKind}){const Icon=kind==='image'?Image:kind==='video'?Video:Type;return <span className={`model-kind kind-${kind}`}><Icon size={12}/>{kinds[kind]}</span>;}
function protocolFor(kind:ModelKind,provider:string):SavedModel['protocol']{return kind==='text'?'chat_completions':kind==='image'&&['openai','custom','doubao','siliconflow','zhipu'].includes(provider)?'images':'catalog';}

export default function ModelsPage({onError,onNotice}:{onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const [models,setModels]=useState<SavedModel[]>([]),[draft,setDraft]=useState<SavedModel|null>(null),[key,setKey]=useState(''),[clear,setClear]=useState(false),[busy,setBusy]=useState('');
  const [loaded,setLoaded]=useState(false),[query,setQuery]=useState(''),[filter,setFilter]=useState('all');
  const [directory,setDirectory]=useState<DirectoryModel[]|null>(null),[directoryQuery,setDirectoryQuery]=useState(''),[directoryFilter,setDirectoryFilter]=useState('all'),[directoryNote,setDirectoryNote]=useState(''),[directoryError,setDirectoryError]=useState('');
  const [manual,setManual]=useState(false),[advanced,setAdvanced]=useState(false),[nameEdited,setNameEdited]=useState(false),[showProviders,setShowProviders]=useState(true);
  const refresh=async()=>{setModels((await api<SavedModel[]>('/models')).filter(m=>m.id!=='default'||m.model||m.key_configured));setLoaded(true);};
  useEffect(()=>{refresh().catch(e=>{setLoaded(true);onError(e.message);});},[]);
  const resetDirectory=()=>{setDirectory(null);setDirectoryError('');setDirectoryNote('');setDirectoryQuery('');setDirectoryFilter('all');};
  const choose=(m:SavedModel)=>{setDraft({...m,provider:providerOf(m).id,model_type:kindOf(m)});setKey('');setClear(false);resetDirectory();setManual(false);setAdvanced(false);setNameEdited(!!m.id);setShowProviders(!m.id);};
  const changeProvider=(id:string)=>{if(!draft)return;const p=providers.find(v=>v.id===id)!;setDraft({...draft,provider:id,base_url:p.url,model:'',name:'',description:'',model_type:'text',protocol:'chat_completions',image_edit:false,output_mode:id==='minimax'?'text':'json_object'});setKey('');setClear(false);resetDirectory();setManual(false);setAdvanced(id==='custom');setNameEdited(false);};
  const close=()=>{if(!busy){setDraft(null);setKey('');resetDirectory();}};
  const changeUrl=(url:string)=>{if(!draft)return;setDraft({...draft,base_url:url,provider:providerFromUrl(url),model:'',name:'',description:''});setNameEdited(false);resetDirectory();};
  const body=()=>draft&&({name:draft.name.trim()||draft.model.slice(0,60)||'我的模型',base_url:draft.base_url,model:draft.model,provider:draft.provider,model_type:draft.model_type,description:draft.description||'',protocol:draft.protocol,image_edit:!!draft.image_edit,output_mode:draft.output_mode,api_key:key,clear_key:clear});
  const path=draft?.id?`/models/${draft.id}`:'/models';
  const discover=async()=>{if(!draft)return;setBusy('discover');setDirectoryError('');try{
    const result=await api<{models:DirectoryModel[];message:string}>(path+'/discover',send('POST',body()));
    setDirectory(result.models);setDirectoryNote(result.message);setDirectoryQuery('');setDirectoryFilter('all');setShowProviders(false);
    if(!result.models.length)setManual(true);
    onNotice(result.models.length?`已获取 ${result.models.length} 个模型，请选择要添加的模型。`:result.message);
  }catch(e){setDirectoryError((e as Error).message);setManual(true);onError((e as Error).message);}finally{setBusy('');}};
  const select=(m:DirectoryModel)=>{if(!draft)return;setDraft({...draft,model:m.id,name:nameEdited?draft.name:m.name.slice(0,60),model_type:m.model_type,description:m.description,protocol:m.protocol,image_edit:false});setManual(m.model_type==='unknown');};
  const act=async(test=false)=>{if(!draft)return;setBusy(test?'test':'save');try{
    if(test){const result=await api<{message:string}>(path+'/test',send('POST',body()));onNotice(result.message);}
    else{await api<SavedModel>(path,send(draft.id?'PUT':'POST',body()));setDraft(null);setKey('');onNotice('模型已保存，可在任务配置中按需选择。');await refresh();}
  }catch(e){onError((e as Error).message);}finally{setBusy('');}};
  const visible=models.filter(m=>(filter==='all'||kindOf(m)===filter)&&`${m.name} ${m.model} ${providerOf(m).name}`.toLowerCase().includes(query.toLowerCase()));
  const available=(directory||[]).filter(m=>(directoryFilter==='all'||m.model_type===directoryFilter)&&`${m.id} ${m.name} ${m.description}`.toLowerCase().includes(directoryQuery.toLowerCase()));
  const selectedProvider=draft?providerOf(draft):providers[0];
  return <section className="models-page"><div className="platform-heading"><div><span className="fn-label">MODEL LIBRARY</span><h1>我的模型</h1><p>连接你喜欢的模型，让文字与画面各有所长。</p></div><button className="ss-btn ss-primary" onClick={()=>choose(blank)}><Plus/>添加模型</button></div>
    <div className="models-toolbar"><div className="model-filters" aria-label="筛选已配置模型">{(['all','text','image','video'] as const).map(k=><button key={k} type="button" aria-pressed={filter===k} onClick={()=>setFilter(k)}>{k==='all'?'全部模型':kinds[k]}<span>{models.filter(m=>k==='all'||kindOf(m)===k).length}</span></button>)}</div><label className="models-search"><Search size={16}/><input aria-label="搜索已配置模型" placeholder="搜索名称或模型" value={query} onChange={e=>setQuery(e.target.value)}/></label></div>
    <div className="models-grid">{visible.map(m=><button className="configured-model" aria-label={`编辑模型 ${m.name}`} key={m.id} onClick={()=>choose(m)}><div className="configured-model-head"><Brand brand={brandOf(m.model,providerOf(m).id)}/><span className="configured-model-title"><strong>{m.name}</strong><small>{providerOf(m).name}</small></span><Settings2 size={16}/></div><code>{m.model||'尚未选择模型'}</code><p>{m.description||(kindOf(m)==='image'?'用于生成封面和文章配图。':'用于文章创作、内容改写和脚本构思。')}</p><div className="configured-model-foot"><KindBadge kind={kindOf(m)}/><span className={`model-state ${m.ready?'is-ready':''}`}><i/>{m.protocol==='catalog'?'仅保存目录':m.ready?'已配置':'待配置'}</span></div></button>)}</div>
    {(!loaded||!visible.length)&&<div className="models-empty">{loaded?<Bot size={30}/>:<LoaderCircle className="spin"/>}<p>{!loaded?'正在读取模型…':models.length?'没有符合条件的模型':'添加第一个模型，开始创作。'}</p></div>}
    <p className="models-footnote"><ShieldCheck size={14}/>密钥保存在本机；各个任务可以独立选择模型。</p>
    {draft&&createPortal(<WorkspaceDrawer placement="center" title={draft.id?'编辑模型':'添加模型'} subtitle="选择服务商，填写 Key，然后从目录选择模型。" onClose={close} footer={<div className="model-dialog-footer"><span>{busy?<><LoaderCircle size={14} className="spin"/>{busy==='discover'?'正在获取模型目录…':busy==='test'?'正在测试模型…':'正在保存…'}</>:draft.model?<><Check size={14}/>已选择 {kinds[kindOf(draft)]}</>:'选择模型后即可保存'}</span><div><button type="button" className="ss-btn" disabled={!!busy} onClick={close}>取消</button><button form="model-setup" type="submit" className="ss-btn ss-primary" disabled={!!busy||!draft.model.trim()||!draft.base_url}><Save size={15}/>保存模型</button></div></div>}>
      <form id="model-setup" onSubmit={e=>{e.preventDefault();act();}}><fieldset className="model-setup-fields" disabled={!!busy}>
        <section className="model-setup-section"><div className="model-section-heading"><span>01</span><h3>{showProviders?'选择服务商':selectedProvider.name}</h3><button type="button" className="text-button" onClick={()=>setShowProviders(!showProviders)}>{showProviders?'收起':'更换服务商'}</button></div>{showProviders&&<div className="model-provider-grid">{providers.map(p=><button type="button" className="model-provider" key={p.id} aria-pressed={selectedProvider.id===p.id} onClick={()=>changeProvider(p.id)}><Brand brand={p.id}/><span>{p.name}</span>{selectedProvider.id===p.id&&<Check size={13}/>}</button>)}</div>}<p className="inline-hint">{selectedProvider.hint}</p></section>
        <section className="model-setup-section"><div className="model-section-heading"><span>02</span><h3>连接模型服务</h3></div><div className="model-key-row"><label className="field">API Key<input type="password" autoComplete="new-password" maxLength={4096} value={key} disabled={clear} onChange={e=>{setKey(e.target.value);resetDirectory();}} placeholder={draft.key_configured?'已保存，留空保留':'粘贴服务商的 API Key'}/></label><button type="button" className="ss-btn ss-primary" disabled={clear||(!key&&!draft.key_configured)||!draft.base_url} onClick={discover}>{busy==='discover'?<LoaderCircle className="spin"/>:<RefreshCw/>}获取模型列表</button></div><div className="model-endpoint"><KeyRound size={12}/><span>{draft.base_url||'请在下方填写 API 地址'}</span><button type="button" className="text-button" onClick={()=>setAdvanced(!advanced)}>修改地址 / 高级设置</button></div>{draft.key_configured&&<label className="ss-check model-clear-key"><input type="checkbox" checked={clear} onChange={e=>{setClear(e.target.checked);setKey('');resetDirectory();}}/>清除已保存密钥</label>}</section>
        <section className="model-setup-section"><div className="model-section-heading"><span>03</span><h3>选择模型</h3><button type="button" className="text-button" onClick={()=>setManual(!manual)}>{manual?'收起手动填写':'手动填写模型 ID'}</button></div>
          {directoryError&&<p className="model-directory-error" role="note">{directoryError}</p>}
          {directory!==null&&<><div className="model-directory-toolbar"><label className="models-search"><Search size={15}/><input aria-label="搜索可用模型" placeholder="搜索模型名称、能力…" value={directoryQuery} onChange={e=>setDirectoryQuery(e.target.value)}/></label><select aria-label="筛选模型类型" value={directoryFilter} onChange={e=>setDirectoryFilter(e.target.value)}><option value="all">全部类型（{directory.length}）</option>{Object.entries(kinds).map(([k,label])=><option key={k} value={k}>{label}（{directory.filter(m=>m.model_type===k).length}）</option>)}</select></div><div className="model-directory" aria-label="可用模型目录">{available.map(m=><button type="button" key={m.id} className="directory-model" aria-pressed={draft.model===m.id} onClick={()=>select(m)}><Brand brand={brandOf(m.id,selectedProvider.id)}/><span className="directory-model-text"><strong>{m.name}</strong>{m.name!==m.id&&<code>{m.id}</code>}<span>{m.description}</span><small>{m.type_source==='api'?'类型来自接口':m.type_source==='inferred'?'类型按名称识别':'类型需手动确认'} · {m.description_source==='api'?'服务商描述':'通用能力说明'}</small></span><span className="directory-model-end"><KindBadge kind={m.model_type}/>{draft.model===m.id?<Check size={16}/>:<ChevronRight size={16}/>}</span></button>)}{!available.length&&<p className="inline-hint">{directory.length?'没有符合条件的模型，试试其他关键词或类型。':'当前目录为空，可使用下方手动填写。'}</p>}</div><p className="inline-hint">{directoryNote}</p></>}
          {directory===null&&!directoryError&&<p className="model-directory-placeholder">{draft.model?<>当前模型：<strong>{draft.model}</strong>，获取目录可更换。</>:'填写 Key 后点击「获取模型列表」，无需记住模型 ID。'}</p>}
          {manual&&<div className="model-manual field-pair"><label className="field">模型 ID / 接入点<input maxLength={150} value={draft.model} onChange={e=>setDraft({...draft,model:e.target.value,description:''})} placeholder="服务商提供的模型 ID 或 ep- 接入点"/></label><label className="field">模型类型<select value={kindOf(draft)} onChange={e=>{const kind=e.target.value as ModelKind;setDraft({...draft,model_type:kind,protocol:protocolFor(kind,selectedProvider.id),image_edit:false,description:''});}}>{Object.entries(kinds).map(([k,label])=><option key={k} value={k}>{label}</option>)}</select></label></div>}
          {draft.model&&<><label className="field model-connection-name">连接名称（选填）<input maxLength={60} value={draft.name} onChange={e=>{setNameEdited(true);setDraft({...draft,name:e.target.value});}} placeholder={draft.model}/></label>{draft.protocol==='catalog'&&<p className="model-directory-error">此模型暂时仅保存到模型库，不会出现在创作模型选项中。{kindOf(draft)==='unknown'?'请先确认模型类型。':'对应的专用生成接口尚未接入。'}</p>}</>}
        </section>
{advanced&&<section className="model-advanced"><h3><Settings2 size={16}/>高级连接设置</h3><label className="field">API 地址<input type="url" required maxLength={2000} value={draft.base_url} onChange={e=>changeUrl(e.target.value)} placeholder="https://api.example.com/v1"/></label><div className="field-pair"><label className="field">接口协议<select value={draft.protocol} onChange={e=>setDraft({...draft,protocol:e.target.value as SavedModel['protocol']})}>{kindOf(draft)==='text'&&<><option value="chat_completions">Chat Completions</option><option value="responses">Responses</option></>}{kindOf(draft)==='image'&&<option value="images">Images · 图片生成</option>}<option value="catalog">仅保存目录（暂不调用）</option></select></label>{draft.protocol==='images'?<label className="ss-check"><input type="checkbox" checked={!!draft.image_edit} onChange={e=>setDraft({...draft,image_edit:e.target.checked})}/>支持 Images 图片编辑接口</label>:draft.protocol!=='catalog'?<label className="field">输出格式<select value={draft.output_mode} onChange={e=>setDraft({...draft,output_mode:e.target.value as SavedModel['output_mode']})}><option value="json_object">JSON 模式</option><option value="json_schema">JSON Schema</option><option value="text">普通文本 JSON</option></select></label>:null}</div><p className="inline-hint">生图需支持 Images 请求格式；不同模型的尺寸、编辑能力和权限以服务商为准。更换地址需重新填写 Key。</p></section>}
        <div className="model-test-row"><p className="inline-hint">获取目录不会生成内容。{draft.protocol==='images'?'生成测试图会产生一次生图费用，并保存到素材库。':'测试连接会产生一次模型请求，可能产生少量费用。'}</p><button type="button" className="ss-btn" disabled={!draft.model||clear||draft.protocol==='catalog'||(!key&&!draft.key_configured)} onClick={()=>act(true)}>{busy==='test'?<LoaderCircle className="spin"/>:<FlaskConical/>}{draft.protocol==='images'?'生成测试图':'测试连接'}</button></div>
      </fieldset></form>
    </WorkspaceDrawer>,document.getElementById('science-fieldnotes')||document.body)}
  </section>;
}
