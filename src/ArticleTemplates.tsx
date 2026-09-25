import {useEffect,useId,useState} from 'react';
import type {CSSProperties} from 'react';
import {Check,ChevronDown,Palette,Search,X,Pause,Play} from 'lucide-react';
import catalog from '../shared/article-templates.json';
import type {ArticleDocument,ArticleTemplateId} from './types';
import './article-templates.css';

type StylePart=keyof typeof catalog.base;
export const articleTemplates=catalog.templates;
export const articleTemplate=(id?:string)=>articleTemplates.find(t=>t.id===id)||articleTemplates[0];
function templateStyles(id?:string){
  const template=articleTemplate(id);
  const overrides=template.styles as Partial<Record<StylePart,CSSProperties>>;
  return Object.fromEntries(Object.entries(catalog.base).map(([part,base])=>[part,{...base,...overrides[part as StylePart]}])) as Record<StylePart,CSSProperties>;
}

function ArticleDecoration({template,style}:{template:typeof articleTemplates[number];style:CSSProperties}){
  const [paused,setPaused]=useState(false),[reduced,setReduced]=useState(()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(()=>{const media=window.matchMedia('(prefers-reduced-motion: reduce)');const change=()=>setReduced(media.matches);media.addEventListener('change',change);return()=>media.removeEventListener('change',change);},[]);
  if(!template.decoration)return null;
  const playing=template.animated&&!paused&&!reduced;
  return <>{template.animated&&<div className="template-motion-controls"><span>{reduced?'已跟随系统减少动态效果':'轻盈动效'}</span><button type="button" disabled={reduced} onClick={()=>setPaused(v=>!v)} aria-label={playing?'暂停模板动效':'播放模板动效'}>{playing?<Pause size={12}/>:<Play size={12}/>} {playing?'暂停':'播放'}</button></div>}<img className="template-decoration" data-motion={playing?'playing':'still'} src={`/article-decorations/${template.decoration}.${playing?'svg':'png'}`} alt="" aria-hidden="true" style={style}/></>;
}

export function ArticleLayout({document:doc,activePart}:{document:ArticleDocument;activePart?:string}){
  const template=articleTemplate(doc.template_id),styles=templateStyles(template.id);
  const highlight=(id:string)=>({'data-preview-part':id,className:activePart===id?'preview-selected':undefined});
  const image=(id:string,caption:string)=>id?<figure style={styles.figure}><img src={`/api/assets/${encodeURIComponent(id)}/file`} alt={caption||'文章配图'} style={styles.image}/>{caption&&<figcaption style={styles.caption}>{caption}</figcaption>}</figure>:null;
  return <section className="article-layout" data-article-template={template.id} style={styles.root}>
    <ArticleDecoration template={template} style={styles.decoration}/>
    <h1 style={styles.title} {...highlight('title')}>{doc.title}</h1>
    {image(doc.cover_asset_id,doc.cover_caption||'')}
    <p style={styles.summary} {...highlight('summary')}>{doc.summary}</p>
    {(doc.opening||activePart==='opening')&&<p style={styles.paragraph} {...highlight('opening')}>{doc.opening||'开头尚未填写'}</p>}
    {doc.sections.map((section,i)=><section key={i}>
      <h2 style={styles.heading} {...highlight(`section-${i}-heading`)}>{template.numbered&&<span style={styles.number}>{String(i+1).padStart(2,'0')}</span>}{section.heading}</h2>
      <div {...highlight(`section-${i}-paragraphs`)}>{section.paragraphs.map((p,j)=><p key={j} style={styles.paragraph} {...highlight(`section-${i}-paragraph-${j}`)}>{p}</p>)}</div>
      {image(section.asset_id,section.caption)}
    </section>)}
    {(doc.closing||activePart==='closing')&&<p style={styles.closing} {...highlight('closing')}>{doc.closing||'结尾尚未填写'}</p>}
  </section>;
}

export default function ArticleTemplatePicker({value='classic',onChange,disabled=false,samplePreview=false}:{value?:ArticleTemplateId;onChange:(id:ArticleTemplateId)=>void;disabled?:boolean;samplePreview?:boolean}){
  const template=articleTemplate(value),id=useId(),sample=template.sample;
  const [category,setCategory]=useState('全部'),[query,setQuery]=useState('');
  const categories=['全部',...new Set(articleTemplates.map(t=>t.category))];
  const ordered=[...articleTemplates.filter(t=>t.animated),...articleTemplates.slice(6).filter(t=>!t.animated),...articleTemplates.slice(0,6)];
  const visible=ordered.filter(t=>(category==='全部'||t.category===category)&&`${t.name} ${t.tag} ${t.description}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const sampleDoc:ArticleDocument={template_id:template.id as ArticleTemplateId,title:sample.title,titles:[sample.title],summary:sample.summary,opening:'',sections:[{heading:sample.heading,paragraphs:[sample.paragraph],evidence:[],asset_id:'',caption:'',image_hint:''}],closing:sample.closing,cover_hint:'',cover_asset_id:''};
  return <details className="article-template-picker"><summary><span className="template-picker-label"><Palette size={16}/>文章排版模板</span><span className="template-current"><i style={{background:template.accent}}/>{template.name}<ChevronDown size={14}/></span></summary>
    <div className="template-picker-content"><div className="template-intro"><span className="fn-label">为内容选一件合适的外衣</span><p>{samplePreview?'设为任务默认模板，手动草稿和自动生成的文章都会沿用。':'点击即预览，保存修改后用于复制、导出和公众号草稿。'}模板调整配色与版式，保留正文内容。</p></div>
    <div className="template-library-tools"><div className="template-categories" aria-label="模板风格分类">{categories.map(c=><button type="button" key={c} aria-pressed={category===c} onClick={()=>setCategory(c)}>{c}{c==='全部'&&<span>{articleTemplates.length}</span>}</button>)}</div><label className="template-search"><Search size={14}/><input aria-label="搜索排版模板" placeholder="搜索风格，例如：纸感、宋体" value={query} onChange={e=>setQuery(e.target.value)}/>{query&&<button type="button" aria-label="清空模板搜索" onClick={()=>setQuery('')}><X size={14}/></button>}</label></div>
    <p className="template-result-count" role="status">{visible.length} 款排版{visible.length<articleTemplates.length&&` / 共 ${articleTemplates.length} 款`} · 选择后即时预览</p>
    <fieldset className="template-options" disabled={disabled}><legend className="sr-only">选择文章排版模板</legend>
      {visible.map(t=>{const s=templateStyles(t.id);return <label className="template-option" key={t.id} style={{'--template-accent':t.accent} as CSSProperties}>
        <input type="radio" name={id} value={t.id} aria-label={t.name} checked={template.id===t.id} onChange={()=>onChange(t.id as ArticleTemplateId)}/>
        <span className={'template-thumb template-thumb-'+t.id} style={{backgroundColor:t.paper,backgroundImage:s.root.backgroundImage,backgroundSize:s.root.backgroundSize,fontFamily:s.root.fontFamily}} aria-hidden="true">
          <span className="template-thumb-kicker">{t.tag}{t.animated&&<span className="template-motion-badge"><Play size={9}/>动效</span>}</span>
          {t.decoration&&<img className="template-thumb-decoration" src={`/article-decorations/${t.decoration}.png`} alt=""/>}
          <strong style={{...s.title,fontSize:'15px',lineHeight:'1.6',margin:'0',padding:'5px 0',letterSpacing:'0.5px'}}>{t.sample.title}</strong>
          <span className="template-thumb-summary" style={{...s.summary,fontSize:'9px',lineHeight:'1.8',margin:'0',padding:'8px'}}>{t.sample.summary}</span>
          <span className="template-thumb-heading" style={{...s.heading,fontSize:'10px',lineHeight:'1.8',margin:'auto 0 0',padding:'5px 0'}}>{t.numbered&&<b>01</b>}{t.sample.heading}</span><span className="template-thumb-lines" style={{color:s.paragraph.color}}><i/><i/><i/></span>
        </span>
        <span className="template-option-label"><strong>{t.name}</strong>{template.id===t.id?<Check size={14}/>:<span>{t.tag}</span>}</span>
      </label>;})}
    </fieldset>
    {!visible.length&&<div className="template-empty">没有找到这种风格，试试“纸感”“旅行”或清空筛选。<button type="button" className="text-button" onClick={()=>{setQuery('');setCategory('全部');}}>查看全部模板</button></div>}
    <p className="template-description"><strong>{template.name}</strong> · {template.description}</p>
    {template.animated&&<p className="template-motion-note">预览支持暂停，系统开启“减少动态效果”时显示静态图。公众号草稿使用同款 GIF 动图，手动复制时请从图文包上传；实际播放以微信端为准。<a href="/template-previews/motion.html" target="_blank" rel="noreferrer">查看六款动效示例 ↗</a></p>}
    {samplePreview&&<details className="template-sample"><summary>展开完整示例预览</summary><p className="inline-hint">以下为版式示例，实际文章使用你的创作内容。</p><div className="template-sample-paper"><ArticleLayout document={sampleDoc}/></div></details>}
    </div>
  </details>;
}
