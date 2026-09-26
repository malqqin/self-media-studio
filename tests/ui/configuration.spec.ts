import {authMock} from './fixtures';
import {test,expect} from '@playwright/test';
import {settings,models} from './fixtures';

test('model library saves multiple gateways and tests the unsaved connection',async({page})=>{
  const library=structuredClone(models),writes:any[]=[];let calls=0;
  await page.route('**/api/**',route=>{
    const req=route.request(),path=new URL(req.url()).pathname.replace('/api',''),body=req.postDataJSON();
    if(path.startsWith('/auth/'))return route.fulfill({json:authMock(path)});
    if(path==='/settings')return route.fulfill({json:settings});
    if(path==='/tasks'||path==='/topics')return route.fulfill({json:[]});
    if(path.startsWith('/models')){
      if(path.endsWith('/test')){calls++;expect(body.api_key).toBe('ui-fake-secret');return route.fulfill({json:{message:'连接成功，模型返回有效 JSON。'}});}
      if(req.method()!=='GET'){writes.push(body);const {api_key,clear_key,...fields}=body;const value={id:'new-model',...fields,key_configured:!!api_key&&!clear_key,ready:true,origin:'library'};library.push(value);return route.fulfill({json:value});}
      return route.fulfill({json:library});
    }
    return route.fulfill({status:500,json:{detail:'Unmocked API'}});
  });
  await page.goto('/#models');await page.getByRole('button',{name:'添加模型',exact:true}).click();
  await page.getByRole('button',{name:'修改地址 / 高级设置'}).click();await page.getByLabel('API 地址',{exact:true}).fill('https://gateway.example.com/v1');
  await page.getByRole('button',{name:'手动填写模型 ID',exact:true}).click();await page.getByLabel('模型 ID / 接入点',{exact:true}).fill('writer-model');
  await page.getByLabel('连接名称（选填）',{exact:true}).fill('日常写作');await page.getByLabel('API Key',{exact:true}).fill('ui-fake-secret');
  await expect(page.getByLabel('API Key',{exact:true})).toHaveAttribute('type','password');
  await page.getByRole('button',{name:'测试连接',exact:true}).click();await expect(page.getByRole('status')).toContainText('连接成功');expect(calls).toBe(1);expect(writes).toHaveLength(0);
  await page.getByRole('button',{name:'保存模型',exact:true}).click();await expect(page.locator('.configured-model')).toHaveCount(2);await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.reload();await expect(page.locator('.configured-model')).toHaveCount(2);await page.locator('.configured-model').filter({hasText:'日常写作'}).click();await expect(page.getByLabel('API Key',{exact:true})).toBeEmpty();await page.getByRole('button',{name:'修改地址 / 高级设置'}).click();await expect(page.getByLabel('API 地址',{exact:true})).toHaveValue('https://gateway.example.com/v1');
});

const directory=[
  {id:'deepseek-flash',name:'DeepSeek Flash',description:'快速写作与内容理解，支持图片输入、文本输出。',description_source:'api',model_type:'text',type_source:'api',protocol:'chat_completions'},
  {id:'doubao-seedream',name:'豆包 Seedream',description:'生成图片，可用于封面和文章配图。',description_source:'summary',model_type:'image',type_source:'inferred',protocol:'images'},
  {id:'doubao-seedance',name:'豆包 Seedance',description:'生成视频，暂未接入视频生成接口。',description_source:'summary',model_type:'video',type_source:'inferred',protocol:'catalog'},
];

test('provider discovery in centered dialog shows types, brands and saves selected model',async({page},testInfo)=>{
  let library:any[]=structuredClone(models),fetches=0,writes:any[]=[];
  await page.route('**/api/**',route=>{
    const req=route.request(),path=new URL(req.url()).pathname.replace('/api','');
    if(path.startsWith('/auth/'))return route.fulfill({json:authMock(path)});
    if(path==='/settings')return route.fulfill({json:settings});
    if(path==='/tasks'||path==='/topics')return route.fulfill({json:[]});
    if(path.endsWith('/discover')){
      const body=req.postDataJSON();fetches++;expect(body.base_url).toBe('https://ark.cn-beijing.volces.com/api/v3');expect(body.api_key).toBe('test-only-key');
      return route.fulfill({json:{models:directory,message:'模型目录不代表调用权限。'}});
    }
    if(path==='/models'&&req.method()==='POST'){
      const {api_key,clear_key,...fields}=req.postDataJSON();writes.push(fields);
      const value={id:'new-model',...fields,key_configured:true,ready:fields.protocol!=='catalog',origin:'library'};library.push(value);return route.fulfill({json:value});
    }
    if(path==='/models')return route.fulfill({json:library});
    return route.fulfill({status:500,json:{detail:'Unmocked API'}});
  });
  await page.goto('/#models');await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'添加模型',exact:true}).click();const dialog=page.getByRole('dialog');
  await expect(dialog).toBeVisible();const rect=await dialog.boundingBox();expect(Math.abs(rect!.x+rect!.width/2-640)).toBeLessThan(3);
  await page.locator('.model-provider').filter({hasText:'豆包 · 火山方舟'}).click();
  await page.getByLabel('API Key',{exact:true}).fill('test-only-key');await page.getByRole('button',{name:'获取模型列表',exact:true}).click();
  await expect(page.locator('.directory-model')).toHaveCount(3);expect(fetches).toBe(1);
  await expect(page.locator('.directory-model').first()).toContainText('类型来自接口');
  await page.screenshot({path:testInfo.outputPath('model-dialog-desktop.png')});
  await page.getByLabel('筛选模型类型',{exact:true}).selectOption('video');await expect(page.locator('.directory-model')).toHaveCount(1);
  await page.locator('.directory-model').click();await expect(page.getByRole('button',{name:'测试连接',exact:true})).toBeDisabled();await expect(page.locator('.model-directory-error')).toContainText('暂时仅保存到模型库');
  await page.getByLabel('筛选模型类型',{exact:true}).selectOption('image');await page.locator('.directory-model').click();
  await expect(page.getByLabel('连接名称（选填）',{exact:true})).toHaveValue('豆包 Seedream');
  await expect(page.getByRole('button',{name:'生成测试图',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'保存模型',exact:true}).click();await expect(dialog).toHaveCount(0);
  expect(writes).toHaveLength(1);expect(writes[0]).toMatchObject({model:'doubao-seedream',protocol:'images',model_type:'image'});
  await expect(page.locator('.configured-model').last().locator('img')).toHaveAttribute('src','/model-providers/doubao.svg');
  await page.screenshot({path:testInfo.outputPath('models-desktop.png')});
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'添加模型',exact:true}).click();
  await page.screenshot({path:testInfo.outputPath('model-dialog-mobile.png')});
  expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth)).toBeTruthy();
  await expect(page.getByRole('button',{name:'保存模型',exact:true})).toBeInViewport();
});

test('directory failure preserves key and offers manual entry without generating',async({page})=>{
  await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname.replace('/api','');
    if(path.startsWith('/auth/'))return route.fulfill({json:authMock(path)});
    if(path==='/settings')return route.fulfill({json:settings});
    if(path==='/models')return route.fulfill({json:models});
    if(path.endsWith('/discover'))return route.fulfill({status:400,json:{detail:'此服务商未开放模型目录，请手动填写。'}});
    return route.fulfill({json:[]});
  });
  await page.goto('/#models');await page.getByRole('button',{name:'添加模型',exact:true}).click();await page.getByLabel('API Key',{exact:true}).fill('fake-key');
  await page.getByRole('button',{name:'获取模型列表',exact:true}).click();await expect(page.getByLabel('模型 ID / 接入点',{exact:true})).toBeVisible();await expect(page.getByLabel('API Key',{exact:true})).toHaveValue('fake-key');
  await page.getByLabel('模型 ID / 接入点',{exact:true}).fill('ep-my-model');await expect(page.getByRole('button',{name:'保存模型',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'取消',exact:true}).click();await page.getByRole('button',{name:'添加模型',exact:true}).click();await expect(page.getByLabel('API Key',{exact:true})).toBeEmpty();
});
