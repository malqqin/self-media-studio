import httpx
import pytest

from backend import ai, config, model_directory, model_library
from backend.models import ModelConnection
from backend.model_errors import ModelRequestError
from test_configuration import client, connection


def upstream(monkeypatch, payload=None, status=200, headers=None, raw=None):
    calls=[]
    original=httpx.Client
    def handler(request):
        calls.append(request)
        return httpx.Response(status,headers=headers,json=payload) if raw is None else httpx.Response(status,headers=headers,content=raw)
    monkeypatch.setattr(model_directory.httpx,'Client',lambda **kwargs:original(**kwargs,transport=httpx.MockTransport(handler)))
    return calls


def test_discover_readonly_normalizes_directory_and_does_not_generate(client,monkeypatch):
    calls=upstream(monkeypatch,{'data':[
        {'id':'deepseek-flash','name':'DeepSeek Flash','description':'擅长日常写作','input_modalities':['text','image'],'output_modalities':['text']},
        {'id':'gpt-image-1'},{'id':'sora-2'},{'id':'my-unknown-model'},
        {'id':'deepseek-flash'},None,{},
    ]})
    result=client.post('/api/models/discover',json=connection(model=''))
    assert result.status_code==200,result.text
    entries=result.json()['models']
    assert [v['model_type'] for v in entries]==['text','image','video','unknown']
    assert entries[0]['type_source']=='api' and entries[0]['description']=='擅长日常写作'
    assert entries[1]['type_source']=='inferred' and entries[1]['protocol']=='images'
    assert entries[2]['protocol']=='catalog'
    assert len(calls)==1 and calls[0].method=='GET' and str(calls[0].url)=='https://relay.example.com/v1/models'
    assert calls[0].headers['Authorization']=='Bearer test-secret-not-real'
    assert not (config.data_dir()/'model-library.json').exists()
    assert client.get('/api/activity').json()['ai_calls']==0


@pytest.mark.parametrize('ident,kind',[
    ('Qwen/Qwen2.5-VL-72B-Instruct','text'),('moonshot-v1-vision-preview','text'),
    ('Qwen/Qwen-Image','image'),('doubao-seedream-4-0','image'),('doubao-seedance-1','video'),
    ('Wan-AI/Wan2.2-T2V','video'),('THUDM/GLM-4','text'),('FunAudioLLM/CosyVoice2','audio'),
    ('BAAI/bge-m3','embedding'),('opaque-ep-123','unknown'),
])
def test_model_name_classification_does_not_confuse_input_and_output(ident,kind):
    assert model_directory.kind_for({'id':ident})[0]==kind


def test_explicit_output_type_takes_precedence_over_model_name():
    assert model_directory.kind_for({'id':'gpt-image-test','output_modalities':['text']})==('text','api')
    assert model_directory.kind_for({'id':'opaque','type':'text-to-video'})==('video','api')
    assert model_directory.normalize({'id':'wan-image','output_modalities':['image']},'qwen')['protocol']=='catalog'


def test_saved_key_reused_but_never_forwarded_to_changed_address(client,monkeypatch):
    body=connection(model_type='text',provider='custom',description='写作模型')
    saved=client.post('/api/models',json=body).json()
    calls=upstream(monkeypatch,{'data':[{'id':'writer','description':'echo test-secret-not-real'}]})
    value={**body,'api_key':''}
    path=f"/api/models/{saved['id']}/discover"
    response=client.post(path,json=value)
    assert response.status_code==200 and 'test-secret-not-real' not in response.text
    assert len(calls)==1
    response=client.post(path,json={**value,'base_url':'https://another.example.com/v1'})
    assert response.status_code==400 and len(calls)==1
    assert model_library.current(saved['id'])['model']=='custom-science'
    public=client.get('/api/models').json()[-1]
    assert public['model_type']=='text' and public['description']=='写作模型'
    assert 'api_key' not in public and 'protected_key' not in public


@pytest.mark.parametrize('status,expected',[(302,'重定向'),(401,'Key'),(403,'权限'),(404,'手动'),(429,'频繁'),(500,'500')])
def test_directory_failures_are_safe_and_not_retried(client,monkeypatch,status,expected):
    calls=upstream(monkeypatch,status=status,headers={'location':'https://other.example.com/models'},raw=b'test-secret-not-real')
    result=client.post('/api/models/discover',json=connection())
    assert result.status_code==400 and expected in result.text
    assert 'test-secret-not-real' not in result.text and len(calls)==1


@pytest.mark.parametrize('raw',[b'<html>not a directory</html>',b'{}',b'x'*4_000_001],ids=['html','invalid-schema','oversized'])
def test_invalid_or_oversized_responses_fail_cleanly(client,monkeypatch,raw):
    upstream(monkeypatch,raw=raw)
    assert client.post('/api/models/discover',json=connection()).status_code==400


def test_empty_and_partial_directories_are_explained(client,monkeypatch):
    upstream(monkeypatch,{'data':[]})
    result=client.post('/api/models/discover',json=connection()).json()
    assert result['models']==[] and '未返回' in result['message']


def test_catalog_models_saved_but_not_executed_as_text(client,monkeypatch):
    body=connection(model='sora-2',model_type='video',protocol='catalog')
    response=client.post('/api/models',json=body)
    assert response.status_code==201 and response.json()['ready'] is False
    assert response.json()['model_type']=='video'
    assert not model_library.ready(response.json()['id'])
    upstream(monkeypatch,{'data':[]})
    assert client.post('/api/models/test',json=body).status_code==400
    with pytest.raises(ModelRequestError,match='文本模型'):
        ai.request_structured(ModelConnection,'',{},'test','test',connection=body)
    assert client.get('/api/activity').json()['ai_calls']==0
    # Prevent an incompatible type/protocol combination from enabling text calls.
    assert client.post('/api/models',json={**body,'protocol':'responses'}).status_code==422


def test_default_connection_metadata_and_legacy_connections(client):
    body=connection(protocol='images',model='gpt-image-1')
    result=client.put('/api/models/default',json=body)
    assert result.status_code==200 and result.json()['model_type']=='image'
    assert client.get('/api/models').json()[0]['model_type']=='image'
    assert not client.get('/api/health').json()['ai_ready']
    result=client.put('/api/models/default',json={**body,'api_key':'','model':'sora-2','model_type':'video','protocol':'catalog'})
    assert result.status_code==200 and not result.json()['ready']
