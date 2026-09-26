import json
import os
import socket

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import ai, config, db, model_config, sources, worker
from backend.app import app
from backend.models import ModelConnection


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(config,'API_KEY','')
    monkeypatch.setattr(config,'MODEL','')
    monkeypatch.setattr(worker.executor,'submit',lambda *args:None)
    with TestClient(app) as client:yield client


def connection(**values):
    return {'name':'测试中转站','base_url':'https://relay.example.com/v1','model':'custom-science',
            'protocol':'chat_completions','output_mode':'json_object','api_key':'test-secret-not-real',**values}


def custom(**values):
    return {'id':'custom-science','name':'科学笔记','url':'https://science.example.com/feed',
            'kind':'auto','enabled':True,'category':'physics',**values}


def test_secret_is_private_persistent_and_immediately_effective(client):
    body=connection()
    response=client.put('/api/model-config',json=body)
    assert response.status_code==200,response.text
    assert body['api_key'] not in response.text
    assert response.json()['key_configured'] and response.json()['ready']
    assert client.get('/api/health').json()['model']=='custom-science'
    assert body['api_key'] not in client.get('/api/settings').text
    assert 'api_key' not in client.get('/api/model-config').json()
    assert model_config.current()['api_key']==body['api_key']
    if os.name=='nt':assert body['api_key'] not in (config.data_dir()/'model-config.json').read_text(encoding='utf-8')
    body.update(api_key='',model='changed-model')
    assert client.put('/api/model-config',json=body).status_code==200
    assert model_config.current()['api_key']=='test-secret-not-real'
    assert client.get('/api/health').json()['model']=='changed-model'
    body.update(base_url='https://another.example.com/v1')
    assert client.put('/api/model-config',json=body).status_code==400
    body.update(clear_key=True)
    assert client.put('/api/model-config',json=body).status_code==200
    assert not client.get('/api/health').json()['ai_ready']
    assert not model_config.current()['api_key']


def test_invalid_configuration_never_echoes_secret(client):
    secret='sensitive-key-do-not-echo'
    for body in [connection(api_key=secret,protocol='invalid'),connection(api_key=secret,base_url='https://user:pass@example.com/v1'),connection(api_key=secret,output_mode='invalid')]:
        result=client.put('/api/model-config',json=body)
        assert result.status_code==422 and secret not in result.text
        assert 'input' not in result.json()['detail'][0]
    normalized=ModelConnection(**connection(base_url='https://relay.example.com/v1/chat/completions/'))
    assert normalized.base_url=='https://relay.example.com/v1'


@pytest.mark.parametrize('protocol',['responses','chat_completions'])
@pytest.mark.parametrize('mode',['json_schema','json_object','text'])
def test_actual_adapter_protocol_payload_and_connection_test(client,monkeypatch,protocol,mode):
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        content='```json\n{"status":"ok"}\n```' if mode=='text' else '{"status":"ok"}'
        result={'choices':[{'finish_reason':'stop','message':{'content':content}}],'usage':{'prompt_tokens':3,'completion_tokens':4}} if protocol=='chat_completions' else {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':content}]}]}
        return httpx.Response(200,request=httpx.Request('POST',url),json=result)
    monkeypatch.setattr(ai.httpx,'post',post)
    body=connection(protocol=protocol,output_mode=mode)
    result=client.post('/api/model-config/test',json=body)
    assert result.status_code==200 and result.json()['ok'],result.text
    assert not (config.data_dir()/'model-config.json').exists() # testing doesn't save
    assert client.get('/api/activity').json()['ai_calls']==1
    url,kwargs=calls[0]
    assert url.endswith('/responses' if protocol=='responses' else '/chat/completions')
    assert kwargs['headers']['Authorization']=='Bearer test-secret-not-real'
    assert kwargs['follow_redirects'] is False
    payload=kwargs['json']
    if mode=='text':assert 'response_format' not in payload and 'text' not in payload
    else:
        fmt=payload['response_format'] if protocol=='chat_completions' else payload['text']['format']
        assert fmt['type']==mode


def test_test_failure_redacts_gateway_errors_and_does_not_retry(client,monkeypatch):
    calls=[]
    def post(url,**kwargs):
        calls.append(url)
        return httpx.Response(401,request=httpx.Request('POST',url),text='echo secret test-secret-not-real')
    monkeypatch.setattr(ai.httpx,'post',post)
    response=client.post('/api/model-config/test',json=connection())
    assert response.status_code==400 and '401' in response.text and 'test-secret-not-real' not in response.text
    assert len(calls)==1


def test_custom_feed_preview_save_collection_and_disable(client,monkeypatch):
    xml='''<feed xmlns="http://www.w3.org/2005/Atom"><title>Science</title><entry><title>粒子实验的新发现</title><link href="https://science.example.com/article"/><summary>'''+'这是关于粒子实验的公开资料，包含具体的实验方法和可验证的科学结果。'*5+'''</summary><updated>2026-09-22T00:00:00Z</updated></entry></feed>'''
    monkeypatch.setattr(sources,'download',lambda *args:xml.encode())
    preview=client.post('/api/sources/preview',json=custom())
    assert preview.status_code==200 and preview.json()['count']==1,preview.text
    assert client.get('/api/topics').json()==[]
    prefs=client.get('/api/settings').json();prefs.update(sources=[],custom_sources=[custom()])
    assert client.put('/api/settings',json=prefs).status_code==200
    assert client.get('/api/settings').json()['custom_sources'][0]['name']=='科学笔记'
    assert client.post('/api/collect').json()['added']==1
    assert client.post('/api/collect').json()['added']==0
    imported=next(t for t in client.get('/api/topics').json() if t['kind']=='live')
    assert imported['source']=='科学笔记' and imported['category']=='general'
    prefs['sources']=['nasa'];prefs['custom_sources'][0]['enabled']=False
    assert client.put('/api/settings',json=prefs).status_code==200
    assert [s['id'] for s in sources.enabled_sources()]==['nasa']


def test_article_list_and_autodiscovery(client,monkeypatch):
    body='<html><head><meta property="og:type" content="article"/></head><main><h1>Science article</h1><p>'+'The observation is a scientific measurement. '*20+'</p></main></html>'
    listing='<main><h2><a href="/one">First article</a></h2><h2><a href="/two">Second article</a></h2></main>'
    def download(url,*args):return (listing if url.endswith('/list') else body).encode()
    monkeypatch.setattr(sources,'download',download)
    response=client.post('/api/sources/preview',json=custom(url='https://science.example.com/list',kind='page'))
    assert response.status_code==200 and response.json()['count']==2,response.text
    response=client.post('/api/sources/preview',json=custom(url='https://science.example.com/one',kind='page'))
    assert response.json()['count']==1
    topic={'sources':[{'url':'https://science.example.com/one','publisher':'Custom'}]}
    assert 'scientific measurement' in sources.hydrate(topic)['sources'][0]['text']


def test_dns_redirect_and_private_network_boundaries(client,monkeypatch):
    from backend import network
    for url in ['file:///etc/passwd','http://127.0.0.1/','https://192.168.1.1/','https://[::1]/','https://example.com:8080/']:
        assert client.post('/api/sources/preview',json=custom(url=url)).status_code==422
    monkeypatch.setattr(network.socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError,match='内网'):network.public_addresses('https://science.example.com/')
    monkeypatch.setattr(network.socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.215.14',443))])
    seen=[]
    def send(self,request,**kwargs):
        seen.append(request)
        return httpx.Response(302,headers={'location':'http://127.0.0.1/private'},request=request)
    monkeypatch.setattr(httpx.Client,'send',send)
    with pytest.raises(ValueError):network.fetch_public('https://science.example.com/')
    assert len(seen)==1 and seen[0].url.host=='93.184.215.14'
    assert seen[0].headers['host']=='science.example.com' and seen[0].extensions['sni_hostname']=='science.example.com'


def test_saved_chat_connection_is_used_for_production_not_environment(client,monkeypatch):
    from backend.models import Script
    body=connection(output_mode='json_schema')
    assert client.put('/api/model-config',json=body).status_code==200
    from backend import seed
    seed.init()
    topic=worker.get_topic('sample-orbit');calls=[]
    def post(url,**kwargs):
        calls.append(url)
        assert kwargs['json']['model']=='custom-science'
        return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(topic['seed_script'])}}]})
    monkeypatch.setattr(ai.httpx,'post',post)
    result=ai.generate(topic,'test-production')
    assert isinstance(result,Script) and result.title_lines==topic['seed_script']['title_lines']
    assert calls==['https://relay.example.com/v1/chat/completions']


def test_auto_source_discovers_feed_and_skips_internal_entries(client,monkeypatch):
    landing='<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"/></head></html>'
    xml='<rss version="2.0"><channel><title>Science</title>'
    for url in ['https://science.example.com/article','http://127.0.0.1/private']:
        xml+='<item><title>Scientific observation</title><link>'+url+'</link><description>'+'A scientific measurement with detailed evidence. '*4+'</description></item>'
    xml+='</channel></rss>'
    calls=[]
    def download(url,*args):
        calls.append(url);return (xml if url.endswith('/feed.xml') else landing).encode()
    monkeypatch.setattr(sources,'download',download)
    result=client.post('/api/sources/preview',json=custom(url='https://science.example.com/'))
    assert result.status_code==200 and result.json()['count']==1,result.text
    assert calls==['https://science.example.com/','https://science.example.com/feed.xml']


def test_fresh_install_and_restart_have_no_topics_or_enabled_sources(client,monkeypatch):
    def unexpected(*args,**kwargs):raise AssertionError('No network or model call expected')
    monkeypatch.setattr(sources,'download',unexpected)
    monkeypatch.setattr(ai.httpx,'post',unexpected)
    prefs=client.get('/api/settings').json()
    assert prefs['sources']==[] and prefs['custom_sources']==[]
    assert prefs['production_mode']=='ai' and not prefs['schedule_enabled']
    assert client.get('/api/topics').json()==[]
    assert client.get('/api/jobs').json()==[]
    response=client.post('/api/collect')
    assert response.status_code==400 and '保存并采集' in response.text
    assert client.get('/api/activity').json()['sources']==[]
    client.__exit__(None,None,None)  # Stop the first scheduler before restarting.
    with TestClient(app) as restarted:
        assert restarted.get('/api/topics').json()==[]
        assert restarted.get('/api/settings').json()['sources']==[]
        with db.connect() as database:
            assert database.execute('SELECT count(*) FROM topics').fetchone()[0]==0


def test_source_settings_without_ai_preserve_preferences_and_execute_immediately(client,monkeypatch):
    prefs=client.get('/api/settings').json()
    prefs.update(account_name='科学采风',resolution='720p',schedule_time='09:12')
    assert client.put('/api/settings',json=prefs).status_code==200
    assert not client.get('/api/health').json()['ai_ready']
    assert client.put('/api/source-settings',json={'custom_sources':[custom()]}).status_code==200
    after=client.get('/api/settings').json()
    assert after['account_name']=='科学采风' and after['resolution']=='720p' and after['schedule_time']=='09:12'
    calls=[]
    def read(source):
        calls.append(source['url'])
        return {'items':[{'title':'New observation','url':'https://science.example.com/article','text':'Scientific observations with original evidence. '*5,'published_at':None,'full_text':True}],'note':'Collected from webpage.'}
    monkeypatch.setattr(sources,'read_source',read)
    assert client.post('/api/collect').json()['added']==1
    topics=client.get('/api/topics').json()
    assert len(topics)==1 and topics[0]['kind']=='live'
    assert topics[0]['source']=='科学笔记'
    client.__exit__(None,None,None)  # Stop the first scheduler before restarting.
    with TestClient(app) as restarted:
        assert restarted.get('/api/settings').json()['custom_sources'][0]['url']==custom()['url']
        assert restarted.get('/api/topics').json()==topics
    assert client.post('/api/collect').json()['added']==0
    assert calls==[custom()['url'],custom()['url']]
    cleared=client.put('/api/source-settings',json={'sources':[],'custom_sources':[]})
    assert cleared.status_code==200
    assert client.get('/api/topics').json()==topics
    assert client.post('/api/collect').status_code==400


def test_empty_sources_disable_schedule_but_preserve_other_settings(client):
    client.put('/api/model-config',json=connection())
    prefs=client.get('/api/settings').json()
    prefs.update(sources=['nasa'],schedule_enabled=True,schedule_time='23:59')
    assert client.put('/api/settings',json=prefs).status_code==200
    result=client.put('/api/source-settings',json={'sources':[],'custom_sources':[]})
    assert result.status_code==200 and not result.json()['schedule_enabled']
    assert result.json()['schedule_time']=='23:59'
    assert client.get('/api/health').json()['ai_ready']
    assert client.put('/api/settings',json={**result.json(),'schedule_enabled':True}).status_code==400


def test_invalid_source_config_does_not_replace_saved_sources(client):
    good={'sources':[],'custom_sources':[custom()]}
    assert client.put('/api/source-settings',json=good).status_code==200
    for invalid in [{'custom_sources':[custom(url='http://127.0.0.1/private')]},
                    {'custom_sources':[custom(),custom(id='custom-duplicate')]},
                    {'sources':['unknown']}]:
        assert client.put('/api/source-settings',json=invalid).status_code==422
        assert client.get('/api/settings').json()['custom_sources']==[{k:v for k,v in custom().items() if k!='category'}]


def test_legacy_topics_hidden_new_sample_jobs_rejected_old_jobs_preserved(client):
    from backend import seed
    seed.init()
    client.put('/api/model-config',json=connection())
    # Represent a pre-upgrade job without deleting its referenced source row.
    with db.connect() as database:database.execute("UPDATE topics SET kind='live' WHERE id='sample-orbit'")
    job=client.post('/api/jobs',json={'topic_id':'sample-orbit','mode':'ai','request_id':'legacy-saved-job'}).json()
    with db.connect() as database:
        database.execute("UPDATE jobs SET mode='sample',status='approved' WHERE id=%s",(job['id'],))
        database.execute("UPDATE topics SET kind='sample' WHERE id='sample-orbit'")
        prefs=client.get('/api/settings').json();prefs['production_mode']='sample'
        database.execute('UPDATE settings SET value=%s WHERE id=1',(db.dump(prefs),))
    assert client.get('/api/topics').json()==[]
    assert client.get('/api/settings').json()['production_mode']=='ai'
    assert client.get('/api/jobs').json()[0]['id']==job['id']
    assert client.get(f'/api/jobs/{job["id"]}').json()['status']=='approved'
    assert client.post('/api/jobs',json={'topic_id':'sample-webb','mode':'ai','request_id':'reject-old-topic'}).status_code==400
    assert client.post('/api/jobs',json={'topic_id':'sample-webb','mode':'sample','request_id':'reject-old-mode'}).status_code==422
    with db.connect() as database:assert database.execute('SELECT count(*) FROM topics').fetchone()[0]==3
