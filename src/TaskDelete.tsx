import {useState} from 'react';
import {Trash2} from 'lucide-react';
import {useConfirmation} from './Confirmation';
import {useNotifications} from './Notifications';
import {api,send} from './api';
import type {CreationTask} from './types';

export default function TaskDelete({task,onDeleted,disabled=false,unsaved=false,compact=false}:{task:CreationTask;onDeleted:(id:string)=>void;disabled?:boolean;unsaved?:boolean;compact?:boolean}){
  const confirm=useConfirmation(),{error,success}=useNotifications(),[busy,setBusy]=useState(false);
  const running=task.is_running||task.runs?.some(r=>['queued','running','publishing'].includes(r.status))||['queued','running','publishing'].includes(task.latest_run?.status||'');
  const remove=async()=>{
    if(!await confirm({title:'删除这个任务？',message:`“${task.name}”将从首页和任务列表移除，定时执行也会停止。`,detail:'已保存的作品和执行记录会保留，可在回收站恢复。'+(unsaved?'当前未保存的修改将被放弃。':''),confirmLabel:'移入回收站',cancelLabel:'保留任务',tone:'delete'}))return;
    setBusy(true);
    try{await api(`/tasks/${task.id}`,send('DELETE',{version:task.version}));onDeleted(task.id);success('任务已移入回收站，定时执行已停止。');}
    catch(e){error((e as Error).message);setBusy(false);}
  };
  return <button type="button" className={compact?'task-delete-button':'ss-btn task-delete-button'} aria-label={`删除任务：${task.name}`} title={running?'任务正在执行，完成后可删除':'删除任务'} disabled={disabled||busy||!!running} onClick={remove}><Trash2/>{busy?'删除中…':'删除任务'}</button>;
}
