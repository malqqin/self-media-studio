import {useEffect,useState} from 'react';
import {History,ArrowRight,LoaderCircle} from 'lucide-react';
import WorkspaceDrawer from './WorkspaceDrawer';
import {api,dateText} from './api';
import {kindNames,runLabels} from './App';
import {useNotifications} from './Notifications';
import type {CreationTask,TaskRun,CreationKind} from './types';

type RecordItem=Pick<TaskRun,'id'|'task_id'|'action'|'status'|'created_at'|'content_id'|'title'>&{task_name?:string;kind?:CreationKind;archived?:boolean};
export function RecordList({records,selected,onOpen}:{records:RecordItem[];selected?:string;onOpen:(run:RecordItem)=>void}){
  return <div className="creation-records-list">{records.map((run,i)=><button type="button" key={run.id} className="creation-record-row" aria-pressed={selected===run.id} onClick={()=>onOpen(run)}><span className="record-number">{String(records.length-i).padStart(2,'0')}</span><span className="record-description"><strong>{run.title||run.task_name||`第 ${records.length-i} 次创作`}</strong><small>{run.title&&run.task_name?run.task_name+' · ':''}{dateText(run.created_at)} · {run.action==='automatic'?'自动执行':run.action==='blank'?'手动草稿':'AI 辅助'}{run.kind?' · '+kindNames[run.kind]:''}{run.archived?' · 已归档':''}</small></span><span className="ss-badge">{runLabels[run.status]||run.status}</span><ArrowRight size={15}/></button>)}{!records.length&&<p className="drawer-empty">还没有创作记录，完成一次创作后会显示在这里。</p>}</div>;
}

export function TaskRecordsButton({task,onOpen}:{task:CreationTask;onOpen:(taskId:string,runId?:string)=>void}){
  const [open,setOpen]=useState(false),[runs,setRuns]=useState<TaskRun[]>([]),[loading,setLoading]=useState(false),[failed,setFailed]=useState(false),[refresh,setRefresh]=useState(0);const {error}=useNotifications();
  useEffect(()=>{if(!open)return;let live=true;setLoading(true);setFailed(false);api<CreationTask>(`/tasks/${task.id}`).then(value=>{if(live)setRuns(value.runs||[]);}).catch(e=>{if(live){setFailed(true);error(e.message);}}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[open,task.id,refresh]);
  return <><button className="text-button task-records-trigger" aria-label={`查看 ${task.name} 的创作记录`} onClick={()=>setOpen(true)}><History size={14}/>创作记录 · {task.run_count||0}</button>{open&&<WorkspaceDrawer title="创作记录" subtitle={task.name+' · 选择一次创作，继续查看或编辑'} onClose={()=>setOpen(false)}>{loading?<p className="inline-hint"><LoaderCircle className="spin"/>正在读取创作记录…</p>:failed?<button className="ss-btn" onClick={()=>setRefresh(v=>v+1)}>重新加载记录</button>:<RecordList records={runs} onOpen={run=>{setOpen(false);onOpen(task.id,run.id);}}/>}</WorkspaceDrawer>}</>;
}

export default function CreationRecords({onOpen}:{onOpen:(taskId:string,runId?:string)=>void}){
  const [records,setRecords]=useState<RecordItem[]>([]),[loading,setLoading]=useState(true),[failed,setFailed]=useState(false),[refresh,setRefresh]=useState(0),[query,setQuery]=useState('');const {error}=useNotifications();
  useEffect(()=>{let live=true;setLoading(true);setFailed(false);api<RecordItem[]>('/task-records').then(value=>{if(live)setRecords(value);}).catch(e=>{if(live){setFailed(true);error(e.message);}}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[refresh]);
  const list=records.filter(r=>r.task_name?.toLowerCase().includes(query.toLowerCase()));
  return <section><div className="platform-heading"><div><h1>创作记录</h1><p>每执行一次任务，就有一条记录。这里包含手动与定时执行的历史。</p></div><span className="ss-badge">{list.length} 条记录</span></div><div className="task-filters"><input aria-label="搜索创作记录" placeholder="按任务名称搜索…" value={query} onChange={e=>setQuery(e.target.value)}/><button className="ss-btn" onClick={()=>setRefresh(v=>v+1)}>刷新记录</button><a className="ss-btn" href="#tasks">返回任务列表</a></div>{loading?<p className="inline-hint">正在读取创作记录…</p>:failed?<p className="inline-hint">读取失败，请点击刷新记录重试。</p>:<RecordList records={list} onOpen={run=>onOpen(run.task_id,run.id)}/>}</section>;
}
