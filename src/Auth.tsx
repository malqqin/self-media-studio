import CenteredModal from './CenteredModal';
import {createContext,useContext,useEffect,useRef,useState,type ReactNode} from 'react';
import {ArrowRight,Bird,FileUp,LoaderCircle,LockKeyhole,LogOut,Mail,ShieldCheck,UserRound,X} from 'lucide-react';
import {api,send} from './api';
import {useNotifications} from './Notifications';
import './auth.css';

export interface User {id:string;email:string;display_name:string;role:'admin'|'user';status:'active'|'disabled';email_verified:boolean;created_at:string;last_login_at:string|null}
interface AuthStatus {setup_required:boolean;registration_open:boolean;mail_ready:boolean}
const AuthContext=createContext<{user:User;logout:()=>Promise<void>}|null>(null);
export const useAuth=()=>useContext(AuthContext)!;

export function AuthGate({children}:{children:ReactNode}){
  const [user,setUser]=useState<User|null>(null),[status,setStatus]=useState<AuthStatus|null>(null),[loading,setLoading]=useState(true),[failure,setFailure]=useState('');
  const load=()=>{setLoading(true);setFailure('');Promise.all([api<{user:User|null}>('/auth/me'),api<AuthStatus>('/auth/status')]).then(([me,s])=>{setUser(me.user);setStatus(s);}).catch(e=>setFailure(e.message)).finally(()=>setLoading(false));};
  useEffect(()=>{load();const expired=()=>setUser(null);addEventListener('studio-session-expired',expired);return()=>removeEventListener('studio-session-expired',expired);},[]);
  const logout=async()=>{await api('/auth/logout',send('POST'));setUser(null);location.hash='home';load();};
  if(loading)return <div className="auth-loading"><LoaderCircle className="spin"/>正在打开创作空间…</div>;
  if(failure)return <div className="auth-loading"><p>{failure}</p><button className="ss-btn" onClick={load}>重新连接</button></div>;
  if(!user)return <Login status={status!} onSignedIn={setUser}/>;
  return <AuthContext.Provider value={{user,logout}}>{children}</AuthContext.Provider>;
}

function Login({status,onSignedIn}:{status:AuthStatus;onSignedIn:(user:User)=>void}){
  const [mode,setMode]=useState<'login'|'register'|'verify'|'forgot'|'reset'|'setup'>(status.setup_required?'setup':'login');
  const [email,setEmail]=useState(''),[password,setPassword]=useState(''),[name,setName]=useState(''),[code,setCode]=useState(''),[token,setToken]=useState('');
  const [tokenError,setTokenError]=useState('');const tokenInput=useRef<HTMLInputElement>(null),tokenFile=useRef<HTMLInputElement>(null);
  const [busy,setBusy]=useState(false),[hint,setHint]=useState(''),[countdown,setCountdown]=useState(0);const {error,success}=useNotifications();
  useEffect(()=>{if(!countdown)return;const timer=setTimeout(()=>setCountdown(x=>x-1),1000);return()=>clearTimeout(timer);},[countdown]);
  const change=(value:typeof mode)=>{setMode(value);setHint('');setCode('');setPassword('');};
  const requestCode=async(register:boolean)=>{const result=await api<{message:string}>(register?'/auth/register':'/auth/forgot',send('POST',register?{email,password,display_name:name}:{email}));setHint(result.message);setCountdown(60);setMode(register?'verify':'reset');};
  const normalizeToken=(value:string)=>value.replace(/^\uFEFF/,'').trim();
  const tokenProblem=(value:string)=>value.length<32||value.length>128?'初始化凭证不完整，请从凭证文件导入，或粘贴文件中的完整内容；这里不是登录密码。':'';
  const importToken=async(file:File)=>{
    try{
      if(file.size>4096)throw new Error('凭证文件内容不正确，请选择服务器 data/admin-setup.txt 文件。');
      const value=normalizeToken(await file.text()),problem=tokenProblem(value);
      if(problem)throw new Error(problem);
      setToken(value);setTokenError('');success('初始化凭证已导入，请继续填写昵称、邮箱和登录密码。');
    }catch(e){const message=(e as Error).message;setTokenError(message);error(message);}
  };
  const submit=async()=>{
    if(mode==='setup'){
      const problem=tokenProblem(normalizeToken(token));setTokenError(problem);
      if(problem){error(problem);tokenInput.current?.focus();return;}
    }
    setBusy(true);try{
      if(mode==='register'||mode==='forgot'){await requestCode(mode==='register');return;}
      if(mode==='reset'){await api('/auth/reset',send('POST',{email,code,password}));success('密码已重置，请重新登录。');change('login');return;}
      const body=mode==='setup'?{email,password,display_name:name,setup_token:normalizeToken(token)}:mode==='verify'?{email,code}:{email,password};
      const result=await api<{user:User}>('/auth/'+mode,send('POST',body));setPassword('');setToken('');onSignedIn(result.user);
    }catch(e){error((e as Error).message);}finally{setBusy(false);}
  };
  const titles={login:'欢迎回到知序',register:'创建你的创作空间',verify:'验证你的邮箱',forgot:'找回账号密码',reset:'设置新密码',setup:'设置管理员账号'};
  return <main className="auth-shell"><section className="auth-story"><a className="auth-brand" href="#home"><Bird/>知序 · 创作空间</a><div><span className="auth-orbit"><FileMark/></span><h1>让想法成篇，<br/>让创作发生。</h1><p>从一篇文章、一支短片到一组图片。<br/>把灵感、素材和日常创作，放进自己的空间。</p><div className="auth-chips"><span>专属工作台</span><span>自动创作</span><span>多模型协作</span></div></div><small>你的作品与模型配置，独立保存。</small></section>
    <section className="auth-card"><span className="auth-card-icon">{mode==='setup'?<ShieldCheck/>:<UserRound/>}</span><h2>{titles[mode]}</h2><p>{mode==='setup'?'先由服务器持有人初始化，历史作品将归入这个管理员账号。':mode==='verify'?`验证码已发送至 ${email}`:'一处管理灵感、任务与作品。'}</p>
      {mode==='setup'&&<div className="auth-note">先导入服务器 <code>data/admin-setup.txt</code> 文件，或复制文件中的完整内容。初始化凭证由系统生成、仅使用一次；下方的登录密码由你自己设置。</div>}
      {(mode==='register'||mode==='forgot')&&!status.mail_ready&&<div className="auth-note">管理员尚未配置邮件服务，暂时无法发送验证码。</div>}
      {hint&&<div className="auth-note" role="status">{hint}</div>}
      <form onSubmit={e=>{e.preventDefault();void submit();}}><fieldset disabled={busy}>
        {mode==='setup'&&<div className="auth-setup-credential"><label className="field">初始化凭证<input ref={tokenInput} type="password" aria-required="true" autoComplete="off" placeholder="粘贴凭证文件中的完整内容" aria-invalid={!!tokenError} aria-describedby={tokenError?'setup-token-help setup-token-error':'setup-token-help'} value={token} onChange={e=>{setToken(normalizeToken(e.target.value));setTokenError('');}}/></label><div className="auth-credential-actions"><input ref={tokenFile} type="file" accept=".txt,text/plain" hidden aria-label="选择凭证文件" onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void importToken(file);}}/><button type="button" className="auth-text" onClick={()=>tokenFile.current?.click()}><FileUp/>从凭证文件导入</button><small id="setup-token-help">填写文件内容，不是文件路径或登录密码。</small></div>{tokenError&&<p id="setup-token-error" className="auth-field-error">{tokenError}</p>}</div>}
        {(mode==='register'||mode==='setup')&&<label className="field">怎么称呼你<input required maxLength={60} value={name} onChange={e=>setName(e.target.value)} placeholder="输入昵称" autoComplete="nickname"/></label>}
        <label className="field">邮箱<div className="auth-input"><Mail/><input type="email" required maxLength={254} autoComplete="email" readOnly={mode==='verify'||mode==='reset'} value={email} onChange={e=>setEmail(e.target.value)} placeholder="你的常用邮箱"/></div></label>
        {(mode==='verify'||mode==='reset')&&<label className="field">邮箱验证码<input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} autoComplete="one-time-code" value={code} onChange={e=>setCode(e.target.value)} placeholder="6 位数字"/></label>}
        {mode!=='forgot'&&mode!=='verify'&&<label className="field">{mode==='reset'?'新密码':'密码'}<div className="auth-input"><LockKeyhole/><input required type="password" maxLength={128} autoComplete={mode==='login'?'current-password':'new-password'} value={password} onChange={e=>setPassword(e.target.value)} placeholder="请输入密码"/></div></label>}
        {mode==='login'&&<button className="auth-text" type="button" onClick={()=>change('forgot')}>忘记密码？</button>}
        <button className="ss-btn ss-primary auth-submit" disabled={((mode==='register'||mode==='forgot')&&!status.mail_ready)||((mode==='register')&&!status.registration_open)}>{busy?<LoaderCircle className="spin"/>:<ArrowRight/>}{mode==='login'?'登录创作空间':mode==='register'||mode==='forgot'?'发送验证码':mode==='verify'?'验证并进入':mode==='reset'?'保存新密码':'创建管理员并进入'}</button>
        {(mode==='verify'||mode==='reset')&&<button type="button" className="auth-text" disabled={countdown>0} onClick={()=>{setBusy(true);requestCode(mode==='verify').catch(e=>error(e.message)).finally(()=>setBusy(false));}}>{countdown?`${countdown} 秒后可重新发送`:'重新发送验证码'}</button>}
      </fieldset></form>
      {mode!=='setup'&&<div className="auth-switch">{mode==='login'?(status.registration_open?<>还没有账号？<button onClick={()=>change('register')}>邮箱注册</button></>:<span>注册已关闭，请联系管理员。</span>):<button onClick={()=>change('login')}>返回登录</button>}</div>}
    </section></main>;
}
function FileMark(){return <><i/><b>知</b><i/></>;}

export function AccountButton(){
  const {user,logout}=useAuth(),{error,success}=useNotifications();const [open,setOpen]=useState(false),[current,setCurrent]=useState(''),[next,setNext]=useState(''),[busy,setBusy]=useState(false);
  const leave=async()=>{try{await logout();}catch(e){error((e as Error).message);}};
  return <><button className="account-button" onClick={()=>setOpen(true)} aria-label="账号设置"><UserRound/><span>{user.display_name}</span></button>{open&&<CenteredModal titleId="account-title" onClose={()=>setOpen(false)} busy={busy}><button className="icon-button auth-close" aria-label="关闭账号设置" disabled={busy} onClick={()=>setOpen(false)}><X/></button><h2 id="account-title">我的账号</h2><p>{user.email} · {user.role==='admin'?'管理员':'创作者'}</p><form onSubmit={async e=>{e.preventDefault();setBusy(true);try{await api('/auth/password',send('POST',{current_password:current,new_password:next}));success('密码已更新，请重新登录。');await leave();}catch(e){error((e as Error).message);}finally{setBusy(false);}}}><fieldset disabled={busy}><label className="field">当前密码<input type="password" required autoComplete="current-password" value={current} onChange={e=>setCurrent(e.target.value)}/></label><label className="field">新密码<input type="password" required maxLength={128} autoComplete="new-password" placeholder="请输入密码" value={next} onChange={e=>setNext(e.target.value)}/></label><button className="ss-btn" disabled={!current||!next}>修改密码</button></fieldset></form><button className="ss-btn account-logout" onClick={leave}><LogOut/>退出登录</button></CenteredModal>}</>;
}
