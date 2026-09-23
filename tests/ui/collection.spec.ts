import {test,expect,type Page} from '@playwright/test';
import type {Settings,Topic} from '../../src/types';

const emptySettings:Settings={account_name:'知序',sources:[],custom_sources:[],schedule_enabled:false,schedule_time:'07:00',production_mode:'ai',duration_seconds:10,audio_mode:'silent',resolution:'1080p'};
const topic:Topic={id:'feed-test',title:'网络采集的新发现',category:'astronomy',source:'science.example.com',kind:'live',angle:'这是一段来自网络的科学观察资料。',rights:'核对原始使用条件',sources:[{id:'source-test',title:'原文',publisher:'science.example.com',url:'https://science.example.com/article',text:'科学观测资料'}],published_at:'2026-09-22T00:00:00Z',discovered_at:'2026-09-22T00:00:00Z',evidence_status:'网页正文快照'};

async function isolated(page:Page){
  const state={settings:structuredClone(emptySettings),topics:[] as Topic[],events:[] as string[]};
  await page.route('**/api/settings',route=>route.fulfill({json:state.settings}));
  await page.route('**/api/topics',route=>route.fulfill({json:state.topics}));
  await page.route('**/api/jobs',route=>route.fulfill({json:[]}));
  await page.route('**/api/health',route=>route.fulfill({json:{ok:true,ai_ready:false,model:null,duration_seconds:10,audio_mode:'silent',local_only:true}}));
  await page.route('**/api/source-settings',async route=>{
    state.events.push('save');state.settings={...state.settings,...route.request().postDataJSON()};
    return route.fulfill({json:state.settings});
  });
  return state;
}

test('fresh homepage is empty; URL alone saves then collects and persists across reloads',async({page})=>{
  const state=await isolated(page);let release:(()=>void)|undefined;
  await page.route('**/api/collect',async route=>{
    state.events.push('collect');expect(state.settings.custom_sources[0].url).toBe('https://science.example.com/feed');
    expect(state.settings.custom_sources[0].name).toBe('science.example.com');
    await new Promise<void>(resolve=>{release=resolve;});state.topics=[topic];
    return route.fulfill({json:{added:1,reports:[{source:'custom-test',status:'success',count:1,message:'网站：新增 1 条资料。'}]}});
  });
  await page.goto('/');
  await expect(page.getByRole('heading',{name:'还没有选题，先配置采集网址。'})).toBeVisible();
  await expect(page.locator('.fn-note')).toHaveCount(0);
  await page.getByRole('button',{name:'配置采集数据'}).click();
  const card=page.locator('#source-settings');
  await expect(card.getByLabel('采集网址',{exact:true})).toBeVisible();
  await expect(card.getByText('科学方向',{exact:true})).toHaveCount(0);
  await expect(page.locator('.ss-topic')).toHaveCount(0);
  await card.getByLabel('采集网址',{exact:true}).fill('https://science.example.com/feed');
  await card.getByRole('button',{name:'保存并采集',exact:true}).click();
  await expect.poll(()=>state.events).toEqual(['save','collect']);
  await expect(card.getByRole('button',{name:'正在采集…'})).toBeDisabled();
  release!();
  await expect(card.locator('.collection-result')).toContainText('新增 1 条资料');
  await expect(page.locator('.ss-detail h2')).toHaveText(topic.title);
  await expect(page.getByRole('button',{name:'制作这一题'})).toBeDisabled();
  await expect(page.getByRole('link',{name:'前往每日路线配置模型'})).toBeVisible();
  await page.reload();
  await expect(card.locator('.custom-source')).toContainText('science.example.com');
  await expect(page.locator('.ss-topic')).toHaveCount(1);
  await page.getByRole('button',{name:'今日漫游',exact:true}).click();
  await expect(page.locator('.fn-note')).toContainText(topic.title);
  expect(state.settings.custom_sources[0]).not.toHaveProperty('category');
});

test('verification failure explains browser difference and supports explicit body import',async({page})=>{
  const state=await isolated(page);
  await page.route('**/api/collect',route=>route.fulfill({json:{added:0,reports:[{source:'custom-test',url:'https://mp.weixin.qq.com/s/public-test',status:'error',count:0,code:'verification_required',message:'网站向采集浏览器返回了验证页，尚未取得正文。你的日常浏览器可能已有访问状态。'}]}}));
  await page.route('**/api/sources/import',route=>{
    const body=route.request().postDataJSON();
    expect(body.url).toBe('https://mp.weixin.qq.com/s/public-test');
    expect(body.title).toBe('企业产品观察');
    state.topics=[{...topic,title:body.title,sources:[{...topic.sources[0],url:body.url,text:body.text}],page_data:{method:'manual',full_text:true,images:[],links:[],captured_at:'2026-09-22T00:00:00Z'}}];
    return route.fulfill({json:{added:1,topic_id:topic.id,message:'正文已导入，保留原文链接，请核对内容与素材。'}});
  });
  await page.goto('/#topics');const card=page.locator('#source-settings');
  await card.getByLabel('采集网址',{exact:true}).fill('https://mp.weixin.qq.com/s/public-test');
  await card.getByText('更多选项 · 名称与采集方式').click();
  await card.getByLabel('采集方式',{exact:true}).selectOption('browser');
  await card.getByRole('button',{name:'保存并采集',exact:true}).click();
  await expect(card.getByRole('alert')).toContainText('验证页');
  await expect(card.getByRole('link',{name:'打开原文 ↗'})).toHaveAttribute('href','https://mp.weixin.qq.com/s/public-test');
  expect(state.settings.custom_sources[0].kind).toBe('browser');
  await card.getByRole('button',{name:'导入网页正文',exact:true}).click();
  await expect(card.getByLabel('原文网址',{exact:true})).toHaveValue('https://mp.weixin.qq.com/s/public-test');
  await card.getByLabel('原文标题',{exact:true}).fill('企业产品观察');
  await card.getByLabel('网页正文',{exact:true}).fill('这是一份从浏览器复制的企业产品介绍，描述不同公司的公开产品资料和特点。');
  await card.getByRole('button',{name:'导入正文到选题库'}).click();
  await expect(page.locator('.ss-detail h2')).toHaveText('企业产品观察');
  await expect(page.locator('.ss-detail')).toContainText('手动导入');
  await page.getByText('查看已采集正文与链接').click();
  await expect(page.locator('.captured-text')).toContainText('描述不同公司的公开产品资料');
});

test('failed collection retains config, shows source errors, and can retry with no new topics',async({page})=>{
  await isolated(page);let attempts=0;
  await page.route('**/api/collect',route=>{
    attempts++;
    return route.fulfill({json:{added:0,reports:[{source:'custom-test',count:0,status:attempts===1?'error':'success',message:attempts===1?'网站：网络连接失败或来源无法读取':'网站：新增 0 条资料，按链接去重。'}]}});
  });
  await page.goto('/#topics');const card=page.locator('#source-settings');
  await card.getByLabel('采集网址',{exact:true}).fill('https://science.example.com/feed');
  await card.getByRole('button',{name:'保存并采集',exact:true}).click();
  await expect(card.getByRole('alert')).toContainText('本次采集未成功');
  await expect(card.getByRole('alert')).toContainText('网络连接失败');
  await expect(card.locator('.custom-source')).toContainText('science.example.com');
  await expect(page.locator('.ss-topic')).toHaveCount(0);
  await card.getByRole('button',{name:'保存并采集',exact:true}).click();
  await expect(card.locator('.collection-result')).toContainText('没有新内容');
  expect(attempts).toBe(2);
});

test('invalid configuration prevents collection; partial failure still displays collected results',async({page})=>{
  const state=await isolated(page);let collects=0;
  await page.route('**/api/source-settings',async route=>{
    const data=route.request().postDataJSON();
    if(data.custom_sources[0]?.url.includes('127.0.0.1'))return route.fulfill({status:422,json:{detail:'不能读取本机或内网地址。'}});
    state.settings={...state.settings,...data};return route.fulfill({json:state.settings});
  });
  await page.route('**/api/collect',route=>{
    collects++;state.topics=[topic];
    return route.fulfill({json:{added:1,reports:[{source:'custom-test',status:'success',count:1,message:'新增 1 条资料'},{source:'nasa',status:'error',count:0,message:'NASA：网络连接失败'}]}});
  });
  await page.goto('/#topics');const card=page.locator('#source-settings');
  await card.getByRole('button',{name:'保存并采集',exact:true}).click();
  await expect(card.getByRole('alert')).toContainText('请先输入采集网址');
  await card.getByLabel('采集网址',{exact:true}).fill('http://127.0.0.1/private');
  await card.getByRole('button',{name:'保存并采集',exact:true}).click();
  await expect(card.getByRole('alert')).toContainText('不能读取本机');expect(collects).toBe(0);
  await card.getByLabel('采集网址',{exact:true}).fill('https://science.example.com/feed');
  await card.getByText('也可选择常用来源 · NASA / ESA / CERN / Nature').click();
  await card.locator('.source-builtin').filter({hasText:'NASA'}).getByRole('checkbox').check();
  await card.getByRole('button',{name:'保存并采集',exact:true}).click();
  await expect(card.locator('.collection-result')).toContainText('1 个来源未成功');
  await expect(page.locator('.ss-topic')).toHaveCount(1);expect(collects).toBe(1);
  await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
