from urllib.parse import urlsplit
import json
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from fastapi.responses import StreamingResponse
import asyncio
import time
from . import db, sources, article_worker as worker, article_export
from .article_models import (ArticleProfile, ArticleInput, ArticleLink, ChooseAngle, EditOutline,
                             EditArticle, ArticleVersion, RestoreArticle, RewriteSection, GenerateArticle, EditArticleContext, CollectArticleContext, EditAngle, RegenerateAngles)

router = APIRouter(prefix='/api')


@router.get('/articles/{article_id}/events')
def article_events(article_id: str):
    from . import article_stream
    with db.connect() as c:worker.require(c,article_id)
    async def events():
        revision=None;checked=0;heartbeat=0;article=None
        while True:
            now=time.monotonic()
            if now-checked>=1:
                article=await asyncio.to_thread(worker.get,article_id);checked=now
            if not article or article['status'] not in worker.BUSY:
                yield 'event: complete\ndata: '+json.dumps({'status':article['status'] if article else 'missing'})+'\n\n'
                return
            value=article_stream.get(article_id)
            if value and value['revision']!=revision:
                revision=value['revision']
                yield 'event: snapshot\ndata: '+json.dumps(value,ensure_ascii=False)+'\n\n'
            elif now-heartbeat>=10:
                heartbeat=now;yield ': keepalive\n\n'
            await asyncio.sleep(.15)
    return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})


@router.get('/article-profile')
def profile_get():
    return db.article_profile()


@router.put('/article-profile')
def profile_save(body: ArticleProfile):
    with db.connect() as c:
        c.execute('UPDATE article_profiles SET value=%s,updated_at=%s WHERE id=1', (db.dump(body.model_dump()),db.now()))
    return body


@router.post('/article-sources/link')
def import_link(body: ArticleLink):
    try:
        item = sources.load_page(body.url)
    except httpx.HTTPError:
        raise ValueError('来源连接失败，请稍后再试或使用正文导入。') from None
    if not item.get('full_text'):
        raise ValueError('暂未取得完整正文，请复制文章正文后导入。')
    # A single explicit link imports one article, never follows an entire list.
    with db.connect() as c:
        _, ident = sources.save_item(c,item,urlsplit(body.url).hostname,'article-link')
        topic = db.topic(c.execute('SELECT * FROM topics WHERE id=%s',(ident,)).fetchone())
    if not topic.get('page_data',{}).get('full_text'):
        from .models import ImportPage
        sources.import_page(ImportPage(url=body.url,title=item['title'],text=item['text']))
        with db.connect() as c:
            topic = db.topic(c.execute('SELECT * FROM topics WHERE id=%s',(ident,)).fetchone())
    return topic


@router.get('/articles')
def list_articles():
    with db.connect() as c:
        rows = c.execute('SELECT id,request_id,status,stage,progress,mode,version,profile,input_data,angles,outline,document,error,note,created_at,updated_at FROM articles ORDER BY updated_at DESC LIMIT 100').fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        document=json.loads(item.pop('document') or 'null')
        outline=json.loads(item.pop('outline') or 'null')
        angles=json.loads(item.pop('angles') or 'null')
        inp=json.loads(item.pop('input_data'))
        item.pop('profile')
        item['title']=(document or outline or {}).get('title') or ((angles or {}).get('choices') or [{}])[0].get('title') or inp.get('brief') or '未命名文章'
        result.append(item)
    return result


@router.post('/articles',status_code=201)
def create(body: ArticleInput):
    return worker.create(body)


@router.get('/articles/{article_id}')
def detail(article_id: str):
    with db.connect() as c:
        article=worker.require(c,article_id)
        article['versions']=[{'version':r['version'],'stage':r['stage'],'at':r['at'],
                              'note':json.loads(r['payload']).get('note',''),
                              'restorable':any(json.loads(r['payload']).get(k) for k in ('angles','outline','document'))}
                             for r in c.execute('SELECT * FROM article_versions WHERE article_id=%s ORDER BY version DESC',(article_id,))]
    return article


@router.post('/articles/{article_id}/angle')
def choose(article_id: str, body: ChooseAngle):
    return worker.enqueue(article_id,body.version,'outline',choice=body.choice,replace_existing=body.replace_existing)


@router.put('/articles/{article_id}/context')
def edit_context(article_id:str,body:EditArticleContext):
    from . import article_context
    return article_context.save(article_id,body)


@router.put('/articles/{article_id}/angles')
def edit_angle(article_id:str,body:EditAngle):
    from . import article_angles
    return article_angles.revise(article_id,body)


@router.post('/articles/{article_id}/angles/regenerate')
def regenerate_angles(article_id:str,body:RegenerateAngles):
    from . import article_angles
    return article_angles.revise(article_id,body,generate=True)


@router.post('/articles/{article_id}/context/collect')
def collect_context(article_id:str,body:CollectArticleContext):
    from . import article_context
    return article_context.collect(article_id,body)


@router.put('/articles/{article_id}/outline')
def edit_outline(article_id: str, body: EditOutline):
    return worker.edit(article_id,body.version,outline_value=body.outline,replace_existing=body.replace_existing)


@router.post('/articles/{article_id}/generate')
def generate(article_id: str, body: GenerateArticle):
    return worker.enqueue(article_id,body.version,'article',replace_existing=body.replace_existing)


@router.put('/articles/{article_id}/document')
def edit_document(article_id: str, body: EditArticle):
    return worker.edit(article_id,body.version,document_value=body.document)


@router.post('/articles/{article_id}/check')
def check(article_id: str, body: ArticleVersion):
    return worker.enqueue(article_id,body.version,'check')


@router.post('/articles/{article_id}/illustrate')
def illustrate(article_id: str, body: ArticleVersion):
    return worker.enqueue(article_id,body.version,'illustrate')


@router.post('/articles/{article_id}/retry')
def retry(article_id: str, body: ArticleVersion):
    return worker.enqueue(article_id,body.version,'retry')


@router.post('/articles/{article_id}/rewrite')
def rewrite(article_id: str, body: RewriteSection):
    return worker.enqueue(article_id,body.version,'section',section=body.section,instruction=body.instruction,
                          target=body.target,paragraph=body.paragraph,document_value=body.document)


@router.post('/articles/{article_id}/restore')
def restore(article_id: str, body: RestoreArticle):
    return worker.restore(article_id,body.version,body.target_version)


@router.get('/articles/{article_id}/export')
def export(article_id: str, format: str='html', version: int | None=None, wechat: bool=False):
    with db.connect() as c:
        article=worker.require(c,article_id)
    if version is not None and version!=article['version']:
        raise HTTPException(409,'文章已更新，请刷新后导出当前版本。')
    if not article['document']:
        raise HTTPException(409,'正文尚未生成。')
    if article['status'] in worker.BUSY:
        raise HTTPException(409,'请等待当前步骤完成后导出。')
    if format=='bundle':
        return Response(article_export.bundle(article),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{article_id}.zip"'})
    if format not in ('html','markdown'):
        raise HTTPException(400,'仅支持 HTML、Markdown 或 ZIP。')
    # Standalone exports contain text; a portable ZIP carries image assets.
    value=article_export.markdown(article['document'],wechat=wechat) if format=='markdown' else '<!doctype html><meta charset="utf-8">'+article_export.html_body(article['document'],wechat=wechat)
    return Response(value,media_type='text/markdown' if format=='markdown' else 'text/html',
                    headers={'Content-Disposition':f'attachment; filename="{article_id}.{ "md" if format=="markdown" else "html"}"'})
