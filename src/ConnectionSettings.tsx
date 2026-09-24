import {useNotifications} from './Notifications';
import {useEffect,useState} from 'react';
import {FlaskConical,KeyRound,LoaderCircle,Plus,Radio,RefreshCw,Save,Trash2,X} from 'lucide-react';
import {api,send} from './api';
import './connections.css';
import type {BuiltinSource,CollectionResult,CollectionSource,ModelConnection,Settings,SourceCatalog,SourcePreview} from './types';

export function ModelSettings({onChanged}:{onChanged:()=>Promise<unknown>}){
  const [saved,setSaved]=useState<ModelConnection|null>(null),[draft,setDraft]=useState<ModelConnection|null>(null);
  const [key,setKey]=useState(''),[clearKey,setClearKey]=useState(false),[busy,setBusy]=useState('');const {error:setError,success:setNotice}=useNotifications();
  useEffect(()=>{api<ModelConnection>('/model-config').then(v=>{setDraft(v);setSaved(v);}).catch(e=>setError(e.message));},[]);
  const patch=(field:string,value:string)=>{setDraft(s=>s?{...s,[field]:value}:s);setNotice('');};
  const act=async(test=false)=>{
    if(!draft)return;setBusy(test?'test':'save');setError('');setNotice('');
    try{
      const body={name:draft.name,base_url:draft.base_url,model:draft.model,protocol:draft.protocol,output_mode:draft.output_mode,api_key:key,clear_key:clearKey};
      if(test){const result=await api<{message:string}>('/model-config/test',send('POST',body));await onChanged();setNotice(result.message+' 测试没有保存改动。');}
      else{const result=await api<ModelConnection>('/model-config',send('PUT',body));setSaved(result);setDraft(result);setKey('');setClearKey(false);await onChanged();setNotice('模型配置已保存，立即生效。');}
    }catch(e){setError((e as Error).message);}finally{setBusy('');}
  };
  return <section className="connection-card" id="model-settings"><div className="connection-heading"><span className="connection-icon"><KeyRound/></span><div><span className="fn-label">MODEL CONNECTION</span><h2>AI 模型连接</h2></div><span className={`ss-badge ${saved?.ready?'ss-green':'ss-amber'}`}>{saved?.ready?'已配置':'待配置'}</span></div>
    <p className="connection-description">连接你的模型服务或中转站，用于筛选选题、写短标题与事实复核。</p>

    {!draft?<p className="inline-hint">正在读取配置…</p>:<form onSubmit={e=>{e.preventDefault();act();}}><fieldset disabled={!!busy} className="connection-fields">
      <div className="connection-presets"><button type="button" onClick={()=>{patch('name','OpenAI');patch('base_url','https://api.openai.com/v1');patch('protocol','responses');patch('output_mode','json_schema');}}>OpenAI 官方</button><button type="button" onClick={()=>{patch('name','自定义中转站');patch('protocol','chat_completions');patch('output_mode','json_object');}}>自定义 / 中转站</button></div>
      <label className="field">连接名称<input value={draft.name} maxLength={60} required onChange={e=>patch('name',e.target.value)} placeholder="例如：我的中转站"/></label>
      <label className="field">API 地址<input aria-label="API 地址" aria-describedby="api-address-hint" type="url" value={draft.base_url} maxLength={2000} required onChange={e=>patch('base_url',e.target.value)} placeholder="https://你的中转站/v1"/><small id="api-address-hint">填写 Base URL，例如 https://api.example.com/v1；也可粘贴完整接口地址。</small></label>
      <div className="field-pair"><label className="field">接口协议<select value={draft.protocol} onChange={e=>patch('protocol',e.target.value)}><option value="chat_completions">Chat Completions（常见中转站）</option><option value="responses">Responses</option></select></label><label className="field">输出格式<select value={draft.output_mode} onChange={e=>patch('output_mode',e.target.value)}><option value="json_schema">JSON Schema（严格结构化）</option><option value="json_object">JSON 模式（兼容）</option><option value="text">普通文本 JSON（兼容）</option></select></label></div>
      <label className="field">模型名称<input value={draft.model} maxLength={150} onChange={e=>patch('model',e.target.value)} placeholder="填写服务商提供的完整模型 ID"/></label>
      <label className="field">API Key<input type="password" autoComplete="new-password" value={key} maxLength={4096} disabled={clearKey} onChange={e=>{setKey(e.target.value);setNotice('');}} placeholder={saved?.key_configured?'已保存；留空保留原密钥':'填写服务商 API Key'}/></label>
      {saved?.key_configured&&<label className="ss-check"><input type="checkbox" checked={clearKey} onChange={e=>{setClearKey(e.target.checked);setKey('');}}/>清除已保存的密钥</label>}
      <p className="inline-hint">密钥只保存在本机服务端，不回显。更换 API 地址时需重新填写密钥。{saved?.origin==='environment'&&saved.key_configured?'目前读取 .env；页面保存后优先使用这里的配置。':''}</p>
      <div className="connection-actions"><button className="ss-btn" type="button" disabled={!draft.model||clearKey||(!key&&!saved?.key_configured)} onClick={()=>act(true)}>{busy==='test'?<LoaderCircle className="spin"/>:<FlaskConical/>}测试连接</button><button className="ss-btn ss-primary" type="submit">{busy==='save'?<LoaderCircle className="spin"/>:<Save/>}保存模型配置</button></div>
      <p className="inline-hint">测试会向填写的服务发起一次模型请求，可能产生少量费用，并计入每日调用次数。普通文本模式仍会校验返回的 JSON。</p>
    </fieldset></form>}
  </section>;
}

const newSource=():CollectionSource=>({id:'custom-'+crypto.randomUUID(),name:'',url:'',kind:'auto',enabled:true});
export function SourceSettings({settings,onSaved,onCollected}:{settings:Settings;onSaved:(settings:Settings)=>void;onCollected:()=>Promise<unknown>}){
  const [importUrl,setImportUrl]=useState(''),[importTitle,setImportTitle]=useState(''),[importText,setImportText]=useState(''),[showImport,setShowImport]=useState(false);
  const [catalog,setCatalog]=useState<SourceCatalog[]>([]),[selected,setSelected]=useState<BuiltinSource[]>(settings.sources),[custom,setCustom]=useState<CollectionSource[]>(settings.custom_sources||[]);
  const [editor,setEditor]=useState<CollectionSource|null>(()=>settings.sources.length||settings.custom_sources.some(s=>s.enabled)?null:newSource());
  const [preview,setPreview]=useState<SourcePreview|null>(null),[result,setResult]=useState<CollectionResult|null>(null),[busy,setBusy]=useState('');const {error:setError,success:setNotice}=useNotifications();
  useEffect(()=>{api<SourceCatalog[]>('/source-catalog').then(setCatalog).catch(e=>setError(e.message));},[]);
  const sourceStamp=JSON.stringify([settings.sources,settings.custom_sources]);
  useEffect(()=>{setSelected(settings.sources);setCustom(settings.custom_sources||[]);},[sourceStamp]);
  const patch=(field:string,value:string)=>{setEditor(s=>s?{...s,[field]:value}:s);setPreview(null);setNotice('');};
  const normalize=(source:CollectionSource)=>{
    const url=source.url.trim();let parsed:URL;
    try{parsed=new URL(url);if(!['https:','http:'].includes(parsed.protocol))throw Error();}catch{throw Error('请填写完整的 HTTP/HTTPS 网址。');}
    return {...source,url,name:source.name.trim()||parsed.hostname.slice(0,60)};
  };
  const inspect=async(source:CollectionSource)=>{setBusy('preview');setError('');setPreview(null);try{setPreview(await api<SourcePreview>('/sources/preview',send('POST',normalize(source))));}catch(e){setError((e as Error).message);}finally{setBusy('');}};
  const save=async(collect:boolean)=>{
    if(busy)return;setBusy(collect?'collect':'save');setError('');setNotice('');setResult(null);
    let persisted=false;
    try{
      let next=custom;
      if(editor&&(editor.url.trim()||editor.name.trim()||custom.some(s=>s.id===editor.id))){
        const source=normalize(editor);
        next=custom.some(s=>s.id===source.id)?custom.map(s=>s.id===source.id?source:s):[...custom,source];
      }
      if(collect&&!selected.length&&!next.some(s=>s.enabled))throw Error('请先输入采集网址，或勾选一个常用来源。');
      const saved=await api<Settings>('/source-settings',send('PUT',{sources:selected,custom_sources:next}));
      persisted=true;onSaved(saved);setCustom(saved.custom_sources);setEditor(null);setPreview(null);
      if(!collect){setNotice('采集配置已保存，立即生效。'+(!saved.sources.length&&!saved.custom_sources.some(s=>s.enabled)?'当前没有启用来源，每日计划已关闭。':''));return;}
      const collected=await api<CollectionResult>('/collect',send('POST'));
      setResult(collected);const failed=collected.reports.filter(r=>r.status==='error');if(failed.length)setError((failed.length===collected.reports.length?'本次采集未成功。':'部分来源采集失败。')+failed.map(r=>r.message).join('；'));else setNotice(`采集完成，新增 ${collected.added} 条资料。`);
      try{await onCollected();}catch{setError('采集已结束，但选题列表刷新失败，请刷新页面查看。');}
    }catch(e){setNotice('');setError((persisted?'配置已保存，可再次点击重试。':'')+(e as Error).message);}finally{setBusy('');}
  };
  const importBody=async()=>{
    if(busy)return;setBusy('import');setError('');setNotice('');
    try{const saved=await api<{message:string}>('/sources/import',send('POST',{url:importUrl,title:importTitle,text:importText}));setNotice(saved.message);setImportText('');await onCollected();}
    catch(e){setError((e as Error).message);}finally{setBusy('');}
  };
  const openImport=(url='')=>{setImportUrl(url);setShowImport(true);};
  const allFailed=!!result?.reports.length&&result.reports.every(r=>r.status==='error');
  const failures=result?.reports.filter(r=>r.status==='error').length||0;
  return <section className="connection-card" id="source-settings"><div className="connection-heading"><span className="connection-icon"><Radio/></span><div><span className="fn-label">COLLECT FROM THE WEB</span><h2>采集数据配置</h2></div><span className="ss-badge">{selected.length+custom.filter(s=>s.enabled).length} 个启用</span></div>
    <p className="connection-description">输入任意领域的网页、公众号文章或订阅地址，保存后立即采集，无需选择分类或配置 AI。</p>

    <form onSubmit={e=>{e.preventDefault();save(true);}}><fieldset disabled={!!busy} className="connection-fields">
    {editor&&<div className="source-editor"><div className="source-editor-heading"><h3>{custom.some(s=>s.id===editor.id)?'编辑采集网址':'从一个网址开始'}</h3><button type="button" className="icon-button" onClick={()=>{setEditor(null);setPreview(null);}} aria-label="取消编辑资料源"><X/></button></div>
      <label className="field">采集网址<input aria-label="采集网址" aria-describedby="source-url-hint" type="url" value={editor.url} maxLength={2000} onChange={e=>patch('url',e.target.value)} placeholder="粘贴网页、公众号文章或 RSS 网址"/><small id="source-url-hint">直接填网址即可，默认自动识别，名称可留空。</small></label>
      <details className="source-options"><summary>更多选项 · 名称与采集方式</summary><label className="field">来源名称<input value={editor.name} maxLength={60} onChange={e=>patch('name',e.target.value)} placeholder="可选，默认使用网站域名"/></label><label className="field">采集方式<select aria-label="采集方式" value={editor.kind} onChange={e=>patch('kind',e.target.value)}><option value="auto">自动识别（必要时浏览器加载）</option><option value="rss">RSS / Atom</option><option value="page">网页正文 / 文章列表</option><option value="browser">浏览器加载（动态网页）</option></select></label></details>
      <button type="button" className="text-button" disabled={!editor.url.trim()} onClick={()=>inspect(editor)}><FlaskConical/>先预览一下</button>
    </div>}
    <div className="custom-source-list">{custom.map(source=><div className="custom-source" key={source.id}><label><input type="checkbox" checked={source.enabled} onChange={()=>{setCustom(s=>s.map(x=>x.id===source.id?{...x,enabled:!x.enabled}:x));setEditor(s=>s?.id===source.id?{...s,enabled:!source.enabled}:s);}}/><span><strong>{source.name}</strong><small>{source.url}</small></span></label><div><button type="button" className="text-button" onClick={()=>{setEditor({...source});setPreview(null);setError('');}}>编辑</button><button type="button" className="icon-button" aria-label={`删除 ${source.name}`} onClick={()=>{setCustom(s=>s.filter(x=>x.id!==source.id));if(editor?.id===source.id)setEditor(null);}}><Trash2/></button></div></div>)}</div>
    {!editor&&<button type="button" className="ss-btn add-source" disabled={custom.length>=20} onClick={()=>{setEditor(newSource());setPreview(null);setError('');}}><Plus/>添加自定义网址</button>}
    <details className="source-options"><summary>也可选择常用来源 · NASA / ESA / CERN / Nature</summary><div className="source-builtins">{catalog.map(source=><div key={source.id} className="source-builtin"><label><input type="checkbox" checked={selected.includes(source.id)} onChange={()=>setSelected(s=>s.includes(source.id)?s.filter(x=>x!==source.id):[...s,source.id])}/><span><strong>{source.name}</strong><small>{source.description}</small></span></label><button type="button" className="text-button" onClick={()=>inspect({...source,id:'custom-preview-'+source.id,enabled:true})}>预览</button></div>)}</div></details>
    <div className="connection-actions"><button type="submit" className="ss-btn ss-primary">{busy==='collect'?<LoaderCircle className="spin"/>:<RefreshCw/>}{busy==='collect'?'正在采集…':'保存并采集'}</button><button type="button" className="ss-btn" onClick={()=>save(false)}>{busy==='save'?<LoaderCircle className="spin"/>:<Save/>}仅保存配置</button></div>
    </fieldset></form>
    {busy==='preview'&&<p className="inline-hint" role="status"><LoaderCircle className="spin"/>正在读取来源与文章，请稍候…</p>}
    {preview&&<div className="source-preview" role="status"><strong>{preview.kind==='rss'?'订阅源':'网页'} · 找到 {preview.count} 条内容</strong><p>{preview.note} 预览不会加入选题库。</p>{preview.items.map(item=><article key={item.url}><a href={item.url} target="_blank" rel="noreferrer">{item.title}</a><p>{item.summary}</p></article>)}</div>}
    {result&&<div className={`collection-result ${allFailed?'collection-failed':''}`} ><strong>{allFailed?'本次采集未成功，请检查网址或稍后重试。':`采集完成，新增 ${result.added} 条资料。${failures?` ${failures} 个来源未成功。`:''}`}</strong>{!allFailed&&result.added===0&&<p>没有新内容，已收录的网址会自动去重。</p>}<ul>{result.reports.map((r,i)=><li key={r.source+i} className={r.status==='error'?'failed':''}>{r.message}{r.status==='error'&&r.url&&<span className="collection-recovery"><a href={r.url} target="_blank" rel="noreferrer">打开原文 ↗</a><button className="text-button" type="button" disabled={!!busy} onClick={()=>openImport(r.url)}>导入网页正文</button></span>}</li>)}</ul></div>}
    <div className="manual-import"><button className="text-button" type="button" disabled={!!busy} onClick={()=>setShowImport(!showImport)}>{showImport?'收起正文导入':'浏览器能打开，采集仍失败？导入网页正文'}</button>
    {showImport&&<form onSubmit={e=>{e.preventDefault();importBody();}}><fieldset disabled={!!busy} className="connection-fields"><p className="inline-hint">在你能正常访问的浏览器中复制正文，保留原文链接。导入内容会标记为待核验，不会自动制作。</p><label className="field">原文网址<input type="url" required maxLength={2000} value={importUrl} onChange={e=>setImportUrl(e.target.value)}/></label><label className="field">原文标题<input required maxLength={240} value={importTitle} onChange={e=>setImportTitle(e.target.value)}/></label><label className="field">网页正文<textarea required minLength={20} maxLength={60000} rows={8} value={importText} onChange={e=>setImportText(e.target.value)} placeholder="粘贴正文，至少 20 个字符"/></label><button className="ss-btn" type="submit">{busy==='import'?<LoaderCircle className="spin"/>:<Save/>}导入正文到选题库</button></fieldset></form>}
    </div>
    <p className="inline-hint">支持公开网页、列表、RSS/Atom 与浏览器动态加载。若网站仍要求登录或验证，可从能打开的浏览器中复制正文导入。停用来源保留已有资料。</p>
  </section>;
}
