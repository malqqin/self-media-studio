import {useState} from 'react';
import {History,RotateCcw} from 'lucide-react';
import WorkspaceDrawer from './WorkspaceDrawer';
import {dateText} from './api';
import type {Article} from './types';

export default function ArticleVersions({article,blocked,onRestore}:{article:Article;blocked:boolean;onRestore:(version:number)=>Promise<unknown>}){
  const [open,setOpen]=useState(false),[selected,setSelected]=useState<number|null>(null),[saving,setSaving]=useState(false);
  return <><button className="ss-btn article-versions-trigger" aria-label="查看版本记录" onClick={()=>setOpen(true)}><History/>版本记录 <span>{article.versions?.length||0}</span></button>
    {open&&<WorkspaceDrawer title="版本记录" subtitle="每次保存都有记录，可恢复角度、大纲、正文及当时的资料。" onClose={()=>{if(!saving)setOpen(false);}}>
      <p className="inline-hint">当前 v{article.version} · 恢复会另存为新版本。</p>
      <div className="version-timeline">{article.versions?.map(v=><label key={v.version} className={'version-item'+(selected===v.version?' is-selected':'')}><input type="radio" name="article-version" value={v.version} aria-label={`恢复 v${v.version}`} checked={selected===v.version} disabled={blocked||saving||!v.restorable||v.version===article.version} onChange={()=>setSelected(v.version)}/><span><strong>v{v.version}{v.version===article.version?' · 当前版本':''}</strong><span>{v.note}</span><small>{dateText(v.at)}{!v.restorable?' · 尚未生成内容':''}</small></span></label>)}</div>
      <div className="version-restore-actions"><p className="inline-hint">{blocked?'请先保存当前修改，并等待创作完成。':selected?`将恢复到 v${selected} 的内容`:'选择需要恢复的版本'}</p><button className="ss-btn ss-primary" disabled={blocked||saving||!selected||selected===article.version} onClick={async()=>{setSaving(true);try{if(await onRestore(selected!)!==false){setSelected(null);setOpen(false);}}finally{setSaving(false);}}}><RotateCcw/>恢复为新版本</button></div>
    </WorkspaceDrawer>}
  </>;
}
