import UnsplashConnection from './UnsplashConnection';
export const pictureSources=[['bing','必应图片'],['360','360 图片'],['baidu','百度图片'],['unsplash','Unsplash'],['commons','Wikimedia Commons'],['openverse','Openverse']] as const;
export default function PictureSources({value,onChange,disabled=false}:{value:string[];onChange:(v:string[])=>void;disabled?:boolean}){
  return <><fieldset className="picture-source-options" disabled={disabled}><legend>搜索来源（可多选）</legend>{pictureSources.map(([id,name])=><label key={id}><input type="checkbox" checked={value.includes(id)} onChange={e=>onChange(e.target.checked?[...value,id]:value.filter(v=>v!==id))}/>{name}</label>)}</fieldset>{value.includes('unsplash')&&<><p className="inline-hint">Unsplash 适合摄影、风景、建筑与生活配图。推荐英文关键词，例如 artificial intelligence、mountain、city。首次使用请连接官方图库账号的应用密钥。</p><UnsplashConnection disabled={disabled}/></>}</>;
}
