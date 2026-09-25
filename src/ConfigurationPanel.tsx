import {useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {ChevronRight,LoaderCircle,type LucideIcon} from 'lucide-react';
import WorkspaceDrawer from './WorkspaceDrawer';

export default function ConfigurationPanel({title,summary,note,icon:Icon,disabled,children}:{title:string;summary:string;note:string;icon:LucideIcon;disabled:boolean;children:ReactNode}){
  const [open,setOpen]=useState(false);
  return <>
    <button type="button" className="configuration-entry" aria-label={`配置${title}`} aria-haspopup="dialog" disabled={disabled} onClick={()=>setOpen(true)}>
      <span className="configuration-entry-icon"><Icon size={18}/></span><span className="configuration-entry-text"><strong>{title}</strong><span>{summary}</span><small>{note}</small></span><ChevronRight size={16}/>
    </button>
    {open&&createPortal(<WorkspaceDrawer placement="center" title={title} subtitle="设置会保留在当前任务中，返回后点击「保存配置」生效。" onClose={()=>setOpen(false)} footer={<div className="configuration-dialog-footer"><span>{disabled?<><LoaderCircle size={14} className="spin"/>正在处理，请稍候…</>:'完成后可继续配置其他项目'}</span><button type="button" className="ss-btn ss-primary" disabled={disabled} onClick={()=>setOpen(false)}>完成设置</button></div>}>
      <fieldset className="configuration-dialog-fields" disabled={disabled}>{children}</fieldset>
    </WorkspaceDrawer>,document.getElementById('science-fieldnotes')||document.body)}
  </>;
}
