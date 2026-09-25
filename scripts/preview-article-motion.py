"""Build the public motion-template gallery from the same catalog as the editor."""
import html
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.article_templates import TEMPLATES
from backend.article_export import html_body

cards=[]
for template in TEMPLATES.values():
    if not template.get('animated'):continue
    sample=template['sample']
    doc={'template_id':template['id'],'title':sample['title'],'summary':sample['summary'],'opening':'',
         'sections':[{'heading':sample['heading'],'paragraphs':[sample['paragraph']],'asset_id':'','caption':''}],
         'closing':sample['closing'],'cover_asset_id':''}
    urls={kind:f'../article-decorations/{template["decoration"]}.{kind}' for kind in ('svg','png')}
    cards.append('<article><header><strong>'+html.escape(template['name'])+'</strong><span>'+html.escape(template['tag'])+'</span></header><div class="paper">'+html_body(doc,animation_paths=urls)+'</div></article>')

page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>轻盈动效 · 六款公众号模板</title>
<style>*{box-sizing:border-box}body{margin:0;padding:40px;background:#e9ece5;color:#354c3f;font-family:"Microsoft YaHei",sans-serif}h1{font-size:30px;font-weight:400;margin:0 0 10px}.intro{font-size:13px;color:#72806e;margin:0 0 24px;line-height:1.8}.top,.gallery{max-width:1136px;margin:auto}.gallery{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px}article{min-width:0}header{display:flex;align-items:center;justify-content:space-between;margin:0 0 12px}header strong{font-weight:500;font-size:15px}header span{font-size:11px;color:#788272}.paper{height:780px;border-radius:12px;overflow:auto;background:white;box-shadow:0 8px 22px #2833260b;scrollbar-width:thin}.paper>section{min-height:100%}button{font:inherit;font-size:12px;border:1px solid #b5c3ac;padding:9px 15px;border-radius:24px;background:#f4f7ee;color:#4f6449;cursor:pointer;margin:0 0 26px}button:focus-visible{outline:2px solid #55764d;outline-offset:3px}@media(max-width:760px){body{padding:24px 16px}.gallery{grid-template-columns:1fr}.paper{height:auto}h1{font-size:25px}}</style>
<div class="top"><h1>轻盈动效 · 让开场有一点呼吸</h1><p class="intro">林间微风 / 海岸潮汐 / 星轨来信 / 萤火夜读 / 雨窗随笔 / 花瓣信笺<br>开场插画轻轻流动，正文安静阅读。选择喜欢的风格，在工作台的「文章排版模板 → 轻盈动效」应用。</p><button id="motion" type="button" aria-pressed="false">暂停全部动效</button></div><main class="gallery">'''+''.join(cards)+'''</main>
<script>const button=document.getElementById('motion');const media=matchMedia('(prefers-reduced-motion: reduce)');let paused=false;function apply(){const still=paused||media.matches;document.querySelectorAll('[data-template-decoration]').forEach(img=>{img.dataset.animated=img.dataset.animated||img.getAttribute('src');img.src=still?img.dataset.animated.replace(/\\.svg$/,'.png'):img.dataset.animated;});button.textContent=media.matches?'已跟随系统减少动态效果':paused?'播放全部动效':'暂停全部动效';button.disabled=media.matches;button.setAttribute('aria-pressed',String(still));}button.onclick=()=>{paused=!paused;apply()};media.addEventListener('change',apply);apply();</script></html>'''
target=ROOT/'public/template-previews/motion.html'
target.parent.mkdir(parents=True,exist_ok=True);target.write_text(page,encoding='utf-8')
print(target)
