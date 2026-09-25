// Rasterize original vector ornaments for image uploads to WeChat.
import {chromium} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
const catalog=JSON.parse(await readFile(new URL('../shared/article-templates.json',import.meta.url),'utf8'));
const sources={cream:'botanical',sage:'botanical',journal:'teacup',rose:'rose',coffee:'teacup',postcard:'mountains'};
const browser=await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
try{
  const page=await browser.newPage({viewport:{width:480,height:200},deviceScaleFactor:2});
  for(const t of catalog.templates.filter(t=>t.decoration&&!t.animated)){
    const vector=await readFile(new URL(`../public/article-decorations/${sources[t.decoration]}.svg`,import.meta.url),'utf8');
    await page.setContent(`<style>html,body{margin:0;background:${t.paper}}svg{display:block;width:480px;height:200px}</style>${vector}`);
    await writeFile(new URL(`../public/article-decorations/${t.decoration}.png`,import.meta.url),await page.screenshot());
  }
}finally{await browser.close();}
