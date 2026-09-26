import json
import httpx
import pytest
from urllib.parse import parse_qs, urlsplit
from backend import config, pictures, unsplash, media, article_worker, article_pictures
from backend.picture_models import PictureRequest
from test_platform import client, create, save, execute
from test_pictures import asset, illustrated


def photo(**changes):
    return {'id':'photo_123','alt_description':'Mountain lake in the Alps','description':None,
            'urls':{'regular':'https://images.unsplash.com/photo-123?ixid=tracking&w=1080','small':'https://images.unsplash.com/photo-123?ixid=tracking&w=400'},
            'links':{'html':'https://unsplash.com/photos/photo_123','download_location':'https://api.unsplash.com/photos/photo_123/download?ixid=tracking'},
            'user':{'name':'Test Photographer','links':{'html':'https://unsplash.com/@photographer'}},
            'tags':[{'title':'mountain'}],**changes}


def test_key_is_validated_protected_not_exposed_and_failed_replacement_keeps_old(client,monkeypatch):
    calls=[]
    def respond(path,params=None,*,access_key=None):
        calls.append((path,params,access_key))
        if access_key=='wrong-key-value':raise ValueError('Unsplash Access Key 无效')
        return {'results':[]}
    monkeypatch.setattr(unsplash,'request',respond)
    assert client.get('/api/picture-sources/unsplash').json()=={'key_configured':False}
    result=client.put('/api/picture-sources/unsplash',json={'access_key':'private-access-key'})
    assert result.json()=={'key_configured':True}
    assert calls[0][0]=='search/photos' and calls[0][1]['per_page']==1
    assert unsplash.key()=='private-access-key'
    raw=(config.data_dir()/'unsplash-connection.json').read_text()
    assert 'private-access-key' not in raw
    assert 'private-access-key' not in client.get('/api/picture-sources/unsplash').text
    assert client.put('/api/picture-sources/unsplash',json={'access_key':'wrong-key-value'}).status_code==400
    assert unsplash.key()=='private-access-key'
    assert client.put('/api/picture-sources/unsplash',json={'clear_key':True}).json()=={'key_configured':False}
    assert not unsplash.key()


def test_search_hotlinks_attribution_original_and_download_event_only_on_import(client,monkeypatch):
    calls=[]
    def respond(path,params=None,**kwargs):
        calls.append((path,params))
        if path=='search/photos':return {'results':[photo(),photo(id='premium',premium=True),photo(id='bad',links={'html':'https://evil.example/a','download_location':'https://evil.example/key'})]}
        return {'url':'https://images.unsplash.com/photo-123'}
    monkeypatch.setattr(unsplash,'request',respond)
    # Old saved candidates retain import and attribution support after removal.
    items=unsplash.search('mountain');assert len(items)==1
    from backend import db
    items[0]['id']='legacy-unsplash-candidate'
    with db.connect() as c:c.execute('INSERT INTO picture_candidates(id,data,at) VALUES (%s,%s,%s)',(items[0]['id'],db.dump(items[0]),db.now()))
    item=items[0]
    assert item['preview_url']==photo()['urls']['small'] and item['url']==photo()['urls']['regular']
    assert item['credit']=='Test Photographer' and item['license']=='Unsplash License'
    assert item['author_url'].startswith('https://unsplash.com/@photographer?')
    assert parse_qs(urlsplit(item['page_url']).query)['utm_source']==['self_media_studio']
    assert len(calls)==1
    original=asset();downloads=[]
    def download(url):downloads.append(url);return media.asset_path(original).read_bytes()
    monkeypatch.setattr(media,'fetch_image',download)
    imported=pictures.produce(PictureRequest(request_id='unsplash-import',action='import',candidate_id=item['id']),'job')
    assert calls[-1]==('photos/photo_123/download',{'ixid':'tracking'})
    assert downloads==[photo()['urls']['regular']]
    assert imported['credit']==item['credit'] and imported['source_url']==item['page_url']
    assert imported['provenance']['author_url']==item['author_url']


def test_retired_provider_is_removed_from_legacy_task_choices():
    from backend.picture_models import IllustrationSettings
    assert IllustrationSettings(web_sources=['unsplash','360']).selected_sources==['360']


@pytest.mark.parametrize('status,headers,message',[(401,{},'Access Key 无效'),(429,{},'额度'),(403,{'X-Ratelimit-Remaining':'0'},'额度'),(302,{'Location':'https://evil.example/'},'重定向')])
def test_errors_never_leak_key_or_follow_redirect(client,monkeypatch,status,headers,message):
    real_client=httpx.Client;calls=[]
    def respond(request):calls.append(request);return httpx.Response(status,headers=headers,text='private-access-key')
    monkeypatch.setattr(unsplash.httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(respond),**kw))
    with pytest.raises(ValueError,match=message) as err:unsplash.request('search/photos',{'query':'mountain'},access_key='private-access-key')
    assert 'private-access-key' not in str(err.value)
    assert len(calls)==1 and calls[0].url.host=='api.unsplash.com'
    assert 'private-access-key' not in str(calls[0].url)
    assert calls[0].headers['Authorization']=='Client-ID private-access-key'


def test_download_tracking_rejects_foreign_host_before_using_credentials(monkeypatch):
    monkeypatch.setattr(unsplash,'request',lambda *a,**k:pytest.fail('unsafe request'))
    with pytest.raises(ValueError,match='来源信息'):
        unsplash.track_download({'unsplash_id':'photo_123','download_location':'https://evil.example/photos/photo_123/download'})


def test_task_keeps_selected_sources_and_automatic_run_uses_them(client,illustrated,monkeypatch):
    task=save(client,illustrated,illustration={**illustrated['settings']['illustration'],'mode':'web','web_sources':['unsplash','360']})
    calls=[]
    candidate={'id':'candidate','title':'Pingyao city','provider':'Unsplash','license_verified':True}
    def search(query,source,sources):calls.append(sources);return [candidate]
    monkeypatch.setattr(pictures,'search',search)
    monkeypatch.setattr(pictures,'produce',lambda *a:pictures.record(asset(),{'kind':'web',**candidate}))
    run=execute(client,task,'automatic')
    assert calls and all(s==['360'] for s in calls)
    assert article_worker.get(run['content_id'])['document']['cover_asset_id']
