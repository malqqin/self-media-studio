import json
import socket
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from backend import ai,browser_fetch,config,db,sources,worker
from backend.app import app
from backend.models import Curation
from backend.web_extract import extract


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(config,'API_KEY','')
    monkeypatch.setattr(config,'MODEL','')
    monkeypatch.setattr(worker.executor,'submit',lambda *args:None)
    def unexpected(url):raise AssertionError('Unexpected browser network access in unit test')
    monkeypatch.setattr(sources,'render_public',unexpected)
    with TestClient(app) as client:yield client


def source(**values):
    return {'id':'custom-any','name':'资料来源','url':'https://content.example.com/page','kind':'auto','enabled':True,**values}


def article_html(title='城市文化活动',body=None):
    body=body or '本次社区文化活动展示了不同创作者的作品，访客可以阅读公开的活动安排与介绍。'*8
    return '<html><head><title>'+title+'</title></head><body><article><h1>'+title+'</h1><p>'+body+'</p><img data-src="/photo.jpg"/><a href="/reference">活动安排原文</a></article></body></html>'


def test_any_domain_and_category_free_configuration_collection_and_curation(client,monkeypatch):
    settings=client.get('/api/settings').json()
    assert 'interests' not in settings
    assert client.put('/api/source-settings',json={'custom_sources':[source()]}).status_code==200
    assert 'category' not in client.get('/api/settings').json()['custom_sources'][0]
    monkeypatch.setattr(sources,'download',lambda *args:article_html().encode())
    assert client.post('/api/collect').json()['added']==1
    topic=client.get('/api/topics').json()[0]
    assert topic['category']=='general' and topic['title']=='城市文化活动'
    assert topic['page_data']['images']==['https://content.example.com/photo.jpg']
    assert topic['page_data']['links'][0]['title']=='活动安排原文'
    assert topic['page_data']['full_text']
    def choose(model,instructions,data,*args,**kwargs):
        assert '无科学内容的公告' not in instructions and 'interests' not in data
        assert data['candidates'][0]['topic_id']==topic['id']
        return Curation(choices=[{'topic_id':topic['id'],'headline':'城市文化活动','angle':'观察不同创作者的活动安排','reason':'公开活动资料，有明确可追溯的来源','evidence':'本次社区文化活动展示了不同创作者的作品'}],note='')
    monkeypatch.setattr(ai,'request_structured',choose)
    assert client.post('/api/curate').json()['selected']==1
    # Old science-only settings no longer hide non-science content.
    with db.connect() as c:
        legacy=db.settings().model_dump();legacy['interests']=['physics']
        c.execute('UPDATE settings SET value=%s WHERE id=1',(db.dump(legacy),))
    assert len(client.get('/api/topics').json())==1


def test_wechat_challenge_falls_back_to_browser_and_snapshot_survives_production(client,monkeypatch):
    url='https://mp.weixin.qq.com/s/test-public-article'
    challenge='<html><body>环境异常 当前环境异常，完成验证后即可继续访问。去验证</body></html>'
    rendered='<h1 id="activity-name">企业平台观察</h1><div id="js_content"><p>'+'企业平台公开资料描述了对象、规则和动作的不同实现方式。'*10+'</p><img data-src="https://mmbiz.qpic.cn/example.jpg"/></div>'
    calls=[]
    monkeypatch.setattr(sources,'download',lambda *args:challenge.encode())
    monkeypatch.setattr(sources,'render_public',lambda value:(calls.append(value) or rendered,value))
    client.put('/api/source-settings',json={'custom_sources':[source(url=url)]})
    result=client.post('/api/collect').json()
    assert result['added']==1 and '浏览器加载' in result['reports'][0]['message']
    topic=client.get('/api/topics').json()[0]
    assert topic['title']=='企业平台观察' and topic['page_data']['method']=='browser'
    assert '环境异常' not in topic['sources'][0]['text']
    assert topic['media'][0]['url']=='https://mmbiz.qpic.cn/example.jpg'
    monkeypatch.setattr(sources,'download',lambda *args:pytest.fail('Must reuse captured page'))
    assert sources.hydrate(topic)['sources']==topic['sources']
    assert calls==[url]


@pytest.mark.parametrize(('body','code'),[
    ('当前环境异常，完成验证后即可继续访问。','verification_required'),
    ('请登录后查看，登录后阅读全文。','login_required'),
    ('该内容已被发布者删除。','unavailable')])
def test_access_pages_are_reported_and_never_inserted(client,monkeypatch,body,code):
    html='<body>'+body+'</body>'
    monkeypatch.setattr(sources,'download',lambda *args:html.encode())
    monkeypatch.setattr(sources,'render_public',lambda url:(html,url))
    client.put('/api/source-settings',json={'custom_sources':[source()]})
    result=client.post('/api/collect').json()
    assert result['added']==0 and result['reports'][0]['code']==code
    assert result['reports'][0]['url']==source()['url']
    assert client.get('/api/topics').json()==[]


def test_article_prefers_original_over_site_feed_and_keeps_short_text(client,monkeypatch):
    html='<head><link type="application/rss+xml" href="/feed"/></head><article><h1>网页内容</h1><p>这是一段简短但完整的网页内容，不应因为少于八十字就被拒绝采集。</p></article>'
    calls=[]
    monkeypatch.setattr(sources,'download',lambda url:(calls.append(url) or html.encode()))
    result=client.post('/api/sources/preview',json=source())
    assert result.status_code==200 and result.json()['count']==1
    assert result.json()['items'][0]['title']=='网页内容'
    assert calls==[source()['url']]


def test_structured_content_and_metadata_and_lists(client,monkeypatch):
    payload={'@graph':[{'@type':'Article','headline':'旅行计划','articleBody':'这是一份包含每日行程安排和交通说明的旅行计划。'*8}]}
    result=extract('<script type="application/ld+json">'+json.dumps(payload)+'</script>',source()['url'])
    assert result['title']=='旅行计划' and result['full_text'] and '每日行程' in result['text']
    listing='<main><h1>活动列表</h1><ul><li><a href="/one">城市文化活动</a></li><li><a href="/two">开放工作坊活动</a></li></ul></main>'
    monkeypatch.setattr(sources,'download',lambda url:(listing if url.endswith('/page') else article_html()).encode())
    response=client.post('/api/sources/preview',json=source())
    assert response.status_code==200 and response.json()['count']==2


def test_browser_mode_renders_even_when_static_text_exists(client,monkeypatch):
    def no_download(*args):pytest.fail('Browser mode must not use static fetch')
    monkeypatch.setattr(sources,'download',no_download)
    monkeypatch.setattr(sources,'render_public',lambda url:(article_html('动态内容'),url))
    response=client.post('/api/sources/preview',json=source(kind='browser'))
    assert response.status_code==200 and response.json()['items'][0]['title']=='动态内容'
    assert response.json()['items'][0]['method']=='browser'


def test_manual_import_retains_source_and_never_fetches_or_calls_ai(client,monkeypatch):
    monkeypatch.setattr(sources,'download',lambda *args:pytest.fail('Import must not fetch'))
    monkeypatch.setattr(ai,'request_structured',lambda *args:pytest.fail('Import must not call model'))
    body={'url':source()['url'],'title':'我能阅读的网页','text':'这段正文从浏览器复制而来，保留原文地址并在制作前核对。'*10}
    response=client.post('/api/sources/import',json=body)
    assert response.status_code==200 and response.json()['added']==1
    topic=client.get('/api/topics').json()[0]
    assert topic['sources'][0]['text']==body['text'] and topic['page_data']['method']=='manual'
    assert '手动导入' in topic['evidence_status']
    assert sources.hydrate(topic)['sources'][0]['url']==body['url']
    assert client.post('/api/sources/import',json=body).json()['added']==0
    assert client.post('/api/sources/import',json={**body,'text':' '} ).status_code==422
    assert client.post('/api/sources/import',json={**body,'url':'http://127.0.0.1/'}).status_code==422


def test_browser_proxy_rejects_private_destinations_before_connect(monkeypatch):
    monkeypatch.setattr(browser_fetch.socket,'create_connection',lambda *args,**kwargs:pytest.fail('Must reject before connecting'))
    for host,port in [('127.0.0.1',443),('localhost',443),('192.168.0.1',80),('public.example.com',8080)]:
        with pytest.raises(ValueError):browser_fetch.connect_public(host,port)
    monkeypatch.setattr(browser_fetch.socket,'getaddrinfo',lambda *args,**kwargs:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError,match='内网'):browser_fetch.connect_public('public.example.com',443)


def test_manual_import_can_complete_existing_summary(client):
    item={'url':source()['url'],'title':'网页摘要','text':'此前只有页面摘要，正文需在浏览器中才能阅读。','published_at':None,'full_text':False,'method':'rss'}
    with db.connect() as c:sources.save_item(c,item,'来源','custom-any')
    response=client.post('/api/sources/import',json={'url':source()['url'],'title':'完整网页','text':'这是用户从浏览器复制的完整文章正文，导入后无需再次请求原始页面。'*5})
    assert response.json()['updated'] and response.json()['added']==0
    topics=client.get('/api/topics').json()
    assert len(topics)==1 and topics[0]['page_data']['full_text'] and topics[0]['title']=='完整网页'


def test_real_browser_loads_javascript_and_blocks_private_subrequests(monkeypatch):
    # Serve a synthetic public origin through the proxy; no real website or account.
    seen=[];paths=[]
    html='''<html><body><main id="content">Loading</main><script>
      fetch('/data').then(r=>r.text()).then(text=>{document.getElementById('content').innerHTML='<article><h1>动态活动页面</h1><p>'+text+'</p></article>';});
      fetch('http://127.0.0.1/private').catch(()=>{});
    </script></body></html>'''
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            paths.append(self.path)
            content=('这是一段由浏览器执行脚本后加载的动态网页正文，描述公开活动和安排。'*5 if self.path=='/data' else html).encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def connect(host,port):
        seen.append((host,port))
        if host!='public.example.com' or port!=80:raise ValueError('Unexpected target')
        return socket.create_connection(('127.0.0.1',server.server_port),timeout=3)
    monkeypatch.setattr(browser_fetch,'connect_public',connect)
    monkeypatch.setattr(browser_fetch,'public_addresses',lambda url:['93.184.215.14'])
    try:
        html,url=browser_fetch.render_public('http://public.example.com/page')
        item=extract(html,url)
        assert item['title']=='动态活动页面' and '动态网页正文' in item['text']
        assert '/data' in paths and '/private' not in paths
        assert all(host not in ('localhost','127.0.0.1') for host,port in seen)
    finally:server.shutdown();server.server_close();thread.join(timeout=2)
