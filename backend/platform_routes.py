import uuid
from pydantic import BaseModel,Field
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from . import db, config, model_library, task_store, task_engine, task_sources, image_studio, pictures
from .models import ModelConnection
from .task_models import CreateTask, EditTask, ExecuteTask, TaskSettings, EditImage
from .picture_models import PictureSearch, PictureRequest, PictureSource
from . import unsplash
from .article_models import ArticleVersion
from . import wechat_accounts, wechat_delivery, wechat_browser, article_export

router=APIRouter(prefix='/api')


@router.get('/pictures/search')
def picture_search(query: str,source: Literal['web','licensed']='web',details: bool=False,sources: list[PictureSource]|None=Query(default=None,max_length=6),page: int=Query(default=1,ge=1,le=50)):
    request=PictureSearch(query=query,source=source)
    return pictures.search_report(request.query,request.source,sources,page) if details else pictures.search(request.query,request.source,sources,page)


@router.get('/picture-sources/unsplash')
def unsplash_connection():return unsplash.public()


@router.put('/picture-sources/unsplash')
def unsplash_connect(body: unsplash.Connection):return unsplash.save(body)


@router.post('/pictures')
def picture_create(body: PictureRequest):
    return pictures.create(body)


@router.get('/pictures/candidates/{ident}/preview')
def picture_preview(ident: str):
    return Response(pictures.preview(ident),media_type='image/jpeg')


@router.get('/pictures/{ident}')
def picture_detail(ident: str):
    return pictures.get(ident)


@router.get('/wechat/accounts')
def wechat_connections():return wechat_accounts.catalog()


@router.post('/wechat/accounts',status_code=201)
def add_wechat_connection(body:wechat_accounts.AccountInput):return wechat_accounts.save(body)


@router.put('/wechat/accounts/{ident}')
def edit_wechat_connection(ident:str,body:wechat_accounts.AccountInput):return wechat_accounts.save(body,ident)


@router.post('/wechat/accounts/{ident}/test')
def probe_wechat_connection(ident:str):return wechat_accounts.probe(ident)


@router.post('/wechat/accounts/{ident}/login')
def start_wechat_login(ident:str):return wechat_browser.start(ident)


@router.get('/wechat/accounts/{ident}/login')
def wechat_login_status(ident:str):return wechat_browser.status(ident)


@router.get('/wechat/accounts/{ident}/login/qr')
def wechat_login_qr(ident:str):return Response(wechat_browser.qr_image(ident),media_type='image/png')


@router.get('/wechat/accounts/{ident}/login/preview')
def wechat_login_preview(ident:str):return Response(wechat_browser.preview(ident),media_type='image/png')


class LoginClick(BaseModel):
    x:float=Field(ge=0,lt=1280)
    y:float=Field(ge=0,lt=850)


@router.post('/wechat/accounts/{ident}/login/click')
def click_wechat_login(ident:str,body:LoginClick):return wechat_browser.click(ident,body.x,body.y)


@router.post('/wechat/accounts/{ident}/login/cancel')
def cancel_wechat_login(ident:str):return wechat_browser.cancel(ident)


@router.delete('/wechat/accounts/{ident}/login')
def forget_wechat_login(ident:str):return wechat_browser.cancel(ident,forget=True)


@router.post('/task-runs/{ident}/publication/refresh')
def refresh_publication(ident:str):return wechat_delivery.refresh(ident)


@router.get('/task-runs/{ident}/publication/content')
def publication_content(ident:str):return wechat_delivery.handoff_content(ident)


@router.get('/task-runs/{ident}/publication/bundle')
def publication_bundle(ident:str):
    content=article_export.bundle(wechat_delivery.handoff_article(ident))
    return Response(content,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="wechat-article.zip"'})


@router.get('/models')
def models():return model_library.catalog()


@router.post('/models',status_code=201)
def add_model(body:ModelConnection):return model_library.save(body)


@router.put('/models/{ident}')
def edit_model(ident:str,body:ModelConnection):return model_library.save(body,ident)


@router.post('/models/test')
def test_new_model(body:ModelConnection):return probe(body)


@router.post('/models/discover')
def discover_new_models(body:ModelConnection):
    from .model_directory import discover
    return discover(model_library.resolve(body))


@router.post('/models/{ident}/discover')
def discover_saved_models(ident:str,body:ModelConnection):
    from .model_directory import discover
    return discover(model_library.resolve(body,ident))


@router.post('/models/{ident}/test')
def test_model(ident:str,body:ModelConnection):return probe(body,ident)


def probe(body,ident=None):
    if body.protocol == 'catalog':raise ValueError('该模型已作为目录保存，暂未接入其生成接口，不能执行生成测试。')
    if body.protocol == 'images':
        value=model_library.resolve(body,ident)
        if not value.get('api_key'):raise ValueError('请填写图片模型密钥。')
        pictures.generate(PictureRequest(request_id='test-'+uuid.uuid4().hex,action='generate',prompt='白色背景上的一片绿色叶子，无文字，无水印',ratio='square'),
                          'picture-test-'+uuid.uuid4().hex,connection=value)
        return {'message':'图片生成成功，测试图片已保存到素材库。'}
    from .ai import request_structured
    from pydantic import BaseModel
    from typing import Literal
    class Probe(BaseModel):
        status:Literal['ok']
    value=model_library.resolve(body,ident)
    request_structured(Probe,'返回 {"status":"ok"}。',{},'connection-test','connection_test',connection=value,max_tokens=128)
    return {'message':'连接成功，模型可以按当前协议返回结果。'}


@router.get('/tasks')
def tasks(deleted:bool=False):return task_store.listing(deleted=deleted)


@router.get('/task-records')
def task_records():return task_store.records()


@router.post('/tasks',status_code=201)
def create_task(body:CreateTask):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM creation_tasks WHERE request_id=?',(body.request_id,)).fetchone()
        if old:
            task_store.require(c,old['id'])
            if old['name']!=body.name or old['kind']!=body.kind:raise HTTPException(409,'请求编号已用于其他任务。')
            ident=old['id']
        else:
            ident='task-'+uuid.uuid4().hex[:18];settings=TaskSettings()
            if body.kind=='article':
                settings.article=db.article_profile()
                settings.article_plan.mode='direction'
                settings.materials.search_scope='wechat'
            c.execute('INSERT INTO creation_tasks VALUES (?,?,?,?,?,?,?,?,?)',(ident,body.request_id,body.name,body.kind,1,settings.model_dump_json(),0,db.now(),db.now()))
    return task_store.detail(ident)


@router.get('/tasks/{ident}')
def task_detail(ident:str):return task_store.detail(ident)


@router.delete('/tasks/{ident}')
def delete_task(ident:str,body:ArticleVersion):return task_store.delete(ident,body.version)


@router.post('/tasks/{ident}/restore')
def restore_task(ident:str,body:ArticleVersion):return task_store.restore(ident,body.version)


@router.put('/tasks/{ident}')
def save_task(ident:str,body:EditTask):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');task=task_store.require(c,ident,body.version)
        if body.settings.execution=='automatic':task_engine.validated(body.settings,task['kind'])
        for asset_id in body.settings.video.asset_ids+[body.settings.image.asset_id]:
            if asset_id and not c.execute('SELECT 1 FROM assets WHERE id=?',(asset_id,)).fetchone():raise ValueError('所选素材已不存在。')
        for asset_id in body.settings.illustration.asset_ids:
            if not c.execute("SELECT 1 FROM assets WHERE id=? AND media_type LIKE 'image/%'",(asset_id,)).fetchone():raise ValueError('配图素材必须为已有图片。')
        c.execute('UPDATE creation_tasks SET name=?,settings=?,version=version+1,updated_at=? WHERE id=?',(body.name,body.settings.model_dump_json(),db.now(),ident))
    return task_store.detail(ident)


@router.post('/tasks/{ident}/archive')
def archive_task(ident:str,body:ArticleVersion):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE');task=task_store.require(c,ident,body.version)
        if any(r['status'] in ('queued','running','publishing') for r in task_store.runs(c,task)):raise HTTPException(409,'请等待正在执行的任务完成后归档。')
        c.execute('UPDATE creation_tasks SET archived=?,version=version+1,updated_at=? WHERE id=?',(not task['archived'],db.now(),ident))
    return task_store.detail(ident)


@router.post('/tasks/{ident}/collect')
def collect_task(ident:str,body:ArticleVersion):
    with task_store.collection(ident,body.version) as task:
        ids,reports=task_sources.collect(ident,TaskSettings.model_validate(task['settings']))
        return {'ids':ids,'reports':reports,'topics':task_store.detail(ident)['topics']}


@router.post('/tasks/{ident}/run')
def run_task(ident:str,body:ExecuteTask):return task_engine.create_run(ident,body.version,body.request_id,body.action)


@router.post('/task-runs/{ident}/retry')
def retry_run(ident:str):return task_engine.retry(ident)


@router.get('/image-jobs/{ident}')
def image_detail(ident:str):return image_studio.get(ident)


@router.put('/image-jobs/{ident}')
def image_edit(ident:str,body:EditImage):return image_studio.edit(ident,body)


@router.get('/image-jobs/{ident}/files/{index}')
def image_file(ident:str,index:int,version:int):
    value=image_studio.get(ident)
    if value['version']!=version:raise HTTPException(409,'图片版本已更新，请刷新。')
    if value['status']!='needs_review' or not value['files'] or not 0<=index<len(value['files']):raise HTTPException(404,'图片尚未生成。')
    path=(config.DATA/value['files'][index]).resolve()
    if not path.is_relative_to(config.DATA) or not path.is_file():raise HTTPException(404,'图片文件不存在。')
    return FileResponse(path,media_type='image/png',filename=f'card-{index+1}.png')


@router.get('/image-jobs/{ident}/bundle')
def image_bundle(ident:str,version:int):
    if image_studio.get(ident)['version']!=version:raise HTTPException(409,'图片版本已更新，请刷新。')
    return Response(image_studio.bundle(ident),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{ident}.zip"'})
