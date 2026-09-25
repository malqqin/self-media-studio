import {useEffect,useState} from 'react';
import {Lightbulb,LoaderCircle,Pencil} from 'lucide-react';
import CollectedSources from './CollectedSources';
import WorkspaceDrawer from './WorkspaceDrawer';
import ArticleContextEditor from './ArticleContextEditor';
import {api} from './api';
import type {Article,TaskRun,Topic} from './types';

export default function TaskTopicDetails({run,topics,modelName,editable=false,workDirty=false,onDirty,onSaved,onError,onNotice}:{run:TaskRun;topics?:Topic[];modelName:string;editable?:boolean;workDirty?:boolean;onDirty:(dirty:boolean)=>void;onSaved:()=>void;onError:(message:string)=>void;onNotice:(message:string)=>void}){
  const [open,setOpen]=useState(false),[editing,setEditing]=useState(false),[article,setArticle]=useState<Article|null>(null),[dirty,setDirty]=useState(false),[busy,setBusy]=useState(false),[discard,setDiscard]=useState(false),[loading,setLoading]=useState(false);
  const plan=run.settings._editorial_plan,changed=!!article?.input_data._context_revision;
  useEffect(()=>{onDirty(dirty);return()=>onDirty(false);},[dirty,onDirty]);
  useEffect(()=>{
    if(!open||!editable||!run.content_id)return;
    let live=true;setLoading(true);setArticle(null);
    api<Article>(`/articles/${run.content_id}`).then(value=>{if(live)setArticle(value);}).catch(e=>{if(live)onError(e.message);}).finally(()=>{if(live)setLoading(false);});
    return()=>{live=false;};
  },[open,run.content_id,editable]);
  const close=()=>{if(busy){onNotice('当前操作正在处理，请稍候再关闭。');return;}if(dirty){setDiscard(true);return;}setOpen(false);setEditing(false);setDiscard(false);};
  const blocked=workDirty||['queued','running','publishing'].includes(run.status)||!!article&&['queued','running'].includes(article.status);
  const subject=changed?String(article?.input_data._subject||article?.input_data.brief||'本次创作方向'):plan?.subject||run.settings.brief||'按任务方向创作';
  return <><button type="button" className="ss-btn topic-details-trigger" aria-label="查看选题与资料" aria-haspopup="dialog" onClick={()=>setOpen(true)}><Lightbulb/>选题与资料</button>
    {open&&<WorkspaceDrawer title="选题与资料" subtitle={editing?'修改当前作品的方向和资料，再选择从哪一步重新创作。':'本次创作的方向、参考资料与配置记录'} onClose={close}>
      {discard&&<div className="context-discard" role="alert"><strong>选题与资料还有未保存的修改</strong><p>关闭将放弃这些修改，已保存的正文不受影响。</p><button type="button" className="ss-btn" onClick={()=>setDiscard(false)}>继续编辑选题</button><button type="button" className="text-button" onClick={()=>{setDirty(false);setEditing(false);setDiscard(false);setOpen(false);}}>放弃选题修改并关闭</button></div>}
      {editing&&article?<ArticleContextEditor key={article.version} article={article} run={run} topics={topics} blocked={blocked} onDirty={setDirty} onBusy={setBusy} onError={onError} onNotice={onNotice} onSaved={(value,generated)=>{setArticle(value);setDirty(false);setEditing(false);onSaved();if(generated)setOpen(false);}}/>:<>
        <section className="topic-brief"><span className="fn-label">{changed?'当前作品选题':plan?`本次选题 · ${plan.date}`:'本次创作方向'}</span><h3>{subject}</h3>{!!(changed?article?.input_data.brief:plan?.brief)&&<p>{String(changed?article?.input_data.brief:plan?.brief)}</p>}{plan&&!changed&&<small>已参考 {plan.recent_titles.length} 篇近期文章，避开相同主题。</small>}
        {editable&&run.content_id&&<button type="button" className="ss-btn" disabled={loading||!article} onClick={()=>setEditing(true)}>{loading?<LoaderCircle className="spin"/>:<Pencil/>}编辑选题与资料</button>}</section>
        <dl className="topic-facts"><div><dt>创作方式</dt><dd>{(article?.mode||run.settings.materials.mode)==='original'?'从零构思':'资料参考'}</dd></div><div><dt>创作模型</dt><dd>{modelName}</dd></div><div><dt>联网关键词</dt><dd>{String(article?.input_data.query??plan?.query??run.settings.materials.query)||'未设置'}</dd></div></dl>
        {changed&&<section className="context-current-sources"><h3>当前采用资料 · {article!.source_data.length} 条</h3>{article!.source_data.map(s=><details key={s.id}><summary>{s.title}</summary><p>{s.text}</p>{s.url&&<a href={s.url} target="_blank" rel="noreferrer">打开原文 ↗</a>}</details>)}{!article!.source_data.length&&<p className="inline-hint">本次未选用参考资料。</p>}</section>}
        <details className="context-original-collection" open={!changed}><summary>{changed?'查看最初执行时的采集记录':'采集与参考资料'}</summary><CollectedSources reports={run.reports} topics={topics} used={run.settings._used_topic_ids||[]} title={run.reports.length?'本次采集资料':'本次参考资料'}/>{!run.reports.length&&!run.settings._used_topic_ids?.length&&<p className="drawer-empty">本次未使用采集资料。</p>}</details>
        {!!plan?.recent_titles.length&&<details className="topic-recent"><summary>近期已写选题 · {plan.recent_titles.length} 篇</summary><ul>{plan.recent_titles.map((title,i)=><li key={i}>{title}</li>)}</ul></details>}
      </>}
    </WorkspaceDrawer>}
  </>;
}
