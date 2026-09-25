"""Manual executions and scheduled workflows, with durable per-task daily claims."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import logging
import uuid
from fastapi import HTTPException
from . import db, task_store, task_sources, model_library, article_worker, worker, image_studio
from . import editorial, wechat_delivery
from .task_models import TaskSettings
from .article_models import ArticleInput, ArticleDocument, ArticleOutline
from .models import Script, Scene

executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='studio-tasks')


def validated(settings, kind, action='automatic'):
    if action=='blank':return
    if action!='blank' and not model_library.ready(settings.model_id):raise ValueError('请选择一个已配置的模型，或先到“我的模型”添加。')
    if model_library.current(settings.model_id).get('protocol')=='images':raise ValueError('请为文字创作选择文字模型，图片模型在配图配置中单独选择。')
    if kind=='article':
        from .article_pictures import validate
        validate(settings.illustration)
    materials=settings.materials
    if materials.discover and not (materials.query or settings.brief or settings.article.direction):raise ValueError('联网查找需要关键词或内容方向。')
    if materials.mode=='reference' and not (materials.urls or materials.topic_ids or materials.discover or len(materials.notes)>=20):raise ValueError('请配置参考网址、联网查找关键词、已有资料或至少 20 字笔记。')
    if materials.mode=='original' and not (settings.brief or (kind=='article' and settings.article.direction) or materials.notes):raise ValueError('请填写创作主题、方向或个人笔记。')
    if kind=='video' and materials.mode=='original' and not (len(materials.notes)>=20 or len(settings.brief)>=20):raise ValueError('原创视频请提供至少 20 字的内容依据，并选择图片或视频素材。')
    if settings.wechat_delivery.mode!='local':
        if kind!='article':raise ValueError('只有公众号文章任务支持发布到公众号。')
        if action=='automatic':wechat_delivery.validate(settings)


def create_run(task_id,version,request_id,action,slot=None,submit=True):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');task=task_store.require(c,task_id,version)
        old=c.execute('SELECT * FROM task_runs WHERE request_id=?',(request_id,)).fetchone()
        if old:
            if old['task_id']!=task_id or old['action']!=action:raise HTTPException(409,'请求编号已用于其他执行。')
            return dict(old)
        if task['archived']:raise ValueError('任务已归档，请先恢复任务。')
        if any(r['status'] in ('queued','running','publishing') for r in task_store.runs(c,task)):raise HTTPException(409,'该任务已有执行中的作品，请等待完成。')
        settings=TaskSettings.model_validate(task['settings']);validated(settings,task['kind'],action)
        ident='run-'+uuid.uuid4().hex[:18];now=db.now()
        c.execute('INSERT INTO task_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (ident,task_id,request_id,slot,action,'queued','prepare',settings.model_dump_json(),None,None,'[]',now,now))
        c.execute('UPDATE creation_tasks SET updated_at=? WHERE id=?',(now,task_id))
    if submit:executor.submit(run,ident)
    return {'id':ident,'task_id':task_id,'status':'queued'}


def persist(ident,**values):
    values['updated_at']=db.now()
    with db.connect() as c:c.execute('UPDATE task_runs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),ident))


def blank_article(task,settings,ids,request_id):
    with db.connect() as c:
        old=c.execute('SELECT id FROM articles WHERE request_id=?',(request_id,)).fetchone()
    if old:return article_worker.get(old['id'])
    now=db.now();ident='article-'+uuid.uuid4().hex[:18]
    source_data=[]
    with db.connect() as c:
        for topic_id in ids:
            row=db.topic(c.execute('SELECT * FROM topics WHERE id=?',(topic_id,)).fetchone())
            if row:source_data.extend(row['sources'])
        if settings.materials.notes:source_data.append({'id':'personal-notes','title':'个人笔记','text':settings.materials.notes,'url':'','publisher':'用户提供','full_text':True})
        title=settings.brief[:100] or task['name']
        doc=ArticleDocument(template_id=settings.article.template_id,title=title,titles=[title],summary='填写文章摘要',sections=[{'heading':'第一个观点','paragraphs':['在这里开始写作。']}])
        outline=ArticleOutline(title=title,angle='手动创作',sections=[{'heading':'第一个观点','points':'填写主要观点'}])
        inp={'mode':settings.materials.mode,'brief':settings.brief,'notes':settings.materials.notes,'topic_ids':ids,'request_id':request_id,'_model_id':settings.model_id,'_illustration':settings.illustration.model_dump()}
        c.execute('INSERT INTO articles(id,request_id,status,stage,progress,mode,version,profile,input_data,source_data,outline,document,created_at,updated_at,note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (ident,request_id,'draft','review',100,settings.materials.mode,1,settings.article.model_dump_json(),db.dump(inp),db.dump(source_data),outline.model_dump_json(),doc.model_dump_json(),now,now,'手动草稿已创建，可以开始编辑。'))
        article_worker.snapshot(c,ident,'创建手动草稿')
    return article_worker.get(ident)


def drive_article(ident,automatic):
    value=article_worker.get(ident)
    if value['status']=='failed':
        article_worker.enqueue(ident,value['version'],'retry',submit=False)
    article_worker.run(ident)
    if automatic:
        # Each transition is committed. A later retry resumes this exact artifact.
        for _ in range(3):
            value=article_worker.get(ident)
            if value['status']=='needs_angle':article_worker.enqueue(ident,value['version'],'outline',choice=0,submit=False)
            elif value['status']=='needs_outline':article_worker.enqueue(ident,value['version'],'article',submit=False)
            else:break
            article_worker.run(ident)
    return article_worker.get(ident)


def run(ident):
    with db.connect() as c:
        claimed=c.execute("UPDATE task_runs SET status='running',updated_at=? WHERE id=? AND status='queued'",(db.now(),ident)).rowcount
        if not claimed:return
        row=dict(c.execute('SELECT * FROM task_runs WHERE id=?',(ident,)).fetchone());task=task_store.require(c,row['task_id'])
    raw=json.loads(row['settings']);settings=TaskSettings.model_validate({k:v for k,v in raw.items() if not k.startswith('_')})
    automatic=row['action']=='automatic';blank=row['action']=='blank'
    try:
        with model_library.use(settings.model_id):
            content_id=row['content_id']
            if not content_id:
                plan=raw.get('_editorial_plan')
                if task['kind']=='article' and not blank and settings.article_plan.mode=='direction':
                    if not plan:
                        persist(ident,stage='plan')
                        plan=editorial.plan_article(task['id'],settings,ident)
                        raw['_editorial_plan']=plan;persist(ident,settings=db.dump(raw))
                    settings=settings.model_copy(update={'brief':plan['brief']})
                persist(ident,stage='collect')
                ids,reports=task_sources.collect(task['id'],settings,**({'intent':plan} if plan and not settings.materials.query else {}))
                ids=task_sources.material_topics(task['id'],settings,ids,automatic)
                persist(ident,reports=db.dump(reports))
                if automatic and settings.materials.mode=='original' and (settings.materials.discover or settings.materials.urls) and not ids and len(settings.materials.notes)<20:
                    raise ValueError('本次已启用资料采集，但没有取得新的可用资料，未继续生成或发布。请查看采集结果后调整来源或重试。')
                if not blank and settings.materials.mode=='reference' and not ids and len(settings.materials.notes)<20:
                    raise ValueError('没有取得新的可用参考资料。'+('结构/文风参考需要完整正文，搜索摘要不能用于模仿。' if settings.materials.reference_style!='facts' else '')+'请检查采集结果、修改来源或导入文章正文。')
                raw['_used_topic_ids']=ids;persist(ident,settings=db.dump(raw),stage='create')
                if task['kind']=='article':
                    if blank:content=blank_article(task,settings,ids,ident)
                    else:
                        inp=ArticleInput(mode=settings.materials.mode,brief=settings.brief,notes=settings.materials.notes,topic_ids=ids,request_id=ident)
                        profile=settings.article.model_copy(deep=True)
                        if automatic and settings.wechat_delivery.mode!='local':
                            profile.preferences=('交付到微信公众号：标题不超过32字，摘要不超过120字。\n'+profile.preferences)[:2000]
                        if settings.materials.mode=='reference':
                            method={'facts':'以参考资料提供事实依据，独立组织文章。','structure':'先理解参考文章的叙事结构、开头钩子、信息顺序与结尾方式，再围绕本次主题独立写成新文章；不能逐句替换、拼接原文或照搬特有案例和表达。','tone':'参考文章的句长、节奏、语气与段落密度，围绕本次主题独立创作；不冒充原作者，不照搬特色措辞、经历或引语。'}[settings.materials.reference_style]
                            profile.preferences=('参考方式：'+method+'\n'+profile.preferences)[:2000]
                        content=article_worker.create(inp,submit=False,profile_override=profile,model_id=settings.model_id,illustration=settings.illustration)
                elif task['kind']=='video':
                    notes=settings.materials.notes
                    if blank and len(settings.brief+notes)<20:notes='手动视频草稿：请在编辑器中填写自己的文案、选择素材并核对内容依据。'
                    topic_id=ids[0] if ids else task_sources.note_topic(task['id'],settings.brief,notes)
                    prefs=db.settings().model_dump();prefs.update(model_id=settings.model_id,task_id=task['id'],asset_ids=settings.video.asset_ids,resolution=settings.video.resolution,creative_brief=settings.brief,visual_style=settings.video.visual_style)
                    script=None
                    if blank:
                        topic=worker.get_topic(topic_id);source=topic['sources'][0]
                        script=Script(title=task['name'][:60],description=settings.brief[:500] or task['name'],title_lines=[task['name'][:28]],scenes=[Scene(heading='画面 '+str(i+1),source_id=source['id'],evidence=source['text'][:200],visual='question',asset_id=asset) for i,asset in enumerate(settings.video.asset_ids or [''])])
                    content=worker.create(topic_id,'ai',ident,submit=False,preferences=prefs,manual_script=script)
                else:
                    data=[]
                    with db.connect() as c:
                        for topic_id in ids:
                            topic=db.topic(c.execute('SELECT * FROM topics WHERE id=?',(topic_id,)).fetchone())
                            if topic:data.extend(topic['sources'])
                    if settings.materials.notes:data.append({'id':'notes','title':'个人笔记','text':settings.materials.notes,'url':''})
                    content=image_studio.create(settings.image,settings.brief or task['name'],data,ai=not blank,ident='image-'+ident.removeprefix('run-'))
                content_id=content['id'];persist(ident,content_id=content_id,stage='content')
            if task['kind']=='article':content=drive_article(content_id,automatic) if not blank else article_worker.get(content_id)
            elif task['kind']=='video':
                if not blank:
                    if worker.get_job(content_id)['status']=='failed':worker.retry(content_id,submit=False)
                    worker.run(content_id)
                content=worker.get_job(content_id)
            else:
                content=image_studio.get(content_id)
                if content['status']=='failed':
                    with db.connect() as c:c.execute("UPDATE image_jobs SET status='draft' WHERE id=? AND status='failed'",(content_id,))
                    image_studio.render(content_id);content=image_studio.get(content_id)
            if task['kind']=='article' and automatic and settings.wechat_delivery.mode!='local' and content['status']!='failed':
                persist(ident,stage='delivery')
                wechat_delivery.deliver(ident,content,settings)
            else:persist(ident,status='failed' if content['status']=='failed' else 'ready',stage='content',error=content.get('error'))
    except Exception as error:
        logging.exception('Task execution failed: %s',ident)
        message=str(error) if isinstance(error,ValueError) else '执行未完成，请检查配置后重试。'
        persist(ident,status='failed',stage='error',error=message[:1200])


def retry(ident):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM task_runs WHERE id=?',(ident,)).fetchone()
        if not row:raise HTTPException(404,'执行记录不存在。')
        task=task_store.require(c,row['task_id'])
        if row['status']!='failed':raise HTTPException(409,'当前执行无需重试。')
        if any(r['status'] in ('queued','running','publishing') for r in task_store.runs(c,task)):raise HTTPException(409,'任务已有正在执行的作品。')
        publication=wechat_delivery.get(ident,c)
        if publication and (publication['status']=='uncertain' or publication['data'].get('publish_id')):
            raise HTTPException(409,'本次已提交微信或提交结果待核对，不会重复发布；请查看发布记录和公众号后台。')
        c.execute("UPDATE task_runs SET status='queued',error=NULL WHERE id=?",(ident,))
    executor.submit(run,ident)
    return {'id':ident,'status':'queued'}


def tick(now=None):
    wechat_delivery.tick()
    local=now or datetime.now(db.TZ);today=local.date().isoformat()
    for task in task_store.listing():
        settings=TaskSettings.model_validate(task['settings'])
        if task['archived'] or settings.execution!='automatic' or local.isoweekday() not in settings.schedule.weekdays or local.strftime('%H:%M')<settings.schedule.time:continue
        with db.connect() as c:
            if c.execute('SELECT 1 FROM task_runs WHERE task_id=? AND schedule_slot=?',(task['id'],today)).fetchone():continue
        try:
            create_run(task['id'],task['version'],'scheduled-'+task['id']+'-'+today,'automatic',slot=today)
        except HTTPException as error:
            if error.status_code in (404,409):continue  # Deleted or changed since the scheduler snapshot.
            raise
        except ValueError as error:
            # Invalid external model state gets a visible record once per day.
            with db.connect() as c:
                now_text=db.now()
                c.execute('INSERT OR IGNORE INTO task_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          ('run-'+uuid.uuid4().hex[:18],task['id'],'scheduled-'+task['id']+'-'+today,today,'automatic','failed','prepare',settings.model_dump_json(),None,str(error),'[]',now_text,now_text))


def recover():
    with db.connect() as c:
        c.execute("UPDATE task_runs SET status='failed',stage='interrupted',error=?,updated_at=? WHERE status='running'",('服务中断，已有作品保留，可从执行记录继续。',db.now()))
        c.execute("UPDATE image_jobs SET status='failed',error=? WHERE status='running'",('服务中断，请保存并重新生成。',))
        queued=[row['id'] for row in c.execute("SELECT id FROM task_runs WHERE status='queued'")]
        draft_images=[row['id'] for row in c.execute("SELECT id FROM image_jobs WHERE status='draft'")]
    wechat_delivery.recover()
    for ident in queued:executor.submit(run,ident)
    for ident in draft_images:image_studio.executor.submit(image_studio.render,ident)
