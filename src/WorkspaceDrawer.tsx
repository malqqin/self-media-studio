import {useEffect,useId,useRef,type ReactNode} from 'react';
import {X} from 'lucide-react';
import {useNotificationHost} from './Notifications';
import './workspace-panels.css';

export default function WorkspaceDrawer({title,subtitle,children,onClose}:{title:string;subtitle?:string;children:ReactNode;onClose:()=>void}){
  const ref=useRef<HTMLDialogElement>(null),close=useRef<HTMLButtonElement>(null),id=useId(),setHost=useNotificationHost();
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null,dialog=ref.current!;
    const overflow=document.body.style.overflow;
    dialog.showModal();setHost(dialog);document.body.style.overflow='hidden';close.current?.focus({preventScroll:true});
    return()=>{dialog.close();setHost(null);document.body.style.overflow=overflow;if(previous?.isConnected)previous.focus({preventScroll:true});};
  },[setHost]);
  return <dialog ref={ref} className="workspace-drawer" aria-labelledby={id} onCancel={e=>{e.preventDefault();onClose();}} onClick={e=>{if(e.target===e.currentTarget){const r=e.currentTarget.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)onClose();}}}>
    <header className="workspace-drawer-heading"><div><span className="fn-label">创作工作台</span><h2 id={id}>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div><button ref={close} type="button" className="workspace-icon-button" aria-label={`关闭${title}`} onClick={onClose}><X/></button></header>
    <div className="workspace-drawer-body">{children}</div>
  </dialog>;
}
