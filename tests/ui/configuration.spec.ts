import {test,expect} from '@playwright/test';

test('daily preferences save without task or AI count limits',async({page,request})=>{
  let settings=await (await request.get('/api/settings')).json();let saved=false;
  await page.route('**/api/settings',route=>{
    if(route.request().method()==='PUT'){
      settings=route.request().postDataJSON();saved=true;
      expect(settings).not.toHaveProperty('daily_limit');
      expect(settings).not.toHaveProperty('daily_ai_calls');
    }
    return route.fulfill({json:settings});
  });
  await page.goto('/#flow');
  await expect(page.getByRole('heading',{name:'每日小计划'})).toBeVisible();
  await expect(page.getByLabel('每日任务上限',{exact:true})).toHaveCount(0);
  await expect(page.getByLabel('每日 AI 调用上限',{exact:true})).toHaveCount(0);
  await expect(page.getByText('制作任务和 AI 调用不设每日次数上限。',{exact:false})).toBeVisible();
  await expect(page.locator('.usage-line')).toContainText('次 AI 请求');
  await page.getByLabel('账号名称',{exact:true}).fill('测试编辑部');
  await page.getByRole('button',{name:'保存设置',exact:true}).click();
  await expect.poll(()=>saved).toBe(true);
  await expect(page.getByRole('status')).toContainText('设置已保存');
  await page.reload();
  await expect(page.getByLabel('账号名称',{exact:true})).toHaveValue('测试编辑部');
  await page.getByRole('button',{name:'每日选题',exact:true}).click();
  await expect(page.locator('.ss-plan-flow')).toContainText('按需制作');
  await expect(page.locator('.ss-plan-flow')).not.toContainText('每天最多');
});

test('model page saves gateway settings, keeps secrets hidden and tests explicit drafts',async({page})=>{
  let model={name:'环境变量配置',base_url:'https://api.openai.com/v1',model:'',protocol:'responses',output_mode:'json_schema',key_configured:false,ready:false,origin:'environment'};
  const writes:Record<string,unknown>[]=[];let tests=0;
  await page.route('**/api/model-config**',async route=>{
    if(route.request().url().endsWith('/test')){
      tests++;const data=route.request().postDataJSON();expect(data.protocol).toBe('chat_completions');expect(data.api_key).toBe('ui-fake-secret');
      return route.fulfill({json:{ok:true,message:'连接成功，模型返回有效 JSON。'}});
    }
    if(route.request().method()==='PUT'){
      const data=route.request().postDataJSON();writes.push(data);
      const {api_key,clear_key,...fields}=data;
      model={...model,...fields,key_configured:!clear_key&&(!!api_key||model.key_configured),ready:true,origin:'page'};
    }
    return route.fulfill({json:model});
  });
  await page.goto('/#flow');
  const card=page.locator('#model-settings');
  await card.getByRole('button',{name:'自定义 / 中转站'}).click();
  await card.getByLabel('API 地址',{exact:true}).fill('https://gateway.example.com/v1');
  await card.getByLabel('模型名称',{exact:true}).fill('my-model');
  await card.getByLabel('API Key',{exact:true}).fill('ui-fake-secret');
  await expect(card.getByLabel('API Key',{exact:true})).toHaveAttribute('type','password');
  await card.getByRole('button',{name:'测试连接',exact:true}).click();
  await expect(card.getByRole('status')).toContainText('连接成功');
  expect(tests).toBe(1);expect(writes).toHaveLength(0);
  await card.getByRole('button',{name:'保存模型配置'}).click();
  await expect(card.getByRole('status')).toContainText('已保存');
  await expect(card.getByLabel('API Key',{exact:true})).toBeEmpty();
  expect(writes[0].base_url).toBe('https://gateway.example.com/v1');
  await page.reload();
  await expect(card.getByLabel('模型名称',{exact:true})).toHaveValue('my-model');
  await expect(card.getByLabel('API Key',{exact:true})).toBeEmpty();
  await expect(card).not.toContainText('ui-fake-secret');
});

test('source page previews, persists, edits and removes sources without changing real settings',async({page,request})=>{
  let settings={...await (await request.get('/api/settings')).json(),sources:[],custom_sources:[]};
  await page.route('**/api/settings',route=>route.fulfill({json:settings}));
  await page.route('**/api/source-settings',async route=>{
    expect(route.request().method()).toBe('PUT');
    const body=route.request().postDataJSON();expect(Object.keys(body).sort()).toEqual(['custom_sources','sources']);
    settings={...settings,...body};return route.fulfill({json:settings});
  });
  await page.route('**/api/topics',route=>route.fulfill({json:[]}));
  await page.route('**/api/sources/preview',async route=>{
    const body=route.request().postDataJSON();expect(body.url).toBe('https://science.example.com/feed');
    expect(body.name).toBe('我的科学资料');
    return route.fulfill({json:{kind:'rss',count:1,note:'预览成功',items:[{title:'新发现的恒星',url:'https://science.example.com/article',summary:'科学观测内容'}]}});
  });
  await page.goto('/#topics');const card=page.locator('#source-settings');
  await card.getByLabel('采集网址',{exact:true}).fill('https://science.example.com/feed');
  await card.getByText('更多选项 · 名称与采集方式').click();
  await card.getByLabel('来源名称',{exact:true}).fill('我的科学资料');
  await card.getByRole('button',{name:'先预览一下'}).click();
  await expect(card.locator('.source-preview')).toContainText('新发现的恒星');
  await expect(page.locator('.ss-topic')).toHaveCount(0);
  await card.getByRole('button',{name:'仅保存配置'}).click();
  await expect(card.getByRole('status')).toContainText('采集配置已保存');
  await page.reload();await expect(card.locator('.custom-source')).toContainText('我的科学资料');
  const item=card.locator('.custom-source').filter({hasText:'我的科学资料'});
  await item.getByRole('button',{name:'编辑',exact:true}).click();
  await card.getByText('更多选项 · 名称与采集方式').click();
  await card.getByLabel('来源名称',{exact:true}).fill('更新后的资料');
  await card.getByRole('button',{name:'仅保存配置'}).click();
  await expect(card.locator('.custom-source')).toContainText('更新后的资料');
  await card.locator('.custom-source').getByRole('checkbox').uncheck();
  await card.getByRole('button',{name:'仅保存配置'}).click();
  await expect(card.getByRole('status')).toContainText('采集配置已保存');
  expect(settings.custom_sources[0].enabled).toBe(false);
  await card.getByRole('button',{name:'删除 更新后的资料'}).click();
  await card.getByRole('button',{name:'仅保存配置'}).click();
  await expect(card.getByRole('status')).toContainText('当前没有启用来源');
  expect(settings.custom_sources).toHaveLength(0);
  await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
