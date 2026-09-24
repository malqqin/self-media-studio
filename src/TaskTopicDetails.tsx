import {useState} from 'react';
import {Lightbulb} from 'lucide-react';
import CollectedSources from './CollectedSources';
import WorkspaceDrawer from './WorkspaceDrawer';
import type {TaskRun,Topic} from './types';

export default function TaskTopicDetails({run,topics,modelName}:{run:TaskRun;topics?:Topic[];modelName:string}){
  const [open,setOpen]=useState(false),plan=run.settings._editorial_plan;
  return <><button type="button" className="ss-btn topic-details-trigger" aria-label="查看选题与资料" aria-haspopup="dialog" onClick={()=>setOpen(true)}><Lightbulb/>选题与资料</button>
    {open&&<WorkspaceDrawer title="选题与资料" subtitle="本次创作的方向、参考资料与配置记录" onClose={()=>setOpen(false)}>
      <section className="topic-brief"><span className="fn-label">{plan?`本次选题 · ${plan.date}`:'本次创作方向'}</span><h3>{plan?.subject||run.settings.brief||'按任务方向创作'}</h3>{plan&&<p>{plan.brief}</p>}{plan&&<small>已参考 {plan.recent_titles.length} 篇近期文章，避开相同主题。</small>}</section>
      <dl className="topic-facts"><div><dt>创作方式</dt><dd>{run.settings.materials.mode==='original'?'从零构思':'资料参考'}</dd></div><div><dt>创作模型</dt><dd>{modelName}</dd></div><div><dt>联网关键词</dt><dd>{plan?.query||run.settings.materials.query||'未设置'}</dd></div></dl>
      <CollectedSources reports={run.reports} topics={topics} used={run.settings._used_topic_ids||[]} title={run.reports.length?'本次采集资料':'本次参考资料'}/>
      {!run.reports.length&&!run.settings._used_topic_ids?.length&&<p className="drawer-empty">本次未使用采集资料。</p>}
      {!!plan?.recent_titles.length&&<details className="topic-recent"><summary>近期已写选题 · {plan.recent_titles.length} 篇</summary><ul>{plan.recent_titles.map((title,i)=><li key={i}>{title}</li>)}</ul></details>}
    </WorkspaceDrawer>}
  </>;
}
