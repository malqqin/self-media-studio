import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import config, db, worker
from backend.ai import validate_evidence
from backend.app import app
from backend.models import Script
from backend.short_render import render, run_command, probe_video
from backend.sources import safe_url


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(config,'API_KEY','test-workflow-key')
    monkeypatch.setattr(config,'MODEL','test-model')
    monkeypatch.setattr(worker.executor,'submit',lambda *args:None)
    with TestClient(app) as c:
        from backend import seed
        seed.init()  # Explicit test fixtures; the application never seeds topics.
        with db.connect() as database:database.execute("UPDATE topics SET kind='live'")
        yield c


def create(client,topic='sample-orbit',request='test-request-0001'):
    r=client.post('/api/jobs',json={'topic_id':topic,'mode':'ai','request_id':request})
    assert r.status_code==201,r.text
    return r.json()


def ready(job):
    topic=worker.get_topic(job['topic_id'])
    folder=config.DATA/'jobs'/job['id']/'v1';folder.mkdir(parents=True)
    for name in ['manifest.json','delivery.zip']:(folder/name).write_text('{}',encoding='utf-8')
    with db.connect() as c:
        c.execute('UPDATE jobs SET status=?,script=?,qa=?,artifacts=? WHERE id=?',
                  ('needs_review',db.dump(topic['seed_script']),db.dump({'passed':True}),
                   db.dump({'manifest':f'jobs/{job["id"]}/v1/manifest.json','bundle':f'jobs/{job["id"]}/v1/delivery.zip'}),job['id']))
    return topic['seed_script']


def test_idempotent_creation_without_daily_limit(client):
    with db.connect() as c:
        legacy=db.settings().model_dump();legacy.update(daily_limit=1,daily_ai_calls=1)
        c.execute('UPDATE settings SET value=? WHERE id=1',(db.dump(legacy),))
    first=create(client)
    again=create(client)
    assert first['id']==again['id']
    also=create(client,request='different-request-key')
    assert also['id']==first['id']
    response=client.post('/api/jobs',json={'topic_id':'sample-webb','mode':'ai','request_id':'second-new-job'})
    assert response.status_code==201
    assert len(client.get('/api/jobs').json())==2
    for number in range(6):
        with db.connect() as c:c.execute("UPDATE jobs SET status='needs_review' WHERE status='queued'")
        create(client,request=f'unlimited-job-{number}')
    assert client.get('/api/activity').json()['jobs_today']==8
    assert 'daily_limit' not in client.get('/api/settings').json()


def test_review_requires_checks_and_exact_version(client):
    job=create(client);ready(job);path=f'/api/jobs/{job["id"]}'
    assert client.get(path+'/files/bundle').status_code==409
    assert client.post(path+'/review',json={'decision':'approve','version':1}).status_code==400
    assert client.post(path+'/review',json={'decision':'approve','version':2,'facts_checked':True,'rights_checked':True}).status_code==409
    response=client.post(path+'/review',json={'decision':'approve','version':1,'facts_checked':True,'rights_checked':True})
    assert response.json()['status']=='approved'
    assert client.get(path+'/files/bundle').status_code==200


def test_script_revision_invalidates_exports_and_old_review(client):
    job=create(client);script=ready(job);path=f'/api/jobs/{job["id"]}'
    client.post(path+'/review',json={'decision':'approve','version':1,'facts_checked':True,'rights_checked':True})
    script['title']='卫星为什么留在轨道上？'
    response=client.put(path+'/script',json={'version':1,'script':script})
    assert response.status_code==200,response.text
    assert response.json()['version']==2 and response.json()['status']=='draft'
    assert response.json()['artifacts'] is None
    assert client.get(path+'/files/bundle').status_code==409
    assert client.post(path+'/review',json={'decision':'approve','version':1,'facts_checked':True,'rights_checked':True}).status_code==409
    retry=client.post(path+'/retry')
    assert retry.json()['status']=='queued'
    assert retry.json()['script']['title']==script['title']


def test_fabricated_evidence_rejected(client):
    job=create(client);script=ready(job)
    script['scenes'][0]['evidence']='This exact statement does not exist in the source.'
    response=client.put(f'/api/jobs/{job["id"]}/script',json={'version':1,'script':script})
    assert response.status_code==400
    assert worker.get_job(job['id'])['version']==1


def test_fixture_quotes_are_grounded(client):
    for topic in client.get('/api/topics').json():
        validate_evidence(Script.model_validate(topic['seed_script']),topic['sources'])


def test_settings_persist_and_ai_requires_configuration(client,monkeypatch):
    settings=client.get('/api/settings').json();settings['account_name']='宇宙手记';settings['schedule_time']='08:15'
    assert client.put('/api/settings',json=settings).status_code==200
    assert client.get('/api/settings').json()['account_name']=='宇宙手记'
    monkeypatch.setattr(config,'API_KEY','')
    settings.update(production_mode='ai',sources=['nasa'])
    assert client.put('/api/settings',json=settings).status_code==200
    settings['schedule_enabled']=True
    assert client.put('/api/settings',json=settings).status_code==400
    settings['schedule_time']='28:99'
    assert client.put('/api/settings',json=settings).status_code==422


def test_source_boundary_and_cross_site_guard(client):
    assert safe_url('https://science.nasa.gov/some-page/')
    for url in ['http://127.0.0.1/private','https://localhost/','https://www.nasa.gov:8000/','https://user:pass@www.nasa.gov/','file:///etc/passwd']:
        assert not safe_url(url)
    assert client.post('/api/collect',headers={'Origin':'https://attacker.example'}).status_code==403
    assert client.get('/api/health',headers={'Host':'malicious.example'}).status_code==403


def test_upload_requires_rights_and_valid_image(client):
    image=io.BytesIO();Image.new('RGB',(20,20),'green').save(image,format='PNG')
    assert client.post('/api/assets',files={'file':('x.png',image.getvalue(),'image/png')},data={'rights':'?'}).status_code==400
    upload=client.post('/api/assets',files={'file':('../../x.png',image.getvalue(),'image/png')},data={'rights':'本人原创拍摄','credit':'作者'})
    assert upload.status_code==201,upload.text
    asset=client.get('/api/assets').json()[0]
    assert 'path' not in asset
    assert len(list((config.DATA/'assets').glob('asset-*.jpg')))==1
    assert client.post('/api/assets',files={'file':('x.png',b'not image','image/png')},data={'rights':'本人原创拍摄'}).status_code==400


def test_restart_preserves_script_and_requires_retry(client):
    job=create(client);script=ready(job)
    with db.connect() as c:c.execute("UPDATE jobs SET status='running' WHERE id=?",(job['id'],))
    worker.recover()
    recovered=worker.get_job(job['id'])
    assert recovered['status']=='failed' and recovered['script']==script


def test_daily_run_claim_is_once_per_day(client,monkeypatch):
    from backend import scheduler
    settings=client.get('/api/settings').json();settings.update(schedule_enabled=True,schedule_time='00:00',sources=['nasa'])
    monkeypatch.setattr(scheduler,'collect',lambda:{'added':0})
    monkeypatch.setattr(scheduler,'curate',lambda:{'ids':['sample-orbit']})
    assert client.put('/api/settings',json=settings).status_code==200
    scheduler.tick();scheduler.tick()
    assert len(client.get('/api/jobs').json())==1
    assert len(client.get('/api/activity').json()['daily'])==1


def test_short_titles_and_fixed_settings(client):
    from pydantic import ValidationError
    script=worker.get_topic('sample-orbit')['seed_script']
    for lines in [['一','二','三'],['长'*29],['']]:
        with pytest.raises(ValidationError):Script.model_validate({**script,'title_lines':lines})
    settings=client.get('/api/settings').json()
    assert settings['duration_seconds']==10 and settings['audio_mode']=='silent'
    assert 'voice' not in settings
    for field,value in [('duration_seconds',60),('audio_mode','voice')]:
        assert client.put('/api/settings',json={**settings,field:value}).status_code==422


@pytest.mark.parametrize('mode',['images','video','mixed'])
def test_real_ten_second_render_and_video_upload(client,tmp_path,mode):
    import json
    import zipfile
    from backend.media import store_asset
    image=io.BytesIO();Image.new('RGB',(500,350),'#B37948').save(image,format='PNG')
    picture=store_asset(image.getvalue(),'test.png','测试原创图片','Test')
    video=tmp_path/'input.mp4'
    run_command([config.ffmpeg_path(),'-y','-f','lavfi','-i','testsrc2=size=320x240:rate=25',
                 '-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','1.2',
                 '-c:v','libx264','-threads','2','-c:a','aac',str(video)])
    response=client.post('/api/assets',files={'file':('test.mp4',video.read_bytes(),'video/mp4')},data={'rights':'测试原创视频'})
    assert response.status_code==201,response.text
    clip=response.json()
    assert clip['media_type']=='video/mp4' and 'path' not in clip
    assert client.get(f'/api/assets/{clip["id"]}/file',headers={'Range':'bytes=0-100'}).status_code==206
    with db.connect() as c:clip=dict(c.execute('SELECT * FROM assets WHERE id=?',(clip['id'],)).fetchone())
    script=Script.model_validate(worker.get_topic('sample-orbit')['seed_script'])
    if mode=='images':selected=[picture,picture,picture]
    elif mode=='video':selected=[clip]
    else:selected=[picture,clip,picture]
    script.scenes=[script.scenes[0].model_copy(update={'asset_id':a['id'],'clip_start':.4 if a['media_type'].startswith('video') else 0}) for a in selected]
    result=render(script,tmp_path/mode,'720p',assets={a['id']:a for a in selected})
    assert result.qa['passed'] and result.qa['duration_seconds']==10 and not result.qa['audio_present']
    assert probe_video(result.video)['width']==720
    manifest=json.loads(result.manifest.read_text(encoding='utf-8'))
    assert manifest['timeline'][0]['start']==0 and manifest['timeline'][-1]['end']==10
    assert len(manifest['title_lines'])==2
    with zipfile.ZipFile(result.video.parent/'delivery.zip') as bundle:
        assert not any(name.endswith(('.srt','.ass','.wav')) for name in bundle.namelist())
    assert client.post('/api/assets',files={'file':('invalid.mp4',b'not a video','video/mp4')},data={'rights':'测试原创视频'}).status_code==400


def test_ai_adapter_validates_and_tracks_calls_without_daily_limit(client,monkeypatch):
    from backend import ai
    import httpx
    monkeypatch.setattr(config,'API_KEY','test-key-not-real');monkeypatch.setattr(config,'MODEL','test-model')
    topic=worker.get_topic('sample-orbit')
    calls=[]
    def mocked(url,**kwargs):
        calls.append(kwargs['json'])
        return httpx.Response(200,request=httpx.Request('POST',url),json={'status':'completed','usage':{'input_tokens':100,'output_tokens':70},
          'output':[{'type':'message','content':[{'type':'output_text','text':db.dump(topic['seed_script'])}]}]})
    monkeypatch.setattr(ai.httpx,'post',mocked)
    with db.connect() as c:
        legacy=db.settings().model_dump();legacy.update(daily_limit=1,daily_ai_calls=1)
        c.execute('UPDATE settings SET value=? WHERE id=1',(db.dump(legacy),))
        c.executemany('INSERT INTO ai_usage(job_id,day,kind,status,at) VALUES (?,?,?,?,?)',
                      [('previous',db.day(),'script','received',db.now())]*25)
    generated=ai.generate(topic,'test-ai-job')
    assert generated.title==topic['title']
    assert calls[0]['text']['format']['strict'] is True
    assert calls[0]['text']['format']['schema']['additionalProperties'] is False
    assert ai.generate(topic,'test-ai-job').title==topic['title']
    assert len(calls)==2
    assert client.get('/api/activity').json()['ai_calls']==27
    with db.connect() as c:
        latest=c.execute('SELECT * FROM ai_usage ORDER BY id DESC LIMIT 1').fetchone()
    assert latest['status']=='received' and latest['input_tokens']==100 and latest['output_tokens']==70


def test_ai_rejects_unknown_curation_and_failed_fact_check(client,monkeypatch):
    from backend import ai
    from backend.models import Curation,FactCheck
    sample=worker.get_topic('sample-orbit')
    with db.connect() as c:
        c.execute("UPDATE topics SET kind='live' WHERE id=?",(sample['id'],))
    monkeypatch.setattr(ai,'request_structured',lambda *a:Curation(choices=[{'topic_id':'unknown','headline':'测试选题','angle':'足够长度的切入角度','reason':'足够长度的推荐理由','evidence':'This is an invalid evidence quote.'}],note=''))
    with pytest.raises(ValueError,match='未知'):ai.curate()
    assert worker.get_topic(sample['id'])['title']==sample['title']
    monkeypatch.setattr(ai,'request_structured',lambda *a:FactCheck(supported=False,issues=['把相关性说成了因果']))
    with pytest.raises(ValueError,match='事实复核'):ai.verify_script(Script.model_validate(sample['seed_script']),sample['sources'],'test')


def test_all_ai_entrypoints_work_after_previous_daily_ceiling(client,monkeypatch):
    from backend import ai
    from backend.models import ModelConnection
    import httpx
    with db.connect() as c:
        c.executemany('INSERT INTO ai_usage(job_id,day,kind,status,at) VALUES (?,?,?,?,?)',
                      [('previous',db.day(),'script','received',db.now())]*25)
    calls=[]
    answers={'connection_test':{'status':'ok'},'fact_check':{'supported':True,'issues':[]},'curation':{'choices':[],'note':'本次没有推荐'}}
    def post(url,**kwargs):
        kind=kwargs['json']['text']['format']['name'];calls.append(kind)
        return httpx.Response(200,request=httpx.Request('POST',url),json={'status':'completed',
            'output':[{'type':'message','content':[{'type':'output_text','text':db.dump(answers[kind])}]}]})
    monkeypatch.setattr(ai.httpx,'post',post)
    connection=ModelConnection(model='test-model',api_key='fake-key')
    assert ai.test_connection(connection)['ok']
    topic=worker.get_topic('sample-orbit')
    ai.verify_script(Script.model_validate(topic['seed_script']),topic['sources'],'test-job')
    assert ai.curate()['selected']==0
    assert calls==['connection_test','fact_check','curation']
    assert client.get('/api/activity').json()['ai_calls']==28


def test_old_limits_are_ignored_in_settings_and_saved_job_snapshots(client):
    from backend.models import Settings
    legacy=client.get('/api/settings').json()
    legacy.update(daily_limit=1,daily_ai_calls=1)
    response=client.put('/api/settings',json=legacy)
    assert response.status_code==200
    assert 'daily_limit' not in response.json() and 'daily_ai_calls' not in response.json()
    assert 'daily_ai_calls' not in Settings.model_validate(legacy).model_dump()
    assert create(client)['settings']==response.json()


def test_read_only_collection_deduplicates_and_handles_failure(client,monkeypatch):
    from backend import sources
    xml=b'''<rss version="2.0"><channel><title>NASA</title><item><title>A new orbit explanation</title><link>https://www.nasa.gov/example-test-article/</link><description>This official educational explanation describes an orbit and motion around a planet in enough detail for a source summary.</description><pubDate>Tue, 22 Sep 2026 07:00:00 GMT</pubDate></item></channel></rss>'''
    def download(url,limit=0):
        if 'esa.int' in url:raise TimeoutError('test timeout')
        return xml
    monkeypatch.setattr(sources,'download',download)
    assert client.put('/api/source-settings',json={'sources':['nasa','esa']}).status_code==200
    first=client.post('/api/collect').json();second=client.post('/api/collect').json()
    assert first['added']==1 and second['added']==0
    assert first['reports'][1]['status']=='error'
