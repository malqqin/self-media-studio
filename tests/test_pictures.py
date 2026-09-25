import io
import base64
import httpx
import json
import uuid
import pytest
from PIL import Image
from backend import pictures, article_pictures, article_worker, article_ai, db, media
from backend.article_models import ArticleDocument
from backend.picture_models import PictureRequest
from test_platform import client, create, save, execute, model


def asset(color='green'):
    stream=io.BytesIO();Image.new('RGB',(800,600),color).save(stream,'JPEG')
    return media.store_asset(stream.getvalue(),color+'.jpg','本人绘制，可用于公众号','测试作者')


@pytest.fixture
def illustrated(client,monkeypatch):
    monkeypatch.setattr(pictures.executor,'submit',lambda *args:None)
    connection,_=model(client,protocol='images',model='image-test',image_edit=True)
    task=create(client)
    settings={**task['settings']['illustration'],'enabled':True,'mode':'ai','model_id':connection['id'],'count':1}
    task=save(client,task,brief='介绍古城建筑',article_plan={'mode':'fixed','avoid_days':30},illustration=settings)
    def planned(schema,instruction,data,*args,**kwargs):
        if schema is article_pictures.Match:return schema(candidate_id=data['candidates'][0]['id'])
        return schema(items=[{'slot':item['slot'],'query':'Pingyao city','prompt':'平遥古城的建筑插画，无文字','real_subject':True} for item in data['slots']])
    monkeypatch.setattr(article_pictures,'request_structured',planned)
    return task


def test_disabled_configuration_makes_no_picture_requests(client,monkeypatch):
    def forbidden(*args,**kwargs):pytest.fail('disabled pictures must not make requests')
    monkeypatch.setattr(article_pictures,'request_structured',forbidden)
    monkeypatch.setattr(pictures,'produce',forbidden)
    task=save(client,create(client),brief='如何观察古城建筑')
    assert task['settings']['illustration']['enabled'] is False
    run=execute(client,task,'automatic');article=article_worker.get(run['content_id'])
    assert run['status']=='needs_review'
    assert not article['document']['cover_asset_id']
    assert all(not s['asset_id'] for s in article['document']['sections'])


def test_manual_asset_configuration_applies_without_image_ai(client,monkeypatch):
    first,second=asset(),asset('blue')
    monkeypatch.setattr(pictures,'search',lambda *a:pytest.fail('manual search'))
    monkeypatch.setattr(article_pictures,'request_structured',lambda *a:pytest.fail('manual planning'))
    task=create(client);task=save(client,task,brief='观察城市建筑',illustration={'enabled':True,'mode':'manual','cover':True,'count':1,'asset_ids':[first['id'],second['id']]})
    run=execute(client,task,'automatic');doc=article_worker.get(run['content_id'])['document']
    assert doc['cover_asset_id']==first['id'] and doc['sections'][0]['asset_id']==second['id']
    assert doc['sections'][0]['caption']=='测试作者'


def test_ai_images_use_config_and_do_not_duplicate_existing_images(client,illustrated,monkeypatch):
    calls=[]
    def generated(body,ident):calls.append(body);return pictures.record(asset('blue' if len(calls)==1 else 'red'),{'kind':'ai','model':'image-test'})
    monkeypatch.setattr(pictures,'generate',generated)
    run=execute(client,illustrated,'automatic');article=article_worker.get(run['content_id'])
    assert len(calls)==2
    assert all(body.model_id==illustrated['settings']['illustration']['model_id'] and body.ratio=='landscape' for body in calls)
    assert article['document']['cover_caption']=='AI 生成示意图'
    assert article['document']['sections'][0]['asset_id']
    article_pictures.apply(article['id']);assert len(calls)==2
    exported=client.get(f"/api/articles/{article['id']}/export?format=bundle&version={article['version']}")
    assert exported.status_code==200


def test_pause_preserves_completed_images_and_retry_never_repeats_unknown_generation(client,illustrated,monkeypatch):
    illustrated=save(client,illustrated,illustration={**illustrated['settings']['illustration'],'failure':'pause'})
    calls=[]
    def generated(body,ident):
        calls.append(ident)
        if len(calls)>1:raise ValueError('图片服务响应超时，未自动重复请求。')
        return asset()
    monkeypatch.setattr(pictures,'generate',generated)
    run=execute(client,illustrated,'automatic');article=article_worker.get(run['content_id'])
    assert article['status']=='failed' and article['stage']=='illustrate'
    assert article['document']['cover_asset_id'] and not article['document']['sections'][0]['asset_id']
    article_worker.enqueue(article['id'],article['version'],'retry',submit=False);article_worker.run(article['id'])
    assert len(calls)==2
    article=article_worker.get(article['id']);assert '超时' in article['error']
    # Explicitly asking to fill missing images creates a new attempt, preserving the cover.
    monkeypatch.setattr(pictures,'generate',lambda *args:asset('blue'))
    article_worker.enqueue(article['id'],article['version'],'illustrate',submit=False);article_worker.run(article['id'])
    completed=article_worker.get(article['id']);assert completed['document']['sections'][0]['asset_id']
    assert completed['document']['cover_asset_id']==article['document']['cover_asset_id']


@pytest.mark.parametrize('failure,expected',[('skip',0),('ai',2)])
def test_web_miss_obeys_fallback_and_reports_missing_images(client,illustrated,monkeypatch,failure,expected):
    illustrated=save(client,illustrated,illustration={**illustrated['settings']['illustration'],'mode':'web','failure':failure})
    monkeypatch.setattr(pictures,'search',lambda *args:[])
    calls=[]
    def generated(*args):calls.append(1);return asset()
    monkeypatch.setattr(pictures,'generate',generated)
    run=execute(client,illustrated,'automatic');article=article_worker.get(run['content_id'])
    assert len(calls)==expected and article['status']=='needs_review'
    if failure=='skip':assert any('授权' in item['message'] for item in article['checks']['issues'])


def test_images_model_cannot_be_used_for_writing(client,illustrated):
    task=save(client,illustrated,model_id=illustrated['settings']['illustration']['model_id'])
    response=client.post('/api/tasks/'+task['id']+'/run',json={'version':task['version'],'action':'assist','request_id':str(uuid.uuid4())})
    assert response.status_code==400 and '文字模型' in response.text


def test_picture_search_filters_licenses_and_import_crop_are_immutable_idempotent(client,monkeypatch):
    monkeypatch.setattr(pictures.executor,'submit',lambda *args:None)
    def page(license):return {'title':'File:City.jpg','imageinfo':[{'url':'https://upload.wikimedia.org/city.jpg','descriptionurl':'https://commons.wikimedia.org/wiki/File:City.jpg','width':800,'height':600,'mime':'image/jpeg','extmetadata':{'LicenseShortName':{'value':license},'Artist':{'value':'<a>作者</a>'}}}]}
    monkeypatch.setattr(pictures,'fetch_public',lambda *args,**kwargs:(json.dumps({'query':{'pages':{'1':page('CC BY-SA 4.0'),'2':page('All rights reserved')}}}).encode(),''))
    monkeypatch.setattr(pictures,'search_openverse',lambda query:[])
    results=client.get('/api/pictures/search?query=city&source=licensed').json()
    assert len(results)==1 and results[0]['credit']=='作者'
    source=asset();monkeypatch.setattr(media,'fetch_image',lambda *args:media.asset_path(source).read_bytes())
    request={'request_id':'import-once','action':'import','candidate_id':results[0]['id']}
    job=client.post('/api/pictures',json=request).json();pictures.run(job['id'])
    ready=client.get('/api/pictures/'+job['id']).json();assert ready['status']=='ready'
    assert ready['asset']['provenance']['license']=='CC BY-SA 4.0'
    assert 'path' not in ready['asset']
    assert client.post('/api/pictures',json=request).json()['id']==job['id']
    assert client.post('/api/pictures',json={**request,'candidate_id':'different'}).status_code==409
    crop=PictureRequest(request_id='crop-once',action='crop',asset_id=ready['asset']['id'],width=.5,height=.5)
    cropped=pictures.produce(crop,'crop-test')
    assert cropped['id']!=ready['asset']['id']
    with Image.open(pictures.path(cropped['id'])) as img:assert img.size==(400,300)
    with Image.open(pictures.path(ready['asset']['id'])) as img:assert img.size==(800,600)
    assert cropped['provenance']['parent_asset_id']==ready['asset']['id']
    assert client.post('/api/pictures',json={**crop.model_dump(),'x':.9}).status_code==422


def test_locked_images_survive_rewrites_and_version_restore(client,illustrated,monkeypatch):
    monkeypatch.setattr(pictures,'generate',lambda *args:asset())
    run=execute(client,illustrated,'automatic');article=article_worker.get(run['content_id']);doc=article['document']
    doc['cover_image_locked']=True;doc['sections'][0]['image_locked']=True
    saved=article_worker.edit(article['id'],article['version'],document_value=ArticleDocument.model_validate(doc))
    article_worker.enqueue(article['id'],saved['version'],'article',replace_existing=True,submit=False)
    article_worker.run(article['id']);revised=article_worker.get(article['id'])
    assert revised['document']['cover_asset_id']==doc['cover_asset_id'] and revised['document']['cover_image_locked']
    assert revised['document']['sections'][0]['asset_id']==doc['sections'][0]['asset_id']
    assert revised['document']['sections'][0]['image_locked']
    restored=article_worker.restore(article['id'],revised['version'],saved['version'])
    assert restored['document']==doc


def test_image_transport_posts_generation_and_multipart_edit_without_retries(client,illustrated,monkeypatch):
    source=asset();content=pictures.path(source['id']).read_bytes();calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(content).decode()}]})
    real_client=httpx.Client
    monkeypatch.setattr(pictures.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(respond),**kwargs))
    ident=illustrated['settings']['illustration']['model_id']
    first=pictures.generate(PictureRequest(request_id='transport-one',action='generate',model_id=ident,prompt='古城屋檐插画',ratio='portrait'),'generate-job')
    second=pictures.generate(PictureRequest(request_id='transport-two',action='edit',model_id=ident,prompt='暖色光线',asset_id=first['id']),'edit-job')
    assert calls[0].url.path=='/v1/images/generations'
    assert json.loads(calls[0].content)=={'model':'image-test','prompt':'古城屋檐插画','size':'1024x1536','n':1}
    assert calls[1].url.path=='/v1/images/edits' and 'multipart/form-data' in calls[1].headers['content-type']
    assert b'name="image"' in calls[1].content and b'image/jpeg' in calls[1].content
    assert second['provenance']['parent_asset_id']==first['id']
    assert 'private' not in json.dumps(second)


def test_image_redirect_rejected_without_leaking_provider_response(client,illustrated,monkeypatch):
    calls=[];real_client=httpx.Client
    def respond(request):calls.append(request);return httpx.Response(302,headers={'Location':'https://other.example.com'},text='fake-private-key')
    monkeypatch.setattr(pictures.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(respond),**kwargs))
    with pytest.raises(ValueError,match='重定向'):
        pictures.generate(PictureRequest(request_id='redirect-test',action='generate',model_id=illustrated['settings']['illustration']['model_id'],prompt='插画'),'redirect-job')
    assert len(calls)==1


def test_bing_search_uses_chinese_query_validates_urls_and_imports_original(client,monkeypatch):
    import html
    from urllib.parse import parse_qs,urlsplit
    urls=[]
    first={'t':'平遥古城 城墙','murl':'https://photos.example.com/wall.jpg','turl':'https://ts1.mm.bing.net/thumb.jpg','purl':'https://travel.example.com/pingyao','desc':'平遥古城的城墙'}
    candidates=[first,first,{**first,'murl':'http://127.0.0.1/secret.jpg'},{**first,'murl':'https://photos.example.com/unsafe.jpg','purl':'javascript:alert(1)'}]
    content=''.join('<a class="iusc" m="'+html.escape(json.dumps(c),quote=True)+'"></a>' for c in candidates)
    def fetch(url,**kwargs):
        urls.append(url);assert kwargs['timeout']==6
        return content.encode(),url
    monkeypatch.setattr(pictures,'fetch_public',fetch)
    result=client.get('/api/pictures/search',params={'query':'平遥古城 城墙','details':True}).json()
    assert parse_qs(urlsplit(urls[0]).query)['q']==['平遥古城 城墙']
    assert len(result['items'])==1 and result['providers'][0]['status']=='success'
    candidate=result['items'][0]
    assert candidate['preview_url']==first['turl'] and candidate['url']==first['murl']
    assert candidate['license']=='授权待核对' and not candidate['license_verified']
    source=asset();downloaded=[]
    def download(url):downloaded.append(url);return media.asset_path(source).read_bytes()
    monkeypatch.setattr(media,'fetch_image',download)
    imported=pictures.produce(PictureRequest(request_id='bing-import',action='import',candidate_id=candidate['id']),'test-import')
    assert downloaded==[first['murl']]
    assert imported['source_url']==first['purl']
    assert imported['provenance']['license_verified'] is False


def test_licensed_provider_outage_falls_back_without_general_web_images(client,monkeypatch):
    monkeypatch.setattr(pictures,'search_bing',lambda q:pytest.fail('licensed mode must not search general web'))
    monkeypatch.setattr(pictures,'search_commons',lambda q:(_ for _ in ()).throw(httpx.ConnectTimeout('timeout')))
    good={'title':'Pingyao','url':'https://photos.example.com/city.jpg','foreign_landing_url':'https://photos.example.com/city','creator':'摄影作者','license':'by-sa','license_version':'4.0','license_url':'https://creativecommons.org/licenses/by-sa/4.0/','width':1000,'height':800}
    payload={'results':[good,{**good,'license':'by-nc'},{**good,'width':100,'height':100}]}
    monkeypatch.setattr(pictures,'fetch_public',lambda *a,**k:(json.dumps(payload).encode(),''))
    report=client.get('/api/pictures/search?query=Pingyao&source=licensed&details=true').json()
    assert [p['status'] for p in report['providers']]==['error','success']
    assert len(report['items'])==1 and report['items'][0]['license']=='CC BY-SA 4.0'
    assert report['items'][0]['license_verified']
    monkeypatch.setattr(pictures,'search_openverse',lambda q:(_ for _ in ()).throw(ValueError('offline')))
    report=client.get('/api/pictures/search?query=Pingyao&source=licensed&details=true').json()
    assert not report['items'] and all(p['status']=='error' for p in report['providers'])
    assert client.get('/api/pictures/search?query=Pingyao&source=licensed').status_code==400
    monkeypatch.setattr(pictures,'search_openverse',lambda q:[])
    assert client.get('/api/pictures/search?query=Pingyao&source=licensed').json()==[]
    assert client.get('/api/pictures/search?query=city&source=bad').status_code==422


def test_automatic_web_source_is_saved_used_and_keeps_origin(client,illustrated,monkeypatch):
    illustrated=save(client,illustrated,illustration={**illustrated['settings']['illustration'],'mode':'web','web_source':'web'})
    assert illustrated['settings']['illustration']['web_source']=='web'
    candidate={'id':'pic-web','title':'平遥古城','url':'https://photos.example.com/city.jpg','page_url':'https://travel.example.com/pingyao','license':'授权待核对','license_url':'','license_verified':False,'credit':''}
    queries=[]
    def search(query,source):queries.append((query,source));return [candidate]
    monkeypatch.setattr(pictures,'search',search)
    monkeypatch.setattr(pictures,'produce',lambda *args:pictures.record(asset(),{'kind':'web',**candidate}))
    run=execute(client,illustrated,'automatic');article=article_worker.get(run['content_id'])
    assert len(queries)==2 and all(source=='web' for _,source in queries)
    assert article['document']['cover_asset_id'] and article['document']['sections'][0]['asset_id']
    assert any('使用条件' in issue['message'] for issue in article['checks']['issues'])


def test_web_search_outage_uses_available_library(client,monkeypatch):
    monkeypatch.setattr(pictures,'search_bing',lambda q:(_ for _ in ()).throw(ValueError('search unavailable')))
    monkeypatch.setattr(pictures,'search_commons',lambda q:[])
    candidate={'url':'https://photos.example.com/photo.jpg','page_url':'https://photos.example.com/source','title':'City','license':'CC0','license_verified':True,'provider':'Openverse'}
    monkeypatch.setattr(pictures,'search_openverse',lambda q:[candidate])
    report=client.get('/api/pictures/search?query=City&source=web&details=true').json()
    assert [p['status'] for p in report['providers']]==['error','empty','success']
    assert report['items'][0]['provider']=='Openverse'
