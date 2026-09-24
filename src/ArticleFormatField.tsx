import {useId} from 'react';
import catalog from '../shared/article-formats.json';
import type {ArticleFormat} from './types';

const formats=Object.entries(catalog);
const groups=[...new Set(formats.map(([,value])=>value.group))];

export default function ArticleFormatField({value,onChange,disabled=false}:{value:ArticleFormat;onChange:(value:ArticleFormat)=>void;disabled?:boolean}){
  const id=useId();
  return <div className="article-format-field">
    <div className="field"><label htmlFor={id}>文章形式</label><select id={id} value={value} disabled={disabled} aria-describedby={id+'-hint'} onChange={e=>onChange(e.target.value as ArticleFormat)}>
      {groups.map(group=><optgroup key={group} label={group}>{formats.filter(([,item])=>item.group===group).map(([name])=><option key={name} value={name}>{name}</option>)}</optgroup>)}
    </select></div>
    <p id={id+'-hint'} className="inline-hint article-format-hint">{catalog[value]?.description}<span>共 {formats.length} 种形式 · 按 {groups.length} 类选择</span></p>
  </div>;
}
