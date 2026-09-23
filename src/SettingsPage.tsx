import { useEffect, useState } from 'react';
import { CheckCircle2, CircleAlert, Clock3, LoaderCircle, Save, Settings2, UserRound } from 'lucide-react';
import { api, dateText, send } from './api';
import {ModelSettings} from './ConnectionSettings';
import type { Activity, Health, Settings } from './types';

const steps=[['采集你关注的网页','读取已启用的内置或自定义网址，保留链接与摘要。'],['整理选题与依据','AI 筛选最多 5 个题目，给出中文标题与推荐理由。'],['挑画面，写短标题','匹配相关图片或视频，只写 1–2 句简短标题，保留依据。'],['剪成十秒视觉手记','图集、视频或混合画面，叠加短标题；无配音、无原声。'],['技术检查，交付审核','检查固定 10 秒时长、无音轨、黑帧与画面解码。']];

export default function SettingsPage({settings,health,onSaved,onError,onNotice,onConnectionChanged}:{onConnectionChanged:()=>Promise<unknown>;settings:Settings;health:Health;onSaved:(s:Settings)=>void;onError:(e:string)=>void;onNotice:(e:string)=>void}){
  const [draft,setDraft]=useState<Settings>(()=>structuredClone(settings));
  const [busy,setBusy]=useState(false),[activity,setActivity]=useState<Activity|null>(null);
  useEffect(()=>{api<Activity>('/activity').then(setActivity).catch(e=>onError(e.message));},[]);
  useEffect(()=>{setDraft(s=>({...s,sources:settings.sources,custom_sources:settings.custom_sources}));},[settings.sources,settings.custom_sources]);
  const patch=<K extends keyof Settings>(key:K,value:Settings[K])=>setDraft(s=>({...s,[key]:value}));
  const save=async()=>{setBusy(true);try{const saved=await api<Settings>('/settings',send('PUT',draft));onSaved(saved);onNotice(saved.schedule_enabled?`设置已保存。服务运行时，每天北京时间 ${saved.schedule_time} 自动开始。`:'设置已保存。每日定时当前关闭。');}catch(e){onError((e as Error).message);}finally{setBusy(false);}};
  return <section><div className="ss-heading"><div><div className="ss-eyebrow">THE DAILY ROUTE / 每日路线</div><h1>每天，沿着好奇出发。</h1><p>定好方向，让日常制作沿着熟悉的路线进行。</p></div><span className={`ss-badge ${settings.schedule_enabled?'ss-green':''}`}><Clock3/>{settings.schedule_enabled?'每日计划已启用':'每日计划未启用'}</span></div>
    <div className="configuration-grid"><ModelSettings onChanged={onConnectionChanged}/><section className="connection-card"><span className="fn-label">YOUR SOURCES</span><h2>先配置网址，再收集灵感。</h2><p className="connection-description">采集配置在“每日选题”中。输入网址后可直接保存并执行，结果在同一页查看。</p><a className="ss-btn" href="#topics">前往配置采集数据 →</a></section></div>
    <div className="ss-pipeline"><div><div className="ss-flow">{steps.map(([heading,body],i)=><div className="ss-flow-step" key={heading}><span className="ss-step-num">0{i+1}</span><div><h3>{heading}</h3><p>{body}</p></div></div>)}<div className="ss-flow-step ss-human"><span className="ss-step-num"><UserRound/></span><div><h3>你审核 → 下载 → 手动发布</h3><p>事实与素材检查通过后，下载完整成片包。</p></div></div></div>
      <div className="connection-note"><Settings2/><div><h3>{health.ai_ready?'AI 服务已配置':'连接 AI，把网络资料变成短片。'}</h3><p>{health.ai_ready?`当前模型：${health.model}。AI 调用按模型服务商规则计费，工作台不限制每日调用次数。`:'在上方“AI 模型连接”填写接口地址、模型名和 API Key，保存即可生效。也支持中转站。'}</p></div></div>
      <div className="activity-list"><h3>最近的采风记录</h3>{!activity?.sources.length?<p className="ss-small">还没有采集记录。可以到每日选题点击“保存并采集”。</p>:activity.sources.slice(0,4).map(run=><div key={run.id}>{run.status==='success'?<CheckCircle2/>:<CircleAlert/>}<span>{run.message}<small>{dateText(run.at)}</small></span></div>)}{activity?.daily.map(run=><div key={run.day}><Clock3/><span>{run.day} · {run.message}</span></div>)}</div>
    </div><div><form onSubmit={e=>{e.preventDefault();save();}} className="preferences"><div className="ss-settings-box"><h3>你的创作偏好</h3><label className="field">账号名称<input value={draft.account_name} maxLength={24} required onChange={e=>patch('account_name',e.target.value)}/></label><div className="ss-setting-row"><span>制作方式</span><strong>网络资料 → AI 短标题</strong></div></div>
      <div className="ss-settings-box"><h3>十秒成片</h3><div className="ss-setting-row"><span>时长</span><strong>固定 10 秒</strong></div><div className="ss-setting-row"><span>画面</span><strong>图片图集 / 视频 / 混合</strong></div><div className="ss-setting-row"><span>文案</span><strong>1–2 句简短标题</strong></div><div className="ss-setting-row"><span>声音</span><strong>静音，不生成配音</strong></div><label className="field">竖屏规格<select value={draft.resolution} onChange={e=>patch('resolution',e.target.value as Settings['resolution'])}><option value="1080p">1080 × 1920</option><option value="720p">720 × 1280</option></select></label></div>
      <div className="ss-settings-box"><h3>每日小计划</h3><label className="switch-row"><span>每天自动开始</span><input type="checkbox" checked={draft.schedule_enabled} onChange={e=>patch('schedule_enabled',e.target.checked)}/></label><label className="field">开始时间 · 北京时间<input type="time" value={draft.schedule_time} required onChange={e=>patch('schedule_time',e.target.value)}/></label><p className="inline-hint">制作任务和 AI 调用不设每日次数上限。服务需要持续运行。每天自动选择一个未制作题目；没有合适候选时记录缺稿。启用前需配置采集源和 AI 模型。</p>{activity&&<p className="usage-line">今天：{activity.jobs_today} 个制作任务 / {activity.ai_calls} 次 AI 请求</p>}</div>
      <button type="submit" className="ss-btn ss-primary save-settings" disabled={busy}>{busy?<LoaderCircle className="spin"/>:<Save/>}保存设置</button>
    </form></div></div>
  </section>;
}
