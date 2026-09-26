import io
import json
import uuid
import zipfile
from backend.tenancy import ContextExecutor as ThreadPoolExecutor
from datetime import datetime

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend import config, db, task_engine, task_store, task_sources, editorial, model_library, article_worker, article_ai, image_studio, worker
from backend.app import app
from backend.article_models import Angles, ArticleOutline, ArticleDocument, ArticleCheck
from backend.task_models import TaskSettings


@pytest.fixture
def wechat(client,monkeypatch):
    from backend import wechat_accounts, media
    calls=[]
    def request(path,**kwargs):
        calls.append((path,kwargs))
        return {'stable_token':{'access_token':'private-access-token','expires_in':7200},
                'draft/count':{'total_count':0},'freepublish/batchget':{'total_count':0,'item':[]},
                'material/add_material':{'media_id':'cover-media'},'media/uploadimg':{'url':'https://mmbiz.qpic.cn/image.jpg'},
                'draft/add':{'media_id':'draft-media'},'freepublish/submit':{'publish_id':'publish-1'},
                'freepublish/get':{'publish_status':0,'article_id':'wx-article','article_detail':{'item':[{'article_url':'https://mp.weixin.qq.com/s/published'}]}}}[path]
    monkeypatch.setattr(wechat_accounts,'request',request)
    body={'name':'旅行公众号','appid':'wx1234567890abcdef','secret':'private-wechat-secret'}
    account=client.post('/api/wechat/accounts',json=body).json()
    assert client.post('/api/wechat/accounts/'+account['id']+'/test').status_code==200
    image=io.BytesIO();Image.new('RGB',(500,300),'green').save(image,'JPEG')
    asset=media.store_asset(image.getvalue(),'cover.jpg','本人绘制封面')
    prefs={'mode':'publish','account_id':account['id'],'cover_asset_id':asset['id'],'author':'旅行编辑','content_declaration':'none'}
    calls.clear()
    return prefs,calls,request


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    monkeypatch.setattr(config,'MODEL','test-only')
    monkeypatch.setattr(config,'API_KEY','test-only')
    for pool in (task_engine.executor,article_worker.executor,image_studio.executor,worker.executor):
        monkeypatch.setattr(pool,'submit',lambda *args:None)
    monkeypatch.setattr(article_ai,'angles',lambda *args:Angles(choices=[{'title':'从小任务开始','angle':'理解实际工作中的适用边界','reason':'帮助读者开始自己的尝试'}]))
    monkeypatch.setattr(article_ai,'outline',lambda *args:ArticleOutline(title='从小任务开始',angle='理解适用边界',sections=[{'heading':'先理解任务','points':'解释方法与局限'}]))
    monkeypatch.setattr(article_ai,'document',lambda *args:ArticleDocument(title='从小任务开始',titles=['从小任务开始'],summary='一次有边界的尝试',sections=[{'heading':'理解局限','paragraphs':['描述实际任务，再考虑工具是否合适。']}]))
    monkeypatch.setattr(article_ai,'check',lambda *args,**kwargs:ArticleCheck(issues=[],note='模拟检查完成，请人工核验。'))
    def editorial_response(schema,prompt,data,job_id,kind,**kwargs):
        if schema is editorial.SearchIntent:return editorial.SearchIntent(query=data['topic'],required_terms=[data['topic']])
        if schema is editorial.DailyTopic:return editorial.DailyTopic(subject='每日具体主题',brief='围绕'+(data['direction'] or '当前方向')+'写一篇完整文章',query='主题 资料',required_terms=['主题'])
        return editorial.RelevanceBatch(items=[{'index':v['index'],'relevant':True,'reason':'符合本次主题'} for v in data['candidates']])
    monkeypatch.setattr(editorial,'request_structured',editorial_response)
    with TestClient(app) as c:yield c


def create(client,kind='article',name='我的创作任务'):
    r=client.post('/api/tasks',json={'name':name,'kind':kind,'request_id':str(uuid.uuid4())})
    assert r.status_code==201,r.text
    return r.json()


def save(client,task,**patch):
    task['settings'].update(patch)
    r=client.put('/api/tasks/'+task['id'],json={k:task[k] for k in ('name','version','settings')})
    assert r.status_code==200,r.text
    return r.json()


def execute(client,task,action='assist',run_now=True):
    r=client.post('/api/tasks/'+task['id']+'/run',json={'version':task['version'],'action':action,'request_id':str(uuid.uuid4())})
    assert r.status_code==200,r.text
    if run_now:task_engine.run(r.json()['id'])
    return client.get('/api/tasks/'+task['id']).json()['runs'][0]


def model(client,**extra):
    body={'name':'写作连接','base_url':'https://relay.example.com/v1','model':'writer','protocol':'chat_completions','output_mode':'json_object','api_key':'fake-private-key',**extra}
    r=client.post('/api/models',json=body)
    assert r.status_code==201,r.text
    return r.json(),body


@pytest.mark.parametrize('angle',['短','详细内容'*180])
def test_manual_outline_can_generate_without_angle_choices(client,angle):
    task=create(client)
    run=execute(client,task,'blank')
    value=article_worker.get(run['content_id'])
    path='/api/articles/'+value['id']
    outline={**value['outline'],'angle':angle}
    edited=client.put(path+'/outline',json={'version':value['version'],'outline':outline,'replace_existing':True})
    assert edited.status_code==200,edited.text
    queued=client.post(path+'/generate',json={'version':edited.json()['version']})
    assert queued.status_code==200,queued.text
    article_worker.run(value['id'])
    result=article_worker.get(value['id'])
    assert result['document'] is not None
    assert result['status'] in ('needs_review','needs_revision')


def test_task_create_idempotency_versions_and_archive(client):
    body={'name':'每周观察','kind':'article','request_id':'create-idempotent'}
    first=client.post('/api/tasks',json=body).json()
    assert client.post('/api/tasks',json=body).json()['id']==first['id']
    assert client.post('/api/tasks',json={**body,'kind':'video'}).status_code==409
    saved=save(client,first,brief='如何记录自己的工作方法')
    assert saved['version']==2
    assert client.put('/api/tasks/'+first['id'],json={k:first[k] for k in ('name','version','settings')}).status_code==409
    path='/api/tasks/'+first['id']
    assert client.post(path+'/archive',json={'version':2}).json()['archived']
    assert client.post(path+'/run',json={'version':3,'action':'blank','request_id':'archived-run'}).status_code==400
    assert not client.post(path+'/archive',json={'version':3}).json()['archived']
    assert client.get(path).json()['version']==4


@pytest.mark.parametrize('kind',['article','video','image'])
def test_delete_task_keeps_work_in_recycle_bin_and_does_not_resurrect_on_restart(client,kind):
    task=create(client,kind);run=execute(client,task,'blank');path='/api/tasks/'+task['id']
    original=client.get(path).json()
    response=client.request('DELETE',path,json={'version':task['version']})
    assert response.status_code==200 and response.json()['deleted_at']
    assert all(t['id']!=task['id'] for t in client.get('/api/tasks').json())
    trashed=next(t for t in client.get('/api/tasks?deleted=true').json() if t['id']==task['id'])
    assert trashed['run_count']==1 and trashed['archived'] and trashed['version']==task['version']+1
    assert client.get(path).status_code==404
    assert client.post(path+'/run',json={'version':trashed['version'],'action':'blank','request_id':'deleted-new-run'}).status_code==404
    assert client.post(path+'/collect',json={'version':trashed['version']}).status_code==404
    assert client.post(path+'/archive',json={'version':trashed['version']}).status_code==404
    assert client.put(path,json={k:original[k] for k in ('name','version','settings')}).status_code==404
    task_store.init()
    assert client.get('/api/tasks').json()==[]
    assert len(client.get('/api/tasks?deleted=true').json())==1
    restored=client.post(path+'/restore',json={'version':trashed['version']})
    assert restored.status_code==200
    assert restored.json()['archived'] and not restored.json()['deleted_at']
    assert restored.json()['runs'][0]['content_id']==run['content_id']
    assert restored.json()['settings']==original['settings']
    assert client.get('/api/tasks?deleted=true').json()==[]


def test_delete_version_guards_and_create_request_does_not_revive_deleted_task(client):
    task=create(client);path='/api/tasks/'+task['id']
    current=save(client,task,brief='新内容')
    assert client.request('DELETE',path,json={'version':1}).status_code==409
    assert client.request('DELETE',path,json={'version':current['version']}).status_code==200
    assert client.post('/api/tasks',json={'name':task['name'],'kind':task['kind'],'request_id':task['request_id']}).status_code==404
    assert client.request('DELETE',path,json={'version':current['version']}).status_code==404
    assert client.post(path+'/restore',json={'version':current['version']}).status_code==409
    restored=client.post(path+'/restore',json={'version':current['version']+1}).json()
    assert client.post(path+'/restore',json={'version':restored['version']}).status_code==409


def test_deletion_stops_schedule_and_restore_requires_explicit_reactivation(client):
    task=save(client,create(client),brief='一天的工作记录',execution='automatic');path='/api/tasks/'+task['id']
    assert client.request('DELETE',path,json={'version':task['version']}).status_code==200
    task_engine.tick(datetime(2026,9,24,12,tzinfo=db.TZ))
    restored=client.post(path+'/restore',json={'version':task['version']+1}).json()
    task_engine.tick(datetime(2026,9,25,12,tzinfo=db.TZ))
    assert task_store.detail(task['id'])['runs']==[]
    client.post(path+'/archive',json={'version':restored['version']})
    task_engine.tick(datetime(2026,9,25,12,tzinfo=db.TZ))
    assert len(task_store.detail(task['id'])['runs'])==1


def test_delete_protects_queued_run_active_article_and_collection(client):
    task=create(client);path='/api/tasks/'+task['id'];run=execute(client,task,'blank',run_now=False)
    assert client.request('DELETE',path,json={'version':task['version']}).status_code==409
    task_engine.run(run['id']);content=task_store.detail(task['id'])['runs'][0]['content_id']
    with db.connect() as c:c.execute("UPDATE articles SET status='running' WHERE id=%s",(content,))
    assert client.request('DELETE',path,json={'version':task['version']}).status_code==409
    assert client.get('/api/tasks').json()[0]['is_running']
    with db.connect() as c:c.execute("UPDATE articles SET status='draft' WHERE id=%s",(content,))
    with task_store.collection(task['id'],task['version']):
        assert '采集' in client.request('DELETE',path,json={'version':task['version']}).json()['detail']
    assert client.request('DELETE',path,json={'version':task['version']}).status_code==200


def test_delete_waits_for_pending_image_render(client):
    task=create(client,'image');run=execute(client,task,'blank');path='/api/tasks/'+task['id']
    content=image_studio.get(run['content_id'])
    edited=client.put('/api/image-jobs/'+content['id'],json={k:content[k] for k in ('version','document','settings')})
    assert edited.status_code==200 and edited.json()['status']=='draft'
    assert client.get(path).json()['is_running']
    assert client.request('DELETE',path,json={'version':task['version']}).status_code==409
    image_studio.render(content['id'])
    assert client.request('DELETE',path,json={'version':task['version']}).status_code==200


def test_delete_waits_for_wechat_publication(client,wechat):
    prefs,_,_=wechat
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs)
    run=execute(client,task,'automatic');path='/api/tasks/'+task['id']
    assert run['status']=='publishing'
    assert client.get(path).json()['is_running']
    assert client.request('DELETE',path,json={'version':task['version']}).status_code==409
    assert not client.get(path).json()['deleted_at']


def test_deleted_task_cannot_retry_failed_run(client):
    task=create(client);path='/api/tasks/'+task['id'];run=execute(client,task,'blank',run_now=False)
    with db.connect() as c:c.execute("UPDATE task_runs SET status='failed' WHERE id=%s",(run['id'],))
    client.request('DELETE',path,json={'version':task['version']})
    assert client.post('/api/task-runs/'+run['id']+'/retry').status_code==404


def test_deletion_racing_with_scheduler_snapshot_is_ignored(client,monkeypatch):
    task=save(client,create(client),brief='工作记录',execution='automatic')
    snapshot=task_store.listing();task_store.delete(task['id'],task['version'])
    monkeypatch.setattr(task_store,'listing',lambda:snapshot)
    task_engine.tick(datetime(2026,9,24,12,tzinfo=db.TZ))
    with db.connect() as c:assert c.execute('SELECT count(*) FROM task_runs').fetchone()[0]==0


def test_named_models_are_private_persistent_and_context_isolated(client):
    a,body=model(client)
    b,_=model(client,name='另一连接',model='other',api_key='another-private-key')
    assert 'fake-private-key' not in client.get('/api/models').text
    assert model_library.current(a['id'])['api_key']=='fake-private-key'
    def resolve(ident):
        with model_library.use(ident):return model_library.connection()['model']
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(resolve,[a['id'],b['id']]))==['writer','other']
    assert model_library.connection()['model']=='test-only'
    path='/api/models/'+a['id']
    assert client.put(path,json={**body,'base_url':'https://elsewhere.example/v1','api_key':''}).status_code==400
    assert client.put(path,json={**body,'api_key':'','clear_key':True}).status_code==200
    assert not model_library.ready(a['id'])
    assert model_library.current(a['id'])['api_key']==''
    assert client.put(path,json={**body,'api_key':'new-key'}).json()['ready']


@pytest.mark.parametrize('kind',['article','video','image'])
def test_manual_blank_works_without_model_or_brief(client,monkeypatch,kind):
    monkeypatch.setattr(config,'API_KEY','');monkeypatch.setattr(config,'MODEL','')
    task=create(client,kind)
    run=execute(client,task,'blank')
    assert run['content_id'] and run['status'] in ('draft','needs_review'),run
    if kind=='article':assert article_worker.get(run['content_id'])['document']
    if kind=='video':assert worker.get_job(run['content_id'])['mode']=='manual'
    if kind=='image':assert image_studio.get(run['content_id'])['files']
    assert client.post('/api/tasks/'+task['id']+'/run',json={'version':task['version'],'action':'assist','request_id':'needs-model'}).status_code==400


def test_manual_assist_pauses_and_automatic_finishes_with_model_snapshot(client,monkeypatch):
    selected,_=model(client);seen=[]
    original=article_ai.angles
    def angles(*args):seen.append(model_library.connection()['model']);return original(*args)
    monkeypatch.setattr(article_ai,'angles',angles)
    task=save(client,create(client),brief='如何记录自己的工作方法',model_id=selected['id'])
    one=execute(client,task)
    assert one['status']=='needs_angle' and one['content_id']
    two=execute(client,task,'automatic')
    assert two['status']=='needs_review',two
    assert two['content_id']!=one['content_id']
    assert seen==['writer','writer']
    saved_article=article_worker.get(two['content_id'])
    assert saved_article['input_data']['_model_id']==selected['id']
    task=save(client,task,brief='改变后续任务方向')
    assert client.get('/api/tasks/'+task['id']).json()['runs'][0]['settings']['brief']=='如何记录自己的工作方法'
    assert 'private-key' not in client.get('/api/tasks').text


def test_active_execution_deduplicates_and_prevents_archive(client):
    task=save(client,create(client),brief='新的创作主题')
    body={'version':task['version'],'action':'assist','request_id':'same-run-request'}
    path='/api/tasks/'+task['id']
    first=client.post(path+'/run',json=body)
    assert first.status_code==200
    assert client.post(path+'/run',json=body).json()['id']==first.json()['id']
    assert client.post(path+'/run',json={**body,'request_id':'another-request'}).status_code==409
    assert client.post(path+'/archive',json={'version':task['version']}).status_code==409


def test_scheduler_independent_claims_weekdays_overlap_and_failed_day(client,monkeypatch):
    a=save(client,create(client,name='任务 A'),brief='生活与工作实践',execution='automatic',schedule={'time':'10:30','weekdays':[3]})
    b=save(client,create(client,name='任务 B'),brief='生活与工作实践',execution='automatic',schedule={'time':'10:30','weekdays':[3]})
    for hour,minute in [(9,0),(10,29)]:task_engine.tick(datetime(2026,9,23,hour,minute,tzinfo=db.TZ))
    assert not task_store.detail(a['id'])['runs']
    task_engine.tick(datetime(2026,9,24,12,tzinfo=db.TZ))
    assert not task_store.detail(a['id'])['runs']
    at=datetime(2026,9,23,10,30,tzinfo=db.TZ)
    task_engine.tick(at);task_engine.tick(at)
    assert len(task_store.detail(a['id'])['runs'])==len(task_store.detail(b['id'])['runs'])==1
    task_engine.tick(datetime(2026,9,30,12,tzinfo=db.TZ)) # ongoing previous execution defers a new day
    assert len(task_store.detail(a['id'])['runs'])==1
    for task in (a,b):task_engine.run(task_store.detail(task['id'])['runs'][0]['id'])
    monkeypatch.setattr(config,'API_KEY','')
    next_day=datetime(2026,9,30,12,tzinfo=db.TZ)
    task_engine.tick(next_day);task_engine.tick(next_day)
    for task in (a,b):
        runs=task_store.detail(task['id'])['runs'];assert len(runs)==2
        assert sum(r['status']=='failed' for r in runs)==1


def test_sources_search_custom_urls_and_successful_usage_are_per_task(client,monkeypatch):
    seen=[]
    def read(target):
        seen.append(target['url'])
        return {'items':[{'url':'https://example.com/article','title':'AI 新工具','text':'这是一段公开资讯的完整正文，足以作为自动任务的参考来源与线索。','full_text':True,'published_at':None,'images':[],'links':[],'method':'http'}]}
    monkeypatch.setattr(task_sources.sources,'read_source',read)
    settings=TaskSettings().materials.model_dump();settings.update(mode='reference',discover=True,query='AI 新工具',search_scope='web',urls=['https://example.com/feed'])
    task=save(client,create(client),materials=settings,article_plan={'mode':'fixed','avoid_days':30})
    first=execute(client,task,'automatic')
    assert first['status']=='needs_review',first
    assert len(first['reports'])==2 and 'bing.com/news/search?' in seen[0]
    assert task_store.detail(task['id'])['topics']
    second=execute(client,task,'automatic')
    assert second['status']=='failed' and '没有取得新的' in second['error']
    other=save(client,create(client),materials=settings,article_plan={'mode':'fixed','avoid_days':30})
    assert execute(client,other,'automatic')['status']=='needs_review'
    assert execute(client,task,'assist')['status']=='needs_angle' # explicit manual reuse is allowed


@pytest.mark.parametrize('ratio,size',[('portrait',(1080,1440)),('square',(1080,1080)),('landscape',(1440,810))])
def test_image_render_edit_version_and_export(client,ratio,size):
    task=create(client,'image');prefs=task['settings']['image'];prefs.update(ratio=ratio,format='poster')
    task=save(client,task,image=prefs)
    run=execute(client,task,'blank');ident=run['content_id'];value=image_studio.get(ident)
    assert value['status']=='needs_review',value
    file=client.get(f'/api/image-jobs/{ident}/files/0?version=1')
    assert file.status_code==200 and Image.open(io.BytesIO(file.content)).size==size
    value['document']['cards'][0]['body']='修改后的中文图文内容。'
    body={k:value[k] for k in ('version','document','settings')}
    edited=client.put('/api/image-jobs/'+ident,json=body)
    assert edited.status_code==200 and edited.json()['version']==2
    assert client.put('/api/image-jobs/'+ident,json=body).status_code==409
    assert client.get(f'/api/image-jobs/{ident}/files/0?version=1').status_code==409
    image_studio.render(ident)
    bundle=client.get(f'/api/image-jobs/{ident}/bundle?version=2')
    assert bundle.status_code==200
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert {'card-01.png','content.json','sources.json','settings.json'}<=set(archive.namelist())
        assert json.loads(archive.read('content.json'))['cards'][0]['body']=='修改后的中文图文内容。'


def test_image_rejects_missing_assets_and_reports_overflow(client):
    task=create(client,'image')
    run=execute(client,task,'blank');value=image_studio.get(run['content_id'])
    value['settings']['asset_id']='missing'
    assert client.put('/api/image-jobs/'+value['id'],json={k:value[k] for k in ('version','document','settings')}).status_code==400
    value['settings'].update(asset_id='',ratio='landscape')
    value['document']['cards'][0]['body']='每行\n'*100
    edited=client.put('/api/image-jobs/'+value['id'],json={k:value[k] for k in ('version','document','settings')})
    assert edited.status_code==200
    image_studio.render(value['id'])
    assert '超出' in image_studio.get(value['id'])['error']
    assert client.get(f'/api/image-jobs/{value["id"]}/bundle?version=2').status_code==409


def test_existing_content_migrates_once_and_recovers_interruption(client):
    from backend.article_models import ArticleInput
    old=article_worker.create(ArticleInput(mode='original',brief='历史内容',request_id='legacy-article-test'),submit=False)
    task_store.init();task_store.init()
    imported=[t for t in task_store.listing() if t['latest_run'] and t['latest_run']['content_id']==old['id']]
    assert len(imported)==1
    task=save(client,create(client),brief='新任务')
    run=execute(client,task,run_now=False)
    task_engine.persist(run['id'],status='running')
    task_engine.recover()
    assert task_store.detail(task['id'])['runs'][0]['status']=='failed'
    assert article_worker.get(old['id'])


def test_failed_automatic_article_resumes_saved_body(client,monkeypatch):
    task=save(client,create(client),brief='记录实践方法')
    monkeypatch.setattr(article_ai,'check',lambda *args,**kwargs:(_ for _ in ()).throw(ValueError('模拟检查失败')))
    run=execute(client,task,'automatic');article=article_worker.get(run['content_id'])
    assert run['status']=='failed' and article['document']
    monkeypatch.setattr(article_ai,'document',lambda *args:pytest.fail('must preserve generated body'))
    monkeypatch.setattr(article_ai,'check',lambda *args,**kwargs:ArticleCheck(issues=[],note='再次检查完成'))
    assert client.post('/api/task-runs/'+run['id']+'/retry').status_code==200
    task_engine.run(run['id'])
    updated=task_store.detail(task['id'])['runs'][0]
    assert updated['status']=='needs_review' and updated['content_id']==article['id']
    assert updated['error'] is None

def test_interrupted_automatic_task_keeps_resume_action_even_with_saved_angle(client):
    task=save(client,create(client),brief='实践记录')
    run=execute(client,task)
    assert run['status']=='needs_angle'
    task_engine.persist(run['id'],status='running')
    task_engine.recover()
    recovered=task_store.detail(task['id'])['runs'][0]
    assert recovered['status']=='failed' and recovered['stage']=='interrupted'
    assert recovered['error'] and recovered['content_id']==run['content_id']


def test_image_copy_uses_selected_model_and_reuses_persisted_image(client,monkeypatch):
    from backend.task_models import ImageDocument,ImageSettings
    selected,_=model(client,model='image-writer');calls=[]
    def copy(*args,**kwargs):
        calls.append(model_library.connection()['model'])
        return ImageDocument(title='卡片主题',cards=[{'heading':'从小事开始','body':'这是一段来自个人观察的简短说明。'}])
    monkeypatch.setattr(image_studio,'request_structured',copy)
    t=create(client,'image');prefs=t['settings']['image'];prefs['format']='poster'
    t=save(client,t,image=prefs,brief='周末生活观察',model_id=selected['id'])
    run=execute(client,t)
    assert run['status']=='needs_review' and calls==['image-writer']
    old=image_studio.get(run['content_id'])
    reused=image_studio.create(ImageSettings(), '不应重新生成',[],ident=old['id'])
    assert reused['id']==old['id'] and calls==['image-writer']

def test_recovery_queues_owned_articles_only_through_task_engine(client,monkeypatch):
    task=save(client,create(client),brief='实践记录')
    run=execute(client,task)
    article=article_worker.get(run['content_id'])
    article_worker.enqueue(article['id'],article['version'],'outline',choice=0,submit=False)
    task_engine.persist(run['id'],status='queued')
    dispatched=[]
    monkeypatch.setattr(article_worker.executor,'submit',lambda *args:dispatched.append(args))
    article_worker.recover()
    assert dispatched==[]
    monkeypatch.setattr(task_engine.executor,'submit',lambda *args:dispatched.append(args))
    task_engine.recover()
    assert len(dispatched)==1 and dispatched[0][1]==run['id']

def uploaded_image(client):
    buffer=io.BytesIO();Image.new('RGB',(720,900),'#7c996c').save(buffer,format='PNG')
    r=client.post('/api/assets',files={'file':('personal.png',buffer.getvalue(),'image/png')},data={'rights':'本人创作的测试素材','credit':'测试作者'})
    assert r.status_code==201,r.text
    return r.json()['id']


def test_landscape_card_with_image_and_footer_can_render(client):
    task=create(client,'image');prefs=task['settings']['image'];prefs.update(format='poster',ratio='landscape',asset_id=uploaded_image(client))
    task=save(client,task,image=prefs);run=execute(client,task,'blank');value=image_studio.get(run['content_id'])
    value['document']['cards'][0].update(heading='给自己一个周末',body='从熟悉的公园开始，留意身边的风景，也记录自己的观察。',footer='个人生活记录，仅供参考。')
    r=client.put('/api/image-jobs/'+value['id'],json={k:value[k] for k in ('version','document','settings')})
    assert r.status_code==200,r.text
    image_studio.render(value['id']);result=image_studio.get(value['id'])
    assert result['status']=='needs_review',result
    with zipfile.ZipFile(io.BytesIO(image_studio.bundle(value['id']))) as archive:
        assert json.loads(archive.read('image-rights.json'))['credit']=='测试作者'


def test_manual_video_task_renders_selected_asset_without_model(client,monkeypatch):
    monkeypatch.setattr(config,'API_KEY','');monkeypatch.setattr(config,'MODEL','')
    asset=uploaded_image(client);t=create(client,'video');prefs=t['settings']['video'];prefs.update(resolution='720p',asset_ids=[asset])
    t=save(client,t,video=prefs);run=execute(client,t,'blank');ident=run['content_id']
    assert worker.get_job(ident)['script']['scenes'][0]['asset_id']==asset
    worker.retry(ident,submit=False);worker.run(ident)
    job=worker.get_job(ident)
    assert job['status']=='needs_review',job['error']
    assert job['qa']['passed'] and abs(job['qa']['duration_seconds']-10)<.1
    assert not job['qa']['audio_present']
    assert client.get('/api/tasks/'+t['id']).json()['runs'][0]['status']=='needs_review'

def test_discovery_falls_back_to_web_search_when_news_redirects(client,monkeypatch):
    seen=[]
    def read(target):
        seen.append(target['url'])
        if '/news/' in target['url']:raise ValueError('没有找到 RSS/Atom 条目')
        return {'items':[{'url':'https://example.com/fallback','title':'个人实践资料','text':'这是用于测试备用网页搜索的公开资料正文，来源需要进一步人工核验。','published_at':None,'full_text':True,'method':'http'}]}
    monkeypatch.setattr(task_sources.sources,'read_source',read)
    t=create(client);m=t['settings']['materials'];m.update(mode='reference',discover=True,query='个人实践',search_scope='web')
    t=save(client,t,materials=m)
    result=client.post('/api/tasks/'+t['id']+'/collect',json={'version':t['version']})
    assert result.status_code==200,result.text
    assert len(result.json()['ids'])==1 and len(seen)==2
    assert 'cn.bing.com/search?' in seen[1]
    assert '公开网页搜索' in result.json()['reports'][0]['message']

def test_restart_resumes_pending_image_edits(client,monkeypatch):
    run=execute(client,create(client,'image'),'blank');value=image_studio.get(run['content_id'])
    value['document']['cards'][0]['body']='服务重启前保存的内容。'
    assert client.put('/api/image-jobs/'+value['id'],json={k:value[k] for k in ('version','document','settings')}).status_code==200
    queued=[];monkeypatch.setattr(image_studio.executor,'submit',lambda *args:queued.append(args))
    task_engine.recover()
    assert len(queued)==1 and queued[0][1]==value['id']
    queued[0][0](queued[0][1])
    assert image_studio.get(value['id'])['status']=='needs_review'

def test_collection_report_freezes_all_eight_results_and_used_subset(client,monkeypatch):
    def read(target):
        return {'items':[{'url':f'https://example.com/article-{i}','title':f'资料标题 {i}','text':f'第 {i} 篇公开资料的完整内容，记录个人实践的发现与注意事项。','published_at':None,'full_text':True,'method':'http'} for i in range(8)]}
    monkeypatch.setattr(task_sources.sources,'read_source',read)
    t=create(client);m=t['settings']['materials'];m.update(mode='reference',urls=['https://example.com/feed'])
    t=save(client,t,materials=m);run=execute(client,t)
    report=run['reports'][0]
    assert report['count']==len(report['items'])==8
    assert len(run['settings']['_used_topic_ids'])==5
    assert all(item['url'] and item['summary'] for item in report['items'])
    first=report['items'][0]
    with db.connect() as c:c.execute('UPDATE topics SET title=%s WHERE id=%s',('已改变的题目',first['topic_id']))
    saved=task_store.detail(t['id'])['runs'][0]['reports'][0]['items']
    assert saved[0]['title']==first['title']


def test_daily_planning_uses_history_and_freezes_per_run_topic(client,monkeypatch):
    from backend.editorial import DailyTopic
    calls=[]
    def plan(schema,prompt,data,*args,**kwargs):
        calls.append(data)
        subject='平遥古城' if not data['recent_topics'] else '云冈石窟'
        return DailyTopic(subject=subject,brief='介绍山西的'+subject+'与值得细看的地方',query=subject,required_terms=[subject])
    monkeypatch.setattr(editorial,'request_structured',plan)
    task=save(client,create(client),brief='山西旅游景点',article_plan={'mode':'direction','avoid_days':30})
    first=execute(client,task,'automatic')
    second=execute(client,task,'automatic')
    assert first['settings']['_editorial_plan']['subject']=='平遥古城'
    assert second['settings']['_editorial_plan']['subject']=='云冈石窟'
    assert calls[1]['recent_topics'][0]['subject']=='平遥古城'
    assert article_worker.get(second['content_id'])['input_data']['brief'].startswith('介绍山西的云冈石窟')
    assert task_store.detail(task['id'])['settings']['brief']=='山西旅游景点'
    assert second['settings']['brief']=='山西旅游景点'


def test_daily_planning_rejects_duplicate_and_retries_existing_plan(client,monkeypatch):
    task=save(client,create(client),brief='山西旅游景点')
    first=execute(client,task,'automatic')
    duplicate=execute(client,task,'automatic')
    assert duplicate['status']=='failed' and '重复' in duplicate['error']
    assert duplicate['content_id'] is None
    # A failed later stage must reuse the chosen subject, not choose another one on retry.
    other=save(client,create(client),brief='山西文化')
    monkeypatch.setattr(article_ai,'angles',lambda *args:(_ for _ in ()).throw(ValueError('temporary')))
    failed=execute(client,other,'automatic');saved_plan=failed['settings']['_editorial_plan']
    monkeypatch.setattr(editorial,'plan_article',lambda *args:pytest.fail('must reuse saved plan'))
    monkeypatch.setattr(article_ai,'angles',lambda *args:Angles(choices=[{'title':'晋祠','angle':'从古建筑认识晋祠','reason':'给出具体文化信息'}]))
    task_engine.retry(failed['id']);task_engine.run(failed['id'])
    retried=task_store.detail(other['id'])['runs'][0]
    assert retried['settings']['_editorial_plan']==saved_plan and retried['status']=='needs_review'


def test_search_filters_unrelated_results_and_does_not_reuse_stale_materials(client,monkeypatch):
    from backend import wechat_search
    items=[{'url':'https://mp.weixin.qq.com/s/'+str(i),'title':title,'text':text,'full_text':False,'published_at':db.now(),'method':'wechat-search','platform':'wechat','publisher':'测试公众号'} for i,(title,text) in enumerate([
        ('平遥古城怎么玩','从平遥古城的建筑与街巷开始，介绍旅途中的具体看点。'),
        ('分享是什么意思','这是一篇解释分享词义的字典，与山西旅游没有关系。'),
        ('平遥古城旅游公司更名','平遥古城旅游公司更名公告，与旅游景点的建筑介绍无关。')])]
    monkeypatch.setattr(wechat_search,'search',lambda query:{'items':items})
    monkeypatch.setattr('backend.network.fetch_public',lambda *args:(_ for _ in ()).throw(ValueError('verification')))
    def rank(schema,prompt,data,*args,**kwargs):
        assert len(data['candidates'])==3
        assert data['required_terms']==['平遥','古城']
        return editorial.RelevanceBatch(items=[{'index':0,'relevant':True,'reason':'介绍平遥古城游览看点'},{'index':1,'relevant':False,'reason':'词典释义，与旅游无关'},{'index':2,'relevant':False,'reason':'公司公告，不是景点介绍'}])
    monkeypatch.setattr(editorial,'request_structured',rank)
    t=create(client);m=t['settings']['materials'];m.update(discover=True,mode='reference',query='平遥 古城',search_scope='wechat')
    t=save(client,t,brief='介绍平遥旅游景点',materials=m)
    ids,reports=task_sources.collect(t['id'],TaskSettings.model_validate(t['settings']))
    assert len(ids)==1 and len(reports[0]['excluded'])==2
    item=reports[0]['items'][0]
    assert item['heat']=='unknown' and item['publisher']=='测试公众号' and not item['full_text']
    assert '暂未取得全文' in item['access_note']
    # A new empty search cannot silently fall back to previously collected material.
    monkeypatch.setattr(wechat_search,'search',lambda query:{'items':[]})
    settings=TaskSettings.model_validate(t['settings'])
    empty,report=task_sources.collect(t['id'],settings)
    assert empty==[] and '没有符合主题' in report[0]['message']
    assert task_sources.material_topics(t['id'],settings,empty)==[]


def test_reference_structure_requires_full_text_and_reaches_article_prompt(client,monkeypatch):
    topic=client.post('/api/sources/import',json={'url':'https://example.com/full','title':'平遥原文','text':'这是一篇完整的平遥介绍文章，开头从建筑出发，按主街和院落的次序组织内容。'}).json()['topic_id']
    t=create(client);m=t['settings']['materials'];m.update(mode='reference',topic_ids=[topic],reference_style='structure')
    t=save(client,t,brief='山西旅游',materials=m,article_plan={'mode':'fixed','avoid_days':30})
    run=execute(client,t)
    assert '叙事结构' in article_worker.get(run['content_id'])['profile']['preferences']
    with db.connect() as c:
        row=db.topic(c.execute('SELECT * FROM topics WHERE id=%s',(topic,)).fetchone())
        payload={k:v for k,v in row.items() if k not in ('id','title','category','kind','source','published_at','discovered_at','score')}
        payload['page_data']['full_text']=False;c.execute('UPDATE topics SET data=%s WHERE id=%s',(db.dump(payload),topic))
    assert task_sources.material_topics(t['id'],TaskSettings.model_validate(t['settings']),[topic])==[]


def test_search_date_window_rejects_unknown_dates(client,monkeypatch):
    from backend import wechat_search
    monkeypatch.setattr(wechat_search,'search',lambda query:{'items':[{'url':'https://mp.weixin.qq.com/s/old','title':'平遥古城','text':'介绍平遥古城的建筑与街巷文化，适合周末旅行阅读。','full_text':False,'published_at':None,'method':'wechat-search'}]})
    t=create(client);m=t['settings']['materials'];m.update(discover=True,query='平遥',search_scope='wechat',max_age_days=7)
    t=save(client,t,materials=m);ids,reports=task_sources.collect(t['id'],TaskSettings.model_validate(t['settings']))
    assert not ids and reports[0]['excluded'][0]['reason']=='没有可核验的发布时间'


def test_collection_filters_dates_before_semantics_and_keeps_ai_synonyms(client,monkeypatch):
    from backend import wechat_search
    from datetime import timedelta,timezone
    now=datetime.now(timezone.utc)
    items=[{'url':f'https://mp.weixin.qq.com/s/{i}','title':title,'text':text,'published_at':stamp,'full_text':True,'method':'wechat-search','publisher':'测试号'}
           for i,(title,text,stamp) in enumerate([
               ('旧的无关材料','这是一篇旅游介绍',(now-timedelta(days=8)).isoformat()),
               ('AI 推理模型升级','介绍新模型的推理能力以及应用中的限制',(now-timedelta(days=1)).isoformat()),
               ('旅游企业公告','假期业务安排',(now-timedelta(days=1)).isoformat()),
               ('未来文章','AI 技术进展',(now+timedelta(days=1)).isoformat()),
               ('日期不明的文章','AI 技术进展',None)])]
    monkeypatch.setattr(wechat_search,'search',lambda query:{'items':items,'pages_searched':2})
    def rank(schema,prompt,data,*args,**kwargs):
        assert [v['title'] for v in data['candidates']]==['AI 推理模型升级','旅游企业公告']
        assert data['required_terms']==['人工智能','技术热点']
        return editorial.RelevanceBatch(items=[{'index':0,'relevant':True,'reason':'介绍人工智能领域的新技术'},{'index':1,'relevant':False,'reason':'旅游企业安排，与 AI 技术无关'}])
    monkeypatch.setattr(editorial,'request_structured',rank)
    t=create(client);m=t['settings']['materials'];m.update(discover=True,search_scope='wechat',max_age_days=7)
    t=save(client,t,brief='AI相关的技术热点',materials=m)
    ids,reports=task_sources.collect(t['id'],TaskSettings.model_validate(t['settings']),intent={'query':'AI 技术热点','required_terms':['人工智能','技术热点']})
    r=reports[0]
    assert len(ids)==r['count']==1 and r['candidate_count']==5
    assert r['date_excluded_count']==3 and r['relevance_excluded_count']==1
    assert r['excluded'][0]['stage']=='date' and r['excluded'][0]['reason']=='超过设置的发布时间范围'
    assert r['excluded'][0]['published_at']==items[0]['published_at'] and r['excluded'][0]['url']==items[0]['url']
    assert r['date_filter']['max_age_days']==7 and r['date_filter']['to']==r['collected_at']
    assert datetime.fromisoformat(r['date_filter']['to'])-datetime.fromisoformat(r['date_filter']['from'])==timedelta(days=7)


def test_date_window_boundaries_are_inclusive_and_reject_future_and_unknown():
    from datetime import timedelta,timezone
    end=datetime(2026,9,23,15,0,tzinfo=timezone.utc);start=end-timedelta(days=7)
    for stamp in (start.isoformat(),end.isoformat(),'2026-09-16T23:00:00+08:00'):
        assert task_sources.date_rejection({'published_at':stamp},start,end)==''
    assert task_sources.date_rejection({'published_at':(start-timedelta(seconds=1)).isoformat()},start,end)=='超过设置的发布时间范围'
    assert task_sources.date_rejection({'published_at':(end+timedelta(seconds=1)).isoformat()},start,end)=='发布时间晚于本次采集时间'
    for stamp in (None,'invalid',123):
        assert task_sources.date_rejection({'published_at':stamp},start,end)=='没有可核验的发布时间'
    assert task_sources.date_rejection({'published_at':None},None,end)==''


@pytest.mark.parametrize('action',['blank','automatic'])
def test_article_tasks_inherit_saved_template_in_manual_and_automatic_work(client,action):
    t=create(client);profile={**t['settings']['article'],'template_id':'guide'}
    t=save(client,t,brief='从小任务开始安排一天',article=profile)
    run=execute(client,t,action)
    assert article_worker.get(run['content_id'])['document']['template_id']=='guide'
    assert run['settings']['article']['template_id']=='guide'
    t=save(client,task_store.detail(t['id']),article={**profile,'template_id':'opinion'})
    assert article_worker.get(run['content_id'])['document']['template_id']=='guide'


@pytest.mark.parametrize('action',['assist','automatic'])
def test_article_form_is_saved_in_task_run_and_content(client,monkeypatch,action):
    from backend.article_formats import ARTICLE_FORMATS
    calls=[];original=editorial.request_structured
    def plan(schema,prompt,data,*args,**kwargs):
        calls.append((prompt,data))
        return original(schema,prompt,data,*args,**kwargs)
    monkeypatch.setattr(editorial,'request_structured',plan)
    task=create(client);profile={**task['settings']['article'],'format':'旅行攻略'}
    task=save(client,task,brief='山西旅游景点',article=profile,execution='automatic' if action=='automatic' else 'manual')
    if action=='automatic':
        task_engine.tick(datetime(2026,9,24,12,tzinfo=db.TZ))
        queued=task_store.detail(task['id'])['runs'][0];task_engine.run(queued['id'])
        run=task_store.detail(task['id'])['runs'][0]
    else:run=execute(client,task,action)
    assert run['status']!='failed',run
    assert run['settings']['article']['format']=='旅行攻略'
    assert article_worker.get(run['content_id'])['profile']['format']=='旅行攻略'
    assert calls[0][1]['account']['format']=='旅行攻略'
    assert ARTICLE_FORMATS['旅行攻略']['guide'] in calls[0][0]
    save(client,task_store.detail(task['id']),article={**profile,'format':'案例分析'})
    assert article_worker.get(run['content_id'])['profile']['format']=='旅行攻略'
    assert task_store.detail(task['id'])['runs'][0]['settings']['article']['format']=='旅行攻略'


def test_full_article_date_cannot_replace_recent_search_date_with_old_content(client,monkeypatch):
    from backend import wechat_search,sources
    item={'url':'https://mp.weixin.qq.com/s/changed-date','title':'AI 新技术','text':'人工智能的模型研究和应用进展','published_at':db.now(),'full_text':False,'method':'wechat-search'}
    monkeypatch.setattr(wechat_search,'search',lambda query:{'items':[item]})
    monkeypatch.setattr('backend.network.fetch_public',lambda url:(b'<html></html>',url))
    monkeypatch.setattr('backend.web_extract.extract',lambda *args:{**item,'published_at':'2018-01-01T00:00:00Z','full_text':True})
    monkeypatch.setattr(sources,'check_page',lambda *args:None)
    t=create(client);m=t['settings']['materials'];m.update(discover=True,query='AI',search_scope='wechat',max_age_days=7)
    t=save(client,t,materials=m);ids,reports=task_sources.collect(t['id'],TaskSettings.model_validate(t['settings']))
    assert not ids and reports[0]['date_excluded_count']==1
    assert reports[0]['excluded'][0]['published_at']=='2018-01-01T00:00:00Z'
    assert '均未通过发布时间核验' in reports[0]['message']


def test_semantic_fallback_keeps_all_subject_constraints(client,monkeypatch):
    monkeypatch.setattr(model_library,'ready',lambda *args:False)
    items=[{'title':title,'text':'','url':'https://example.com/'+str(i)} for i,title in enumerate(['山西 AI 技术研究','山西 人工智能研究','山西 mail 配置','北京 AI 技术研究'])]
    kept,rejected=editorial.rank_candidates(items,TaskSettings(),{'query':'山西 AI','required_terms':['山西','人工智能']})
    assert [item['title'] for item in kept]==['山西 AI 技术研究','山西 人工智能研究']
    assert len(rejected)==2


def test_relevance_checks_small_batches_and_splits_truncated_output_once(client,monkeypatch):
    items=[{'title':f'AI 研究 {i}','text':'人工智能模型进展','url':f'https://example.com/{i}'} for i in range(11)]
    sizes=[]
    def rank(schema,prompt,data,*args,**kwargs):
        candidates=data['candidates'];sizes.append(len(candidates))
        if len(candidates)>3:raise editorial.ModelOutputLimitError('truncated')
        return editorial.RelevanceBatch(items=[{'index':i,'relevant':True,'reason':'人工智能技术进展'} for i in range(len(candidates))])
    monkeypatch.setattr(editorial,'request_structured',rank)
    kept,rejected=editorial.rank_candidates(items,TaskSettings(),{'query':'AI','required_terms':['人工智能']})
    assert sizes==[6,3,3,5,2,3] and not rejected
    assert [v['title'] for v in kept]==[v['title'] for v in items]


def test_relevance_failure_reports_unprocessed_items_instead_of_exclusions(client,monkeypatch):
    from backend import wechat_search
    items=[{'title':f'AI {i}','text':'人工智能模型进展','published_at':db.now(),'url':f'https://mp.weixin.qq.com/s/{i}'} for i in range(4)]
    monkeypatch.setattr(wechat_search,'search',lambda query:{'items':items})
    calls=[]
    def fail(*args,**kwargs):
        calls.append(1);raise editorial.ModelOutputLimitError('truncated')
    monkeypatch.setattr(editorial,'request_structured',fail)
    t=create(client);m=t['settings']['materials'];m.update(discover=True,query='AI',search_scope='wechat',max_age_days=7)
    t=save(client,t,materials=m);ids,reports=task_sources.collect(t['id'],TaskSettings.model_validate(t['settings']))
    assert len(calls)==2 and not ids and reports[0]['status']=='error'
    assert reports[0]['unprocessed_count']==4 and reports[0]['excluded']==[]


def test_wechat_search_paginates_deduplicates_and_stops_on_verification(monkeypatch):
    from backend import wechat_search
    from urllib.parse import urlencode,parse_qs,urlsplit
    calls=[]
    def listing(titles,page):
        rows=''.join(f'<li><h3><a href="/link?url={page}-{i}">{title}</a></h3><p class="txt-info">介绍 AI 技术进展</p><span class="all-time-y2">测试号</span></li>' for i,title in enumerate(titles))
        return '<ul class="news-list">'+rows+'</ul><a id="sogou_next" href="/weixin?'+urlencode({'type':2,'query':'AI 技术热点','page':page+1})+'">下一页</a>'
    def fetch(url):
        calls.append(url);page=int(parse_qs(urlsplit(url).query).get('page',['1'])[0])
        if page==3:return '用户您好，您的访问过于频繁','https://weixin.sogou.com/antispider/'
        return listing(['文章一','文章二'] if page==1 else ['文章一','文章三'],page),url
    monkeypatch.setattr(wechat_search,'fetch_public',fetch)
    result=wechat_search.search('AI 技术热点')
    assert len(calls)==3 and result['pages_searched']==2
    assert [i['title'] for i in result['items']]==['文章一','文章二','文章三']
    assert '验证' in result['search_note'] and '停止翻页' in result['search_note']
    # The first page gate is an error, not a successful empty search.
    monkeypatch.setattr(wechat_search,'fetch_public',lambda url:('','https://weixin.sogou.com/antispider/'))
    with pytest.raises(ValueError,match='验证'):wechat_search.search('AI')


@pytest.mark.parametrize('next_href',['/weixin?type=2&query=AI&page=1','https://other.example/weixin?type=2&query=AI&page=2'])
def test_wechat_search_does_not_follow_unsafe_or_repeating_pages(monkeypatch,next_href):
    from backend import wechat_search
    calls=[]
    def fetch(url):
        calls.append(url)
        return '<ul class="news-list"><li><h3><a href="/link?url=1">AI 新闻</a></h3><p class="txt-info">AI 新进展</p></li></ul><a id="sogou_next" href="'+next_href+'">下一页</a>',url
    monkeypatch.setattr(wechat_search,'fetch_public',fetch)
    assert len(wechat_search.search('AI')['items'])==1 and len(calls)==1


def test_wechat_search_never_requests_more_than_three_pages(monkeypatch):
    from backend import wechat_search
    calls=[]
    def fetch(url):
        page=len(calls)+1;calls.append(url)
        return f'<ul class="news-list"><li><h3><a href="/link?url={page}">AI 新闻{page}</a></h3><p class="txt-info">AI 新进展</p></li></ul><a id="sogou_next" href="/weixin?type=2&query=AI&page={page+1}">下一页</a>',url
    monkeypatch.setattr(wechat_search,'fetch_public',fetch)
    assert wechat_search.search('AI',max_pages=100)['pages_searched']==3 and len(calls)==3


def test_wechat_parser_retains_account_date_and_does_not_claim_popularity():
    from backend.wechat_search import parse_listing
    page='''<ul class="news-list"><li><h3><a href="/link?url=sample">平遥古城怎么玩</a></h3><p class="txt-info">山西平遥古城的街巷与建筑</p><span class="all-time-y2">文化旅行</span><script>document.write(timeConvert('1727000000'))</script></li></ul>'''
    items=parse_listing(page,'https://weixin.sogou.com/weixin?type=2')
    assert items[0]['publisher']=='文化旅行' and items[0]['published_at']
    assert items[0]['heat']=='unknown' and not items[0]['full_text']
    assert items[0]['url'].startswith('https://weixin.sogou.com/link?')
    with pytest.raises(ValueError,match='验证'):parse_listing('验证','https://weixin.sogou.com/antispider/')


def test_explicit_search_keeps_subject_without_requiring_exact_guide_phrase():
    settings=TaskSettings();settings.materials.query='平遥古城 游览攻略'
    intent=editorial.search_intent(settings)
    assert intent['query']=='平遥古城 游览攻略' and intent['required_terms']==['平遥古城']
    assert editorial.lexical_match({'title':'平遥古城旅游攻略','text':'介绍古城的建筑看点'},intent['required_terms'])
    assert not editorial.lexical_match({'title':'分享的意思','text':'词典释义'},intent['required_terms'])


def test_wechat_tracking_links_deduplicate_by_account_title_and_date(client):
    from backend.wechat_search import parse_listing
    page='<ul class="news-list"><li><h3><a href="/link?url=changing">平遥古城攻略</a></h3><p class="txt-info">平遥古城的建筑与文化看点，介绍旅途中的街巷。</p><span class="all-time-y2">文化旅行</span></li></ul>'
    item=parse_listing(page,'https://weixin.sogou.com/weixin?type=2')[0]
    with db.connect() as c:
        first,ident=task_sources.sources.save_item(c,item,'公众号','test')
        second,again=task_sources.sources.save_item(c,{**item,'url':'https://weixin.sogou.com/link?url=new-token'},'公众号','test')
    assert first==1 and second==0 and again==ident


def test_wechat_account_permissions_and_secrets(client,wechat):
    from backend import wechat_accounts
    prefs,calls,_=wechat
    value=client.get('/api/wechat/accounts').json()[0]
    assert value['publish_ready'] and value['draft_ready'] and value['secret_configured']
    assert 'private-wechat-secret' not in client.get('/api/wechat/accounts').text
    assert 'private-wechat-secret' not in (config.data_dir()/'wechat-accounts.json').read_text(encoding='utf-8')
    response=client.put('/api/wechat/accounts/'+prefs['account_id'],json={'name':'改名','appid':'wx1234567890abcdef','secret':''})
    assert response.status_code==200 and response.json()['publish_ready']
    assert wechat_accounts.current(prefs['account_id'])['secret']=='private-wechat-secret'
    response=client.put('/api/wechat/accounts/'+prefs['account_id'],json={'name':'其他账号','appid':'wxfedcba0987654321','secret':'new-secret'})
    assert response.status_code==400
    client.post('/api/wechat/accounts/'+prefs['account_id']+'/test')
    assert [path for path,_ in calls]==['draft/count','freepublish/batchget']
    response=client.put('/api/wechat/accounts/'+prefs['account_id'],json={'name':'新密钥','appid':'wx1234567890abcdef','secret':'changed-secret'})
    assert response.status_code==200 and not response.json()['publish_ready']


def test_wechat_auto_publish_waits_for_final_result_and_does_not_republish(client,wechat):
    from backend import wechat_delivery
    prefs,calls,_=wechat
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs,article_plan={'mode':'fixed','avoid_days':30},article={'template_id':'tech'})
    run=execute(client,task,'automatic')
    assert run['status']=='publishing',run
    assert run['publication']['publish_id']=='publish-1' and not run['publication']['article_url']
    assert [p for p,_ in calls]==['material/add_material','draft/add','freepublish/submit']
    payload=next(v['payload'] for p,v in calls if p=='draft/add')['articles'][0]
    assert payload['thumb_media_id']=='cover-media' and payload['author']=='旅行编辑'
    assert '<h2' in payload['content'] and '描述实际任务' in payload['content']
    assert 'data-article-template="tech"' in payload['content'] and '#2861c2' in payload['content']
    assert 'private-' not in client.get('/api/tasks/'+task['id']).text
    wechat_delivery.deliver(run['id'],article_worker.get(run['content_id']),TaskSettings.model_validate(task['settings']))
    assert [p for p,_ in calls].count('freepublish/submit')==1
    response=client.post('/api/task-runs/'+run['id']+'/publication/refresh')
    assert response.json()['article_url']=='https://mp.weixin.qq.com/s/published'
    final=task_store.detail(task['id'])['runs'][0]
    assert final['status']=='published'
    article=article_worker.get(run['content_id'])
    article_worker.edit(article['id'],article['version'],document_value=ArticleDocument.model_validate({**article['document'],'title':'后续本地修改'}))
    assert task_store.detail(task['id'])['runs'][0]['status']=='published'
    assert task_store.detail(task['id'])['runs'][0]['publication']['title']=='从小任务开始'
    assert client.post('/api/task-runs/'+run['id']+'/retry').status_code==409
    assert [p for p,_ in calls].count('freepublish/submit')==1


def test_wechat_draft_only_and_manual_assist_never_publish(client,wechat):
    prefs,calls,_=wechat
    task=save(client,create(client),brief='旅行文化',wechat_delivery={**prefs,'mode':'draft'},article_plan={'mode':'fixed','avoid_days':30})
    assist=execute(client,task,'assist')
    assert assist['status']=='needs_angle' and not calls
    run=execute(client,task,'automatic')
    assert run['status']=='wechat_draft' and run['publication']['media_id']=='draft-media'
    assert not any(path=='freepublish/submit' for path,_ in calls)


@pytest.mark.parametrize('phase',['draft/add','freepublish/submit'])
def test_wechat_unknown_submission_is_not_retried_after_restart(client,wechat,monkeypatch,phase):
    from backend import wechat_accounts,wechat_delivery
    prefs,calls,request=wechat
    def fail(path,**kwargs):
        if path==phase:
            calls.append((path,kwargs));raise wechat_accounts.WeChatError('网络中断',uncertain=True)
        return request(path,**kwargs)
    monkeypatch.setattr(wechat_accounts,'request',fail)
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs)
    run=execute(client,task,'automatic')
    assert run['status']=='failed' and run['publication']['status']=='uncertain'
    assert not run['publication']['can_retry']
    assert client.post('/api/task-runs/'+run['id']+'/retry').status_code==409
    task_engine.recover()
    assert wechat_delivery.get(run['id'])['status']=='uncertain'
    assert [p for p,_ in calls].count(phase)==1


def test_wechat_definite_rejection_reuses_existing_draft(client,wechat,monkeypatch):
    from backend import wechat_accounts
    prefs,calls,request=wechat
    def reject(path,**kwargs):
        if path=='freepublish/submit':
            calls.append((path,kwargs));raise wechat_accounts.WeChatError('今日额度已用完',code=45009)
        return request(path,**kwargs)
    monkeypatch.setattr(wechat_accounts,'request',reject)
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs)
    run=execute(client,task,'automatic')
    assert run['status']=='failed' and run['publication']['can_retry']
    monkeypatch.setattr(wechat_accounts,'request',request)
    assert client.post('/api/task-runs/'+run['id']+'/retry').status_code==200
    task_engine.run(run['id'])
    assert task_store.detail(task['id'])['runs'][0]['status']=='publishing'
    assert [p for p,_ in calls].count('draft/add')==1
    assert [p for p,_ in calls].count('freepublish/submit')==2


def test_wechat_poll_failure_recovers_without_resubmission(client,wechat,monkeypatch):
    from backend import wechat_accounts,wechat_delivery
    prefs,calls,request=wechat
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs)
    run=execute(client,task,'automatic')
    def poll_failure(path,**kwargs):
        if path=='freepublish/get':raise wechat_accounts.WeChatError('查询超时',uncertain=True)
        return request(path,**kwargs)
    monkeypatch.setattr(wechat_accounts,'request',poll_failure)
    result=wechat_delivery.refresh(run['id'])
    assert result['status']=='publishing' and '查询超时' in result['error']
    task_engine.recover()
    assert task_store.detail(task['id'])['runs'][0]['status']=='publishing'
    monkeypatch.setattr(wechat_accounts,'request',request)
    assert wechat_delivery.refresh(run['id'])['status']=='published'
    assert [p for p,_ in calls].count('freepublish/submit')==1


def test_wechat_platform_review_failure_cannot_resubmit(client,wechat,monkeypatch):
    from backend import wechat_accounts,wechat_delivery
    prefs,calls,request=wechat
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs)
    run=execute(client,task,'automatic')
    monkeypatch.setattr(wechat_accounts,'request',lambda path,**kw:{'publish_status':4} if path=='freepublish/get' else request(path,**kw))
    assert wechat_delivery.refresh(run['id'])['status']=='failed'
    assert client.post('/api/task-runs/'+run['id']+'/retry').status_code==409
    assert [p for p,_ in calls].count('freepublish/submit')==1


def test_wechat_error_checks_block_release_and_allow_corrected_article(client,wechat,monkeypatch):
    prefs,calls,_=wechat
    monkeypatch.setattr(article_ai,'check',lambda *a,**kw:ArticleCheck(issues=[{'severity':'error','section':0,'message':'存在事实错误'}],note='需要修订'))
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs)
    run=execute(client,task,'automatic')
    assert run['status']=='failed' and '未自动发布' in run['error'] and not calls
    value=article_worker.get(run['content_id'])
    monkeypatch.setattr(article_ai,'check',lambda *a,**kw:ArticleCheck(issues=[],note='已完成检查'))
    article_worker.enqueue(value['id'],value['version'],'check',submit=False);article_worker.run(value['id'])
    client.post('/api/task-runs/'+run['id']+'/retry');task_engine.run(run['id'])
    assert task_store.detail(task['id'])['runs'][0]['status']=='publishing'


def test_scheduled_collection_switch_and_no_results(client,monkeypatch):
    from backend import wechat_search
    calls=[]
    monkeypatch.setattr(wechat_search,'search',lambda q:(calls.append(q) or {'items':[]}))
    task=save(client,create(client),brief='平遥文化',execution='automatic',schedule={'time':'09:00','weekdays':[3]},article_plan={'mode':'fixed','avoid_days':30})
    task_engine.tick(datetime(2026,9,23,9,0,tzinfo=db.TZ))
    run=task_store.detail(task['id'])['runs'][0];task_engine.run(run['id'])
    assert not calls and task_store.detail(task['id'])['runs'][0]['status']=='needs_review'
    task=save(client,task,materials={**task['settings']['materials'],'discover':True,'query':'平遥文化'})
    task_engine.tick(datetime(2026,9,30,9,0,tzinfo=db.TZ))
    run=next(r for r in task_store.detail(task['id'])['runs'] if r['status']=='queued');task_engine.run(run['id'])
    result=next(r for r in task_store.detail(task['id'])['runs'] if r['id']==run['id'])
    assert calls==['平遥文化'] and result['status']=='failed' and not result['content_id']
    task_engine.tick(datetime(2026,9,30,9,30,tzinfo=db.TZ))
    assert len(task_store.detail(task['id'])['runs'])==2


def test_wechat_request_methods_unicode_and_redacted_errors(monkeypatch):
    import httpx
    from backend import wechat_accounts
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={'total_count':0} if request.method=='GET' else {'media_id':'one'})
    original=httpx.Client
    monkeypatch.setattr(wechat_accounts.httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(handler)))
    wechat_accounts.request('draft/count',token='token-secret')
    wechat_accounts.request('draft/add',token='token-secret',payload={'title':'中文文章'})
    assert seen[0].method=='GET' and not seen[0].content
    assert '中文文章' in seen[1].content.decode() and r'\u4e2d' not in seen[1].content.decode()
    def bad(request):return httpx.Response(400,text='token-secret')
    monkeypatch.setattr(wechat_accounts.httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(bad)))
    with pytest.raises(wechat_accounts.WeChatError) as error:wechat_accounts.request('draft/add',token='token-secret')
    assert error.value.uncertain and 'token-secret' not in str(error.value)


@pytest.mark.parametrize('diagnostic,expected',[
    ('invalid ip 8.8.4.4, not in whitelist rid: private-token','8.8.4.4'),
    ('invalid ip ::ffff:8.8.4.4, not in whitelist','8.8.4.4'),
    ('invalid ip 2001:4860:4860::8888, not in whitelist','2001:4860:4860::8888'),
    ('invalid ip 127.0.0.1, not in whitelist',None),
    ('invalid ip private-token, not in whitelist',None),
    ('private-token 8.8.4.4',None),
])
def test_wechat_whitelist_error_extracts_only_public_ip(monkeypatch,diagnostic,expected):
    import httpx
    from backend import wechat_accounts
    assert wechat_accounts.whitelist_ip(diagnostic)==expected
    original=httpx.Client
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'errcode':40164,'errmsg':diagnostic}))
    monkeypatch.setattr(wechat_accounts.httpx,'Client',lambda **kw:original(**kw,transport=transport))
    with pytest.raises(wechat_accounts.WeChatError) as error:
        wechat_accounts.request('stable_token',payload={'secret':'private-token'})
    message=str(error.value)
    assert '40164' in message and 'private-token' not in message and 'rid:' not in message
    if expected:assert '当前出口 IP：'+expected+'。' in message
    else:assert '当前出口 IP：' not in message


def test_wechat_denied_permission_prevents_enabling_publish(client,wechat,monkeypatch):
    from backend import wechat_accounts
    prefs,calls,request=wechat
    def denied(path,**kwargs):
        if path=='freepublish/batchget':raise wechat_accounts.WeChatError('未授权',code=48001)
        return request(path,**kwargs)
    monkeypatch.setattr(wechat_accounts,'request',denied)
    value=client.post('/api/wechat/accounts/'+prefs['account_id']+'/test').json()['account']
    assert value['draft_ready'] and not value['publish_ready']
    task=create(client);task['settings'].update(execution='automatic',brief='旅行文化',wechat_delivery=prefs)
    response=client.put('/api/tasks/'+task['id'],json={k:task[k] for k in ('name','version','settings')})
    assert response.status_code==400 and '检测公众号连接' in response.text
    task['settings']['wechat_delivery']['mode']='draft'
    assert client.put('/api/tasks/'+task['id'],json={k:task[k] for k in ('name','version','settings')}).status_code==200


@pytest.mark.parametrize('reuse_cover_in_section',[False,True])
def test_wechat_uploads_inline_images_before_draft_and_preserves_snapshot(client,wechat,monkeypatch,reuse_cover_in_section):
    from bs4 import BeautifulSoup
    prefs,calls,_=wechat
    monkeypatch.setattr(article_ai,'check',lambda *a,**kw:ArticleCheck(issues=[{'severity':'error','section':0,'message':'待编辑'}],note='待检查'))
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs)
    run=execute(client,task,'automatic')
    article=article_worker.get(run['content_id']);doc=article['document']
    doc['cover_asset_id']=prefs['cover_asset_id']
    doc['sections'][0].update(asset_id=prefs['cover_asset_id'] if reuse_cover_in_section else '',caption='摄影作者 · 授权待核对')
    article=article_worker.edit(article['id'],article['version'],document_value=ArticleDocument.model_validate(doc))
    monkeypatch.setattr(article_ai,'check',lambda *a,**kw:ArticleCheck(issues=[],note='检查完成'))
    article_worker.enqueue(article['id'],article['version'],'check',submit=False);article_worker.run(article['id'])
    client.post('/api/task-runs/'+run['id']+'/retry');task_engine.run(run['id'])
    run=task_store.detail(task['id'])['runs'][0]
    assert run['status']=='publishing',run
    assert [p for p,_ in calls]==['material/add_material',*(['media/uploadimg'] if reuse_cover_in_section else []),'draft/add','freepublish/submit']
    payload=next(v['payload'] for p,v in calls if p=='draft/add')
    content=payload['articles'][0]['content'];soup=BeautifulSoup(content,'html.parser')
    assert ('https://mmbiz.qpic.cn/image.jpg' in content)==reuse_cover_in_section
    assert '/api/assets/' not in content and '授权待核对' not in content
    assert payload['articles'][0]['title']==doc['title'] and not soup.h1
    assert soup.section.contents[0].get_text()==doc['summary']
    assert len(soup.select('img'))==int(reuse_cover_in_section)
    if reuse_cover_in_section:assert soup.figcaption.get_text()=='摄影作者'
    assert article_worker.get(article['id'])['document']['sections'][0]['caption']=='摄影作者 · 授权待核对'


def test_wechat_uploads_template_decoration_without_replacing_cover(client,wechat):
    from bs4 import BeautifulSoup
    prefs,calls,_=wechat
    task=create(client)
    task=save(client,task,brief='旅行文化',article={**task['settings']['article'],'template_id':'sage'},wechat_delivery={**prefs,'mode':'draft'})
    run=execute(client,task,'automatic')
    assert run['status']=='wechat_draft',run
    assert [p for p,_ in calls]==['material/add_material','media/uploadimg','draft/add']
    payload=next(v['payload'] for p,v in calls if p=='draft/add')
    soup=BeautifulSoup(payload['articles'][0]['content'],'html.parser')
    assert soup.select_one('img[data-template-decoration]')['src']=='https://mmbiz.qpic.cn/image.jpg'
    assert payload['articles'][0]['thumb_media_id']=='cover-media'
    assert soup.select_one('[data-article-template]')['data-article-template']=='sage'


def test_api_declaration_is_retained_for_drafts_and_cannot_be_silently_ignored_on_publish(client,wechat):
    from backend import wechat_delivery
    prefs,calls,_=wechat
    task=create(client)
    invalid={**task['settings'],'execution':'automatic','brief':'旅行文化','wechat_delivery':{**prefs,'content_declaration':'opinion'}}
    result=client.put('/api/tasks/'+task['id'],json={'name':task['name'],'version':task['version'],'settings':invalid})
    assert result.status_code==400 and '创作来源' in result.text and calls==[]
    task=save(client,task,brief='旅行文化',wechat_delivery={**prefs,'mode':'draft','content_declaration':'opinion'})
    run=execute(client,task,'automatic')
    value=wechat_delivery.public(wechat_delivery.get(run['id']))
    assert value['status']=='draft' and value['content_declaration']=='opinion' and not value['declaration_applied']
    assert all(path!='freepublish/submit' for path,_ in calls)


@pytest.mark.parametrize('declaration',['news','fiction','opinion','health','finance','none'])
def test_browser_delivery_receives_frozen_user_declaration(client,wechat,monkeypatch,declaration):
    from backend import wechat_delivery,wechat_browser_delivery
    account=personal_account(client)
    # Reuse the established browser-account fixture setup.
    from backend import wechat_accounts
    original=wechat_accounts.require_ready
    monkeypatch.setattr(wechat_accounts,'require_ready',lambda ident,mode:{**original(ident,'handoff'),'channel':'browser','appid':'wx-browser'} if ident==account['id'] else original(ident,mode))
    prefs,_,_=wechat
    task=save(client,create(client),brief='文章测试',wechat_delivery={**prefs,'account_id':account['id'],'mode':'draft','content_declaration':declaration})
    received=[]
    def deliver(value):
        received.append(value['data']['content_declaration']);value['data']['declaration_applied']=True
        wechat_delivery.update(value['run_id'],'draft',value['data'])
    monkeypatch.setattr(wechat_browser_delivery,'deliver',deliver)
    run=execute(client,task,'automatic')
    assert received==[declaration] and run['publication']['content_declaration']==declaration


@pytest.mark.parametrize('phase',['drafting','submitting'])
def test_wechat_crash_during_write_requires_reconciliation(client,wechat,phase):
    from backend import wechat_delivery
    prefs,_,_=wechat
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs)
    run=execute(client,task,'automatic')
    value=wechat_delivery.get(run['id']);value['data'].pop('publish_id',None)
    wechat_delivery.update(run['id'],phase,value['data'])
    task_engine.recover()
    result=task_store.detail(task['id'])['runs'][0]
    assert result['status']=='failed' and result['publication']['status']=='uncertain'
    assert client.post('/api/task-runs/'+run['id']+'/retry').status_code==409


def test_wechat_interrupted_preparation_can_resume_without_new_draft(client,wechat):
    from backend import wechat_delivery
    prefs,calls,_=wechat
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs)
    run=execute(client,task,'automatic')
    value=wechat_delivery.get(run['id']);value['data'].pop('publish_id',None)
    wechat_delivery.update(run['id'],'preparing',value['data'])
    calls.clear();task_engine.recover()
    assert task_store.detail(task['id'])['runs'][0]['publication']['can_retry']
    assert client.post('/api/task-runs/'+run['id']+'/retry').status_code==200
    task_engine.run(run['id'])
    assert [p for p,_ in calls]==['freepublish/submit']


def personal_account(client):
    result=client.post('/api/wechat/accounts',json={'name':'我的个人公众号','channel':'browser','subject':'personal'})
    assert result.status_code==201,result.text
    return result.json()


def test_personal_connection_needs_no_api_keys_and_does_not_grant_publish(client):
    from backend import wechat_accounts
    account=personal_account(client)
    assert account['channel']=='browser' and account['subject']=='personal'
    assert not account['secret_configured'] and not account['publish_ready'] and not account['draft_ready']
    assert 'secret' not in wechat_accounts.current(account['id'])
    result=client.post('/api/wechat/accounts/'+account['id']+'/test')
    assert result.status_code==400 and '无需检测 API' in result.text
    task=create(client)
    task['settings'].update(execution='automatic',brief='介绍家乡的旅游景点',wechat_delivery={'mode':'publish','account_id':account['id']})
    result=client.put('/api/tasks/'+task['id'],json={k:task[k] for k in ('name','version','settings')})
    assert result.status_code==400 and '尚未完成验证' in result.text
    assert client.get('/api/tasks/'+task['id']).json()['settings']['wechat_delivery']['mode']=='local'
    # The caller cannot smuggle credentials into a browser connection or change its channel.
    assert client.post('/api/wechat/accounts',json={'name':'bad','channel':'browser','secret':'do-not-echo'}).status_code==422
    result=client.put('/api/wechat/accounts/'+account['id'],json={'name':'bad','appid':'wx1234567890abcdef','secret':'do-not-echo'})
    assert result.status_code==400 and 'do-not-echo' not in result.text


def test_personal_automatic_handoff_freezes_content_and_never_calls_wechat(client,monkeypatch):
    from backend import wechat_accounts,wechat_delivery
    monkeypatch.setattr(wechat_accounts,'call',lambda *a,**k:pytest.fail('Handoff must not call a WeChat API'))
    account=personal_account(client)
    prefs={'mode':'handoff','account_id':account['id'],'cover_asset_id':'','author':''}
    task=save(client,create(client),brief='旅行文化',wechat_delivery=prefs,execution='automatic')
    run=execute(client,task,'automatic')
    assert run['status']=='awaiting_publish' and run['publication']['status']=='awaiting_publish'
    assert not run['publication']['article_url'] and not run['publication']['can_retry']
    content_path='/api/task-runs/'+run['id']+'/publication'
    original=client.get(content_path+'/content').json()
    assert original['title']=='从小任务开始' and '<h1' not in original['html']
    assert not original['text'].startswith('# ') and '描述实际任务' in original['text']
    article=article_worker.get(run['content_id'])
    with db.connect() as c:
        edited={**article['document'],'title':'之后的本地修改'}
        c.execute('UPDATE articles SET document=%s,version=version+1 WHERE id=%s',(db.dump(edited),article['id']))
    assert client.get(content_path+'/content').json()==original
    wechat_delivery.deliver(run['id'],article_worker.get(article['id']),TaskSettings.model_validate(task['settings']))
    assert client.get(content_path+'/content').json()==original
    response=client.get(content_path+'/bundle');assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert json.loads(archive.read('article.json'))['title']=='从小任务开始'
    assert client.post('/api/task-runs/'+run['id']+'/retry').status_code==409
    wechat_delivery.recover()
    assert wechat_delivery.get(run['id'])['status']=='awaiting_publish'


def test_wechat_browser_session_encryption_and_forget(client,monkeypatch):
    from backend import wechat_accounts,wechat_browser
    from types import SimpleNamespace
    account=personal_account(client);ident=account['id']
    state={'cookies':[{'name':'secret-cookie','value':'cookie-private'}],'origins':[]}
    # Exercise the Windows DPAPI boundary even on non-Windows CI.
    def crypt(raw,decrypt=False):return bytes(byte^73 for byte in raw)
    monkeypatch.setattr(wechat_browser.model_config,'secret_transform',crypt)
    monkeypatch.setattr(wechat_browser,'os',SimpleNamespace(name='nt'))
    wechat_browser._save(ident,SimpleNamespace(storage_state=lambda:state),'https://mp.weixin.qq.com/cgi-bin/home?token=private-token')
    assert wechat_browser._load(ident)['storage']==state
    assert 'private-token' not in (config.data_dir()/'wechat-accounts.json').read_text(encoding='utf-8')
    public=client.get('/api/wechat/accounts').text
    assert 'cookie-private' not in public and 'protected_session' not in public and 'private-token' not in public
    assert client.get('/api/wechat/accounts').json()[0]['session_saved']
    assert not client.get('/api/wechat/accounts').json()[0]['publish_ready']
    assert client.delete('/api/wechat/accounts/'+ident+'/login').status_code==200
    assert wechat_browser._load(ident) is None
    assert not wechat_accounts.catalog()[0]['session_saved']


def test_wechat_qr_login_lifecycle_is_isolated_and_redacts_internal_fields(client,monkeypatch):
    from backend import wechat_browser
    account=personal_account(client);second=personal_account(client)
    path='/api/wechat/accounts/'+account['id']+'/login'
    def worker(ident,value):
        wechat_browser._set(value,'waiting_scan','请扫码',b'png-test')
        value['stop'].wait(3)
    monkeypatch.setattr(wechat_browser,'_run',worker)
    result=client.post(path);assert result.status_code==200
    import time
    for _ in range(20):
        if client.get(path).json()['has_qr']:break
        time.sleep(.01)
    result=client.get(path+'/qr');assert result.content==b'png-test' and result.headers['cache-control']=='no-store'
    assert client.get('/api/wechat/accounts/'+second['id']+'/login/qr').status_code==400
    assert 'qr' not in client.get(path).json() and 'thread' not in client.get(path).json()
    first_thread=wechat_browser.sessions[wechat_browser._key(account['id'])]['thread']
    assert client.post(path).status_code==200
    assert wechat_browser.sessions[wechat_browser._key(account['id'])]['thread'] is first_thread
    client.post(path+'/cancel')
    assert client.get(path+'/qr').status_code==400
    assert client.post(path).status_code==200
    assert wechat_browser.sessions[wechat_browser._key(account['id'])]['thread'] is not first_thread
    client.post(path+'/cancel')


def test_legacy_api_account_remains_api_and_handoff_available(client,wechat):
    prefs,calls,_=wechat
    account=client.get('/api/wechat/accounts').json()[0]
    assert account['channel']=='api' and account['subject']=='unknown'
    assert client.post('/api/wechat/accounts/'+account['id']+'/login').status_code==400
    task=save(client,create(client),brief='企业旅行号',wechat_delivery={**prefs,'mode':'handoff'})
    run=execute(client,task,'automatic')
    assert run['status']=='awaiting_publish' and calls==[]
    with zipfile.ZipFile(io.BytesIO(client.get('/api/task-runs/'+run['id']+'/publication/bundle').content)) as archive:
        assert any(name.startswith('images/') for name in archive.namelist())


def connected_personal(client):
    from backend import wechat_accounts
    account=personal_account(client)
    with wechat_accounts.lock:
        values=wechat_accounts.read()
        values[account['id']].update(appid='wx1234567890abcdef',protected_session='test-encrypted-session',draft_ready=True)
        wechat_accounts.write(values)
    return account


def test_revising_article_context_never_changes_schedule_run_snapshot_or_wechat_delivery(client,wechat,monkeypatch):
    from backend import wechat_delivery
    prefs,_,_=wechat
    task=save(client,create(client),brief='旧的旅行方向',wechat_delivery={**prefs,'mode':'draft'})
    run=execute(client,task,'automatic');original=article_worker.get(run['content_id'])
    before=wechat_delivery.get(run['id'])['data'];settings_before=task_store.detail(task['id'])['settings']
    body={'version':original['version'],'subject':'新的建筑观察','brief':'介绍屋檐与空间关系','action':'article'}
    result=client.put('/api/articles/'+original['id']+'/context',json=body)
    assert result.status_code==200,result.text
    article_worker.run(original['id'])
    assert wechat_delivery.get(run['id'])['data']==before
    assert task_store.detail(task['id'])['settings']==settings_before
    with db.connect() as c:
        stored=json.loads(c.execute('SELECT settings FROM task_runs WHERE id=%s',(run['id'],)).fetchone()['settings'])
        assert stored['brief']==run['settings']['brief']
        c.execute("UPDATE task_runs SET status='publishing' WHERE id=%s",(run['id'],))
    latest=article_worker.get(original['id'])
    blocked=client.put('/api/articles/'+original['id']+'/context',json={**body,'version':latest['version'],'action':'save'})
    assert blocked.status_code==409 and '交付' in blocked.text


def test_article_context_search_uses_current_form_without_rewriting_saved_task(client,monkeypatch):
    task=save(client,create(client),brief='旧主题',materials={'mode':'original','query':'旧关键词','discover':False,'urls':[],'topic_ids':[],'notes':''})
    run=execute(client,task,'automatic');article=article_worker.get(run['content_id']);seen=[]
    def collect(ident,settings):
        seen.append(settings.model_dump());return [],[{'source':'搜索','status':'success','count':0,'items':[]}]
    monkeypatch.setattr(task_sources,'collect',collect)
    response=client.post('/api/articles/'+article['id']+'/context/collect',json={'version':article['version'],'brief':'新主题：平遥建筑','query':'平遥 建筑','max_age_days':7,'search_scope':'wechat'})
    assert response.status_code==200,response.text
    assert seen[0]['brief']=='新主题：平遥建筑' and seen[0]['materials']['query']=='平遥 建筑'
    assert seen[0]['materials']['max_age_days']==7 and seen[0]['materials']['discover']
    assert task_store.detail(task['id'])['settings']['materials']['query']=='旧关键词'
    assert article_worker.get(article['id'])['version']==article['version']


def test_personal_browser_draft_dispatch_and_unknown_write_protection(client,wechat,monkeypatch):
    from backend import wechat_browser_delivery,wechat_delivery
    prefs,api_calls,_=wechat
    account=connected_personal(client)
    prefs={**prefs,'account_id':account['id'],'mode':'draft','author':'编辑'}
    task=save(client,create(client),brief='古城旅行',wechat_delivery=prefs,execution='automatic',article_plan={'mode':'fixed','avoid_days':30})
    calls=[]
    def draft(value):
        calls.append(value['run_id'])
        data=value['data'];data.update(media_id='browser-draft-1',browser_editor='encrypted-url')
        wechat_delivery.update(value['run_id'],'draft',data)
    monkeypatch.setattr(wechat_browser_delivery,'deliver',draft)
    run=execute(client,task,'automatic')
    assert run['status']=='wechat_draft' and run['publication']['media_id']=='browser-draft-1'
    assert 'browser_editor' not in run['publication'] and 'encrypted-url' not in json.dumps(run)
    wechat_delivery.deliver(run['id'],article_worker.get(run['content_id']),TaskSettings.model_validate(task['settings']))
    assert len(calls)==1 and not api_calls
    def interrupted(value):
        wechat_delivery.update(value['run_id'],'drafting',value['data'])
        raise ValueError('编辑器中断，微信可能已经自动保存')
    monkeypatch.setattr(wechat_browser_delivery,'deliver',interrupted)
    unknown=execute(client,task,'automatic')
    assert unknown['publication']['status']=='uncertain' and not unknown['publication']['can_retry']
    assert client.post('/api/task-runs/'+unknown['id']+'/retry').status_code==409


def test_personal_session_expiration_before_write_can_retry_without_regeneration(client,wechat,monkeypatch):
    from backend import wechat_browser_delivery,wechat_delivery
    prefs,_,_=wechat;account=connected_personal(client)
    prefs={**prefs,'mode':'draft','account_id':account['id'],'author':''}
    task=save(client,create(client),brief='古城旅行',wechat_delivery=prefs)
    def expired(value):raise ValueError('公众号登录已失效，请重新扫码后重试。')
    monkeypatch.setattr(wechat_browser_delivery,'deliver',expired)
    run=execute(client,task,'automatic')
    assert run['publication']['status']=='failed' and run['publication']['can_retry']
    def recovered(value):
        value['data']['media_id']='after-login'
        wechat_delivery.update(value['run_id'],'draft',value['data'])
    monkeypatch.setattr(wechat_browser_delivery,'deliver',recovered)
    assert client.post('/api/task-runs/'+run['id']+'/retry').status_code==200
    task_engine.run(run['id'])
    resumed=task_store.detail(task['id'])['runs'][0]
    assert resumed['content_id']==run['content_id'] and resumed['status']=='wechat_draft'


def test_browser_identity_cannot_change_and_urls_are_encrypted(client):
    from backend import wechat_browser,wechat_browser_delivery,wechat_accounts
    from types import SimpleNamespace
    account=personal_account(client);ident=account['id']
    context=SimpleNamespace(storage_state=lambda:{'cookies':[],'origins':[]})
    first={'appid':'wx1234567890abcdef','name':'已登录账号'}
    wechat_browser._save(ident,context,'https://mp.weixin.qq.com/cgi-bin/home?token=private-token',first)
    assert wechat_accounts.require_ready(ident,'draft')['appid']==first['appid']
    with pytest.raises(ValueError,match='不一致'):
        wechat_browser._save(ident,context,'https://mp.weixin.qq.com/cgi-bin/home',{'appid':'wxfedcba0987654321','name':'其他账号'})
    assert wechat_accounts.current(ident)['appid']==first['appid']
    wechat_accounts.save(wechat_accounts.AccountInput(name='改连接名',channel='browser',subject='personal'),ident)
    assert wechat_accounts.current(ident)['appid']==first['appid']
    url='https://mp.weixin.qq.com/cgi-bin/appmsg?appmsgid=123&token=private-token'
    encrypted=wechat_browser_delivery.seal(url)
    assert 'private-token' not in encrypted and wechat_browser_delivery.unseal(encrypted)==url
    with pytest.raises(ValueError):wechat_browser_delivery.unseal(wechat_browser_delivery.seal('https://evil.example/'))
    with pytest.raises(ValueError,match='尚未完成验证'):wechat_accounts.require_ready(ident,'publish')


def test_record_counts_include_scheduled_and_archived_but_exclude_deleted_tasks(client):
    manual=save(client,create(client,name='手动任务'),brief='日常工具的使用方法')
    scheduled=save(client,create(client,name='定时任务'),execution='automatic',brief='日常工具的使用方法')
    first=execute(client,manual,'automatic')
    execute(client,scheduled,'automatic');execute(client,scheduled,'automatic')
    listing=client.get('/api/tasks').json();records=client.get('/api/task-records').json()
    assert len(listing)==2 and sum(t['run_count'] for t in listing)==len(records)==3
    assert sum(t['settings']['execution']=='automatic' for t in listing)==1
    assert {r['task_name'] for r in records}=={'手动任务','定时任务'}
    assert all('settings' not in r and 'publication' not in r for r in records)
    archived=client.post('/api/tasks/'+scheduled['id']+'/archive',json={'version':scheduled['version']})
    assert archived.status_code==200
    records=client.get('/api/task-records').json()
    assert len(records)==3 and sum(r['archived'] for r in records)==2
    assert client.request('DELETE','/api/tasks/'+manual['id'],json={'version':manual['version']}).status_code==200
    records=client.get('/api/task-records').json()
    assert len(records)==2 and not any(r['id']==first['id'] for r in records)


@pytest.mark.parametrize('action',['blank','automatic'])
def test_explicit_delivery_uses_saved_article_without_model_or_regeneration(client,wechat,monkeypatch,action):
    from backend import wechat_delivery
    prefs,calls,_=wechat
    task=save(client,create(client),brief='古城旅行')
    run=execute(client,task,action)
    article=article_worker.get(run['content_id']);original=article['document']
    # A failed review does not prevent saving the existing body to a draft.
    with db.connect() as c:
        c.execute("UPDATE articles SET status='failed',stage='check',error='review failed' WHERE id=%s",(article['id'],))
        c.execute("UPDATE task_runs SET status='failed' WHERE id=%s",(run['id'],))
    def forbidden(*args,**kwargs):raise AssertionError('Delivery must not generate, review, collect or validate a model')
    monkeypatch.setattr(task_engine,'drive_article',forbidden)
    monkeypatch.setattr(task_sources,'collect',forbidden)
    monkeypatch.setattr(model_library,'ready',forbidden)
    body={'version':article['version'],'delivery':{**prefs,'mode':'draft'}}
    path='/api/task-runs/'+run['id']+'/publication'
    assert client.post(path,json={**body,'version':article['version']+1}).status_code==409
    before=len(calls)
    first=client.post(path,json=body)
    assert first.status_code==200,first.text
    assert first.json()['status']=='queued' and len(calls)==before
    assert client.post(path,json=body).status_code==200
    assert client.put('/api/articles/'+article['id']+'/document',json={'version':article['version'],'document':original}).status_code==409
    task_engine.run(run['id'])
    delivered=wechat_delivery.get(run['id'])
    assert delivered['status']=='draft'
    assert delivered['data']['document']==original and article_worker.get(article['id'])['document']==original
    assert len([p for p,_ in calls if p=='draft/add'])==1
    assert client.post(path,json=body).json()['status']=='draft'
    assert client.post(path,json={**body,'delivery':{**body['delivery'],'content_declaration':'opinion'}}).status_code==409
    task_engine.run(run['id'])
    assert len([p for p,_ in calls if p=='draft/add'])==1


def test_explicit_delivery_validates_missing_cover_and_publish_checks(client,wechat):
    prefs,_,_=wechat
    run=execute(client,save(client,create(client),brief='古城旅行'),'blank')
    article=article_worker.get(run['content_id']);path='/api/task-runs/'+run['id']+'/publication'
    assert client.post(path,json={'version':article['version'],'delivery':{**prefs,'mode':'draft','cover_asset_id':''}}).status_code==400
    assert client.post(path,json={'version':article['version'],'delivery':{**prefs,'mode':'publish'}}).status_code==400
    assert client.post('/api/task-runs/missing/publication',json={'version':1,'delivery':prefs}).status_code==404
    with db.connect() as c:assert not c.execute('SELECT 1 FROM wechat_deliveries WHERE run_id=%s',(run['id'],)).fetchone()


def test_explicit_publish_uses_checked_saved_document_and_waits_for_wechat(client,wechat,monkeypatch):
    prefs,calls,_=wechat
    run=execute(client,save(client,create(client),brief='古城旅行'),'automatic')
    article=article_worker.get(run['content_id'])
    monkeypatch.setattr(task_engine,'drive_article',lambda *a:pytest.fail('Unexpected article generation'))
    result=client.post('/api/task-runs/'+run['id']+'/publication',json={'version':article['version'],'delivery':prefs})
    assert result.status_code==200,result.text
    task_engine.run(run['id'])
    current=task_store.detail(run['task_id'])['runs'][0]
    assert current['publication']['status']=='publishing'
    assert len([p for p,_ in calls if p=='freepublish/submit'])==1
    assert article_worker.get(article['id'])['document']==article['document']


def test_explicit_resume_reuses_known_browser_draft_and_rejects_unknown_outcome(client,wechat,monkeypatch):
    from backend import wechat_delivery,wechat_browser_delivery as adapter
    prefs,_,_=wechat;account=connected_personal(client)
    prefs={**prefs,'mode':'draft','account_id':account['id'],'author':''}
    def fail(value):
        data=value['data'];data.update(browser_draft_id='123',browser_editor=adapter.seal('https://mp.weixin.qq.com/cgi-bin/appmsg?appmsgid=123'))
        wechat_delivery.update(value['run_id'],'drafting',data)
        raise ValueError('interrupted')
    monkeypatch.setattr(adapter,'deliver',fail)
    run=execute(client,save(client,create(client),brief='古城旅行',wechat_delivery=prefs),'automatic')
    article=article_worker.get(run['content_id']);path='/api/task-runs/'+run['id']+'/publication'
    assert run['publication']['can_resume']
    body={'version':article['version'],'delivery':prefs,'resume':True}
    assert client.post(path,json={**body,'resume':False}).status_code==409
    assert client.post(path,json={**body,'delivery':{**prefs,'account_id':'other'}}).status_code==409
    with db.connect() as c:
        d=wechat_delivery.get(run['id'],c);data=d['data'];data.pop('browser_draft_id')
        c.execute('UPDATE wechat_deliveries SET data=%s WHERE run_id=%s',(db.dump(data),run['id']))
    assert client.post(path,json=body).status_code==409
    with db.connect() as c:
        data['browser_draft_id']='123';c.execute('UPDATE wechat_deliveries SET data=%s WHERE run_id=%s',(db.dump(data),run['id']))
    seen=[]
    def resume(value):
        seen.append(value['data']['browser_draft_id'])
        assert value['data']['document']==article['document']
        value['data']['media_id']='123';value['data'].pop('_resume_browser')
        wechat_delivery.update(value['run_id'],'draft',value['data'])
    monkeypatch.setattr(adapter,'resume',resume)
    assert client.post(path,json=body).status_code==200
    task_engine.run(run['id'])
    assert seen==['123'] and wechat_delivery.get(run['id'])['status']=='draft'
