import {createContext,useCallback,useContext,useEffect,useRef,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {CheckCircle2,CircleAlert,X} from 'lucide-react';

type Notice={id:number;kind:'success'|'error';message:string;key?:string;scope?:string};
type Notify=(message:string,key?:string)=>void;
const Context=createContext<{success:Notify;error:Notify;outcomeError:(message:string,key:string,scope:string)=>void;clearOutcome:(scope:string)=>void}>({success:()=>{},error:()=>{},outcomeError:()=>{},clearOutcome:()=>{}});
const HostContext=createContext<(host:HTMLElement|null)=>void>(()=>{});

export function NotificationProvider({children}:{children:ReactNode}){
  const [notices,setNotices]=useState<Notice[]>([]),counter=useRef(0),seen=useRef(new Set<string>()),stack=useRef<HTMLDivElement>(null);
  const [host,setHost]=useState<HTMLElement|null>(null);
  const show=useCallback((kind:Notice['kind'],message:string,key?:string,scope?:string)=>{
    if(!message.trim()||(key&&seen.current.has(key)))return;
    if(key)seen.current.add(key);
    setNotices(old=>old.some(n=>n.kind===kind&&n.message===message&&n.scope===scope)?old:[...old.filter(n=>(kind==='error'||n.kind==='error')&&(!scope||n.scope!==scope)).slice(-3),{id:++counter.current,kind,message,key,scope}]);
  },[]);
  const success=useCallback<Notify>((message,key)=>show('success',message,key),[show]);
  const error=useCallback<Notify>((message,key)=>show('error',message,key),[show]);
  const outcomeError=useCallback((message:string,key:string,scope:string)=>show('error',message,key,scope),[show]);
  const clearOutcome=useCallback((scope:string)=>setNotices(old=>old.some(n=>n.scope===scope)?old.filter(n=>n.scope!==scope):old),[]);
  const dismiss=useCallback((id:number)=>setNotices(old=>old.filter(n=>n.id!==id)),[]);
  useEffect(()=>{stack.current?.hidePopover?.();if(notices.length)stack.current?.showPopover?.();},[notices,host]);
  // A modal makes outside content inert, even when that content is in the top layer.
  return <Context.Provider value={{success,error,outcomeError,clearOutcome}}><HostContext.Provider value={setHost}>{children}{createPortal(<div ref={stack} popover="manual" className="notification-stack" aria-label="操作提示">{notices.map(n=><Notification key={n.id} notice={n} dismiss={dismiss}/>)}</div>,host||document.body)}</HostContext.Provider></Context.Provider>;
}

function Notification({notice,dismiss}:{notice:Notice;dismiss:(id:number)=>void}){
  useEffect(()=>{if(notice.kind==='error')return;const timer=setTimeout(()=>dismiss(notice.id),6500);return()=>clearTimeout(timer);},[notice,dismiss]);
  return <div className={'notification-popup notification-'+notice.kind} role={notice.kind==='error'?'alert':'status'}><span className="notification-icon">{notice.kind==='error'?<CircleAlert/>:<CheckCircle2/>}</span><div><strong>{notice.kind==='error'?'操作未完成':'操作成功'}</strong><p>{notice.message}</p></div><button type="button" onClick={()=>dismiss(notice.id)} aria-label={notice.kind==='error'?'关闭错误提示':'关闭成功提示'}><X/></button></div>;
}

export const useNotifications=()=>useContext(Context);
export const useNotificationHost=()=>useContext(HostContext);

export function useOutcomeNotice(id:string,status:string|undefined,error:string|null|undefined,version:number|string|undefined,successText:string){
  const notify=useNotifications(),previous=useRef<{id:string;status:string|undefined}>({id,status});
  useEffect(()=>{
    if(error)notify.outcomeError(error,`${id}:${version}:${error}`,id);
    else {
      notify.clearOutcome(id);
      if(previous.current.id===id&&['queued','running','publishing'].includes(previous.current.status||'')&&status&&!['queued','running','publishing','failed'].includes(status))notify.success(successText,`${id}:${version}:${status}`);
    }
    previous.current={id,status};
  },[id,status,error,version,successText,notify.outcomeError,notify.clearOutcome,notify.success]);
  useEffect(()=>()=>notify.clearOutcome(id),[id,notify.clearOutcome]);
  return ()=>{if(error)notify.outcomeError(error,'',id);};
}
