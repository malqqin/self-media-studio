import {useEffect,useRef,type ReactNode} from 'react';
import {useNotificationHost} from './Notifications';

export default function CenteredModal({children,titleId,onClose,busy=false,className=''}:{children:ReactNode;titleId:string;onClose:()=>void;busy?:boolean;className?:string}){
  const element=useRef<HTMLDialogElement>(null),setHost=useNotificationHost();
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null,dialog=element.current!;
    dialog.showModal();setHost(dialog);
    const overflow=document.body.style.overflow;document.body.style.overflow='hidden';
    return()=>{dialog.close();setHost(null);document.body.style.overflow=overflow;previous?.isConnected&&previous.focus();};
  },[setHost]);
  return <dialog ref={element} className={'auth-modal '+className} aria-labelledby={titleId} onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>{children}</dialog>;
}
