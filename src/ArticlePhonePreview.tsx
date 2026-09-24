import type {RefObject} from 'react';
import {ChevronLeft,Ellipsis,Signal,Wifi,BatteryFull} from 'lucide-react';
import {ArticleLayout,articleTemplate} from './ArticleTemplates';
import type {ArticleDocument} from './types';

export default function ArticlePhonePreview({document:doc,activePart,readingRef}:{document:ArticleDocument;activePart?:string;readingRef:RefObject<HTMLDivElement|null>}){
  const count=doc.sections.reduce((n,s)=>n+s.paragraphs.join('').length,doc.opening.length+doc.closing.length);
  return <aside className="phone-preview" aria-label="手机阅读预览">
    <div className="phone-preview-label"><strong>手机阅读预览</strong><span>{articleTemplate(doc.template_id).name} · {count} 字</span></div>
    <div className="phone-device">
      <span className="phone-side-key" aria-hidden="true"/>
      <div className="phone-screen">
        <div className="phone-status" aria-hidden="true"><span>9:41</span><i className="phone-speaker"/><span className="phone-status-icons"><Signal/><Wifi/><BatteryFull/></span></div>
        <div className="phone-navigation" aria-hidden="true"><ChevronLeft/><span>公众号图文</span><Ellipsis/></div>
        <div className="phone-reading-area" ref={readingRef} tabIndex={0} role="region" aria-label="文章手机预览内容"><ArticleLayout document={doc} activePart={activePart}/></div>
        <div className="phone-bottom" aria-hidden="true"><i/></div>
      </div>
    </div>
    <div className="phone-preview-hint">在手机内滚动阅读 · 编辑时自动定位</div>
  </aside>;
}
