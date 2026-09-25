import {useEffect,useRef,useState} from 'react';
import {LoaderCircle,RefreshCw} from 'lucide-react';
import type {PictureCandidate} from './types';

export default function SearchPicture({picture}:{picture:PictureCandidate}){
  const holder=useRef<HTMLDivElement>(null);
  const [visible,setVisible]=useState(false),[attempt,setAttempt]=useState(0),[loaded,setLoaded]=useState(false),[retry,setRetry]=useState(0);
  const urls=[...new Set([picture.preview_url,picture.url,picture.provider==='Unsplash'?null:`/api/pictures/candidates/${encodeURIComponent(picture.id)}/preview`].filter((v):v is string=>!!v))];
  const src=urls[attempt],failed=attempt>=urls.length;
  useEffect(()=>{
    const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){setVisible(true);observer.disconnect();}},{rootMargin:'200px'});
    if(holder.current)observer.observe(holder.current);
    return()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    setLoaded(false);
  },[src,retry]);
  useEffect(()=>{
    if(!visible||loaded||failed)return;
    const timeout=setTimeout(()=>setAttempt(n=>n===attempt?n+1:n),15000);
    return()=>clearTimeout(timeout);
  },[src,retry,visible,loaded,failed,attempt]);
  return <div ref={holder} className="picture-preview-frame">
    {failed?<div className="picture-preview-missing"><span>缩略图和原图均未能加载</span><small>可能链接失效或来源限制访问，可查看来源。</small><button type="button" className="text-button" aria-label={`重新加载预览：${picture.title}`} onClick={()=>{setLoaded(false);setAttempt(0);setRetry(n=>n+1);}}><RefreshCw size={13}/>重新加载</button></div>:<>
      {!loaded&&<div className="picture-preview-loading" role="status"><LoaderCircle className="spin"/>{attempt?'正在尝试备用预览…':'正在加载预览…'}</div>}
      {visible&&<img key={`${src}:${retry}`} src={src} alt={picture.title} referrerPolicy="no-referrer" className={loaded?'is-loaded':''} onLoad={()=>setLoaded(true)} onError={()=>{setLoaded(false);setAttempt(n=>n===attempt?n+1:n);}}/>}
    </>}
  </div>;
}
