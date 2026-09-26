import {useEffect,useState} from 'react';
import {api,send} from './api';
import {AssetUpload} from './MaterialsPage';
import type {Asset,TaskSettings,TaskRun,WeChatAccount} from './types';
import WeChatDeclaration,{declarationLabel} from './WeChatDeclaration';
import {useNotifications} from './Notifications';

const defaultDelivery={mode:'local' as const,account_id:'',cover_asset_id:'',author:''};
export function WeChatPublishing({settings,assets,onAssets,onChange,onError,onNotice}:{settings:TaskSettings;assets:Asset[];onAssets:(v:Asset[])=>void;onChange:(v:NonNullable<TaskSettings['wechat_delivery']>)=>void;onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const delivery:NonNullable<TaskSettings['wechat_delivery']>=settings.wechat_delivery||defaultDelivery;
  const [accounts,setAccounts]=useState<WeChatAccount[]>([]),[loading,setLoading]=useState(true);
  useEffect(()=>{
    let active=true;
    const refresh=()=>api<WeChatAccount[]>('/wechat/accounts').then(v=>{if(active)setAccounts(v);}).catch(e=>{if(active)onError(e.message);}).finally(()=>{if(active)setLoading(false);});
    void refresh();addEventListener('focus',refresh);
    return()=>{active=false;removeEventListener('focus',refresh);};
  },[]);
  const patch=(v:Partial<typeof delivery>)=>onChange({...delivery,...v});
  const selected=accounts.find(a=>a.id===delivery.account_id);
  return <section className="wechat-publishing">
    <label className="field">文章交付方式<select value={delivery.mode} onChange={e=>patch({mode:e.target.value as typeof delivery.mode})}><option value="local">留在本地工作台</option><option value="handoff">生成待发布稿件（个人 / 企业）</option><option value="draft">保存到公众号草稿箱</option><option value="publish" disabled={selected?.channel==='browser'}>自动发布到公众号（官方 API）</option></select></label>
    {loading&&<p className="inline-hint">正在读取已连接账号…</p>}
    {delivery.mode!=='local'&&<>
      <p className="inline-hint">{settings.execution==='automatic'?'定时执行和“立即自动执行一次”都会按此设置交付。':'自动任务会按此设置交付；手动写完后可在文章编辑区点击“发送到公众号”。'}{delivery.mode==='handoff'?'生成后提供排版正文和图片包，由你到公众号后台完成发布。':delivery.mode==='publish'?'文章检查通过后自动发布，无需每次确认；不向粉丝群发。':'生成完成后自动存入微信草稿箱。'}</p>
      <label className="field">发布公众号<select value={delivery.account_id} onChange={e=>patch({account_id:e.target.value})}><option value="">请选择已连接的公众号</option>{accounts.map(a=><option key={a.id} value={a.id} disabled={delivery.mode==='publish'&&a.channel==='browser'}>{a.name} · {a.channel==='browser'?(a.draft_ready?'扫码 / 可存草稿':'扫码 / 待登录'):a.publish_ready?'可发布':a.draft_ready?'可存草稿':'待检测'}</option>)}</select></label>
      {selected&&<div className="wechat-account-state"><strong>{selected.name} · {selected.channel==='browser'?'扫码接入':'官方 API'}</strong><span>{selected.channel==='browser'?(selected.session_saved?'已保存登录会话，执行前会检查有效性':'尚未扫码，请到发布账号完成登录'):selected.checked_at?`草稿${selected.draft_ready?'已就绪':'未授权'} · 发布${selected.publish_ready?'已就绪':'未授权'}`:'连接尚未检测，请到发布账号检测权限'}</span></div>}
      <label className="field">默认封面<select aria-label="默认封面" value={delivery.cover_asset_id} onChange={e=>patch({cover_asset_id:e.target.value})}><option value="">请选择封面图片</option>{assets.filter(a=>a.media_type.startsWith('image/')).map(a=><option value={a.id} key={a.id}>{a.filename}</option>)}</select></label>
      {delivery.cover_asset_id&&<img className="wechat-cover-preview" src={`/api/assets/${delivery.cover_asset_id}/file`} alt="默认发布封面"/>}
      <p className="inline-hint">文章没有单独封面时使用此图。{settings.illustration?.enabled&&settings.illustration.cover?'已启用任务封面配图，此处可选，作为生成失败时的备用封面。':''}{delivery.mode==='handoff'?'可选；封面和配图会放入下载包，需在公众号编辑器中上传。':'封面与文内配图会自动上传到微信。'}</p>
      <AssetUpload onError={onError} onUploaded={a=>{onAssets([a,...assets]);if(a.media_type.startsWith('image/'))patch({cover_asset_id:a.id});onNotice('素材已保存。');}}/>
      <label className="field">文章署名（可选）<input value={delivery.author} maxLength={selected?.channel==='browser'?8:16} onChange={e=>patch({author:e.target.value})}/></label>
    </>}

    <WeChatDeclaration value={delivery.content_declaration} channel={selected?.channel} mode={delivery.mode} onChange={content_declaration=>patch({content_declaration})}/>
    <p className="inline-hint">账号连接、扫码登录和权限检测统一在「发布账号」管理。</p><a className="text-button" href="#accounts" target="_blank" rel="noreferrer">管理发布账号（新窗口）↗</a>
  </section>;
}

const labels:Record<string,string>={queued:'公众号交付已排队',awaiting_publish:'稿件已备好 · 待你发布',preparing:'正在准备发布素材',drafting:'正在保存微信草稿',draft:'已保存到公众号草稿箱',submitting:'正在提交发布',publishing:'微信正在处理发布',published:'已发布到公众号',failed:'公众号交付未完成',uncertain:'提交结果待核对'};
export function PublicationResult({run,onRefresh,onError}:{run:TaskRun;onRefresh:()=>Promise<unknown>;onError:(s:string)=>void}){
  const [busy,setBusy]=useState(false),notify=useNotifications();const p=run.publication;if(!p)return null;
  const copy=async()=>{setBusy(true);try{const value=await api<{html:string;text:string}>(`/task-runs/${run.id}/publication/content`);await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([value.html],{type:'text/html'}),'text/plain':new Blob([value.text],{type:'text/plain'})})]);notify.success('排版正文已复制。请粘贴到公众号编辑器，并另行上传图片和封面。');}catch(e){onError((e as Error).message||'复制未完成，请下载稿件包。');}finally{setBusy(false);}};
  const refresh=async()=>{setBusy(true);try{await api(`/task-runs/${run.id}/publication/refresh`,send('POST'));await onRefresh();}catch(e){onError((e as Error).message);}finally{setBusy(false);}};
  return <section className="publication-result"><div className="section-title"><h3>{labels[p.status]||p.status}</h3>{p.status==='publishing'&&<button className="text-button" disabled={busy} onClick={refresh}>{busy?'查询中…':'查询发布结果'}</button>}</div>
    <p>{p.account_name} · {p.title}</p><small>{p.status==='awaiting_publish'?`保留的是文章第 ${p.article_version} 版，尚未上传或发布到微信。后续编辑可从作品导出最新版本。`:`交付的是文章第 ${p.article_version} 版；之后在本地编辑不会改动微信上的内容。`}</small>
    {p.status==='awaiting_publish'&&<div className="wechat-handoff-actions"><button className="ss-btn" disabled={busy} onClick={copy}>复制排版正文</button><a className="ss-btn" href={`/api/task-runs/${run.id}/publication/bundle`}>下载稿件与图片</a><p className="inline-hint">在公众号后台新建图文，粘贴正文、上传配图与封面，再预览并发布。当前没有自动写入微信草稿箱。</p></div>}
    <p className="inline-hint">创作来源：{declarationLabel(p.content_declaration)}{p.declaration_applied?' · 已在公众号核对':p.content_declaration==='none'?'':' · 请在公众号后台设置并确认'}</p>
    {p.error&&<p className="publication-error">{p.error}</p>}
    {p.article_url?<a href={p.article_url} target="_blank" rel="noreferrer">查看已发布文章 ↗</a>:<a href="https://mp.weixin.qq.com/" target="_blank" rel="noreferrer">打开公众号后台 ↗</a>}
    {p.status==='publishing'&&<p className="inline-hint">系统会自动查询最终状态。提交成功不代表已经发布成功。</p>}
    {p.media_id&&<details><summary>交付凭据</summary><p>草稿编号：{p.media_id}</p>{p.publish_id&&<p>发布编号：{p.publish_id}</p>}</details>}
  </section>;
}
