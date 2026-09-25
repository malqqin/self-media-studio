import {useEffect,useState} from 'react';
import {LoaderCircle} from 'lucide-react';
import {api,send} from './api';
import {useNotifications} from './Notifications';

type Status={key_configured:boolean};
export default function UnsplashConnection({disabled=false}:{disabled?:boolean}){
  const [status,setStatus]=useState<Status|null>(null),[key,setKey]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const notify=useNotifications();
  useEffect(()=>{let active=true;api<Status>('/picture-sources/unsplash').then(v=>{if(active)setStatus(v);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[]);
  const save=async(clear=false)=>{
    setBusy(true);setError('');
    try{
      setStatus(await api<Status>('/picture-sources/unsplash',send('PUT',clear?{clear_key:true}:{access_key:key.trim()})));
      setKey('');notify.success(clear?'已断开 Unsplash 连接。':'Unsplash 已连接，可用于所有任务的配图搜索。');
    }catch(e){setError((e as Error).message);notify.error((e as Error).message);}finally{setBusy(false);}
  };
  return <details className="unsplash-connection"><summary>连接 Unsplash <span>{status?.key_configured?'已配置':status?'待连接':'查看连接设置'}</span></summary>
    <p className="inline-hint">在 <a href="https://unsplash.com/developers" target="_blank" rel="noreferrer">Unsplash Developers ↗</a> 创建应用，将 Access Key 填在这里（无需 Secret Key）。本机保存后所有任务共用；验证会使用一次搜索请求。</p>
    <label className="field">Unsplash Access Key<input type="password" autoComplete="off" maxLength={200} value={key} disabled={busy||disabled} onChange={e=>setKey(e.target.value)} placeholder={status?.key_configured?'已保存；填入新值可更换':'粘贴应用的 Access Key'}/></label>
    <div className="picture-card-actions"><button type="button" className="ss-btn" disabled={disabled||busy||!key.trim()} onClick={()=>void save()}>{busy&&<LoaderCircle className="spin"/>}{busy?'正在处理…':'验证并保存连接'}</button>{status?.key_configured&&<button type="button" className="text-button" disabled={busy||disabled} onClick={()=>void save(true)}>断开连接</button>}</div>
    {error&&<p className="picture-search-error" role="alert">{error}</p>}
  </details>;
}
