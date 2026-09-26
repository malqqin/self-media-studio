import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Wind } from 'lucide-react';
import drawing from './assets/pelican.svg?raw';

export default function PelicanScene({onExplore}:{onExplore:()=>void}) {
  const art=useRef<HTMLDivElement>(null);
  const [paused,setPaused]=useState(false);
  const [reduced,setReduced]=useState(false);
  useEffect(()=>{
    const host=art.current;
    if(!host)return;
    const svg=host.querySelector('svg')!;
    const mq=window.matchMedia('(prefers-reduced-motion: reduce)');
    const narrow=window.matchMedia('(max-width: 650px)');
    let frame=0,last=0,phase=.6;
    const find=(id:string)=>host.querySelector<SVGElement>('#'+id)!;
    const legs=['front','back'].map(side=>({outer:find('fn-leg-'+side+'-outline'),inner:find('fn-leg-'+side),foot:find('fn-foot-'+side)}));
    const pose=()=>{
      const feet=legs.map((leg,i)=>{
        const angle=phase+i*Math.PI,foot={x:785+23*Math.cos(angle),y:462+23*Math.sin(angle)},hip={x:i?738:728,y:i?309:310};
        const dx=foot.x-hip.x,dy=foot.y-hip.y,d=Math.hypot(dx,dy),along=(97*97-95*95+d*d)/(2*d),out=Math.sqrt(Math.max(0,97*97-along*along));
        const knee={x:hip.x+along*dx/d+out*dy/d,y:hip.y+along*dy/d-out*dx/d};
        const line=`M${hip.x} ${hip.y}L${knee.x} ${knee.y}L${foot.x} ${foot.y}`;
        leg.outer.setAttribute('d',line);leg.inner.setAttribute('d',line);leg.foot.setAttribute('transform',`translate(${foot.x} ${foot.y})`);return foot;
      });
      find('fn-crank').setAttribute('d',`M${feet[0].x} ${feet[0].y}L${feet[1].x} ${feet[1].y}`);
      find('fn-cycle').setAttribute('transform',`translate(0 ${Math.sin(phase*2)*.75})`);
    };
    const active=()=>!paused&&!mq.matches&&!document.hidden;
    const step=(time:number)=>{frame=0;if(!active()){last=0;return;}if(last)phase+=Math.min(time-last,50)*Math.PI*2/4500;last=time;pose();frame=requestAnimationFrame(step);};
    const sync=()=>{setReduced(mq.matches);host.dataset.paused=String(!active());if(active()&&!frame){last=0;frame=requestAnimationFrame(step);}else if(!active()&&frame){cancelAnimationFrame(frame);frame=0;last=0;}};
    const resize=()=>{svg.setAttribute('viewBox',narrow.matches?'495 60 570 590':'0 0 1200 650');svg.setAttribute('preserveAspectRatio','xMidYMid slice');};
    pose();resize();sync();mq.addEventListener('change',sync);narrow.addEventListener('change',resize);document.addEventListener('visibilitychange',sync);
    return ()=>{cancelAnimationFrame(frame);mq.removeEventListener('change',sync);narrow.removeEventListener('change',resize);document.removeEventListener('visibilitychange',sync);};
  },[paused]);
  return <div className="fn-hero">
    <div className="fn-hero-copy"><h1>今天，<br/>让好奇心出发。</h1><p>把繁琐留在身后，<br/>把值得讲的科学，带给更多人。</p><button className="fn-main-action" onClick={onExplore}>翻开今日选题 <ArrowUpRight/></button></div>
    <div ref={art} className="scene-art" dangerouslySetInnerHTML={{__html:drawing}} />
    <div className="fn-hero-caption"><Wind/><span>沿途收集灵感，回来讲个好故事。</span></div>
    <button className="fn-motion" onClick={()=>setPaused(v=>!v)} disabled={reduced} aria-label={reduced?'已减少动态效果':paused?'播放动画':'暂停动画'} aria-pressed={paused||reduced}>{reduced?'已减少动态效果':paused?'播放动画':'暂停动画'}</button>
  </div>;
}
