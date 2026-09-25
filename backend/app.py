from contextlib import asynccontextmanager
import asyncio
import json
import logging

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, worker
from .ai import validate_evidence, curate
from .models import CreateJob, EditScript, Review, Settings, CollectionSource, ModelConnection, SourceConfiguration, ImportPage
from .sources import collect, preview, FEEDS, import_page
from . import model_config
from .ai import test_connection
from .scheduler import tick
from .media import MAX_UPLOAD, store_asset, asset_path
from .article_routes import router as article_router
from . import article_worker
from .platform_routes import router as platform_router
from . import task_store, task_engine, pictures

async def scheduler_loop(stop: asyncio.Event):
    while not stop.is_set():
        try:await asyncio.to_thread(tick)
        except Exception:logging.exception('Scheduler loop failed')
        try:await asyncio.wait_for(stop.wait(),timeout=30)
        except asyncio.TimeoutError:pass


@asynccontextmanager
async def lifespan(app):
    db.init();pictures.init()
    task_store.init();worker.recover();article_worker.recover();pictures.recover();task_engine.recover();stop=asyncio.Event()
    with db.connect() as c:
        c.execute("UPDATE daily_runs SET status='attention',message=? WHERE status='running'",('采集期间服务中断；请手动采集并选择制作。',))
    task=asyncio.create_task(scheduler_loop(stop))
    yield
    stop.set();await task
    from . import wechat_browser
    wechat_browser.shutdown()


app=FastAPI(title='知序 · 自媒体创作平台',lifespan=lifespan)
app.include_router(article_router)
app.include_router(platform_router)


@app.middleware('http')
async def local_guard(request: Request,call_next):
    host=request.headers.get('host','').split(':')[0]
    if host not in ('127.0.0.1','localhost','testserver'):
        return JSONResponse({'detail':'本地版本仅允许本机访问。'},status_code=403)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        allowed={'http://127.0.0.1:8765','http://localhost:8765','http://127.0.0.1:5173','http://localhost:5173'}
        if origin and origin not in allowed:return JSONResponse({'detail':'拒绝跨站写入。'},status_code=403)
        if request.headers.get('content-length','0').isdigit() and int(request.headers.get('content-length','0'))>MAX_UPLOAD+1_000_000:
            return JSONResponse({'detail':'请求超过大小限制。'},status_code=413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
    return response


@app.exception_handler(ValueError)
async def validation_error(request,error):return JSONResponse({'detail':str(error)},status_code=400)


@app.exception_handler(RequestValidationError)
async def input_error(request,error):
    # Validation responses must not echo API keys submitted in an invalid request.
    return JSONResponse({'detail':[{'loc':e['loc'],'msg':e['msg'],'type':e['type']} for e in error.errors()]},status_code=422)


def require_job(job_id):
    job=worker.get_job(job_id)
    if not job:raise HTTPException(404,'任务不存在。')
    return job


@app.get('/api/health')
def health():
    connection=model_config.public()
    return {'ok':True,'name':'知序','version':'0.1.0','ai_ready':connection['ready'],
            'model':connection['model'] or None,'audio_mode':'silent','duration_seconds':10,'local_only':True}


@app.get('/api/model-config')
def model_get():return model_config.public()


@app.put('/api/model-config')
def model_save(body: ModelConnection):return model_config.save(body)


@app.post('/api/model-config/test')
def model_test(body: ModelConnection):return test_connection(body)


@app.get('/api/source-catalog')
def source_catalog():return list(FEEDS.values())


@app.post('/api/sources/preview')
def source_preview(body: CollectionSource):return preview(body.model_dump())


@app.post('/api/sources/import')
def source_import(body: ImportPage):return import_page(body)


@app.get('/api/settings')
def settings_get():return db.settings()


@app.put('/api/settings')
def settings_update(settings: Settings):
    if settings.schedule_enabled:
        if not (settings.sources or any(s.enabled for s in settings.custom_sources)):raise ValueError('请先在素材库配置并启用采集源，再开启每日计划。')
        if not config.ai_ready():raise ValueError('尚未配置 AI 密钥与模型，不能启用每日自动制作。')
    with db.connect() as c:c.execute('UPDATE settings SET value=? WHERE id=1',(settings.model_dump_json(),))
    return settings


@app.put('/api/source-settings')
def source_settings_update(body: SourceConfiguration):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        settings=Settings.model_validate_json(c.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])
        settings.sources=body.sources;settings.custom_sources=body.custom_sources
        if not (body.sources or any(s.enabled for s in body.custom_sources)):
            settings.schedule_enabled=False
        c.execute('UPDATE settings SET value=? WHERE id=1',(settings.model_dump_json(),))
    return settings


@app.get('/api/topics')
def topics():
    with db.connect() as c:
        rows=c.execute("SELECT * FROM topics WHERE kind='live' ORDER BY score DESC,published_at DESC,discovered_at DESC LIMIT 100").fetchall()
    return [db.topic(row) for row in rows]


@app.post('/api/collect')
def collect_now():return collect()


@app.post('/api/curate')
def curate_now():return curate()


@app.get('/api/activity')
def activity():
    with db.connect() as c:
        return {'sources':[dict(r) for r in c.execute('SELECT * FROM source_runs ORDER BY id DESC LIMIT 8')],
                'daily':[dict(r) for r in c.execute('SELECT * FROM daily_runs ORDER BY day DESC LIMIT 7')],
                'ai_calls':c.execute('SELECT count(*) FROM ai_usage WHERE day=?',(db.day(),)).fetchone()[0],
                'jobs_today':c.execute('SELECT count(*) FROM jobs WHERE day=?',(db.day(),)).fetchone()[0]}


@app.get('/api/jobs')
def jobs():
    with db.connect() as c:return [db.job(r) for r in c.execute('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50')]


@app.post('/api/jobs',status_code=201)
def create_job(body: CreateJob):return worker.create(body.topic_id,body.mode,body.request_id)


@app.get('/api/jobs/{job_id}')
def job_detail(job_id: str):
    job=require_job(job_id)
    with db.connect() as c:
        job['events']=[dict(r) for r in c.execute('SELECT * FROM job_events WHERE job_id=? ORDER BY id',(job_id,))]
        job['reviews']=[dict(r) for r in c.execute('SELECT * FROM reviews WHERE job_id=? ORDER BY id',(job_id,))]
    if job.get('artifacts'):
        path=artifact_path(job,'manifest')
        if path.exists():job['manifest']=json.loads(path.read_text(encoding='utf-8'))
    return job


@app.post('/api/jobs/{job_id}/retry')
def retry_job(job_id: str):return worker.retry(job_id)


@app.post('/api/jobs/{job_id}/review')
def review_job(job_id: str,body: Review):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        job=db.job(c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone())
        if not job:raise HTTPException(404,'任务不存在。')
        if body.version!=job['version']:raise HTTPException(409,'版本已更新，请刷新后重新审核。')
        if job['status'] not in ('needs_review','approved'):raise HTTPException(409,'当前任务不在可审核状态。')
        if body.decision=='approve':
            if not (body.facts_checked and body.rights_checked):raise ValueError('请完成事实与素材检查后再通过。')
            if not job['qa'] or not job['qa'].get('passed'):raise ValueError('自动质检未通过，不能标记为审核通过。')
        elif not body.note.strip():raise ValueError('请填写修改意见。')
        status='approved' if body.decision=='approve' else 'changes_requested'
        c.execute('UPDATE jobs SET status=?,note=?,updated_at=? WHERE id=?',(status,body.note or '人工审核通过。',db.now(),job_id))
        c.execute('INSERT INTO reviews(job_id,version,decision,facts_checked,rights_checked,note,at) VALUES (?,?,?,?,?,?,?)',
                  (job_id,body.version,body.decision,body.facts_checked,body.rights_checked,body.note,db.now()))
        db.event(c,job_id,'review','审核通过。' if status=='approved' else '退回修改：'+body.note)
    return require_job(job_id)


@app.put('/api/jobs/{job_id}/script')
def edit_script(job_id: str,body: EditScript):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        job=db.job(c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone())
        if not job:raise HTTPException(404,'任务不存在。')
        if job['status'] in ('queued','running'):raise HTTPException(409,'正在制作，暂不可修改。')
        if body.version!=job['version']:raise HTTPException(409,'脚本已被修改，请刷新后再保存。')
        validate_evidence(body.script,job['source_data'])
        for scene in body.script.scenes:
            if scene.asset_id and not c.execute('SELECT 1 FROM assets WHERE id=?',(scene.asset_id,)).fetchone():raise ValueError('替换素材不存在。')
        c.execute("UPDATE jobs SET script=?,version=version+1,status='draft',stage='script',progress=25,artifacts=NULL,qa=NULL,error=NULL,note=?,updated_at=? WHERE id=?",
                  (body.script.model_dump_json(),body.note,db.now(),job_id))
        db.event(c,job_id,'script','脚本已更新，旧版本审核失效。请重新制作。')
    return require_job(job_id)


def artifact_path(job,kind):
    value=(job.get('artifacts') or {}).get(kind)
    if not value:raise HTTPException(404,'文件尚未生成。')
    resolved=(config.DATA/value).resolve()
    if not resolved.is_relative_to(config.DATA.resolve()):raise HTTPException(400,'无效路径。')
    return resolved


@app.get('/api/jobs/{job_id}/files/{kind}')
def get_artifact(job_id: str,kind: str):
    if kind not in ('video','cover','subtitle','script','manifest','bundle'):raise HTTPException(404)
    job=require_job(job_id)
    if kind=='bundle' and job['status']!='approved':raise HTTPException(409,'请通过审核后下载交付包。')
    path=artifact_path(job,kind)
    if not path.is_file():raise HTTPException(404,'文件不存在。')
    media={'video':'video/mp4','cover':'image/jpeg','subtitle':'application/x-subrip','bundle':'application/zip','script':'application/json','manifest':'application/json'}[kind]
    return FileResponse(path,media_type=media,filename=path.name if kind not in ('video','cover') else None)


@app.get('/api/assets')
def list_assets():
    with db.connect() as c:
        rows=c.execute('SELECT a.*,p.data AS provenance FROM assets a LEFT JOIN asset_provenance p ON p.asset_id=a.id ORDER BY a.at DESC')
        return [{**{k:v for k,v in dict(r).items() if k not in ('path','provenance')},'provenance':json.loads(r['provenance']) if r['provenance'] else {'kind':'upload'}} for r in rows]


@app.post('/api/assets',status_code=201)
async def upload_asset(file: UploadFile=File(...),rights: str=Form(...),credit: str=Form(''),source_url: str=Form('')):
    if len(rights.strip())<4 or len(rights)>2000:raise ValueError('请说明素材的使用权来源。')
    if len(credit)>120 or len(source_url)>2000:raise ValueError('署名或来源过长。')
    content=await file.read(MAX_UPLOAD+1)
    if len(content)>MAX_UPLOAD:raise HTTPException(413,'素材不能超过 100 MB。')
    asset=await asyncio.to_thread(store_asset,content,file.filename or '图片',rights,credit,source_url)
    return {k:v for k,v in asset.items() if k!='path'}


@app.get('/api/assets/{asset_id}/file')
def get_asset(asset_id: str):
    with db.connect() as c:row=c.execute('SELECT * FROM assets WHERE id=?',(asset_id,)).fetchone()
    if not row:raise HTTPException(404,'素材不存在。')
    path=asset_path(dict(row)).resolve()
    if not path.is_relative_to(config.DATA.resolve()) or not path.is_file():raise HTTPException(404,'素材文件不存在。')
    return FileResponse(path,media_type=row['media_type'])


if (config.ROOT/'dist').exists():
    app.mount('/',StaticFiles(directory=config.ROOT/'dist',html=True),name='frontend')
