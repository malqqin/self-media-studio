import {useState} from 'react';
import {Plus,Trash2} from 'lucide-react';
import catalog from '../shared/picture-sources.json';
export const defaultPictureSources=catalog.map(s=>s.id);
export const selectedPictureSources=(value?:{web_sources?:string[];custom_sites?:string[]})=>{
  const selected=value?.web_sources?.filter(id=>defaultPictureSources.includes(id))||[];
  return selected.length?selected:value?.custom_sites?.length?[]:defaultPictureSources;
};
export default function PictureSources({value,onChange,sites=[],onSitesChange,disabled=false}:{value:string[];onChange:(v:string[])=>void;sites?:string[];onSitesChange?:(v:string[])=>void;disabled?:boolean}){
  const [url,setUrl]=useState(''),[error,setError]=useState('');
  const add=()=>{
    try{
      const raw=url.trim(),parsed=new URL(raw.includes('://')?raw:'https://'+raw);
      if(!raw||!['https:','http:'].includes(parsed.protocol)||!parsed.hostname.includes('.')||parsed.username||parsed.password||parsed.port||/[\s"'{}]/.test(raw))throw Error();
      const normalized=parsed.origin+parsed.pathname.replace(/\/$/,'');
      if(sites.includes(normalized)){setError('这个网站已添加。');return;}
      onSitesChange?.([...sites,normalized]);setUrl('');setError('');
    }catch{setError('请填写网站或栏目网址，例如 https://www.example.com/photos。');}
  };
  return <fieldset className="picture-source-options" disabled={disabled}><legend>搜索来源（可多选）</legend>
    <div className="picture-source-heading"><strong>内置搜索</strong><button type="button" className="text-button" disabled={disabled} onClick={()=>onChange([...defaultPictureSources])}>使用国内推荐</button></div>
    <div className="picture-source-group">{catalog.map(s=><label key={s.id} title={s.note}><input type="checkbox" aria-label={s.name} checked={value.includes(s.id)} onChange={e=>onChange(e.target.checked?[...value,s.id]:value.filter(v=>v!==s.id))}/><span>{s.name}<small>{s.note}</small></span></label>)}</div>
    {onSitesChange&&<div className="picture-custom-sites"><strong>指定网站找图</strong><p className="picture-source-note">填写网站或栏目网址，在该范围内按关键词找图，最多 5 个。取消上方渠道可只搜索自定义网站；未被搜索引擎收录的图片可能找不到。</p>
      {sites.map(site=><div className="picture-custom-site" key={site}><span>{site}</span><button type="button" className="icon-button" aria-label={'移除图片网站 '+site} onClick={()=>onSitesChange(sites.filter(v=>v!==site))}><Trash2 size={14}/></button></div>)}
      <div className="picture-custom-input"><input aria-label="自定义图片网站" placeholder="https://www.example.com/photos" maxLength={2000} value={url} disabled={disabled||sites.length>=5} onChange={e=>{setUrl(e.target.value);setError('');}} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();if(url.trim()&&sites.length<5)add();}}}/><button type="button" className="ss-btn" disabled={disabled||sites.length>=5||!url.trim()} onClick={add}><Plus size={14}/>添加网站</button></div>
      {error&&<p className="picture-site-error" role="alert">{error}</p>}
    </div>}
    <p className="picture-source-note">搜索由服务器发起。网站需要登录、限制访问或未被收录时，会提示原因。</p>
  </fieldset>;
}
