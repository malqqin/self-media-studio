import {authMock} from './fixtures';
import {test,expect,type Page} from '@playwright/test';
import {settings,taskSettings,models,task as makeTask} from './fixtures';
import type {CreationTask,ImageJob,TaskRun} from '../../src/types';

async function openConfig(page:Page,title:string){await page.getByRole('button',{name:'配置'+title,exact:true}).click();}
async function finishConfig(page:Page){await page.getByRole('button',{name:'完成设置',exact:true}).click();}

export async function mockPlatform(page:Page){
  const state={tasks:[] as CreationTask[],writes:[] as {path:string;body:any}[],image:null as ImageJob|null};
  await page.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname.replace('/api',''),body=req.postDataJSON(),method=req.method();
    if(path.startsWith('/auth/'))return route.fulfill({json:authMock(path)});
    const reply=(json:unknown,status=200)=>route.fulfill({json,status});
    if(method!=='GET')state.writes.push({path,body});
    if(path==='/settings')return reply(settings);
    if(path==='/topics'||path==='/assets'||path==='/source-catalog')return reply([]);
    if(path==='/models')return reply(models);
    if(path==='/wechat/accounts')return reply([]);
    if(path==='/task-records')return reply(state.tasks.filter(t=>!t.deleted_at).flatMap(t=>(t.runs||[]).map(r=>({...r,task_name:t.name,kind:t.kind,archived:t.archived}))));
    if(path==='/tasks'){
      if(method==='POST'){const t={...makeTask(body.kind,'task-'+(state.tasks.length+1)),name:body.name};state.tasks.unshift(t);return reply(t,201);}
      return reply(state.tasks.filter(t=>Boolean(t.deleted_at)===(new URL(req.url()).searchParams.get('deleted')==='true')));
    }
    const t=state.tasks.find(t=>path.startsWith('/tasks/'+t.id));
    if(t){
      if(path.endsWith('/restore')){t.deleted_at=null;t.archived=true;t.version++;return reply(t);}
      if(method==='DELETE'){if(body.version!==t.version)return reply({detail:'任务配置已更新，请刷新后再操作。'},409);if(t.is_running)return reply({detail:'任务正在执行。'},409);t.deleted_at='2026-09-24T01:00:00Z';t.archived=true;t.version++;return reply({id:t.id,deleted_at:t.deleted_at});}
      if(t.deleted_at)return reply({detail:'任务已删除，可到回收站恢复。'},404);
      if(path.endsWith('/collect'))return reply({topics:[],reports:[{source:'联网资讯',message:'没有新的资料，请调整关键词',status:'success',count:0}]});
      if(path.endsWith('/archive')){t.archived=!t.archived;t.version++;return reply(t);}
      if(path.endsWith('/run')){
        const run:TaskRun={id:'run-'+(t.runs!.length+1),task_id:t.id,action:body.action,status:'needs_review',stage:'content',content_id:'image-ui-test',settings:structuredClone(t.settings),reports:[],error:null,created_at:'2026-09-23T00:00:00Z',updated_at:'2026-09-23T00:00:00Z'};
        t.runs!.unshift(run);t.latest_run=run;t.run_count=t.runs!.length;
        state.image={id:'image-ui-test',version:1,status:'needs_review',document:{title:t.name,cards:[{heading:'开始自己的创作',body:'这是可以手动编辑的中文图文内容。',footer:''}]},settings:structuredClone(t.settings.image),files:[],source_data:[],error:null};return reply(run);
      }
      if(method==='PUT'){Object.assign(t,body,{version:t.version+1});}
      return reply(t);
    }
    if(path==='/image-jobs/image-ui-test'&&state.image){if(method==='PUT')Object.assign(state.image,body,{version:state.image.version+1});return reply(state.image);}
    return reply({detail:'Unmocked route: '+method+' '+path},500);
  });
  return state;
}

test('home creates named tasks of each type and filters task list',async({page},testInfo)=>{
  const state=await mockPlatform(page),errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');await expect(page.getByRole('heading',{name:'给第一个想法起个名字。'})).toBeVisible();
  await expect(page.getByRole('navigation')).toHaveText('首页任务列表素材库我的模型发布账号');
  for(const [kind,name] of [['公众号文章','每周工具观察'],['视频','城市生活短片'],['图片','周末生活卡片']]){
    await page.getByRole('button',{name:'新建任务',exact:true}).click();const dialog=page.getByRole('dialog');
    await dialog.getByLabel('任务名称').fill(name);await dialog.getByRole('button',{name:new RegExp(kind)}).click();await dialog.getByRole('button',{name:'创建并进入工作台'}).click();
    await expect(page.getByRole('heading',{name,exact:true})).toBeVisible();
    await expect(page.getByRole('navigation',{name:'主导航'})).toHaveCount(0);
    await page.getByRole('link',{name:'任务列表',exact:true}).click();
  }
  await page.getByRole('button',{name:'任务列表',exact:true}).click();await expect(page.locator('.task-card')).toHaveCount(3);
  await page.locator('.task-filters').getByRole('button',{name:'图片',exact:true}).click();await expect(page.locator('.task-card')).toHaveCount(1);
  await page.getByRole('button',{name:'首页',exact:true}).click();await page.screenshot({path:testInfo.outputPath('platform-home.png'),fullPage:true});
  expect(state.tasks).toHaveLength(3);expect(errors).toEqual([]);
});

test('main pages and creation dialog remove decorative English headings and their empty spacing',async({page},testInfo)=>{
  const state=await mockPlatform(page);state.tasks.push(makeTask('article','heading-task'));
  const removed=['SELF MEDIA STUDIO','YOUR IDEAS, TAKING SHAPE','RECENT PROJECTS','ALL PROJECTS','MATERIAL LIBRARY','MODEL LIBRARY','PUBLISHING ACCOUNTS','A NEW BEGINNING'];
  const expectRemoved=async()=>{for(const text of removed)await expect(page.getByText(text,{exact:true})).toHaveCount(0);};
  await page.goto('/');await expectRemoved();
  for(const name of ['任务列表','素材库','我的模型','发布账号']){
    await page.getByRole('button',{name,exact:true}).click();await expectRemoved();
  }
  const main=await page.locator('main').boundingBox(),pageTitle=await page.getByRole('heading',{name:'发布账号',exact:true}).boundingBox();
  expect(pageTitle!.y-main!.y).toBeLessThan(12);
  await page.getByRole('button',{name:'新建任务',exact:true}).click();const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();await expectRemoved();
  const dialogBox=await dialog.boundingBox(),dialogTitle=await dialog.getByRole('heading',{name:'新建创作任务',exact:true}).boundingBox();
  expect(dialogTitle!.y-dialogBox!.y).toBeLessThan(55);
  await page.screenshot({path:testInfo.outputPath('compact-headings.png'),fullPage:true});
});

test('configuration summaries open focused dialogs and preserve choices until saved',async({page},testInfo)=>{
  const state=await mockPlatform(page),task=makeTask('article','summary-task');state.tasks.push(task);
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/#task/summary-task');
  await expect(page.locator('.configuration-entry')).toHaveCount(6);
  await expect(page.getByLabel('AppSecret',{exact:true})).toHaveCount(0);
  await expect(page.getByLabel('文章交付方式')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'配置作品交付',exact:true})).toContainText('留在工作台');
  await page.getByLabel('这篇想写的话题').fill('周末去平遥，看看古建筑');
  await openConfig(page,'写作偏好');await page.getByLabel('目标字数').fill('1800');await page.getByLabel('文章形式',{exact:true}).selectOption('旅行攻略');await page.keyboard.press('Escape');
  await expect(page.getByRole('button',{name:'配置写作偏好',exact:true})).toContainText('旅行攻略 · 约 1800 字');
  await expect(page.getByRole('button',{name:'配置写作偏好',exact:true})).toBeFocused();
  await openConfig(page,'文章排版');await expect(page.getByRole('dialog').getByRole('radio')).toHaveCount(18);
  await page.getByLabel('搜索排版模板').fill('鼠尾草');await page.getByRole('radio',{name:'鼠尾草花园',exact:true}).check();
  await page.getByRole('dialog').screenshot({path:testInfo.outputPath('configuration-template-desktop.png')});await finishConfig(page);
  await expect(page.getByRole('button',{name:'配置文章排版',exact:true})).toContainText('鼠尾草花园');
  await openConfig(page,'参考资料');await page.getByLabel('平台自动联网查找资料').check();await page.getByLabel('搜索范围').selectOption('wechat');await page.getByLabel('发布时间',{exact:true}).selectOption('7');await finishConfig(page);
  await expect(page.getByRole('button',{name:'配置参考资料',exact:true})).toContainText('近 7 天');
  expect(state.writes).toHaveLength(0);
  await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect.poll(()=>task.settings.article.template_id).toBe('sage');
  expect(task.settings.article.length).toBe(1800);expect(task.settings.materials.max_age_days).toBe(7);
  await page.getByRole('button',{name:'关闭成功提示'}).click();await expect(page.locator('.notification-success')).toHaveCount(0);await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:testInfo.outputPath('configuration-summary-desktop.png'),fullPage:true});
  await page.reload();await expect(page.getByRole('button',{name:'配置文章排版',exact:true})).toContainText('鼠尾草花园');
  await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('configuration-summary-mobile.png'),fullPage:true});
  await openConfig(page,'文章排版');await page.getByLabel('搜索排版模板').fill('奶油');await expect(page.getByRole('dialog').getByRole('radio')).toHaveCount(1);
  await page.getByRole('dialog').screenshot({path:testInfo.outputPath('configuration-template-mobile.png')});await finishConfig(page);
  expect(errors).toEqual([]);
});

test('per-task model, collection and schedule persist; manual image remains editable',async({page},testInfo)=>{
  const state=await mockPlatform(page);state.tasks.push(makeTask('image','task-1'));
  await page.goto('/#task/task-1');await page.getByLabel('创作主题与受众').fill('周末城市生活，写给喜欢散步和记录的年轻人');
  await page.getByLabel('自动执行',{exact:false}).check();await page.getByLabel('执行时间（北京时间）').fill('18:45');
  await page.getByLabel('周日',{exact:true}).click();await openConfig(page,'参考资料');await page.getByLabel('平台自动联网查找资料').check();await page.getByLabel('查找关键词').fill('城市生活');
  await finishConfig(page);await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect(page.getByRole('status')).toContainText('设定时间自动执行');
  await page.reload();await expect(page.getByLabel('执行时间（北京时间）')).toHaveValue('18:45');await openConfig(page,'参考资料');await expect(page.getByLabel('查找关键词')).toHaveValue('城市生活');await finishConfig(page);
  expect(state.tasks[0].settings.schedule.weekdays).not.toContain(7);
  await page.getByRole('button',{name:'创建手动草稿',exact:true}).click();await expect(page.getByLabel('第 1 页标题')).toHaveValue('开始自己的创作');
  await page.getByLabel('第 1 页标题').fill('周末走出家门');await page.waitForResponse(r=>r.url().includes('/api/image-jobs/'));
  await expect(page.getByLabel('第 1 页标题')).toHaveValue('周末走出家门');
  await page.getByRole('button',{name:'保存并生成图片'}).click();await expect(page.getByRole('status')).toContainText('文案已保存');
  expect(state.image!.document.cards[0].heading).toBe('周末走出家门');
  await page.screenshot({path:testInfo.outputPath('image-workspace.png'),fullPage:true});
});

test('article forms are grouped, explained and persist independently of templates',async({page},testInfo)=>{
  const state=await mockPlatform(page),task=makeTask('article','task-forms');state.tasks.push(task);
  await page.goto('/#task/task-forms');await openConfig(page,'写作偏好');
  const field=page.getByLabel('文章形式',{exact:true});
  await expect(field).toHaveValue('教程');await expect(field.locator('option')).toHaveCount(48);await expect(field.locator('optgroup')).toHaveCount(8);
  const oldTemplate=task.settings.article.template_id;
  await field.selectOption('访谈');await expect(page.locator('.article-format-hint')).toContainText('真实对话');
  await field.selectOption('旅行攻略');await expect(page.locator('.article-format-hint')).toContainText('路线');
  await finishConfig(page);await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await expect.poll(()=>task.settings.article.format).toBe('旅行攻略');expect(task.settings.article.template_id).toBe(oldTemplate);
  await page.reload();await openConfig(page,'写作偏好');await expect(field).toHaveValue('旅行攻略');
  await page.getByRole('dialog').screenshot({path:testInfo.outputPath('article-forms-desktop.png'),animations:'disabled'});
  await page.setViewportSize({width:390,height:844});await field.selectOption('项目复盘');
  await expect(page.locator('.article-format-hint')).toContainText('项目目标');
  await expect(page.locator('.article-format-hint')).toHaveCSS('display','block');
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('dialog').screenshot({path:testInfo.outputPath('article-forms-mobile.png'),animations:'disabled'});
  await finishConfig(page);await page.getByRole('button',{name:'保存配置',exact:true}).click();await expect.poll(()=>task.settings.article.format).toBe('项目复盘');
});

test('all navigation and task configuration fit narrow screens',async({page},testInfo)=>{
  const state=await mockPlatform(page);state.tasks.push(makeTask('article','task-1'));
  await page.setViewportSize({width:390,height:844});await page.emulateMedia({reducedMotion:'reduce'});await page.goto('/');
  for(const name of ['首页','任务列表','素材库','我的模型','发布账号']){await page.getByRole('navigation').getByRole('button',{name,exact:true}).click();await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}
  await page.goto('/#task/task-1');await openConfig(page,'写作偏好');await expect(page.getByRole('textbox',{name:'公众号定位',exact:true})).toHaveValue(taskSettings.article.direction);
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('task-mobile.png'),fullPage:true});
});

test('configuration edits survive polling and cancelled navigation',async({page})=>{
  const state=await mockPlatform(page);state.tasks.push(makeTask('article','task-1'));await page.goto('/#task/task-1');
  await openConfig(page,'写作偏好');await page.getByRole('textbox',{name:'公众号定位',exact:true}).fill('新的定位尚未保存');
  await finishConfig(page);await page.getByRole('link',{name:'任务列表',exact:true}).click();await expect(page.getByRole('alertdialog')).toBeVisible();await page.getByRole('button',{name:'继续编辑',exact:true}).click();
  await expect(page).toHaveURL(/#task\/task-1$/);await page.waitForResponse(r=>r.url().endsWith('/api/tasks/task-1'));
  await openConfig(page,'写作偏好');await expect(page.getByRole('textbox',{name:'公众号定位',exact:true})).toHaveValue('新的定位尚未保存');
});

test('video task opens editable scenes and preserves the manual script',async({page})=>{
  const state=await mockPlatform(page),t=makeTask('video','task-1');state.tasks.push(t);
  t.runs=[{id:'run-video',task_id:t.id,action:'blank',status:'draft',stage:'content',content_id:'job-ui',settings:t.settings,reports:[],error:null,created_at:t.created_at,updated_at:t.updated_at}];
  let job={id:'job-ui',topic_id:'note-1',status:'draft',stage:'script',progress:25,mode:'manual',version:1,settings,source_data:[{id:'source-1',title:'创作笔记',text:'关于周末生活的个人实践记录，画面来源于本人拍摄。',url:'',publisher:'本人'}],script:{title:'周末生活短片',description:'城市生活观察',title_lines:['记录周末生活'],scenes:[{heading:'城市公园',source_id:'source-1',evidence:'关于周末生活的个人实践记录',visual:'question',asset_id:'',clip_start:0}]},artifacts:null,qa:null,error:null,note:'手动草稿',created_at:t.created_at,updated_at:t.updated_at};
  await page.route('**/api/jobs/job-ui**',route=>{if(route.request().method()==='PUT'){job={...job,script:route.request().postDataJSON().script,version:2};}return route.fulfill({json:job});});
  await page.goto('/#task/task-1');await page.getByRole('button',{name:'编辑文案与画面'}).click();
  await expect(page.getByRole('dialog')).toBeVisible();await page.getByLabel('视频标题',{exact:true}).fill('周末去公园走走');
  await page.getByLabel('画面标题 1',{exact:false}).fill('留一点时间给自己');await page.getByRole('button',{name:'保存新版本'}).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);expect(job.script.title).toBe('周末去公园走走');expect(job.script.title_lines).toEqual(['留一点时间给自己']);
});

test('execution exposes all collected articles and error popup does not repeat on polling',async({page},testInfo)=>{
  const state=await mockPlatform(page),t=makeTask('article','task-sources');state.tasks.push(t);
  const items=Array.from({length:8},(_,i)=>({topic_id:'source-'+i,title:'山西旅行观察 '+(i+1),url:'https://example.com/shanxi/'+i,summary:'这一篇资料介绍山西的历史文化、地方旅行路线与个人见闻。',full_text:i%2===0}));
  t.runs=[{id:'run-sources',task_id:t.id,action:'assist',status:'failed',stage:'error',content_id:null,settings:{...t.settings,_used_topic_ids:items.slice(0,5).map(i=>i.topic_id)},reports:[{source:'联网查找',status:'success',count:8,message:'已取得 8 条资料，新增 8 条。',items}],error:'模型输出达到上限，已保存内容保留。',created_at:t.created_at,updated_at:t.updated_at}];
  await page.goto('/#task/task-sources');
  await expect(page.getByRole('alert')).toContainText('模型输出达到上限');
  await page.getByRole('button',{name:'查看选题与资料'}).click();
  await expect(page.locator('.collected-item')).toHaveCount(8);
  await expect(page.locator('.collected-item').getByText('本次采用',{exact:true})).toHaveCount(5);
  await expect(page.locator('.collected-item').last().getByRole('link')).toHaveAttribute('href','https://example.com/shanxi/7');
  await expect(page.getByRole('navigation',{name:'主导航'})).toHaveCount(0);
  await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
  const popup=await page.getByRole('alert').boundingBox();expect(popup!.y).toBeGreaterThanOrEqual(0);expect(popup!.y+popup!.height).toBeLessThan(1000);
  await page.getByRole('button',{name:'关闭错误提示'}).click();
  await page.waitForResponse(r=>r.url().endsWith('/api/tasks/task-sources'));
  await expect(page.getByRole('alert')).toHaveCount(0);
  await page.getByRole('button',{name:'关闭选题与资料'}).click();
  await page.getByRole('button',{name:'查看失败原因',exact:true}).click();await expect(page.getByRole('alert')).toBeVisible();
  await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:testInfo.outputPath('collection-and-popup.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('collection-mobile.png'),fullPage:true});
});

test('create failure appears above the creation dialog and remains dismissible',async({page})=>{
  await mockPlatform(page);
  await page.route('**/api/tasks',route=>route.request().method()==='POST'?route.fulfill({status:400,json:{detail:'创建失败，请检查任务名称。'}}):route.fulfill({json:[]}));
  await page.goto('/');await page.getByRole('button',{name:'新建任务',exact:true}).click();await page.getByRole('dialog').getByLabel('任务名称').fill('测试任务');
  await page.getByRole('button',{name:'创建并进入工作台'}).click();await expect(page.getByRole('alert')).toContainText('创建失败');
  await page.getByRole('button',{name:'关闭错误提示'}).click();await expect(page.getByRole('alert')).toHaveCount(0);await expect(page.getByRole('dialog')).toBeVisible();
});

test('runs without collection show only their selected materials',async({page})=>{
  const state=await mockPlatform(page),t=makeTask('article','task-materials');state.tasks.push(t);
  t.topics=Array.from({length:2},(_,i)=>({id:'saved-'+i,title:'已保存资料 '+i,category:'general',kind:'live',source:'公开资料',angle:'任务曾经保存的资料摘要',sources:[{id:'saved-'+i,title:'已保存资料 '+i,text:'公开资料的内容摘要',url:'https://example.com/'+i,publisher:'公开来源'}],published_at:null,discovered_at:t.created_at,rights:'待核验',evidence_status:'摘要'}));
  t.runs=[{id:'run-no-collection',task_id:t.id,action:'assist',status:'failed',stage:'error',content_id:null,settings:{...t.settings,_used_topic_ids:[]},reports:[],error:null,created_at:t.created_at,updated_at:t.updated_at}];
  await page.goto('/#task/task-materials');await expect(page.locator('.run-snapshot')).toBeVisible();
  await expect(page.locator('.collected-sources')).toHaveCount(0);
  t.runs[0].settings._used_topic_ids=['saved-1'];await page.reload();
  await page.getByRole('button',{name:'查看选题与资料'}).click();
  await expect(page.locator('.collected-sources')).toContainText('本次参考资料');
  await expect(page.locator('.collected-item')).toHaveCount(1);
  await expect(page.locator('.collected-item')).toContainText('已保存资料 1');
});

test('retry clears the previous error popup when the run starts again',async({page})=>{
  const state=await mockPlatform(page),t=makeTask('article','task-retry');state.tasks.push(t);
  const run:TaskRun={id:'run-retry',task_id:t.id,action:'assist',status:'failed',stage:'error',content_id:null,settings:t.settings,reports:[],error:'上一轮生成失败，请重试。',created_at:t.created_at,updated_at:t.updated_at};t.runs=[run];
  await page.route('**/api/task-runs/run-retry/retry',route=>{run.status='running';run.error=null;run.updated_at='2026-09-23T00:01:00Z';return route.fulfill({json:{id:run.id,status:'queued'}});});
  await page.goto('/#task/task-retry');await expect(page.getByRole('alert')).toContainText('上一轮生成失败');
  await page.getByRole('button',{name:'关闭错误提示'}).click();await page.getByRole('button',{name:'查看失败原因',exact:true}).click();
  await expect(page.getByRole('alert')).toBeVisible();await page.getByRole('button',{name:'重试本次执行'}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);await expect(page.getByRole('heading',{name:'正在创作内容…'})).toBeVisible();
});

test('article direction, daily schedule and WeChat reference preferences persist',async({page},testInfo)=>{
  const state=await mockPlatform(page),t=makeTask('article','task-daily');state.tasks.push(t);
  await page.goto('/#task/task-daily');await page.getByRole('button',{name:'围绕方向持续创作',exact:false}).click();
  await page.getByLabel('长期写作方向',{exact:true}).fill('山西值得去的旅游景点，每篇介绍一个地方，讲清文化特色与看点。');
  await openConfig(page,'参考资料');await page.getByRole('button',{name:'参考文章创作',exact:true}).click();await page.getByLabel('希望参考什么').selectOption('structure');
  await page.getByLabel('平台自动联网查找资料').check();await page.getByLabel('搜索范围').selectOption('wechat');
  await page.getByLabel('发布时间',{exact:true}).selectOption('30');
  await expect(page.locator('.wechat-reference-note')).toContainText('不把搜索排名当作热度');await finishConfig(page);await page.getByLabel('自动执行',{exact:false}).check();await page.getByLabel('执行时间（北京时间）').fill('08:30');
  await expect(page.locator('.configuration-overview')).toContainText('围绕方向选择新话题');
  await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('设定时间自动执行');await page.getByRole('button',{name:'关闭成功提示'}).click();
  await page.reload();await expect(page.getByLabel('长期写作方向')).toHaveValue(t.settings.brief);
  await openConfig(page,'参考资料');await expect(page.getByLabel('希望参考什么')).toHaveValue('structure');await expect(page.getByLabel('搜索范围')).toHaveValue('wechat');
  await finishConfig(page);expect(t.settings.article_plan?.mode).toBe('direction');expect(t.settings.materials.max_age_days).toBe(30);
  await page.screenshot({path:testInfo.outputPath('article-direction-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('article-direction-mobile.png'),fullPage:true});
});

test('collection displays relevance decisions and unknown readership',async({page})=>{
  const state=await mockPlatform(page),t=makeTask('article','task-filter');state.tasks.push(t);
  t.runs=[{id:'run-filter',task_id:t.id,action:'assist',status:'failed',stage:'collect',content_id:null,settings:{...t.settings,_used_topic_ids:[]},error:null,created_at:t.created_at,updated_at:t.updated_at,
    reports:[{source:'公众号文章 · 平遥',status:'success',count:1,candidate_count:2,query:'平遥 古城',message:'保留 1 篇相关资料。',heat_note:'搜索来源不提供可核验阅读量，不标记为爆款。',excluded:[{title:'分享是什么意思',reason:'词典释义，与景点介绍无关'}],items:[{topic_id:'wechat-1',title:'在平遥看古建筑',url:'https://mp.weixin.qq.com/s/test',summary:'平遥古城的街巷文化与历史建筑介绍。',full_text:false,platform:'wechat',publisher:'文化旅行',published_at:'2026-09-22T00:00:00Z',heat:'unknown',relevance_reason:'直接介绍平遥建筑看点',access_note:'暂未取得全文'}]}]}];
  await page.goto('/#task/task-filter');await page.getByRole('button',{name:'查看选题与资料'}).click();await expect(page.locator('.collected-item')).toContainText('文化旅行');
  await expect(page.locator('.collected-item')).toContainText('阅读量未提供');await expect(page.locator('.collected-item')).toContainText('入选原因');
  await page.locator('.collection-log>summary').click();await page.getByText('已排除 1 条不符合要求的结果',{exact:true}).click();
  await expect(page.locator('.collection-log')).toContainText('词典释义，与景点介绍无关');
});

test('delete task uses confirmation, removes cards and restores into archive',async({page},testInfo)=>{
  const state=await mockPlatform(page),task=makeTask('article','task-delete');task.name='待清理任务';task.settings.execution='automatic';state.tasks.push(task);
  let nativeDialogs=0;page.on('dialog',async d=>{nativeDialogs++;await d.dismiss();});
  await page.goto('/#tasks');await page.getByRole('button',{name:'删除任务：待清理任务',exact:true}).click();
  const confirm=page.getByRole('alertdialog',{name:'删除这个任务？'});
  await expect(confirm).toContainText('定时执行也会停止');await expect(confirm.getByRole('button',{name:'保留任务'})).toBeFocused();
  await page.keyboard.press('Escape');await expect(page.locator('.task-card')).toHaveCount(1);
  expect(state.writes.filter(w=>w.path==='/tasks/task-delete')).toHaveLength(0);
  await page.getByRole('button',{name:'删除任务：待清理任务',exact:true}).click();
  await page.screenshot({path:testInfo.outputPath('delete-task-confirm.png'),fullPage:true,animations:'disabled'});
  await confirm.getByRole('button',{name:'移入回收站'}).click();
  await expect(page.locator('.task-card')).toHaveCount(0);await expect(page.getByRole('status')).toContainText('回收站');
  await page.reload();await expect(page.locator('.task-card')).toHaveCount(0);
  await page.getByRole('button',{name:'回收站',exact:true}).click();
  await expect(page.getByRole('heading',{name:'任务回收站'})).toBeVisible();await expect(page.locator('.trash-task-card')).toContainText(task.name);
  await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('task-trash-mobile.png'),fullPage:true});
  await page.getByRole('button',{name:'从回收站恢复'}).click();await expect(page.locator('.trash-task-card')).toHaveCount(0);
  await page.getByRole('button',{name:'返回任务列表',exact:true}).click();await page.getByLabel('已归档',{exact:true}).check();
  await expect(page.locator('.task-card')).toContainText('待清理任务');await expect(page.locator('.task-card')).toContainText('定时执行已暂停');
  expect(task.deleted_at).toBeNull();expect(task.archived).toBe(true);expect(nativeDialogs).toBe(0);
});

test('detail deletion warns about unsaved edits and returns directly to list',async({page})=>{
  const state=await mockPlatform(page),task=makeTask('article','task-delete-detail');state.tasks.push(task);
  await page.goto('/#task/task-delete-detail');await page.getByLabel('任务名称',{exact:true}).fill('尚未保存的新名字');
  await page.getByRole('button',{name:'删除任务：我的创作任务',exact:true}).click();
  await expect(page.getByRole('alertdialog')).toContainText('当前未保存的修改将被放弃');
  await page.getByRole('button',{name:'保留任务',exact:true}).click();await expect(page.getByLabel('任务名称',{exact:true})).toHaveValue('尚未保存的新名字');
  await page.getByRole('button',{name:'删除任务：我的创作任务',exact:true}).click();await page.getByRole('button',{name:'移入回收站',exact:true}).click();
  await expect(page).toHaveURL(/#tasks$/);await expect(page.getByRole('alertdialog')).toHaveCount(0);
  expect(state.writes.filter(w=>w.path==='/tasks/task-delete-detail')).toHaveLength(1);expect(task.name).toBe('我的创作任务');
});

test('active tasks cannot be deleted and stale deletion errors retain task',async({page})=>{
  const state=await mockPlatform(page),task=makeTask('article','task-stale-delete');task.is_running=true;state.tasks.push(task);
  await page.goto('/#tasks');await expect(page.getByRole('button',{name:'删除任务：我的创作任务',exact:true})).toBeDisabled();
  task.is_running=false;await page.reload();await page.getByRole('button',{name:'删除任务：我的创作任务',exact:true}).click();
  task.version++;
  await page.getByRole('button',{name:'移入回收站',exact:true}).click();await expect(page.getByRole('alert')).toContainText('任务配置已更新');
  await expect(page.locator('.task-card')).toHaveCount(1);expect(task.deleted_at).toBeUndefined();
});

test('task default template persists without changing the writing brief',async({page},testInfo)=>{
  const state=await mockPlatform(page),t=makeTask('article','task-template');state.tasks.push(t);
  t.settings.brief='介绍山西值得去的旅游景点';
  await page.goto('/#task/task-template');
  await openConfig(page,'文章排版');
  await page.getByRole('radio',{name:'奶油纸笺',exact:true}).check();
  await page.getByText('展开完整示例预览',{exact:true}).click();
  await expect(page.locator('.template-sample-paper .article-layout')).toHaveAttribute('data-article-template','cream');
  await page.screenshot({path:testInfo.outputPath('task-templates-desktop.png'),fullPage:true});
  await finishConfig(page);
  await page.getByRole('button',{name:'保存配置',exact:true}).click();
  expect(t.settings.article.template_id).toBe('cream');expect(t.settings.brief).toBe('介绍山西值得去的旅游景点');
  await page.reload();await expect(page.getByRole('button',{name:'配置文章排版'})).toContainText('奶油纸笺');
  await page.setViewportSize({width:390,height:844});await openConfig(page,'文章排版');
  await expect(page.getByRole('radio',{name:'奶油纸笺',exact:true})).toBeChecked();
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('task-templates-mobile.png'),fullPage:true});
});

test('collection shows frozen date window and the date of every rejected candidate',async({page},testInfo)=>{
  const state=await mockPlatform(page),t=makeTask('article','task-date-filter');state.tasks.push(t);
  t.settings.materials.max_age_days=30;
  t.runs=[{id:'run-date-filter',task_id:t.id,action:'assist',status:'failed',stage:'collect',content_id:null,settings:t.settings,error:null,created_at:t.created_at,updated_at:t.updated_at,
    reports:[{source:'公众号文章 · AI 技术热点',status:'success',count:0,candidate_count:3,query:'AI 技术热点',message:'本次搜索候选均未通过发布时间核验。',collected_at:'2026-09-23T15:00:00Z',date_filter:{max_age_days:7,from:'2026-09-16T15:00:00Z',to:'2026-09-23T15:00:00Z'},date_excluded_count:3,relevance_excluded_count:0,pages_searched:2,search_note:'平台按文章标注的发布时间核验。',items:[],excluded:[
      {title:'旧的 AI 技术回顾',reason:'超过设置的发布时间范围',stage:'date',published_at:'2026-03-09T02:00:00Z',publisher:'科技记录',url:'https://mp.weixin.qq.com/s/old'},
      {title:'没有日期的资料',reason:'没有可核验的发布时间',stage:'date',published_at:null},
      {title:'未来日期的文章',reason:'发布时间晚于本次采集时间',stage:'date',published_at:'2026-09-24T02:00:00Z'}]}]}];
  await page.goto('/#task/task-date-filter');
  await page.getByRole('button',{name:'查看选题与资料'}).click();
  const summary=page.locator('.search-result-summary');
  await expect(summary).toContainText('搜索候选 3 条 · 排除 3 条 · 保留 0 篇');
  await expect(summary).toContainText('本次筛选：近 7 天');await expect(summary).not.toContainText('近 30 天');
  await expect(summary).toContainText('2026/09/16 23:00 至 2026/09/23 23:00');
  await expect(summary).toContainText('时间不符或日期不明 3 条 · 主题不符 0 条');
  await expect(summary).toContainText('修改配置后需重新采集');
  await page.locator('.collection-log>summary').click();await page.getByText('已排除 3 条不符合要求的结果',{exact:true}).click();
  await expect(page.locator('.excluded-source').first()).toContainText('2026/03/09 10:00');
  await expect(page.locator('.excluded-source').nth(1)).toContainText('发布时间：日期不明');
  await expect(page.getByRole('link',{name:'查看该候选文章'})).toHaveAttribute('href','https://mp.weixin.qq.com/s/old');
  await page.screenshot({path:testInfo.outputPath('collection-date-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('collection-date-mobile.png'),fullPage:true});
});

test('collection failure distinguishes unprocessed candidates from rejected ones',async({page})=>{
  const state=await mockPlatform(page),t=makeTask('article','task-incomplete');state.tasks.push(t);
  t.runs=[{id:'run-incomplete',task_id:t.id,action:'assist',status:'failed',stage:'collect',content_id:null,settings:t.settings,error:null,created_at:t.created_at,updated_at:t.updated_at,
    reports:[{source:'公众号文章 · AI',query:'AI',status:'error',count:0,candidate_count:4,unprocessed_count:3,message:'资料相关性筛选未完整返回',items:[],excluded:[{title:'旧文章',reason:'超过设置的发布时间范围'}]}]}];
  await page.goto('/#task/task-incomplete');
  await page.getByRole('button',{name:'查看选题与资料'}).click();
  await expect(page.locator('.search-result-summary')).toContainText('搜索候选 4 条 · 排除 1 条 · 保留 0 篇 · 未完成筛选或采集 3 条');
  await page.locator('.collection-log>summary').click();await expect(page.locator('.collection-log')).toContainText('资料相关性筛选未完整返回');
});


test('WeChat connection, permissions and automatic delivery settings persist',async({page},testInfo)=>{
  const state=await mockPlatform(page),t=makeTask('article','wechat-task');state.tasks.push(t);
  const accounts:any[]=[];const requests:{path:string;body:any}[]=[];
  await page.route('**/api/wechat/accounts**',route=>{
    const request=route.request(),path=new URL(request.url()).pathname,body=request.postDataJSON();
    if(request.method()==='GET')return route.fulfill({json:accounts});
    requests.push({path,body});
    if(path.endsWith('/test')){accounts[0].draft_ready=true;accounts[0].publish_ready=true;accounts[0].checked_at='2026-09-23';return route.fulfill({json:{account:accounts[0],message:'连接成功，权限检测通过。'}});}
    const account={id:'wechat-1',name:body.name,appid:body.appid,secret_configured:true,draft_ready:false,publish_ready:false,checked_at:null};accounts.push(account);return route.fulfill({json:account});
  });
  await page.route('**/api/assets',route=>route.fulfill({json:[{id:'cover-1',filename:'栏目封面.jpg',media_type:'image/jpeg',rights:'本人作品',credit:'',source_url:''}]}));
  await page.goto('/#accounts');
  await page.getByLabel('连接名称',{exact:true}).fill('旅行公众号');
  await page.getByLabel('账号主体',{exact:true}).selectOption('organization');
  await page.getByLabel('AppID',{exact:true}).fill('wx1234567890abcdef');
  await page.getByLabel('AppSecret',{exact:true}).fill('not-a-real-secret');
  await page.getByRole('button',{name:'保存公众号连接',exact:true}).click();
  await expect(page.getByLabel('AppSecret',{exact:true})).toHaveValue('');
  await page.getByRole('button',{name:'检测已保存连接',exact:true}).click();
  await expect(page.locator('.publishing-account-list')).toContainText('发布接口已就绪');
  await page.goto('/#task/wechat-task');await page.getByLabel('自动执行',{exact:false}).check();await openConfig(page,'作品交付');
  await expect(page.getByLabel('文章交付方式')).toHaveValue('local');await page.getByLabel('文章交付方式').selectOption('publish');
  await page.getByLabel('发布公众号').selectOption('wechat-1');
  await expect(page.getByText('草稿已就绪 · 发布已就绪')).toBeVisible();
  await page.getByLabel('默认封面',{exact:true}).selectOption('cover-1');
  await page.getByLabel('文章署名（可选）').fill('旅行编辑');
  await finishConfig(page);await page.getByRole('button',{name:'保存配置',exact:true}).click();
  expect(state.tasks[0].settings.wechat_delivery).toEqual({mode:'publish',account_id:'wechat-1',cover_asset_id:'cover-1',author:'旅行编辑'});
  expect(JSON.stringify(state.tasks)).not.toContain('not-a-real-secret');
  expect(requests[0].body.secret).toBe('not-a-real-secret');
  await page.reload();await openConfig(page,'作品交付');
  await expect(page.getByLabel('文章交付方式')).toHaveValue('publish');
  await expect(page.getByLabel('发布公众号')).toHaveValue('wechat-1');
  await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('wechat-publishing-mobile.png'),fullPage:true});
});

test('WeChat publication waits for final state and uncertain writes cannot be retried',async({page})=>{
  const state=await mockPlatform(page),t=makeTask('article','wechat-result');state.tasks.push(t);
  const run:TaskRun={id:'run-wechat',task_id:t.id,action:'automatic',status:'publishing',stage:'delivery',content_id:null,error:null,reports:[],settings:t.settings,created_at:t.created_at,updated_at:t.updated_at,publication:{mode:'publish',status:'publishing',error:null,updated_at:t.updated_at,account_name:'旅行公众号',title:'平遥的古建之美',article_version:2,publish_id:'wx-publish'}};
  t.runs=[run];
  await page.goto('/#task/wechat-result');
  await expect(page.getByRole('heading',{name:'微信正在处理发布'})).toBeVisible();
  await expect(page.getByRole('link',{name:'查看已发布文章'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'归档任务'})).toBeDisabled();
  run.status='published';run.publication!.status='published';run.publication!.article_url='https://mp.weixin.qq.com/s/published';run.updated_at='2026-09-23T01:00:00Z';
  await expect(page.getByRole('link',{name:'查看已发布文章'})).toHaveAttribute('href','https://mp.weixin.qq.com/s/published');
  await expect(page.getByRole('status')).toContainText('文章已发布到公众号');
  run.status='failed';run.error='提交结果待核对';run.publication!.status='uncertain';run.publication!.can_retry=false;run.publication!.article_url='';run.publication!.error='请到公众号后台核对，系统不会重复提交。';
  await expect(page.getByRole('heading',{name:'提交结果待核对'})).toBeVisible();
  await expect(page.getByRole('button',{name:'重试本次执行'})).toHaveCount(0);
});


test('WeChat IP whitelist failure shows exact address and can retry',async({page})=>{
  const state=await mockPlatform(page),t=makeTask('article','whitelist-task');state.tasks.push(t);
  t.settings.wechat_delivery={mode:'draft',account_id:'wechat-1',cover_asset_id:'',author:''};
  const account={id:'wechat-1',name:'旅行公众号',appid:'wx1234567890abcdef',secret_configured:true,draft_ready:false,publish_ready:false,checked_at:null};
  let checks=0;
  await page.route('**/api/wechat/accounts**',route=>{
    if(route.request().method()==='GET')return route.fulfill({json:[account]});
    if(++checks===1)return route.fulfill({status:400,json:{detail:'微信检测到的当前出口 IP：8.8.4.4。请添加 IP 白名单。（错误码 40164）'}});
    account.draft_ready=true;account.publish_ready=true;
    return route.fulfill({json:{account,message:'连接成功，权限检测通过。'}});
  });
  await page.goto('/#accounts');await page.getByLabel('编辑连接').selectOption('wechat-1');
  await page.getByRole('button',{name:'检测已保存连接',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('8.8.4.4');
  await expect(page.locator('.publishing-account-form code')).toHaveText('8.8.4.4');
  await expect(page.getByRole('button',{name:'复制出口 IP',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'关闭错误提示'}).click();
  await page.getByRole('button',{name:'已添加，重新检测',exact:true}).click();
  await expect(page.locator('.publishing-account-form code')).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('连接成功');
  expect(checks).toBe(2);
});


test('personal account needs no API credentials and QR login never implies publishing permission',async({page},testInfo)=>{
  const state=await mockPlatform(page),t=makeTask('article','personal-task');state.tasks.push(t);
  const accounts:any[]=[];let loginStatus='idle',loginChecks=0;
  await page.route('**/api/wechat/accounts**',route=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    if(path.endsWith('/login/qr'))return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jKZkAAAAASUVORK5CYII=','base64')});
    if(path.endsWith('/login')){
      if(req.method()==='POST'){loginStatus='waiting_scan';loginChecks=0;}
      else if(loginStatus==='waiting_scan'&&++loginChecks>1){loginStatus='connected';accounts[0].session_saved=true;}
      return route.fulfill({json:{status:loginStatus,message:loginStatus==='connected'?'扫码登录成功，后台自动保存与发布仍待验证。':'请用微信扫码',has_qr:loginStatus==='waiting_scan',updated_at:'now'}});
    }
    if(req.method()==='GET')return route.fulfill({json:accounts});
    const body=req.postDataJSON();expect(body.secret).toBe('');expect(body.appid).toBe('');
    const a={...body,id:'personal-1',secret_configured:false,draft_ready:false,publish_ready:false,checked_at:null};accounts.push(a);return route.fulfill({json:a});
  });
  await page.goto('/#accounts');
  await expect(page.getByLabel('账号主体',{exact:true})).toHaveValue('personal');
  await expect(page.getByLabel('AppSecret',{exact:true})).toHaveCount(0);
  await page.getByLabel('连接名称',{exact:true}).fill('我的个人公众号');
  await page.getByRole('button',{name:'保存公众号连接',exact:true}).click();
  await page.getByRole('button',{name:'扫码登录 / 检查登录',exact:true}).first().click();
  const dialog=page.getByRole('dialog',{name:'连接 我的个人公众号'});
  await dialog.getByRole('button',{name:'开始扫码登录'}).click();
  await expect(dialog.getByRole('img',{name:'微信公众平台官方登录二维码'})).toBeVisible();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:testInfo.outputPath('personal-login-mobile.png'),fullPage:true});
  await expect(dialog.locator('p[role=status]')).toContainText('扫码登录成功',{timeout:10000});
  await dialog.getByRole('button',{name:'关闭扫码窗口'}).click();
  await page.goto('/#task/personal-task');await page.getByLabel('自动执行',{exact:false}).check();await openConfig(page,'作品交付');
  await page.getByLabel('文章交付方式').selectOption('handoff');await page.getByLabel('发布公众号').selectOption('personal-1');
  await expect(page.getByLabel('文章交付方式').locator('option[value=publish]')).toHaveAttribute('disabled','');
  await finishConfig(page);await page.getByRole('button',{name:'保存配置',exact:true}).click();
  expect(state.tasks[0].settings.wechat_delivery?.mode).toBe('handoff');
  await expect(page.getByRole('button',{name:'检测连接与权限',exact:true})).toHaveCount(0);
});


test('personal handoff shows prepared content without a published-success claim',async({page})=>{
  const state=await mockPlatform(page),t=makeTask('article','handoff-result');state.tasks.push(t);
  t.runs=[{id:'handoff-1',task_id:t.id,action:'automatic',status:'awaiting_publish',stage:'delivery',content_id:null,error:null,reports:[],settings:t.settings,created_at:t.created_at,updated_at:t.updated_at,publication:{mode:'handoff',status:'awaiting_publish',error:null,updated_at:t.updated_at,account_name:'我的个人公众号',title:'平遥古城',article_version:1,can_retry:false}}];
  await page.goto('/#task/handoff-result');
  await expect(page.getByRole('heading',{name:'稿件已备好 · 待你发布'})).toBeVisible();
  await expect(page.getByRole('button',{name:'复制排版正文',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'下载稿件与图片'})).toHaveAttribute('href','/api/task-runs/handoff-1/publication/bundle');
  await expect(page.getByRole('link',{name:'查看已发布文章'})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'重试本次执行'})).toHaveCount(0);
  await expect(page.locator('.publication-result')).toContainText('尚未上传或发布到微信');
});


test('home counts link to all tasks, the scheduled subset and individual creation records',async({page},testInfo)=>{
  const state=await mockPlatform(page),manual=makeTask('article','manual-task'),scheduled=makeTask('article','scheduled-task'),archived=makeTask('article','archived-task');
  manual.name='手动写作';scheduled.name='每日旅行';scheduled.settings.execution='automatic';archived.archived=true;archived.name='归档任务';
  const run=(t:CreationTask,id:string):TaskRun=>({id,task_id:t.id,action:'assist',status:'failed',stage:'collect',content_id:null,settings:t.settings,reports:[],error:null,created_at:t.created_at,updated_at:t.updated_at});
  manual.runs=[run(manual,'manual-1')];scheduled.runs=[run(scheduled,'scheduled-2'),run(scheduled,'scheduled-1')];manual.run_count=1;scheduled.run_count=2;archived.run_count=0;state.tasks.push(manual,scheduled,archived);
  await page.goto('/');const stats=page.locator('.studio-stats');await expect(stats.getByRole('button',{name:/全部任务/})).toContainText('3');await expect(stats.getByRole('button',{name:/其中定时任务/})).toContainText('1');await expect(stats.getByRole('button',{name:/创作记录/})).toContainText('3');
  await page.screenshot({path:testInfo.outputPath('home-stats-links.png'),fullPage:true});
  await stats.getByRole('button',{name:/其中定时任务/}).click();await expect(page.getByLabel('执行方式筛选')).toHaveValue('automatic');await expect(page.locator('.task-card')).toHaveCount(1);await expect(page.locator('.task-card')).toContainText('每日旅行');
  await page.getByRole('button',{name:'查看 每日旅行 的创作记录'}).click();const drawer=page.getByRole('dialog',{name:'创作记录'});await expect(drawer.locator('.creation-record-row')).toHaveCount(2);
  await drawer.locator('.creation-record-row').last().click();await expect(page).toHaveURL(/task\/scheduled-task\?run=scheduled-1$/);await expect(page.locator('.run-history')).toHaveCount(0);
  await page.getByRole('button',{name:'创作记录 · 2',exact:true}).click();await expect(page.getByRole('dialog',{name:'创作记录'}).locator('.creation-record-row').last()).toHaveAttribute('aria-pressed','true');await page.keyboard.press('Escape');
  await page.getByRole('link',{name:'任务列表',exact:true}).click();await expect(page.locator('.task-card')).toHaveCount(3);
  await page.getByRole('button',{name:'首页',exact:true}).click();await page.locator('.studio-stats').getByRole('button',{name:/创作记录/}).click();await expect(page.getByRole('heading',{name:'创作记录',exact:true})).toBeVisible();await expect(page.locator('.creation-record-row')).toHaveCount(3);
  await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:testInfo.outputPath('all-records-mobile.png'),animations:'disabled'});
});

test('success and error notices expire after three seconds with countdown and exit state',async({page})=>{
  const state=await mockPlatform(page),t=makeTask('article','notice-task');state.tasks.push(t);
  await page.clock.install();await page.goto('/#task/notice-task');await page.getByLabel('任务名称',{exact:true}).fill('提示验证');await page.getByRole('button',{name:'保存配置',exact:true}).click();
  const success=page.locator('.notification-success');await expect(success).toBeVisible();await expect(success.locator('.notification-countdown')).toHaveCSS('animation-duration','3s');
  await page.clock.fastForward(3000);await expect(success).toHaveClass(/is-leaving/);await page.clock.fastForward(250);await expect(success).toHaveCount(0);
  t.runs=[{id:'error-run',task_id:t.id,action:'assist',status:'failed',stage:'collect',content_id:null,settings:t.settings,reports:[],error:'模拟采集失败',created_at:t.created_at,updated_at:t.updated_at}];
  await page.reload();const error=page.getByRole('alert');await expect(error).toContainText('模拟采集失败');await page.clock.fastForward(3000);await expect(error).toHaveClass(/is-leaving/);await page.clock.fastForward(250);await expect(error).toHaveCount(0);
  await page.clock.fastForward(10000);await expect(error).toHaveCount(0);await page.getByRole('button',{name:'查看失败原因',exact:true}).click();await expect(error).toContainText('模拟采集失败');
});


test('optional illustration settings persist and keep image models separate from writing',async({page},testInfo)=>{
  const state=await mockPlatform(page),task=makeTask('article','task-pictures');state.tasks.push(task);
  await page.route('**/api/picture-sources/unsplash',route=>route.fulfill({json:{key_configured:false}}));
  await page.route('**/api/models',route=>route.fulfill({json:[...models,{...models[0],id:'image-model',name:'专用图片模型',protocol:'images',image_edit:true}]}));
  await page.goto('/#task/task-pictures');await openConfig(page,'AI 模型');await expect(page.getByLabel('本任务使用的模型').locator('option')).toHaveCount(2);await expect(page.getByLabel('本任务使用的模型').locator('option[value="image-model"]')).toHaveCount(0);await finishConfig(page);await openConfig(page,'文章配图');
  const config=page.getByRole('group',{name:'文章配图配置'}).or(page.locator('.illustration-config'));
  await expect(page.getByRole('checkbox',{name:'启用智能配图'})).not.toBeChecked();
  await expect(page.getByLabel('配图使用的图片模型')).toHaveCount(0);
  await page.getByRole('checkbox',{name:'启用智能配图'}).check();
  await page.getByRole('button',{name:'AI 生成 按正文内容创作配图'}).click();
  await page.getByLabel('配图使用的图片模型').selectOption('image-model');
  await page.getByLabel('正文配图数量').selectOption('2');await page.getByLabel('同时配置封面').uncheck();
  await page.getByLabel('生成图片比例').selectOption('portrait');await page.getByLabel('配图风格').fill('水彩插画，简洁留白');
  await page.getByLabel('配图失败时').selectOption('pause');await finishConfig(page);await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await expect.poll(()=>task.settings.illustration?.count).toBe(2);
  expect(task.settings.illustration).toMatchObject({enabled:true,mode:'ai',model_id:'image-model',ratio:'portrait',cover:false,failure:'pause'});
  await page.reload();await openConfig(page,'文章配图');await expect(page.getByLabel('配图风格')).toHaveValue('水彩插画，简洁留白');
  await page.getByRole('button',{name:'联网找图 按主体匹配相关实景图'}).click();
  await expect(page.getByRole('checkbox',{name:'Wikimedia Commons',exact:true})).toBeChecked();
  await page.getByRole('checkbox',{name:'360 图片',exact:true}).check();await page.getByRole('checkbox',{name:'Unsplash',exact:true}).check();await finishConfig(page);await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await expect.poll(()=>task.settings.illustration?.web_sources).toEqual(['commons','openverse','360','unsplash']);
  await page.reload();await openConfig(page,'文章配图');await expect(page.getByRole('checkbox',{name:'360 图片',exact:true})).toBeChecked();await expect(page.getByRole('checkbox',{name:'Unsplash',exact:true})).toBeChecked();
  await config.scrollIntoViewIfNeeded();await config.screenshot({path:testInfo.outputPath('illustration-config-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await config.screenshot({path:testInfo.outputPath('illustration-config-mobile.png')});
  await page.getByRole('checkbox',{name:'启用智能配图'}).uncheck();await finishConfig(page);await page.getByRole('button',{name:'保存配置',exact:true}).click();
  await expect.poll(()=>task.settings.illustration?.enabled).toBe(false);
  expect(task.settings.illustration?.model_id).toBe('image-model');
});
