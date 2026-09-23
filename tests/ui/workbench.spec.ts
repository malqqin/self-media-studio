import {test,expect} from '@playwright/test';

test('homepage artwork animates, pauses and guides empty accounts to configuration',async({page})=>{
  await page.route('**/api/topics',route=>route.fulfill({json:[]}));
  await page.route('**/api/settings',async route=>{const response=await route.fetch();return route.fulfill({json:{...await response.json(),sources:[],custom_sources:[]}});});
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');await expect(page.getByRole('heading',{name:/今天，\s*让好奇心出发/})).toBeVisible();
  const leg=page.locator('#fn-leg-front');const before=await leg.getAttribute('d');
  await expect.poll(()=>leg.getAttribute('d')).not.toBe(before);
  await page.getByRole('button',{name:'暂停动画'}).click();
  const paused=await leg.getAttribute('d');await page.waitForTimeout(100);expect(await leg.getAttribute('d')).toBe(paused);
  await page.getByRole('button',{name:'翻开今日选题'}).click();
  await expect(page.getByRole('heading',{name:'捡起一个好问题。'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'今天的手记还是空白。'})).toBeVisible();
  await expect(page.getByLabel('采集网址',{exact:true})).toBeVisible();
  await expect(page.getByText('内置选题')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('generated video is playable and editing opens the saved script',async({page})=>{
  await page.goto('/#review');
  await expect(page.locator('video')).toBeVisible();
  await expect.poll(()=>page.locator('video').evaluate((el:HTMLVideoElement)=>Number.isFinite(el.duration)?el.duration:0)).toBeCloseTo(10,1);
  await page.locator('.ss-shot').nth(1).click();
  await expect.poll(()=>page.locator('video').evaluate((el:HTMLVideoElement)=>el.currentTime)).toBeGreaterThan(0);
  await page.getByRole('button',{name:'编辑文案与画面'}).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByLabel('视频标题')).not.toBeEmpty();
  await expect(page.getByLabel('画面标题 1')).not.toBeEmpty();
  await expect(page.getByText('配音与字幕',{exact:true})).toHaveCount(0);
  await expect(page.locator('.asset-preview img').first()).toBeVisible();
  await page.getByRole('button',{name:'关闭编辑'}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('all four pages fit mobile, reduced motion is respected',async({page})=>{
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto('/');await expect(page.getByRole('button',{name:'已减少动态效果'})).toBeDisabled();
  for(const name of ['今日漫游','每日选题','成片审核','每日路线']){
    await page.getByRole('button',{name,exact:true}).click();
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  }
  await expect(page.getByLabel('账号名称')).toHaveValue('知序');
});
