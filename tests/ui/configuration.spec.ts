import {test,expect} from '@playwright/test';
import {settings,models} from './fixtures';

test('model library saves multiple gateways and tests the unsaved connection',async({page})=>{
  const library=structuredClone(models),writes:any[]=[];let calls=0;
  await page.route('**/api/**',route=>{
    const req=route.request(),path=new URL(req.url()).pathname.replace('/api',''),body=req.postDataJSON();
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
  await page.getByLabel('连接名称',{exact:true}).fill('日常写作');await page.getByLabel('API 地址',{exact:true}).fill('https://gateway.example.com/v1');await page.getByLabel('模型名称',{exact:true}).fill('writer-model');await page.getByLabel('API Key',{exact:true}).fill('ui-fake-secret');
  await expect(page.getByLabel('API Key',{exact:true})).toHaveAttribute('type','password');
  await page.getByRole('button',{name:'测试连接',exact:true}).click();await expect(page.getByRole('status')).toContainText('连接成功');expect(calls).toBe(1);expect(writes).toHaveLength(0);
  await page.getByRole('button',{name:'保存模型',exact:true}).click();await expect(page.locator('.model-card')).toHaveCount(2);await expect(page.getByLabel('API Key',{exact:true})).toBeEmpty();
  await page.reload();await expect(page.locator('.model-card')).toHaveCount(2);await page.locator('.model-card').filter({hasText:'日常写作'}).click();await expect(page.getByLabel('API 地址',{exact:true})).toHaveValue('https://gateway.example.com/v1');
});
