import {task as makeTask,models} from './fixtures';
import { test, expect, type Page } from '@playwright/test';
import type { Article, ArticleDocument, ArticleProfile, Topic } from '../../src/types';

const profile:ArticleProfile={name:'效率手记',direction:'面向普通上班族的 AI 工作方法',audience:'刚开始尝试 AI 的上班族',style:'自然具体，避免夸张',length:1200,format:'教程',preferences:''};
const document:ArticleDocument={title:'从一个小任务开始认识 AI',titles:['从一个小任务开始认识 AI','你的第一个 AI 工作流','先做好一件小事'],summary:'把抽象的能力，放进一个熟悉的工作场景。',opening:'面对一个新工具，我们往往先问它有多强。也许更值得问的是：我现在手头哪件事，可以用它试试看？',sections:[{heading:'从你熟悉的任务出发',paragraphs:['选一个你了解过程、也能判断结果的任务。比如整理一份自己的会议笔记，先列出关心的问题，再检查生成的内容。','第一次尝试，不必追求复杂的自动化。记录输入、输出和需要修改的地方，下次再做调整。'],evidence:[],image_hint:'桌面上的笔记本与一杯茶',asset_id:'',caption:''}],closing:'一个小任务，就是观察工具是否适合自己的起点。',cover_hint:'温暖的日常工作台，自然光',cover_asset_id:''};
const topic:Topic={id:'source-1',title:'一份工具使用观察',category:'general',kind:'live',source:'公开资料',angle:'关于使用方法的观察',sources:[{id:'source-1',title:'一份工具使用观察',publisher:'公开资料',url:'https://example.com/article',text:'这是一份关于工具使用的公开资料，作者提醒读者先了解自己的任务，再尝试合适的方法。'}],published_at:null,discovered_at:'2026-09-23T00:00:00Z',rights:'待核验',evidence_status:'正文快照',page_data:{method:'http',full_text:true,images:[],links:[],captured_at:'2026-09-23T00:00:00Z'}};

async function mockStudio(page:Page, existing=false){
  let task=makeTask();
  let prefs={...profile}; let article:Article|null=null; let sourceList:Topic[]=[];let checks=0;
  const writes:{path:string;body:any}[]=[];const versions=new Map<number,Article>();
  const base=():Article=>({id:'article-ui-test',request_id:'ui-test-request',status:'queued',stage:'angles',progress:5,mode:'original',version:1,profile:prefs,input_data:{brief:'',topic_ids:[],notes:''},source_data:[],angles:null,outline:null,document:null,checks:null,error:null,note:'正在准备写作角度。',created_at:'2026-09-23T00:00:00Z',updated_at:'2026-09-23T00:00:00Z',versions:[]});
  const remember=()=>{if(article){article.versions=[{version:article.version,stage:article.stage,at:article.updated_at,note:'保存内容',restorable:!!article.outline},...(article.versions||[])];versions.set(article.version,structuredClone(article));}};
  if(existing){article={...base(),status:'needs_review',stage:'review',progress:100,version:5,source_data:topic.sources,document:structuredClone(document),outline:{title:document.title,angle:'从熟悉的任务开始',sections:[{heading:document.sections[0].heading,points:'解释如何选任务'}],source_gaps:[]},checks:{issues:[],note:'模拟检查完成，请人工核验。'}};remember();}
  await page.route('**/api/**',async route=>{
    const request=route.request();const path=new URL(request.url()).pathname.replace('/api','');const method=request.method();const body=request.postDataJSON();
    const reply=(json:unknown,status=200)=>route.fulfill({json,status});
    if(method!=='GET')writes.push({path,body});
    if(path==='/models')return reply(models);
    if(path==='/tasks')return reply([{...task,run_count:article?1:0}]);
    if(path==='/tasks/task-ui-test'){
      if(method==='PUT'){task={...task,...body,version:task.version+1};prefs=task.settings.article;}
      return reply({...task,runs:article?[{id:'run-ui',task_id:task.id,action:'assist',status:article.status==='queued'?'needs_angle':article.status,stage:'content',content_id:article.id,settings:task.settings,reports:[],created_at:article.created_at,updated_at:article.updated_at,error:null}]:[]});
    }
    if(path==='/tasks/task-ui-test/run'){
      const input={mode:task.settings.materials.mode,brief:task.settings.brief,topic_ids:task.settings.materials.topic_ids,notes:task.settings.materials.notes};
      article={...base(),input_data:input,mode:input.mode,source_data:input.topic_ids.length?topic.sources:[]};remember();return reply({id:'run-ui'});
    }
    if(path==='/health')return reply({ok:true,ai_ready:true,model:'test-model',local_only:true,duration_seconds:10,audio_mode:'silent'});
    if(path==='/settings')return reply({account_name:'知序',schedule_enabled:false,schedule_time:'07:00',sources:[],custom_sources:[],production_mode:'ai',duration_seconds:10,audio_mode:'silent',resolution:'1080p'});
    if(path==='/jobs'||path==='/assets')return reply([]);
    if(path==='/topics')return reply(sourceList);
    if(path==='/article-profile'){if(method==='PUT')prefs=body;return reply(prefs);}
    if(path==='/article-sources/link'){sourceList=[topic];return reply(topic);}
    if(path==='/sources/import'){sourceList=[topic];return reply({topic_id:topic.id,message:'已导入'});}
    if(path==='/articles'&&method==='POST'){article={...base(),input_data:body,mode:body.mode,source_data:body.topic_ids.length?topic.sources:[]};remember();return reply(article,201);}
    if(path==='/articles')return reply(article?[{...article,title:article.document?.title||article.outline?.title||'写作中的文章'}]:[]);
    if(path==='/articles/article-ui-test'&&article){
      if(article.status==='queued'&&article.stage==='angles'){article={...article,status:'needs_angle',version:2,progress:25,angles:{choices:[{title:'从一个小任务开始',angle:'用具体工作场景介绍方法',reason:'读者容易开始尝试'}]},note:'请选择一个写作角度。'};remember();}
      return reply(article);
    }
    if(path.endsWith('/export'))return route.fulfill({contentType:'text/html',headers:{'Content-Disposition':'attachment; filename="article.html"'},body:'<!doctype html><h1>'+article?.document?.title+'</h1>'});
    if(article&&path.startsWith('/articles/article-ui-test/')){
      if(body?.version!==article.version)return reply({detail:'文章版本已更新，请刷新。'},409);
      if(path.endsWith('/angle'))article={...article,input_data:{...article.input_data,angle_index:body.choice},document:null,status:'needs_outline',stage:'outline',version:article.version+1,progress:45,outline:{title:document.title,angle:'从熟悉的任务开始',sections:[{heading:document.sections[0].heading,points:'解释如何选择任务'}],source_gaps:[]}};
      if(path.endsWith('/outline'))article={...article,version:article.version+1,outline:body.outline,document:null,status:'needs_outline'};
      if(path.endsWith('/generate'))article={...article,status:'needs_review',stage:'review',version:article.version+1,progress:100,document:structuredClone(document),checks:{issues:[],note:'检查完成，请人工核验。'}};
      if(path.endsWith('/document'))article={...article,status:'draft',version:article.version+1,document:body.document,checks:null};
      if(path.endsWith('/check')){checks++;article={...article,status:'needs_review',version:article.version+1,checks:{issues:[],note:'检查完成，请人工核验。'}};}
      if(path.endsWith('/rewrite')){
        const doc=structuredClone(body.document||article.document!);const value='从一个熟悉的小任务开始。';
        if(['title','summary','opening','closing'].includes(body.target))doc[body.target]=value;
        else if(body.target==='heading')doc.sections[body.section].heading=value;
        else if(body.target==='paragraph')doc.sections[body.section].paragraphs[body.paragraph]=value;
        else doc.sections[body.section].paragraphs=[value];
        article={...article,version:article.version+1,document:doc};
      }
      if(path.endsWith('/restore')){const old=versions.get(body.target_version)!;article={...article,version:article.version+1,document:structuredClone(old.document),outline:old.outline,checks:null};}
      remember();return reply(article);
    }
    return reply({detail:'Unmocked route: '+method+' '+path},500);
  });
  return {writes,get article(){return article;},get task(){return task;},get checks(){return checks;}};
}

test('six templates preview safely, save with content and restore with history',async({page},testInfo)=>{
  const state=await mockStudio(page,true);
  await page.goto('/#task/task-ui-test');
  await page.locator('.article-template-picker>summary').click();
  await expect(page.getByRole('radio')).toHaveCount(6);
  const choices=[['清新手记','classic'],['科技蓝图','tech'],['山河游记','travel'],['实用指南','guide'],['观点专栏','opinion'],['极简留白','minimal']];
  for(const [name,id] of choices){
    await page.getByRole('radio',{name,exact:true}).check();
    await expect(page.locator('.phone-preview .article-layout')).toHaveAttribute('data-article-template',id);
    await expect(page.locator('.phone-preview h1')).toHaveText(document.title);
    await expect(page.getByRole('textbox',{name:'第 1 节正文',exact:true})).toHaveValue(document.sections[0].paragraphs.join('\n\n'));
  }
  await page.getByRole('radio',{name:'科技蓝图',exact:true}).check();
  await expect(page.getByRole('button',{name:'复制排版文字'})).toBeDisabled();
  await expect(page.locator('.phone-preview h2')).toContainText('01');
  await page.screenshot({path:testInfo.outputPath('article-templates-desktop.png'),fullPage:true});
  await page.getByRole('button',{name:'保存修改',exact:true}).click();
  await expect.poll(()=>state.article?.document?.template_id).toBe('tech');
  expect(state.article?.document?.sections).toEqual(document.sections);
  await page.reload();await expect(page.locator('.phone-preview .article-layout')).toHaveAttribute('data-article-template','tech');
  await page.getByText(/版本记录 ·/).click();await page.getByLabel('恢复历史版本').selectOption('5');
  await page.getByRole('button',{name:'恢复为新版本'}).click();
  await expect(page.locator('.phone-preview .article-layout')).toHaveAttribute('data-article-template','classic');
  await page.locator('.article-template-picker>summary').click();
  await page.getByRole('radio',{name:'山河游记',exact:true}).check();
  await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('article-templates-mobile.png'),fullPage:true});
});

test('direction to outline to edited article, partial rewrite, versions and export',async({page},testInfo)=>{
  const state=await mockStudio(page);
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/#task/task-ui-test');
  await page.locator('.account-preferences>summary').click();await expect(page.getByRole('textbox',{name:'公众号定位',exact:true})).toHaveValue(profile.direction,{timeout:12000});
  await page.screenshot({path:testInfo.outputPath('article-start.png'),fullPage:true});
  await page.getByRole('button',{name:'AI 辅助创作'}).click();
  await expect(page.locator('.angle-card')).toHaveCount(1,{timeout:12000});
  expect(state.writes.find(w=>w.path.endsWith('/run'))?.body.action).toBe('assist');
  await page.locator('.angle-card').click();
  await expect(page.getByLabel('大纲标题')).toHaveValue(document.title);
  await page.getByLabel('第 1 节要点').fill('使用读者熟悉的真实任务解释方法');
  await expect(page.getByRole('button',{name:'按大纲生成正文'})).toBeDisabled();
  await page.getByRole('button',{name:'保存大纲',exact:true}).click();
  await page.getByRole('button',{name:'按大纲生成正文'}).click();
  await expect(page.getByLabel('主标题',{exact:true})).toHaveValue(document.title);
  await page.getByLabel('主标题',{exact:true}).fill('先做好一件小事');
  await page.getByRole('textbox',{name:'第 1 节正文',exact:true}).fill('保留这一段正文。\n\n');
  await expect(page.locator('.phone-preview h1')).toHaveText('先做好一件小事');
  await expect(page.getByRole('link',{name:'HTML',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'保存修改',exact:true}).click();
  await expect.poll(()=>state.article?.document?.sections[0].paragraphs).toEqual(['保留这一段正文。']);
  await expect(page.getByRole('button',{name:'保存修改',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'重新检查',exact:true}).click();
  await expect.poll(()=>state.checks).toBe(1);
  await page.getByRole('button',{name:'缩短',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'第 1 节正文',exact:true})).toHaveValue('从一个熟悉的小任务开始。');
  await page.getByText(/版本记录 ·/).click();
  await page.getByLabel('恢复历史版本').selectOption('5');
  await page.getByRole('button',{name:'恢复为新版本'}).click();
  await expect(page.getByLabel('主标题',{exact:true})).toHaveValue(document.title);
  // Download navigations bypass page.route in Chromium. Verify the link here;
  // test_articles.py validates the real response, filename and ZIP contents.
  await expect(page.getByRole('link',{name:'HTML',exact:true})).toHaveAttribute('href',`/api/articles/article-ui-test/export?format=html&version=${state.article!.version}`);
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:testInfo.outputPath('article-editor.png'),fullPage:true});
  expect(errors).toEqual([]);
});

test('unsaved text survives polling and cancelled navigation on desktop and mobile',async({page},testInfo)=>{
  await mockStudio(page,true);
  await page.goto('/#task/task-ui-test');
  await page.getByLabel('主标题',{exact:true}).fill('尚未保存的标题');
  await page.getByRole('button',{name:'作品与执行记录',exact:false}).click(); // clicking current tab must preserve the guard
  let dialogs=0;page.on('dialog',async dialog=>{dialogs++;await dialog.dismiss();});
  await page.getByRole('link',{name:'任务列表',exact:true}).click();
  await expect(page.getByRole('alertdialog',{name:'离开当前编辑？'})).toBeVisible();await page.getByRole('button',{name:'继续编辑',exact:true}).click();expect(dialogs).toBe(0);await expect(page).toHaveURL(/#task\/task-ui-test$/);
  await page.waitForResponse(r=>r.url().endsWith('/api/articles/article-ui-test'));
  await expect(page.getByLabel('主标题',{exact:true})).toHaveValue('尚未保存的标题');
  await page.setViewportSize({width:390,height:844});
  await page.getByLabel('主标题',{exact:true}).scrollIntoViewIfNeeded();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('article-mobile.png'),fullPage:true});
});

test('reference link is selected and its source snapshot enters the new article',async({page})=>{
  const state=await mockStudio(page);
  await page.goto('/#task/task-ui-test');
  await page.getByRole('button',{name:'参考文章创作'}).click();
  await page.getByText('立即导入指定文章',{exact:true}).click();
  await page.getByLabel('文章链接',{exact:true}).fill('https://example.com/article');
  await page.getByRole('button',{name:'读取文章并选中'}).click();
  await expect(page.locator('.article-source-picker input')).toBeChecked();
  await page.getByRole('button',{name:'AI 辅助创作'}).click();
  await expect(page.locator('.angle-card')).toBeVisible({timeout:12000});
  expect(state.article?.mode).toBe('reference');
  expect(state.article?.source_data[0].url).toBe(topic.sources[0].url);
});

test('article steps go back without losing work and reselect with confirmation',async({page},testInfo)=>{
  const state=await mockStudio(page);await page.goto('/#task/task-ui-test');
  await page.getByRole('button',{name:'AI 辅助创作'}).click();await page.locator('.angle-card').click();
  await expect(page.getByLabel('大纲标题')).toHaveValue(document.title);
  const version=state.article!.version;
  await page.getByRole('button',{name:'上一步：写作角度',exact:false}).click();
  await expect(page.locator('.angle-card')).toHaveCount(1);expect(state.article!.version).toBe(version);
  await page.locator('.angle-card').click();await expect(page.getByLabel('大纲标题')).toBeVisible();expect(state.article!.version).toBe(version);
  await page.getByLabel('大纲标题').fill('未保存的大纲标题');
  await page.locator('.article-steps').getByRole('button',{name:'写作角度',exact:false}).click();
  await expect(page.getByRole('alert')).toContainText('当前步骤有未保存的修改');
  await expect(page.getByLabel('大纲标题')).toHaveValue('未保存的大纲标题');
  await page.getByRole('button',{name:'关闭错误提示'}).click();await page.getByRole('button',{name:'撤销修改',exact:true}).click();
  await page.getByRole('button',{name:'按大纲生成正文'}).click();await expect(page.getByLabel('主标题',{exact:true})).toBeVisible();
  await page.locator('.article-steps').getByRole('button',{name:'文章大纲',exact:false}).click();
  await page.getByLabel('第 1 节要点').fill('调整后的文章结构');
  await page.getByRole('button',{name:'保存大纲',exact:true}).click();await expect(page.getByRole('alertdialog',{name:'保存新的文章大纲？'})).toBeVisible();await page.getByRole('button',{name:'继续调整',exact:true}).click();expect(state.article!.document).not.toBeNull();
  await page.getByRole('button',{name:'保存大纲',exact:true}).click();await page.getByRole('button',{name:'保存新大纲',exact:true}).click();await expect.poll(()=>state.article!.document).toBeNull();
  expect(state.writes.findLast(w=>w.path.endsWith('/outline'))?.body.replace_existing).toBe(true);
  await expect(page.getByRole('navigation',{name:'主导航'})).toHaveCount(0);
  const box=await page.locator('.task-detail-header').boundingBox();expect(box!.height).toBeLessThan(110);
  await page.screenshot({path:testInfo.outputPath('compact-article-steps.png'),fullPage:true});
});

test('regeneration uses styled confirmation with safe focus, escape and mobile layout',async({page},testInfo)=>{
  const state=await mockStudio(page,true);let nativeDialogs=0;page.on('dialog',d=>{nativeDialogs++;void d.dismiss();});
  await page.goto('/#task/task-ui-test');await page.locator('.article-steps').getByRole('button',{name:'撰写正文',exact:false}).click();
  const start=page.getByRole('button',{name:'按大纲重新生成正文',exact:true});await start.click();
  const dialog=page.getByRole('alertdialog',{name:'重新生成这篇文章？'});
  await expect(dialog).toBeVisible();await expect(dialog.getByRole('button',{name:'保留当前正文'})).toBeFocused();
  await page.screenshot({path:testInfo.outputPath('confirmation-desktop.png'),animations:'disabled'});
  await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(start).toBeFocused();
  expect(state.writes.filter(w=>w.path.endsWith('/generate'))).toHaveLength(0);
  await start.click();await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('confirmation-mobile.png'),animations:'disabled'});
  await dialog.getByRole('button',{name:'重新生成正文',exact:true}).click();
  await expect(dialog).toHaveCount(0);await expect.poll(()=>state.writes.filter(w=>w.path.endsWith('/generate')).length).toBe(1);
  expect(state.writes.find(w=>w.path.endsWith('/generate'))!.body.replace_existing).toBe(true);expect(nativeDialogs).toBe(0);
});

test('confirmed navigation discards edits while cancelled navigation preserves them',async({page})=>{
  await mockStudio(page,true);await page.goto('/#task/task-ui-test');await page.getByLabel('主标题',{exact:true}).fill('未保存标题');
  await page.getByRole('link',{name:'任务列表',exact:true}).click();
  await page.getByRole('alertdialog').getByRole('button',{name:'放弃修改并离开'}).click();
  await expect(page).toHaveURL(/#tasks$/);await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await page.locator('.task-card-open').filter({hasText:'我的创作任务'}).click();await expect(page.getByLabel('主标题',{exact:true})).toHaveValue(document.title);
});


test('focused fields locate preview and custom rewrite preserves other text including unsaved edits',async({page},testInfo)=>{
  const state=await mockStudio(page,true);
  state.article!.document!.sections[0].paragraphs=['保留这段未被选择的正文。'.repeat(25),'需要重写的第二个自然段。'];
  await page.goto('/#task/task-ui-test');await page.emulateMedia({reducedMotion:'reduce'});
  await page.getByRole('textbox',{name:'结尾',exact:true}).focus();
  await expect(page.locator('[data-preview-part="closing"]')).toHaveClass('preview-selected');
  await expect.poll(()=>page.locator('.phone-reading-area').evaluate(e=>e.scrollTop)).toBeGreaterThan(0);
  await page.getByLabel('主标题',{exact:true}).fill('手工调整但还没保存的标题');
  await expect(page.locator('[data-preview-part="title"]')).toHaveClass('preview-selected');
  await page.getByRole('textbox',{name:'第 1 节正文',exact:true}).focus();
  await expect(page.locator('[data-preview-part="section-0-paragraphs"]')).toHaveClass('preview-selected');
  await page.getByRole('button',{name:'自定义改写',exact:true}).click();
  await page.getByLabel('第 1 节正文调整范围',{exact:true}).selectOption('1');
  await expect(page.locator('[data-preview-part="section-0-paragraph-1"]')).toHaveClass('preview-selected');
  await page.getByLabel('第 1 节正文调整要求',{exact:true}).fill('方向错了，改为一个具体的操作例子，不谈抽象感受。');
  await expect(page.locator('.article-local-prompt')).toContainText('会先保存当前修改');
  await page.screenshot({path:testInfo.outputPath('local-rewrite-preview.png'),animations:'disabled'});
  await page.getByRole('button',{name:'按要求调整',exact:true}).click();
  await expect(page.getByLabel('主标题',{exact:true})).toHaveValue('手工调整但还没保存的标题');
  expect(state.article!.document!.sections[0].paragraphs[0]).toBe('保留这段未被选择的正文。'.repeat(25));
  expect(state.article!.document!.sections[0].paragraphs[1]).toBe('从一个熟悉的小任务开始。');
  const write=state.writes.findLast(w=>w.path.endsWith('/rewrite'))!;
  expect(write.body.target).toBe('paragraph');expect(write.body.paragraph).toBe(1);
  expect(write.body.instruction).toContain('方向错了');expect(write.body.document.title).toBe('手工调整但还没保存的标题');
  await page.getByRole('button',{name:'AI 调整摘要',exact:true}).click();
  await page.getByLabel('摘要调整要求',{exact:true}).fill('更简洁地概括核心内容。');
  await page.setViewportSize({width:390,height:844});
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.locator('.article-local-prompt').screenshot({path:testInfo.outputPath('local-rewrite-mobile.png'),animations:'disabled'});
  await page.locator('.phone-preview').screenshot({path:testInfo.outputPath('phone-preview-mobile.png'),animations:'disabled'});
  await page.getByRole('button',{name:'按要求调整',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'摘要',exact:true})).toHaveValue('从一个熟悉的小任务开始。');
  expect(state.writes.filter(w=>w.path.endsWith('/generate'))).toHaveLength(0);
});


test('running tasks display incremental article text and reconnect without overwriting saved content',async({page},testInfo)=>{
  const state=await mockStudio(page,true);state.article!.status='queued';state.article!.stage='section';
  state.article!.note='已加入文章队列。';state.article!.input_data._rewrite={target:'paragraph',section:0,paragraph:1,instruction:'调整这一段'};
  await page.addInitScript(()=>{
    class TestEventSource extends EventTarget {
      onopen:(()=>void)|null=null;onerror:(()=>void)|null=null;
      constructor(public url:string){super();(window as any).articleStream=this;}
      close(){}
      emit(name:string,value:unknown){this.dispatchEvent(new MessageEvent(name,{data:JSON.stringify(value)}));}
    }
    (window as any).EventSource=TestEventSource;
  });
  await page.goto('/#task/task-ui-test');
  const local=page.locator('.article-section-editor').getByRole('region',{name:'实时生成内容'});
  await expect(local).toContainText('局部调整已排队');
  await expect(page.locator('.article-workspace>.article-progress,.article-workspace>.article-live')).toHaveCount(0);
  state.article!.status='running';state.article!.stage='check';state.article!.note='局部修改已保存，正在重新核对。';
  await expect(local).toContainText('局部修改已保存，正在核对');
  await expect(page.locator('.article-workspace>.article-progress,.article-workspace>.article-live')).toHaveCount(0);
  await local.screenshot({path:testInfo.outputPath('local-rewrite-loading.png'),animations:'disabled'});
  // Whole-article activity remains accessible when the editor scrolls offscreen.
  state.article!.stage='article';state.article!.note='正在撰写文章。';
  const activity=page.getByRole('button',{name:'查看创作进度',exact:true});
  await expect(activity).toBeVisible();
  await expect(local).toHaveCount(0);
  await page.getByRole('textbox',{name:'结尾',exact:true}).scrollIntoViewIfNeeded();
  await expect(activity).toBeInViewport();await activity.click();
  const progress=page.getByRole('dialog',{name:'创作进度'});await expect(progress).toBeVisible();
  await expect(page.getByRole('region',{name:'实时生成内容'})).toBeVisible();
  await page.evaluate(()=> (window as any).articleStream.emit('snapshot',{revision:1,kind:'article_document',partial:{title:'实时生成的新标题',opening:'第一批正在返回的文字'}}));
  await expect(page.locator('.article-live-copy')).toContainText('第一批正在返回的文字');
  await expect(page.getByLabel('主标题',{exact:true})).toHaveValue(document.title);
  await page.evaluate(()=> (window as any).articleStream.onerror());
  await expect(page.locator('.article-live-hint')).toContainText('正在重新连接');
  await page.evaluate(()=> (window as any).articleStream.emit('snapshot',{revision:2,kind:'article_document',partial:{title:'实时生成的新标题',opening:'第一批正在返回的文字，后续内容持续补上。',sections:[{heading:'逐步出现的章节',paragraphs:['已返回的一段成品内容。']}]}}));
  await expect(page.locator('.article-live-copy')).toContainText('后续内容持续补上');
  await expect(page.locator('.article-live-copy')).not.toContainText('"sections"');
  await page.screenshot({path:testInfo.outputPath('article-streaming.png'),animations:'disabled'});
  await page.keyboard.press('Escape');await expect(progress).toHaveCount(0);await expect(activity).toBeFocused();
  await expect(activity).toBeInViewport();await activity.click();
  state.article!.status='needs_review';state.article!.stage='review';
  await page.evaluate(()=> (window as any).articleStream.emit('complete',{status:'needs_review'}));
  await expect(progress).toContainText('本次处理完成');await expect(progress.locator('.spin')).toHaveCount(0);
  await page.getByRole('button',{name:'关闭创作进度'}).click();
  await page.getByRole('button',{name:'收起创作状态'}).click();await expect(activity).toHaveCount(0);
  await expect(page.getByLabel('主标题',{exact:true})).toHaveValue(document.title);
});

test('topic details stay collapsed, vertical steps preserve edits and failed activity stays available',async({page},testInfo)=>{
  const state=await mockStudio(page,true);
  Object.assign(state.task.settings,{_editorial_plan:{date:'2026-09-24',subject:'古城里的日常生活',brief:'沿着街巷理解地方生活',query:'古城 居民',required_terms:['古城'],recent_titles:['上一次旅行']}});
  await page.goto('/#task/task-ui-test');
  await expect(page.getByText('古城里的日常生活',{exact:true})).toHaveCount(0);
  const steps=page.locator('.article-steps');const boxes=await steps.getByRole('button').evaluateAll(es=>es.map(e=>({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y})));
  expect(new Set(boxes.map(b=>b.x)).size).toBe(1);expect(boxes[3].y).toBeGreaterThan(boxes[0].y+90);
  await page.getByLabel('主标题',{exact:true}).fill('保留的手动标题');
  const trigger=page.getByRole('button',{name:'查看选题与资料'});await trigger.click();
  const topic=page.getByRole('dialog',{name:'选题与资料'});await expect(topic).toContainText('古城里的日常生活');
  await expect(topic.getByRole('button',{name:'关闭选题与资料'})).toBeFocused();
  await page.screenshot({path:testInfo.outputPath('topic-drawer-desktop.png'),animations:'disabled'});
  await page.keyboard.press('Escape');await expect(topic).toHaveCount(0);await expect(trigger).toBeFocused();
  await expect(page.getByLabel('主标题',{exact:true})).toHaveValue('保留的手动标题');
  await page.screenshot({path:testInfo.outputPath('vertical-workspace-desktop.png'),animations:'disabled'});
  state.article!.status='failed';state.article!.error='模型连接暂时中断';state.article!.updated_at='2026-09-24T05:00:00Z';
  const activity=page.getByRole('button',{name:'查看创作进度'});await expect(activity).toBeVisible();
  await page.getByRole('button',{name:'关闭错误提示'}).click();
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole('button',{name:'写作角度',exact:false})).not.toBeVisible();
  await page.locator('.article-flow>summary').click();await expect(steps.getByRole('button',{name:'写作角度',exact:false})).toBeVisible();
  await page.getByRole('textbox',{name:'结尾',exact:true}).scrollIntoViewIfNeeded();await expect(activity).toBeInViewport();
  await activity.click();const progress=page.getByRole('dialog',{name:'创作进度'});
  await expect(progress).toContainText('模型连接暂时中断');await expect(progress).toContainText('本次没有可展示的实时输出');
  await expect(progress).not.toContainText('等待模型返回文字');await expect(progress.getByRole('button',{name:'从此步骤重试'})).toBeDisabled();
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('activity-mobile.png'),animations:'disabled'});
  await page.keyboard.press('Escape');await expect(activity).toBeFocused();
});
