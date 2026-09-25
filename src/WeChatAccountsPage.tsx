import {useEffect,useState} from 'react';
import {LoaderCircle,Plus,Send} from 'lucide-react';
import {api,send} from './api';
import type {WeChatAccount} from './types';
import {WeChatLogin} from './WeChatLogin';
import './task-configuration.css';

export default function WeChatAccountsPage({onError,onNotice}:{onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const [accounts,setAccounts]=useState<WeChatAccount[]>([]),[busy,setBusy]=useState(''),[loading,setLoading]=useState(true);
  const [editing,setEditing]=useState(''),[name,setName]=useState(''),[appid,setAppid]=useState(''),[secret,setSecret]=useState('');
  const [channel,setChannel]=useState<'api'|'browser'>('browser'),[subject,setSubject]=useState<'unknown'|'personal'|'organization'>('personal');
  const [login,setLogin]=useState<WeChatAccount|null>(null);
  const [whitelist,setWhitelist]=useState<{accountId:string;ip:string}|null>(null);
  const refresh=async()=>{const values=await api<WeChatAccount[]>('/wechat/accounts');setAccounts(values);return values;};
  useEffect(()=>{refresh().catch(e=>onError(e.message)).finally(()=>setLoading(false));},[]);
  const choose=(id:string)=>{const a=accounts.find(v=>v.id===id);setEditing(id);setName(a?.name||'');setAppid(a?.appid||'');setSecret('');setSubject(a?.subject||'personal');setChannel(a?a.channel||'api':'browser');};
  const save=async()=>{setBusy('save');try{
    const value=await api<WeChatAccount>(editing?`/wechat/accounts/${editing}`:'/wechat/accounts',send(editing?'PUT':'POST',{name,appid:channel==='api'?appid:'',secret:channel==='api'?secret:'',channel,subject}));
    setSecret('');await refresh();setEditing(value.id);
    onNotice(channel==='api'?'公众号连接已保存。请检测接口权限；任务中可选择此账号。':'公众号连接已保存。可选择“生成待发布稿件”，或扫码连接后台。');
  }catch(e){onError((e as Error).message);}finally{setBusy('');}};
  const test=async(id:string)=>{setBusy(id);setWhitelist(null);try{const v=await api<{message:string}>(`/wechat/accounts/${id}/test`,send('POST'));await refresh();onNotice(v.message);}catch(e){const message=(e as Error).message;const ip=message.includes('40164')?message.match(/当前出口 IP：([0-9a-fA-F:.]+)。/)?.[1]:null;if(ip)setWhitelist({accountId:id,ip});onError(message);}finally{setBusy('');}};
  const copyIp=async()=>{if(!whitelist)return;try{await navigator.clipboard.writeText(whitelist.ip);onNotice('出口 IP 已复制，请添加到微信 IP 白名单并保留原有条目。');}catch{onError('复制未完成，请选中页面上的 IP 手动复制。');}};
  return <section>
    <div className="platform-heading"><div><span className="fn-label">PUBLISHING ACCOUNTS</span><h1>发布账号</h1><p>统一管理公众号连接，任务中只需选择账号与交付方式。</p></div><button className="ss-btn" disabled={!!busy} onClick={()=>choose('')}><Plus/>添加公众号</button></div>
    <div className="publishing-accounts-grid"><aside className="publishing-account-list" aria-label="已连接的公众号">
      {loading?<p className="inline-hint">正在读取公众号连接…</p>:accounts.length?accounts.map(a=><button type="button" key={a.id} className="publishing-account" aria-pressed={editing===a.id} onClick={()=>choose(a.id)} disabled={!!busy}><strong>{a.name}</strong><span>{a.subject==='personal'?'个人公众号':a.subject==='organization'?'企业 / 组织公众号':'公众号'} · {a.channel==='browser'?'扫码接入':'官方 API'}</span><small>{a.channel==='browser'?(a.session_saved?'已保存登录会话':'等待扫码登录'):a.publish_ready?'发布接口已就绪':a.draft_ready?'草稿接口已就绪':'等待检测权限'}</small></button>):<p className="inline-hint">还没有连接公众号。从右侧添加，之后可在多个任务中复用。</p>}
    </aside><section className="connection-card publishing-account-form"><h2>{editing?'编辑公众号连接':'连接新公众号'}</h2><p className="inline-hint">个人和企业公众号均可扫码连接；官方 API 能力以账号实际权限为准。</p>
    {whitelist&&<div className="wechat-account-state"><strong>{accounts.find(a=>a.id===whitelist.accountId)?.name||'公众号'}需要配置 IP 白名单</strong><span>微信检测到的出口 IP</span><code>{whitelist.ip}</code><button type="button" className="text-button" onClick={copyIp}>复制出口 IP</button><p className="inline-hint">在微信公众平台的开发配置中找到“IP 白名单”，新增此 IP 并保留已有条目。保存后重新检测；网络或代理出口变化时可能需要更新。</p><a className="text-button" href="https://mp.weixin.qq.com/" target="_blank" rel="noreferrer">打开微信公众平台 ↗</a><button type="button" className="ss-btn" disabled={!!busy} onClick={()=>test(whitelist.accountId)}>已添加，重新检测</button></div>}
<div className="wechat-connections">
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
    </div>
    </section></div>
    {login&&<WeChatLogin account={login} onClose={()=>setLogin(null)} onConnected={()=>{refresh().catch(e=>onError(e.message));}} onError={onError} onNotice={onNotice}/>}
  </section>;
}
