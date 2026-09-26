import html
import io
import json
import uuid
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from PIL import Image

from backend import db, pictures, unsplash
from test_platform import client


@pytest.mark.parametrize('provider,key,offset,payload',[
    ('bing','first','49','<a class="iusc" m="'+html.escape(json.dumps({'t':'City','murl':'https://example.com/city.jpg','purl':'https://example.com/city'}),quote=True)+'"></a>'),
    ('360','sn','48',{'list':[],'end':False}),
    ('baidu','pn','48',{'data':[{}],'displayNum':100}),
    ('commons','gsroffset','24',{'query':{},'continue':{'gsroffset':36}}),
    ('openverse','page','3',{'results':[],'page_count':4}),
    ('sogou','start','48','<script>window.__INITIAL_STATE__='+json.dumps({'searchList':{'query':'city','searchList':[{'title':'city','picUrl':'https://example.com/city.jpg','url':'https://example.com/city'}],'totalNum':100}})+'</script>'),
])
def test_provider_requests_real_page_offsets_and_preserves_more_before_filtering(monkeypatch,provider,key,offset,payload):
    calls=[]
    def fetch(url,**kwargs):
        calls.append(url)
        return (payload if isinstance(payload,str) else json.dumps(payload)).encode(),url
    monkeypatch.setattr(pictures,'fetch_public',fetch)
    result=getattr(pictures,'search_'+provider)('city',page=3)
    assert parse_qs(urlsplit(calls[0]).query)[key]==[offset]
    assert result.has_more


def test_unsplash_uses_official_page_and_total_without_extra_requests(monkeypatch):
    calls=[]
    def request(path,params):
        calls.append((path,params));return {'results':[],'total_pages':3}
    monkeypatch.setattr(unsplash,'request',request)
    assert unsplash.search('city',page=2).has_more
    assert not unsplash.search('city',page=3).has_more
    assert [params['page'] for _,params in calls]==[2,3]
    assert all(path=='search/photos' for path,_ in calls)


def test_pagination_keeps_full_provider_page_filters_and_reports_end(client,monkeypatch):
    calls=[]
    def search(query,page=1):
        calls.append((query,page))
        items=[{'title':'City' if page==1 else 'Coffee','url':f'https://example.com/{page}-{i}.jpg','page_url':'https://example.com/source','provider':'360 图片'} for i in range(24)]
        return pictures.SearchResults(items,page<3)
    monkeypatch.setattr(pictures,'search_360',search)
    monkeypatch.setattr(pictures,'search_bing',lambda *a,**kw:pytest.fail('unselected provider'))
    def get(page):return client.get('/api/pictures/search',params={'query':'city','sources':['360'],'details':True,'page':page})
    first=get(1).json();second=get(2).json();last=get(3).json()
    assert len(first['items'])==24  # Do not silently discard half a provider's page.
    assert first['sources']==['360'] and first['page']==1
    assert not second['items'] and second['has_more'] and second['providers'][0]['excluded']==24
    assert not last['has_more'] and last['page']==3
    assert calls==[('city',1),('city',2),('city',3)]
    assert get(0).status_code==422 and get(51).status_code==422


def test_provider_end_markers(monkeypatch):
    payloads=[{'list':[],'end':True},{'data':[],'displayNum':48},{'query':{}},{'results':[],'page_count':2},'<div id="b_results"></div>']
    def fetch(*args,**kwargs):
        payload=payloads.pop(0);return (payload if isinstance(payload,str) else json.dumps(payload)).encode(),''
    monkeypatch.setattr(pictures,'fetch_public',fetch)
    for provider in ('360','baidu','commons','openverse','bing'):
        assert not getattr(pictures,'search_'+provider)('city',page=2).has_more


def test_sogou_parses_public_page_data_filters_unsafe_results_and_imports_original(client,monkeypatch):
    row={'title':'AI 大模型 <b>架构</b>','oriPicUrl':'https://example.com/original.jpg','picUrl':'https://example.com/small.jpg',
         'thumbUrl':'https://i03piccdn.sogoucdn.com/thumb','url':'https://example.com/article','content_major':'神经网络的结构',
         'width':1200,'height':800,'author':'pic.sogou.com'}
    state={'searchList':{'query':'AI大模型','searchList':[row,row,{**row,'oriPicUrl':'http://127.0.0.1/private'},
        {**row,'title':'一杯咖啡','content_major':'咖啡','oriPicUrl':'https://example.com/coffee.jpg'}],'totalNum':60}}
    calls=[]
    def fetch(url,**kwargs):
        calls.append(url)
        return ('<script>window.__INITIAL_STATE__ = '+json.dumps(state)+';alert("never execute");</script>').encode(),url
    monkeypatch.setattr(pictures,'fetch_public',fetch)
    response=client.get('/api/pictures/search',params={'query':'AI大模型','sources':['sogou'],'page':2,'details':True})
    assert response.status_code==200,response.text
    result=response.json();assert len(result['items'])==1 and result['has_more']
    candidate=result['items'][0]
    assert candidate['url']==row['oriPicUrl'] and candidate['page_url']==row['url']
    assert candidate['title']=='AI 大模型 架构' and candidate['credit']==''
    assert candidate['license_verified'] is False and candidate['provider']=='搜狗图片'
    assert parse_qs(urlsplit(calls[0]).query)['start']==['24']
    image=io.BytesIO();Image.new('RGB',(600,400),'green').save(image,format='JPEG');downloads=[]
    monkeypatch.setattr(pictures.media,'fetch_image',lambda url:downloads.append(url) or image.getvalue())
    from backend.picture_models import PictureRequest
    value=pictures.produce(PictureRequest(request_id='sogou-import',action='import',candidate_id=candidate['id']),'sogou-import')
    assert downloads==[row['oriPicUrl']] and value['source_url']==row['url']


@pytest.mark.parametrize('payload',[
    '<html>请完成验证</html>','<script>window.__INITIAL_STATE__=not_json</script>',
    '<script>window.__INITIAL_STATE__='+json.dumps({'searchList':{'query':'coffee','searchList':[]}})+'</script>',
])
def test_sogou_does_not_report_blocked_or_wrong_topic_pages_as_no_matches(monkeypatch,payload):
    monkeypatch.setattr(pictures,'fetch_public',lambda *a,**k:(payload.encode(),''))
    with pytest.raises(ValueError):pictures.search_sogou('AI大模型')


def test_sogou_valid_empty_search_has_no_next_page(monkeypatch):
    data={'searchList':{'query':'city','searchList':[],'totalNum':0}}
    monkeypatch.setattr(pictures,'fetch_public',lambda *a,**k:(('<script>window.__INITIAL_STATE__='+json.dumps(data)+'</script>').encode(),''))
    result=pictures.search_sogou('city')
    assert result==[] and not result.has_more


def test_provider_errors_explain_network_and_blocking_without_treating_them_as_empty(client,monkeypatch):
    def timeout(*a,**k):raise httpx.ConnectTimeout('timeout')
    monkeypatch.setattr(pictures,'search_360',timeout)
    monkeypatch.setattr(pictures,'search_sogou',lambda q:(_ for _ in ()).throw(ValueError('搜狗图片限制了自动访问，请换一个来源。')))
    report=client.get('/api/pictures/search',params={'query':'city','sources':['360','sogou'],'details':True}).json()
    assert [p['status'] for p in report['providers']]==['error','error']
    assert '连接超时' in report['providers'][0]['message']
    assert '限制了自动访问' in report['providers'][1]['message']
    assert not report['items'] and not report['has_more']


def test_domestic_defaults_replace_implicit_legacy_defaults_but_keep_explicit_choices():
    from backend.picture_models import IllustrationSettings
    for value in ({},{'web_source':'licensed'},{'web_sources':[]}):
        assert IllustrationSettings.model_validate(value).selected_sources==['360','sogou','bing']
    explicit=IllustrationSettings.model_validate({'web_sources':['commons','openverse']})
    assert explicit.selected_sources==['360','sogou','bing']


def save_candidate(**changes):
    ident='pic-'+uuid.uuid4().hex
    item={'url':'https://example.com/original.jpg','preview_url':'https://example.com/thumbnail.jpg','provider':'必应图片',**changes}
    with db.connect() as c:c.execute('INSERT INTO picture_candidates(id,data,at) VALUES (%s,%s,%s)',(ident,db.dump(item),db.now()))
    return ident


def test_custom_site_search_keeps_scope_original_urls_pagination_and_user_isolation(client,monkeypatch):
    calls=[]
    def engine(query,page=1):
        calls.append((query,page))
        items=[{'title':'古城旅游','url':f'https://cdn.example.net/{i}.jpg','page_url':url,'provider':'必应图片'} for i,url in enumerate([
            'https://www.example.com/travel/pingyao','https://www.example.com/travel2/wrong',
            'https://www.example.com.evil.test/travel/wrong','https://outside.example/travel/wrong'])]
        return pictures.SearchResults(items,True)
    monkeypatch.setattr(pictures,'search_sogou',engine)
    monkeypatch.setattr(pictures,'search_360',lambda *a,**k:pytest.fail('Custom-only search must respect selection'))
    response=client.get('/api/pictures/search',params={'query':'古城','custom_sites':['www.example.com/travel?x=1#top'],'page':2,'details':True})
    assert response.status_code==200,response.text
    result=response.json();assert len(result['items'])==1 and result['page']==2
    assert result['items'][0]['url']=='https://cdn.example.net/0.jpg'
    assert calls==[('古城 site:www.example.com/travel',2)]
    assert result['custom_sites']==['https://www.example.com/travel'] and result['sources']==[]
    assert result['providers'][0]['name']=='自定义 · www.example.com/travel'


@pytest.mark.parametrize('site',['http://127.0.0.1/private','http://192.168.1.1','file:///etc/passwd','https://name:password@example.com','https://example.com:8080','https://example.com/ site:evil.com','https://example.com/%20site:evil.com'])
def test_custom_site_rejects_private_credentials_ports_and_query_injection(site):
    from backend.picture_models import IllustrationSettings
    with pytest.raises(ValueError):IllustrationSettings(custom_sites=[site])


def test_preview_uses_original_returns_small_jpeg_caches_and_does_not_import(client,monkeypatch):
    ident=save_candidate();calls=[];buffer=io.BytesIO()
    Image.new('RGB',(1280,720),'green').save(buffer,format='PNG')
    def fetch(url,limit,**kwargs):
        calls.append(url);assert limit==8_000_000 and kwargs['timeout']==6
        return buffer.getvalue(),url
    monkeypatch.setattr(pictures,'fetch_public',fetch)
    response=client.get(f'/api/pictures/candidates/{ident}/preview')
    assert response.status_code==200 and response.headers['content-type']=='image/jpeg'
    with Image.open(io.BytesIO(response.content)) as image:assert image.format=='JPEG' and image.size==(640,360)
    assert client.get(f'/api/pictures/candidates/{ident}/preview').content==response.content
    assert calls==['https://example.com/original.jpg']
    with db.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM assets').fetchone()[0]==0
        assert c.execute('SELECT COUNT(*) FROM picture_jobs').fetchone()[0]==0


def test_preview_can_try_thumbnail_and_failed_requests_can_be_retried(client,monkeypatch):
    ident=save_candidate();calls=[];available=False;buffer=io.BytesIO()
    Image.new('RGB',(500,500),'blue').save(buffer,format='JPEG')
    def fetch(url,*args,**kwargs):
        calls.append(url)
        if url.endswith('original.jpg'):raise httpx.ConnectError('unavailable')
        return (buffer.getvalue() if available else b'<html>access denied</html>'),url
    monkeypatch.setattr(pictures,'fetch_public',fetch)
    url=f'/api/pictures/candidates/{ident}/preview'
    assert client.get(url).status_code==502
    available=True
    assert client.get(url).status_code==200 and len(calls)==4


def test_preview_rejects_unknown_unsplash_and_private_urls_without_fetch(client,monkeypatch):
    monkeypatch.setattr(pictures,'fetch_public',lambda *a,**kw:pytest.fail('must not fetch'))
    monkeypatch.setattr(unsplash,'track_download',lambda *a:pytest.fail('preview must not track downloads'))
    assert client.get('/api/pictures/candidates/missing/preview').status_code==404
    ident=save_candidate(provider='Unsplash')
    assert client.get(f'/api/pictures/candidates/{ident}/preview').status_code==400
    ident=save_candidate(url='http://127.0.0.1/secrets',preview_url='http://192.168.0.1/secrets')
    assert client.get(f'/api/pictures/candidates/{ident}/preview').status_code==502
