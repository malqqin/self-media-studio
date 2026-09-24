import {useEffect,useRef,useState} from 'react';
import {CheckCircle2,LoaderCircle,QrCode,X} from 'lucide-react';
import {api,send} from './api';
import {useNotificationHost} from './Notifications';

type LoginState={status:string;message:string;has_qr:boolean;has_preview?:boolean;updated_at:string|null};
export function WeChatLogin({account,onClose,onConnected,onError,onNotice}:{account:{id:string;name:string};onClose:()=>void;onConnected:()=>void;onError:(s:string)=>void;onNotice:(s:string)=>void}){
  const dialog=useRef<HTMLDialogElement>(null),setHost=useNotificationHost();
  const [state,setState]=useState<LoginState|null>(null),[busy,setBusy]=useState(false);
  const active=!!state&&['starting','waiting_scan'].includes(state.status);
  const path=`/wechat/accounts/${account.id}/login`;
  useEffect(()=>{const d=dialog.current!;d.showModal();setHost(d);return()=>{d.close();setHost(null);};},[setHost]);
  useEffect(()=>{let alive=true;api<LoginState>(path).then(v=>{if(alive)setState(v);}).catch(e=>onError(e.message));return()=>{alive=false;};},[path]);
  useEffect(()=>{
    if(!active)return;
    let alive=true,timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{try{const v=await api<LoginState>(path);if(!alive)return;setState(v);if(v.status==='connected'){onNotice(v.message);onConnected();}else if(v.status==='failed'||v.status==='expired')onError(v.message);else timer=setTimeout(poll,2000);}catch(e){if(alive){setState(old=>old?{...old,status:'failed',has_qr:false}:old);onError((e as Error).message);}}};
    timer=setTimeout(poll,1500);return()=>{alive=false;clearTimeout(timer);};
  },[active,path]);
  const start=async()=>{setBusy(true);try{if(active)await api(path+'/cancel',send('POST'));setState(await api<LoginState>(path,send('POST')));}catch(e){onError((e as Error).message);}finally{setBusy(false);}};
  const cancel=async()=>{setBusy(true);try{setState(await api<LoginState>(path+'/cancel',send('POST')));onClose();}catch(e){onError((e as Error).message);}finally{setBusy(false);}};
  return <dialog ref={dialog} className={'wechat-login-dialog'+(state?.has_preview?' wechat-login-wide':'')} aria-labelledby="wechat-login-title" onCancel={e=>{e.preventDefault();onClose();}}>
    <button type="button" className="confirm-close" aria-label="关闭扫码窗口" onClick={onClose}><X/></button>
    <span className="wechat-login-icon"><QrCode/></span><h2 id="wechat-login-title">连接 {account.name}</h2>
    <p>使用管理员微信扫描官方二维码，在手机上选择公众号并确认登录。</p>
    {state?.has_preview?<img className="wechat-login-preview" src={`/api${path}/preview?v=${encodeURIComponent(state.updated_at||'')}`} alt="微信登录中间页面，点击账号或按钮继续" onClick={async e=>{const rect=e.currentTarget.getBoundingClientRect();try{await api(path+'/click',send('POST',{x:(e.clientX-rect.left)/rect.width*1280,y:(e.clientY-rect.top)/rect.height*850}));}catch(error){onError((error as Error).message);}}}/>:<div className="wechat-qr-box">{state?.has_qr?<img src={`/api${path}/qr?v=${encodeURIComponent(state.updated_at||'')}`} alt="微信公众平台官方登录二维码"/>:active?<LoaderCircle className="spin"/>:state?.status==='connected'?<CheckCircle2/>:<QrCode/>}</div>}
    <p role="status">{state?.message||'正在读取登录状态…'}</p>
    <div className="wechat-login-actions"><button className="ss-btn ss-primary" disabled={busy||state?.status==='starting'} onClick={start}>{active?'重新扫码':state?.status==='connected'?'检查登录状态':'开始扫码登录'}</button>{active&&<button className="ss-btn" disabled={busy} onClick={cancel}>取消登录</button>}</div>
    <small>独立会话，仅保存在本机；Windows 下加密保存。扫码后可自动保存草稿；只有任务选择草稿交付并执行时才会写入。个人号自动发布尚未开放。</small>
  </dialog>;
}
