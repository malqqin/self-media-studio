import {useEffect,useState} from 'react';
import {CheckCircle2,LoaderCircle,Send} from 'lucide-react';
import {api,send} from './api';
import {AssetUpload} from './MaterialsPage';
import type {Asset,TaskSettings,TaskRun,WeChatAccount} from './types';
import {WeChatLogin} from './WeChatLogin';
import {useNotifications} from './Notifications';

const defaultDelivery={mode:'local' as const,account_id:'',cover_asset_id:'',author:''};
export function WeChatPublishing({settings,assets,onAssets,onChange,onError,onNotice}:{settings:TaskSettings;assets:Asset[];onAssets:(v:Asset[])=>void;onChange:(v:NonNullable<TaskSettings['wechat_delivery']>)=>void;onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const delivery=settings.wechat_delivery||defaultDelivery;
  const [accounts,setAccounts]=useState<WeChatAccount[]>([]),[open,setOpen]=useState(false),[loaded,setLoaded]=useState(false),[busy,setBusy]=useState('');
  const [editing,setEditing]=useState(''),[name,setName]=useState(''),[appid,setAppid]=useState(''),[secret,setSecret]=useState('');
  const [channel,setChannel]=useState<'api'|'browser'>('browser'),[subject,setSubject]=useState<'unknown'|'personal'|'organization'>('personal');
  const [login,setLogin]=useState<WeChatAccount|null>(null);
  const [whitelist,setWhitelist]=useState<{accountId:string;ip:string}|null>(null);
  const refresh=async()=>{const values=await api<WeChatAccount[]>('/wechat/accounts');setAccounts(values);setLoaded(true);return values;};
  useEffect(()=>{if((open||delivery.mode!=='local')&&!loaded)refresh().catch(e=>onError(e.message));},[open,delivery.mode,loaded]);
  const patch=(v:Partial<typeof delivery>)=>onChange({...delivery,...v});
  const selected=accounts.find(a=>a.id===delivery.account_id);
  const choose=(id:string)=>{const a=accounts.find(v=>v.id===id);setEditing(id);setName(a?.name||'');setAppid(a?.appid||'');setSecret('');setSubject(a?.subject||'personal');setChannel(a?a.channel||'api':'browser');};
  const save=async()=>{setBusy('save');try{
    const value=await api<WeChatAccount>(editing?`/wechat/accounts/${editing}`:'/wechat/accounts',send(editing?'PUT':'POST',{name,appid:channel==='api'?appid:'',secret:channel==='api'?secret:'',channel,subject}));
    setSecret('');await refresh();setEditing(value.id);patch({account_id:value.id});
    onNotice(channel==='api'?'公众号连接已保存。请检测接口权限后保存任务配置。':'公众号连接已保存。可选择“生成待发布稿件”，或扫码连接后台。');
  }catch(e){onError((e as Error).message);}finally{setBusy('');}};
  const test=async(id:string)=>{setBusy(id);setWhitelist(null);try{const v=await api<{message:string}>(`/wechat/accounts/${id}/test`,send('POST'));await refresh();onNotice(v.message);}catch(e){const message=(e as Error).message;const ip=message.includes('40164')?message.match(/当前出口 IP：([0-9a-fA-F:.]+)。/)?.[1]:null;if(ip)setWhitelist({accountId:id,ip});onError(message);}finally{setBusy('');}};
  const copyIp=async()=>{if(!whitelist)return;try{await navigator.clipboard.writeText(whitelist.ip);onNotice('出口 IP 已复制，请添加到微信 IP 白名单并保留原有条目。');}catch{onError('复制未完成，请选中页面上的 IP 手动复制。');}};
  return <section className="connection-card wechat-publishing"><span className="fn-label">05 / PUBLISH</span><h2>生成后，交付到哪里？</h2>
    <p className="inline-hint">支持个人和企业公众号。个人号扫码后可自动存入微信草稿箱；企业号可按官方 API 权限自动发布。</p>
    <label className="field">文章交付方式<select value={delivery.mode} onChange={e=>patch({mode:e.target.value as typeof delivery.mode})}><option value="local">留在本地工作台</option><option value="handoff">生成待发布稿件（个人 / 企业）</option><option value="draft">保存到公众号草稿箱</option><option value="publish" disabled={selected?.channel==='browser'}>自动发布到公众号（官方 API）</option></select></label>
    {whitelist&&<div className="wechat-account-state"><strong>{accounts.find(a=>a.id===whitelist.accountId)?.name||'公众号'}需要配置 IP 白名单</strong><span>微信检测到的出口 IP</span><code>{whitelist.ip}</code><button type="button" className="text-button" onClick={copyIp}>复制出口 IP</button><p className="inline-hint">在微信公众平台的开发配置中找到“IP 白名单”，新增此 IP 并保留已有条目。保存后重新检测；网络或代理出口变化时可能需要更新。</p><a className="text-button" href="https://mp.weixin.qq.com/" target="_blank" rel="noreferrer">打开微信公众平台 ↗</a><button type="button" className="ss-btn" disabled={!!busy} onClick={()=>test(whitelist.accountId)}>已添加，重新检测</button></div>}
    {delivery.mode!=='local'&&<>
      <p className="inline-hint">{settings.execution==='automatic'?'定时执行和“立即自动执行一次”都会按此设置交付。':'切换为“自动执行”后生效；手动编辑和 AI 辅助只生成本地作品。'}{delivery.mode==='handoff'?'生成后提供排版正文和图片包，由你到公众号后台完成发布。':delivery.mode==='publish'?'文章检查通过后自动发布，无需每次确认；不向粉丝群发。':'生成完成后自动存入微信草稿箱。'}</p>
      <label className="field">发布公众号<select value={delivery.account_id} onChange={e=>patch({account_id:e.target.value})}><option value="">请选择已连接的公众号</option>{accounts.map(a=><option key={a.id} value={a.id}>{a.name} · {a.channel==='browser'?(a.draft_ready?'扫码 / 可存草稿':'扫码 / 待登录'):a.publish_ready?'可发布':a.draft_ready?'可存草稿':'待检测'}</option>)}</select></label>
      {selected&&<div className="wechat-account-state">{selected.channel==='browser'?<><strong>扫码接入 · 无需 AppSecret 和 IP 白名单</strong><span>{selected.session_saved?'已保存登录会话，执行前需检查是否有效':'尚未扫码；生成待发布稿件不要求登录'}</span><button type="button" className="text-button" onClick={()=>setLogin(selected)}>扫码登录 / 检查登录</button><small>扫码草稿接入已验证；自动发布尚未验证，当前可保存草稿或生成待发布稿件。</small></>:<><small>{selected.appid}</small><span>{selected.checked_at?<><CheckCircle2/>草稿{selected.draft_ready?'已就绪':'未授权'} · 发布{selected.publish_ready?'已就绪':'未授权'}</>:'连接尚未检测'}</span><button type="button" className="text-button" disabled={!!busy} onClick={()=>test(selected.id)}>{busy===selected.id?'检测中…':'检测连接与权限'}</button></>}</div>}
      <label className="field">默认封面<select aria-label="默认封面" value={delivery.cover_asset_id} onChange={e=>patch({cover_asset_id:e.target.value})}><option value="">请选择封面图片</option>{assets.filter(a=>a.media_type.startsWith('image/')).map(a=><option value={a.id} key={a.id}>{a.filename}</option>)}</select></label>
      {delivery.cover_asset_id&&<img className="wechat-cover-preview" src={`/api/assets/${delivery.cover_asset_id}/file`} alt="默认发布封面"/>}
      <p className="inline-hint">文章没有单独封面时使用此图。{delivery.mode==='handoff'?'可选；封面和配图会放入下载包，需在公众号编辑器中上传。':'封面与文内配图会自动上传到微信。'}</p>
      <AssetUpload onError={onError} onUploaded={a=>{onAssets([a,...assets]);if(a.media_type.startsWith('image/'))patch({cover_asset_id:a.id});onNotice('素材已保存。');}}/>
      <label className="field">文章署名（可选）<input value={delivery.author} maxLength={selected?.channel==='browser'?8:16} onChange={e=>patch({author:e.target.value})}/></label>
    </>}
    <details className="wechat-connections" open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary>连接 / 管理公众号</summary>
      <fieldset disabled={!!busy} className="article-fields"><label className="field">编辑连接<select value={editing} onChange={e=>choose(e.target.value)}><option value="">新增公众号</option>{accounts.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
      <label className="field">连接名称<input value={name} maxLength={40} onChange={e=>setName(e.target.value)} placeholder="例如：我的旅游公众号"/></label>
      <label className="field">账号主体<select aria-label="账号主体" value={subject} onChange={e=>{const s=e.target.value as typeof subject;setSubject(s);if(!editing)setChannel(s==='organization'?'api':'browser');}}><option value="personal">个人公众号</option><option value="organization">企业 / 组织公众号</option><option value="unknown">暂不确定</option></select></label>
      <label className="field">接入方式<select aria-label="接入方式" value={channel} disabled={!!editing} onChange={e=>{setChannel(e.target.value as typeof channel);setSecret('');}}><option value="browser">扫码接入（个人 / 企业）</option><option value="api">官方 API（按接口权限）</option></select></label>
      <p className="inline-hint">{channel==='browser'?'不需要开发者密钥。扫码后可自动保存草稿，也可生成待发布稿件；无需配置 IP 白名单。个人号自动发布尚未开放。':'填写 AppID 和 AppSecret，并将服务出口 IP 加入微信白名单。企业认证也需检测实际权限；密钥仅在本机加密保存。'}</p>
      {subject==='personal'&&channel==='api'&&<p className="inline-hint">微信自 2025 年 7 月起收回个人主体的发布接口权限。配置 IP 白名单不能解除此限制；草稿以检测结果为准，也可新增扫码连接。</p>}
      {channel==='api'&&<><label className="field">AppID<input value={appid} readOnly={!!editing} maxLength={18} onChange={e=>setAppid(e.target.value.trim())} autoComplete="off" placeholder="wx…"/></label>
      <label className="field">AppSecret<input type="password" value={secret} maxLength={256} onChange={e=>setSecret(e.target.value.trim())} autoComplete="new-password" placeholder={editing?'留空保留已保存的密钥':'填写公众号密钥'}/></label>
      </>}
      <button type="button" className="ss-btn" disabled={!name.trim()||(channel==='api'&&(!/^wx[a-zA-Z0-9]{16}$/.test(appid)||(!editing&&!secret)))} onClick={save}>{busy==='save'?<LoaderCircle className="spin"/>:<Send/>}保存公众号连接</button>
      {editing&&(channel==='api'?<button type="button" className="ss-btn" onClick={()=>test(editing)}>检测已保存连接</button>:<><button type="button" className="ss-btn" onClick={()=>{const a=accounts.find(a=>a.id===editing);if(a)setLogin(a);}}>扫码登录 / 检查登录</button><button type="button" className="text-button" onClick={async()=>{try{await api(`/wechat/accounts/${editing}/login`,send('DELETE'));await refresh();onNotice('本机登录会话已清除，任务配置保留。');}catch(e){onError((e as Error).message);}}}>清除本机登录</button></>)}
      </fieldset><a className="text-button" href="https://mp.weixin.qq.com/" target="_blank" rel="noreferrer">打开微信公众平台 ↗</a>
    </details>
    {login&&<WeChatLogin account={login} onClose={()=>setLogin(null)} onConnected={()=>{refresh().catch(e=>onError(e.message));}} onError={onError} onNotice={onNotice}/>}
  </section>;
}

const labels:Record<string,string>={awaiting_publish:'稿件已备好 · 待你发布',preparing:'正在准备发布素材',drafting:'正在保存微信草稿',draft:'已保存到公众号草稿箱',submitting:'正在提交发布',publishing:'微信正在处理发布',published:'已发布到公众号',failed:'公众号交付未完成',uncertain:'提交结果待核对'};
export function PublicationResult({run,onRefresh,onError}:{run:TaskRun;onRefresh:()=>Promise<unknown>;onError:(s:string)=>void}){
  const [busy,setBusy]=useState(false),notify=useNotifications();const p=run.publication;if(!p)return null;
  const copy=async()=>{setBusy(true);try{const value=await api<{html:string;text:string}>(`/task-runs/${run.id}/publication/content`);await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([value.html],{type:'text/html'}),'text/plain':new Blob([value.text],{type:'text/plain'})})]);notify.success('排版正文已复制。请粘贴到公众号编辑器，并另行上传图片和封面。');}catch(e){onError((e as Error).message||'复制未完成，请下载稿件包。');}finally{setBusy(false);}};
  const refresh=async()=>{setBusy(true);try{await api(`/task-runs/${run.id}/publication/refresh`,send('POST'));await onRefresh();}catch(e){onError((e as Error).message);}finally{setBusy(false);}};
  return <section className="publication-result"><div className="section-title"><h3>{labels[p.status]||p.status}</h3>{p.status==='publishing'&&<button className="text-button" disabled={busy} onClick={refresh}>{busy?'查询中…':'查询发布结果'}</button>}</div>
    <p>{p.account_name} · {p.title}</p><small>{p.status==='awaiting_publish'?`保留的是文章第 ${p.article_version} 版，尚未上传或发布到微信。后续编辑可从作品导出最新版本。`:`交付的是文章第 ${p.article_version} 版；之后在本地编辑不会改动微信上的内容。`}</small>
    {p.status==='awaiting_publish'&&<div className="wechat-handoff-actions"><button className="ss-btn" disabled={busy} onClick={copy}>复制排版正文</button><a className="ss-btn" href={`/api/task-runs/${run.id}/publication/bundle`}>下载稿件与图片</a><p className="inline-hint">在公众号后台新建图文，粘贴正文、上传配图与封面，再预览并发布。当前没有自动写入微信草稿箱。</p></div>}
    {p.error&&<p className="publication-error">{p.error}</p>}
    {p.article_url?<a href={p.article_url} target="_blank" rel="noreferrer">查看已发布文章 ↗</a>:<a href="https://mp.weixin.qq.com/" target="_blank" rel="noreferrer">打开公众号后台 ↗</a>}
    {p.status==='publishing'&&<p className="inline-hint">系统会自动查询最终状态。提交成功不代表已经发布成功。</p>}
    {p.media_id&&<details><summary>交付凭据</summary><p>草稿编号：{p.media_id}</p>{p.publish_id&&<p>发布编号：{p.publish_id}</p>}</details>}
  </section>;
}
