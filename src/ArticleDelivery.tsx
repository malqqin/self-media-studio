import {useEffect,useState} from 'react';
import {Send,LoaderCircle,X} from 'lucide-react';
import WeChatDeclaration,{declarationLabel} from './WeChatDeclaration';
import CenteredModal from './CenteredModal';
import {api,send} from './api';
import {useConfirmation} from './Confirmation';
import type {Article,Asset,TaskRun,TaskSettings,WeChatAccount} from './types';

type Delivery=NonNullable<TaskSettings['wechat_delivery']>;
export default function ArticleDelivery({article,run,disabled,onUpdated,onError,onNotice}:{article:Article;run:TaskRun;disabled:boolean;onUpdated:()=>Promise<unknown>;onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const [open,setOpen]=useState(false);
  if(!article.document)return null;
  const publication=run.publication,done=publication&&['draft','published'].includes(publication.status);
  return <><button className="ss-btn" disabled={disabled} onClick={()=>setOpen(true)}><Send/>{done?'查看公众号交付':publication?.can_resume?'继续保存原草稿':'发送到公众号'}</button>{open&&<DeliveryDialog article={article} run={run} disabled={disabled} onClose={()=>setOpen(false)} onUpdated={onUpdated} onError={onError} onNotice={onNotice}/>}</>;
}

function DeliveryDialog({article,run,disabled,onClose,onUpdated,onError,onNotice}:{article:Article;run:TaskRun;disabled:boolean;onClose:()=>void;onUpdated:()=>Promise<unknown>;onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const p=run.publication,resume=!!p?.can_resume,done=!!p&&['draft','published'].includes(p.status);
  const stopped=!!p&&(p.status==='uncertain'&&!resume||!!p.publish_id);
  const [delivery,setDelivery]=useState<Delivery>(()=>({mode:p?.mode==='publish'?'publish':'draft',account_id:p?.account_id||run.settings.wechat_delivery?.account_id||'',content_declaration:p?.content_declaration??run.settings.wechat_delivery?.content_declaration??'ai',author:p?.author??run.settings.wechat_delivery?.author??'',cover_asset_id:article.document?.cover_asset_id||p?.cover_asset_id||run.settings.wechat_delivery?.cover_asset_id||''}));
  const [accounts,setAccounts]=useState<WeChatAccount[]>([]),[assets,setAssets]=useState<Asset[]>([]),[loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[loadError,setLoadError]=useState(''),[reload,setReload]=useState(0);
  const confirm=useConfirmation();
  useEffect(()=>{let alive=true;setLoading(true);setLoadError('');Promise.all([api<WeChatAccount[]>('/wechat/accounts'),api<Asset[]>('/assets')]).then(([a,s])=>{if(alive){setAccounts(a);setAssets(s);setDelivery(d=>d.account_id||a.length!==1?d:{...d,account_id:a[0].id});}}).catch(e=>{if(alive)setLoadError(e.message);}).finally(()=>{if(alive)setLoading(false);});return()=>{alive=false;};},[reload]);
  const account=accounts.find(a=>a.id===delivery.account_id),patch=(v:Partial<Delivery>)=>setDelivery(d=>({...d,...v}));
  const publishBlocked=delivery.mode==='publish'&&(!article.checks||article.checks.issues.some(i=>i.severity==='error'));
  const declarationBlocked=delivery.mode==='publish'&&account?.channel==='api'&&(delivery.content_declaration||'ai')!=='none';
  const ready=account?.draft_ready&&(account.channel==='browser'?account.session_saved:delivery.mode!=='publish'||account.publish_ready);
  const submit=async()=>{
    if(delivery.mode==='publish'&&!await confirm({title:'公开发布这篇文章？',message:`将已保存的第 ${article.version} 版《${article.document?.title}》发布到「${account?.name}」。`,confirmLabel:'确认公开发布',cancelLabel:'返回检查'}))return;
    if(resume&&!await confirm({title:'继续保存原草稿？',message:`将当前已保存的第 ${article.version} 版写入「${account?.name}」的原草稿。若你在公众号后台修改过内容，本次会覆盖这些修改。`,confirmLabel:'继续保存原草稿',cancelLabel:'返回核对'}))return;
    setBusy(true);try{await api(`/task-runs/${run.id}/publication`,send('POST',{version:article.version,delivery,resume}));onNotice('已开始发送当前文章，进度会在公众号交付记录中更新。');await onUpdated();onClose();}catch(e){onError((e as Error).message);}finally{setBusy(false);}
  };
  return <CenteredModal titleId="article-delivery-title" onClose={onClose} busy={busy} className="article-delivery-modal"><button className="icon-button auth-close" aria-label="关闭公众号交付" disabled={busy} onClick={onClose}><X/></button><h2 id="article-delivery-title">发送到公众号</h2><p>《{article.document?.title}》 · 已保存版本 v{article.version}<br/>直接交付这篇文章，正文保持不变。</p>
    {done?<div className="auth-note">{p?.status==='published'?'文章已发布。':'文章已保存到公众号草稿箱。'} 本次交付版本为 v{p?.article_version}，请到公众号后台查看。<p>创作来源：{declarationLabel(p?.content_declaration)}{p?.declaration_applied?' · 已核对':p?.content_declaration==='none'?'':' · 需在公众号后台设置并确认'}</p></div>:stopped?<div className="auth-note">上次提交结果尚未确认，请先到公众号后台核对。当前无法安全定位可恢复的草稿，不会重复新建。</div>:loading?<p><LoaderCircle className="spin"/>正在读取发布账号和封面…</p>:loadError?<div><p>{loadError}</p><button className="ss-btn" onClick={()=>setReload(n=>n+1)}>重新加载</button></div>:<fieldset disabled={busy||disabled}>
      {resume&&<div className="auth-note">已定位上次的公众号草稿，将在同一篇草稿中继续保存，不会重新生成文章。</div>}
      <label className="field">发送到哪个公众号<select value={delivery.account_id} disabled={resume} onChange={e=>patch({account_id:e.target.value,mode:'draft'})}><option value="">选择已连接的公众号</option>{accounts.map(a=><option key={a.id} value={a.id}>{a.name} · {a.channel==='browser'?'扫码接入':'官方 API'}</option>)}</select></label>
      <label className="field">交付方式<select value={delivery.mode} disabled={resume} onChange={e=>patch({mode:e.target.value as Delivery['mode']})}><option value="draft">保存到公众号草稿箱</option><option value="publish" disabled={account?.channel==='browser'||!account?.publish_ready}>公开发布（官方 API）</option></select></label>
      {account?.channel==='browser'&&<p className="inline-hint">扫码接入支持保存草稿，之后可在公众号后台发表。</p>}
      <WeChatDeclaration value={delivery.content_declaration} channel={account?.channel} mode={delivery.mode} onChange={content_declaration=>patch({content_declaration})}/>
      <label className="field">文章署名（可选）<input value={delivery.author} maxLength={account?.channel==='browser'?8:16} onChange={e=>patch({author:e.target.value})}/></label>
      <label className="field">发布封面<select value={delivery.cover_asset_id} disabled={!!article.document?.cover_asset_id} onChange={e=>patch({cover_asset_id:e.target.value})}><option value="">请选择封面</option>{assets.filter(a=>a.media_type.startsWith('image/')).map(a=><option key={a.id} value={a.id}>{a.filename}</option>)}</select></label>
      {delivery.cover_asset_id&&<img className="wechat-cover-preview" src={`/api/assets/${delivery.cover_asset_id}/file`} alt="本次发布封面"/>}
      {article.document?.cover_asset_id&&<p className="inline-hint">使用文章已保存的封面，可在文章编辑区更换。</p>}
      {publishBlocked&&<p className="auth-note">公开发布前，请完成文章核对并处理检查中的问题。也可以先保存到草稿箱。</p>}
      {account&&!ready&&<p className="auth-note">请先在“发布账号”完成扫码登录或连接检测。</p>}
      <button className="ss-btn ss-primary auth-submit" disabled={!ready||!delivery.cover_asset_id||publishBlocked||declarationBlocked||loading||busy||disabled} onClick={submit}>{busy?<LoaderCircle className="spin"/>:<Send/>}{resume?'继续保存原草稿':delivery.mode==='publish'?'公开发布当前文章':'发送当前文章到草稿箱'}</button>
    </fieldset>}
    <div className="article-delivery-links"><a href="#accounts" target="_blank" rel="noreferrer">管理发布账号 ↗</a><a href="https://mp.weixin.qq.com/" target="_blank" rel="noreferrer">打开公众号后台 ↗</a></div>
  </CenteredModal>;
}
