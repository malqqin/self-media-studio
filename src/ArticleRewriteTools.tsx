import {useId,useState} from 'react';
import {Sparkles} from 'lucide-react';

export type RewriteTarget={target:'title'|'summary'|'opening'|'closing'|'heading'|'paragraphs'|'paragraph';section?:number;paragraph?:number};
export const previewPart=(value:RewriteTarget)=>value.section===undefined?value.target:`section-${value.section}-${value.target}${value.target==='paragraph'?'-'+value.paragraph:''}`;

export default function ArticleRewriteTools({label,target,paragraphs,disabled,dirty,onSelect,onRewrite}:{label:string;target:RewriteTarget;paragraphs?:string[];disabled:boolean;dirty:boolean;onSelect:(target:RewriteTarget)=>void;onRewrite:(target:RewriteTarget,prompt:string)=>Promise<boolean>}){
  const [open,setOpen]=useState(false),[prompt,setPrompt]=useState(''),[scope,setScope]=useState('all');const id=useId();
  const current:RewriteTarget=scope!=='all'&&paragraphs?{target:'paragraph',section:target.section,paragraph:Number(scope)}:target;
  const run=async(instruction:string)=>{onSelect(current);if(await onRewrite(current,instruction)){setPrompt('');setOpen(false);}};
  return <div className="article-local-tools" onFocus={()=>onSelect(current)}>
    <div className="article-rewrite-actions">{target.target==='paragraphs'&&['缩短','补充解释','调整为口语','重新组织表达'].map(instruction=><button type="button" key={instruction} className="text-button" disabled={disabled} onClick={()=>run(instruction)}>{instruction}</button>)}
      <button type="button" className="text-button local-rewrite-toggle" disabled={disabled} aria-expanded={open} aria-controls={id} onClick={()=>{setOpen(v=>!v);onSelect(target);}}><Sparkles size={13}/>{target.target==='paragraphs'?'自定义改写':`AI 调整${label}`}</button>
    </div>
    {open&&<div className="article-local-prompt" id={id}>
      <div className="local-prompt-title"><strong>只调整{label}</strong><span>其他内容保持原样</span></div>
      {paragraphs&&<label className="field">调整范围<select aria-label={`${label}调整范围`} value={scope} onChange={e=>{setScope(e.target.value);onSelect(e.target.value==='all'?target:{target:'paragraph',section:target.section,paragraph:Number(e.target.value)});}} disabled={disabled}><option value="all">本节全部正文</option>{paragraphs.map((p,i)=><option key={i} value={i}>第 {i+1} 个自然段 · {p.slice(0,22)}</option>)}</select></label>}
      <label className="field">调整要求<textarea aria-label={`${label}调整要求`} rows={3} maxLength={2000} value={prompt} onChange={e=>setPrompt(e.target.value)} disabled={disabled} placeholder="例如：这里方向不对，改为说明实际用途；用一个具体例子开头，语气自然，控制在 150 字。"/></label>
      <div className="local-prompt-actions"><button type="button" className="ss-btn ss-primary" disabled={disabled||!prompt.trim()} onClick={()=>run(prompt.trim())}><Sparkles size={14}/>按要求调整</button><button type="button" className="text-button" disabled={disabled} onClick={()=>setOpen(false)}>收起</button><small>{dirty?'会先保存当前修改，再仅调整所选内容。':'当前版本保留在历史记录中。'}</small></div>
    </div>}
  </div>;
}
