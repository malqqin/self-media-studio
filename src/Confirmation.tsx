import {createContext,useCallback,useContext,useEffect,useRef,useState,type ReactNode} from 'react';
import {History,ArrowRight,Undo2,Trash2,X} from 'lucide-react';
import {useNotificationHost} from './Notifications';

type ConfirmOptions={title:string;message:string;confirmLabel:string;cancelLabel?:string;detail?:string;tone?:'replace'|'discard'|'delete'};
type Confirm=(options:ConfirmOptions)=>Promise<boolean>;
const Context=createContext<Confirm>(async()=>false);

export function ConfirmationProvider({children}:{children:ReactNode}){
  const [options,setOptions]=useState<ConfirmOptions|null>(null);
  const pending=useRef<((confirmed:boolean)=>void)|null>(null);
  const confirm=useCallback<Confirm>(value=>{
    if(pending.current)return Promise.resolve(false);
    return new Promise(resolve=>{pending.current=resolve;setOptions(value);});
  },[]);
  const finish=useCallback((confirmed:boolean)=>{const resolve=pending.current;pending.current=null;setOptions(null);resolve?.(confirmed);},[]);
  useEffect(()=>()=>pending.current?.(false),[]);
  return <Context.Provider value={confirm}>{children}{options&&<Confirmation options={options} onFinish={finish}/>}</Context.Provider>;
}

function Confirmation({options,onFinish}:{options:ConfirmOptions;onFinish:(v:boolean)=>void}){
  const dialog=useRef<HTMLDialogElement>(null),cancel=useRef<HTMLButtonElement>(null),setHost=useNotificationHost();
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    const element=dialog.current!;element.showModal();setHost(element);cancel.current?.focus();
    const overflow=document.body.style.overflow;document.body.style.overflow='hidden';
    return()=>{element.close();setHost(null);document.body.style.overflow=overflow;if(previous?.isConnected)previous.focus();};
  },[setHost]);
  const Icon=options.tone==='delete'?Trash2:options.tone==='discard'?Undo2:History;
  return <dialog ref={dialog} className={'studio-confirm'+(options.tone==='delete'?' confirm-delete':'')} role="alertdialog" aria-labelledby="confirm-title" aria-describedby="confirm-message" onCancel={e=>{e.preventDefault();onFinish(false);}}>
    <button type="button" className="confirm-close" aria-label="关闭确认窗口" onClick={()=>onFinish(false)}><X/></button>
    <span className="confirm-symbol"><Icon/></span>
    <span className="confirm-eyebrow">{options.tone==='delete'?'整理创作空间':options.tone==='discard'?'离开编辑之前':'继续创作'}</span>
    <h2 id="confirm-title">{options.title}</h2><p id="confirm-message">{options.message}</p>
    {options.detail&&<div className="confirm-detail"><History/><span>{options.detail}</span></div>}
    <div className="confirm-actions"><button type="button" ref={cancel} onClick={()=>onFinish(false)}>{options.cancelLabel||'暂不更改'}</button><button type="button" className="confirm-primary" onClick={()=>onFinish(true)}>{options.confirmLabel}<ArrowRight/></button></div>
  </dialog>;
}

export const useConfirmation=()=>useContext(Context);
