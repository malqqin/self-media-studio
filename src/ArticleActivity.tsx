import {useEffect,useState} from 'react';
import {CheckCircle2,ChevronUp,CircleAlert,LoaderCircle,X} from 'lucide-react';
import {ArticleStreamPanel,type LiveDraft} from './ArticleStreaming';
import WorkspaceDrawer from './WorkspaceDrawer';
import type {Article} from './types';

export default function ArticleActivity({article,draft,reconnecting,local,canRetry,onRetry}:{article:Article;draft:LiveDraft|null;reconnecting:boolean;local:boolean;canRetry:boolean;onRetry:()=>void}){
  const [open,setOpen]=useState(false),[recent,setRecent]=useState(false),[dismissed,setDismissed]=useState(false);
  const running=['queued','running'].includes(article.status),failed=article.status==='failed';
  useEffect(()=>{if(running&&!local){setRecent(true);setDismissed(false);}},[running,local]);
  useEffect(()=>{if(local)setOpen(false);},[local]);
  const visible=!local&&(running||failed||recent)&&!dismissed;
  if(!visible)return null;
  const title=failed?'创作需要处理':running?(article.status==='queued'?'等待开始创作':article.stage==='illustrate'?'正在处理文章配图':article.stage==='angle_refresh'?'正在重新构思角度':article.stage==='replan'?'正在按新选题创作':article.stage==='check'?'正在核对文章':article.stage==='outline'?'正在整理大纲':article.stage==='angles'?'正在构思角度':'正在生成文章'):'本次处理完成';
  const Icon=failed?CircleAlert:running?LoaderCircle:CheckCircle2;
  return <><div className={'article-activity-dock'+(failed?' has-error':'')} aria-label="创作状态">
    <button type="button" className="article-activity-trigger" aria-label="查看创作进度" aria-haspopup="dialog" onClick={()=>setOpen(true)}><span className="activity-icon"><Icon className={running?'spin':''}/></span><span><strong role="status">{title}</strong><small>{failed?'查看原因与保留内容':running?'点击查看实时输出':'查看本次处理结果'}</small></span><ChevronUp size={16}/></button>
    {!running&&!failed&&<button type="button" className="workspace-icon-button activity-dismiss" aria-label="收起创作状态" onClick={()=>{setDismissed(true);setOpen(false);}}><X size={14}/></button>}
  </div>
    {open&&<WorkspaceDrawer title="创作进度" subtitle="收起窗口后，任务会继续在后台处理。" onClose={()=>setOpen(false)}>
      <div className={'activity-summary'+(failed?' has-error':'')}><Icon className={running?'spin':''}/><div><strong>{title}</strong><p>{failed?article.error||'此步骤未完成，已保存的内容保留。':article.note}</p></div></div>
      <ArticleStreamPanel draft={draft} reconnecting={running&&reconnecting} failed={failed} completed={!running&&!failed}/>
      {failed&&<div className="activity-recovery"><p>已保存的正文和历史版本仍然保留。</p><button type="button" className="ss-btn ss-primary" disabled={!canRetry} onClick={onRetry}>从此步骤重试</button>{!canRetry&&<small>请先保存当前编辑，再重试。</small>}</div>}
    </WorkspaceDrawer>}
  </>;
}
