"""Render original SVG animations into portable GIFs and static PNG fallbacks."""
import io,json
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
catalog=json.loads((root/'shared/article-templates.json').read_text(encoding='utf-8'))
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':480,'height':200},device_scale_factor=1)
    for item in catalog['templates']:
        if not item.get('animated'):continue
        folder=root/'public/article-decorations';name=item['decoration']
        page.set_content('<style>html,body{margin:0}svg{display:block;width:480px;height:200px}</style>'+(folder/(name+'.svg')).read_text(encoding='utf-8'))
        page.evaluate('document.getAnimations().forEach(a=>a.pause())')
        frames=[]
        for index in range(64):
            page.evaluate('(t)=>document.getAnimations().forEach(a=>a.currentTime=t)',index*125)
            frames.append(Image.open(io.BytesIO(page.screenshot(animations='allow'))).convert('RGB'))
        frames[0].save(folder/(name+'.png'))
        frames[0].save(folder/(name+'.gif'),save_all=True,append_images=frames[1:],duration=125,loop=0,disposal=1,optimize=True)
        size=(folder/(name+'.gif')).stat().st_size
        if size>=1_000_000:raise ValueError(f'{name}: GIF exceeds template size budget ({size})')
        print(name,size,flush=True)
    browser.close()
