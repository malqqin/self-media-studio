import options from '../shared/wechat-declarations.json';
import type {WeChatDeclaration as Declaration} from './types';

export const declarationLabel=(value?:string)=>options.find(o=>o.id===(value||'ai'))?.label||'内容由AI生成';
export default function WeChatDeclaration({value='ai',onChange,channel,mode}:{value?:Declaration;onChange:(value:Declaration)=>void;channel?:string;mode?:string}){
  return <div className="wechat-declaration"><label className="field">公众号创作来源<select aria-label="公众号创作来源" value={value} onChange={e=>onChange(e.target.value as Declaration)}>{options.map(o=><option value={o.id} key={o.id}>{o.label}</option>)}</select></label>
    <p className="inline-hint">按文章实际内容选择。扫码保存草稿时会设置同名声明，并在保存后核对；单篇发送时可以修改。</p>
    {channel==='api'&&value!=='none'&&mode!=='local'&&<p className="auth-note">微信官方 API 暂未开放这个字段。{mode==='publish'?'带声明的文章无法通过 API 自动发布，请改为保存草稿或扫码接入。':'API 保存草稿后，需到公众号后台手动选择此声明；要自动设置请使用扫码接入。'}</p>}
    {mode==='handoff'&&<p className="inline-hint">手动发布时，请在公众号后台选择上述声明。</p>}
  </div>;
}
