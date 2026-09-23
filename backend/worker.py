from concurrent.futures import ThreadPoolExecutor
import logging
import uuid

from . import config, db
from .ai import generate, validate_evidence, verify_script
from .models import Script, Settings
from .short_render import render
from .sources import hydrate
from .media import prepare_assets

executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='science-studio')


def get_job(job_id):
    with db.connect() as c:return db.job(c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone())


def get_topic(topic_id):
    with db.connect() as c:return db.topic(c.execute('SELECT * FROM topics WHERE id=?',(topic_id,)).fetchone())


def update(job_id,stage,progress,message):
    with db.connect() as c:
        c.execute('UPDATE jobs SET status=?,stage=?,progress=?,updated_at=?,note=? WHERE id=?',
                  ('running',stage,progress,db.now(),message,job_id))
        db.event(c,job_id,stage,message)


def create(topic_id,mode,request_id,*,submit=True):
    prefs=db.settings()
    if mode!='ai':raise ValueError('新选题只支持网络资料制作。')
    if not config.ai_ready():raise ValueError('请到每日路线配置 AI 密钥和模型，再制作网络选题。')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=c.execute('SELECT * FROM jobs WHERE request_id=?',(request_id,)).fetchone()
        if existing:return db.job(existing)
        topic=db.topic(c.execute('SELECT * FROM topics WHERE id=?',(topic_id,)).fetchone())
        if not topic:raise ValueError('选题不存在。')
        if topic['kind']!='live':raise ValueError('内置选题已停用，请从网络采集新的选题。')
        active=c.execute("SELECT * FROM jobs WHERE topic_id=? AND status IN ('queued','running')",(topic_id,)).fetchone()
        if active:return db.job(active)
        job_id='job-'+uuid.uuid4().hex[:18];now=db.now()
        c.execute('INSERT INTO jobs(id,topic_id,request_id,status,stage,progress,mode,version,settings,source_data,created_at,updated_at,day) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (job_id,topic_id,request_id,'queued','queued',0,mode,1,db.dump(prefs.model_dump()),db.dump(topic['sources']),now,now,db.day()))
        db.event(c,job_id,'queued','已加入制作队列。')
    if submit:executor.submit(run,job_id)
    return get_job(job_id)


def retry(job_id,*,submit=True):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        job=db.job(c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone())
        if not job:raise ValueError('任务不存在。')
        if job['status'] not in ('failed','changes_requested','draft'):raise ValueError('当前任务不可重新制作。')
        c.execute('UPDATE jobs SET status=?,stage=?,progress=0,error=NULL,updated_at=? WHERE id=?',('queued','queued',db.now(),job_id))
        db.event(c,job_id,'queued','已重新排队；保留已保存脚本与来源，不重复请求模型。')
    if submit:executor.submit(run,job_id)
    return get_job(job_id)


def run(job_id):
    with db.connect() as c:
        claimed=c.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=? AND status='queued'",(db.now(),job_id)).rowcount
    if not claimed:return
    job=get_job(job_id)
    try:
        settings=Settings.model_validate(job['settings']);topic=get_topic(job['topic_id'])
        if job['script']:
            script=Script.model_validate(job['script']);sources=job['source_data']
            update(job_id,'script',25,'复用已保存文案与来源，继续制作 10 秒短片。')
        else:
            update(job_id,'sources',8,'整理原始资料与出处。')
            if topic['kind']=='live':topic=hydrate(topic)
            sources=topic['sources']
            update(job_id,'script',22,'根据资料编写 1–2 句短标题。' if job['mode']=='ai' else '加载内置标题与画面安排。')
            script=generate(topic,job_id) if job['mode']=='ai' else Script.model_validate(topic['seed_script'])
            validate_evidence(script,sources)
            with db.connect() as c:
                c.execute('UPDATE jobs SET script=?,source_data=?,updated_at=? WHERE id=?',
                          (script.model_dump_json(),db.dump(sources),db.now(),job_id))
                db.event(c,job_id,'script','脚本与原文快照已保存；引文匹配通过，科学表达仍需人工审核。')
        if job['mode']=='ai':
            update(job_id,'fact_check',30,'核对脚本的事实表达与原始资料。')
            verify_script(script,sources,job_id)
        update(job_id,'media',35,'准备相关图片或视频素材。')
        if topic['kind']=='live' and 'media' not in topic and any(not scene.asset_id for scene in script.scenes):
            topic=hydrate(topic)
        assets=prepare_assets(script,topic)
        with db.connect() as c:
            c.execute('UPDATE jobs SET script=? WHERE id=?',(script.model_dump_json(),job_id))
        target=config.DATA/'jobs'/job_id/f'v{job["version"]}'
        result=render(script,target,settings.resolution,sources,assets,
                      lambda stage,percent,message:update(job_id,stage,percent,message))
        artifacts={name:str(path.relative_to(config.DATA)).replace('\\','/') for name,path in
                   [('video',result.video),('cover',result.cover),('script',result.script),
                    ('manifest',result.manifest),('bundle',target/'delivery.zip')]}
        status='needs_review' if result.qa['passed'] else 'failed'
        note='成片已生成，等待人工审核。' if result.qa['passed'] else '自动质检未通过，查看检查结果后编辑或重试。'
        with db.connect() as c:
            c.execute('UPDATE jobs SET status=?,stage=?,progress=100,artifacts=?,qa=?,error=?,updated_at=?,note=? WHERE id=?',
                      (status,'review' if status=='needs_review' else 'quality',db.dump(artifacts),db.dump(result.qa),
                       None if status=='needs_review' else note,db.now(),note,job_id))
            db.event(c,job_id,'review',note)
    except Exception as error:
        logging.exception('Production failed: %s',job_id)
        with db.connect() as c:
            c.execute("UPDATE jobs SET status='failed',error=?,updated_at=?,note=? WHERE id=?",
                      (str(error)[:1200],db.now(),'任务已暂停，可修正后继续；已保存的脚本不会丢失。',job_id))
            db.event(c,job_id,'error',str(error)[:1200])


def recover():
    with db.connect() as c:
        interrupted=c.execute("SELECT id FROM jobs WHERE status='running'").fetchall()
        for row in interrupted:
            c.execute("UPDATE jobs SET status='failed',error=?,updated_at=? WHERE id=?",('上次服务退出时任务未完成；可点击重试继续。',db.now(),row['id']))
            db.event(c,row['id'],'interrupted','服务重启，保留脚本和文件，等待显式重试。')
        queued=c.execute("SELECT id FROM jobs WHERE status='queued'").fetchall()
    for row in queued:executor.submit(run,row['id'])
