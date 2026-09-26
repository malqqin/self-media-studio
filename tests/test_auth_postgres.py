import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
import psycopg
from fastapi.testclient import TestClient
from PIL import Image
from backend import auth, config, db, mail_service, model_config, task_engine
from backend.app import app
from backend.tenancy import as_user, LEGACY_OWNER, ContextExecutor, user_id

pytestmark=pytest.mark.auth_flow
PASSWORD='a'


@pytest.mark.parametrize('value',['short-credential','','x'*129])
def test_setup_invalid_length_explains_credential_without_exposing_input(value):
    with TestClient(app) as client:
        response=client.post('/api/auth/setup',json={'email':'owner@example.com','password':PASSWORD,'display_name':'管理员','setup_token':value})
        assert response.status_code==422
        error=response.json()['detail'][0]
        assert error['loc']==['body','setup_token']
        assert '初始化凭证不完整' in error['msg'] and '不是登录密码' in error['msg']
        assert 'String should' not in response.text and 'input' not in error and 'ctx' not in error
        if value:assert value not in response.text
        assert client.get('/api/auth/status').json()['setup_required']
        assert (config.DATA/'admin-setup.txt').is_file()
        assert client.get('/api/tasks').status_code==401


def test_setup_trims_copied_credential_but_still_rejects_wrong_one():
    with TestClient(app) as client:
        token=(config.DATA/'admin-setup.txt').read_text()
        body={'email':'owner@example.com','password':PASSWORD,'display_name':'管理员'}
        rejected=client.post('/api/auth/setup',json={**body,'setup_token':'wrong-credential-'*3})
        assert rejected.status_code==400 and '初始化凭证不匹配' in rejected.json()['detail']
        response=client.post('/api/auth/setup',json={**body,'setup_token':'\ufeff  '+token+'\r\n'})
        assert response.status_code==200,response.text
        assert response.json()['user']['role']=='admin'
        assert not (config.DATA/'admin-setup.txt').exists()


@pytest.mark.parametrize('value,message',[('', '请填写密码。'),('private'*19, '密码不能超过 128 个字符。')])
def test_auth_password_validation_is_chinese_and_does_not_echo_password(value,message):
    with TestClient(app) as client:
        response=client.post('/api/auth/setup',json={'email':'owner@example.com','password':value,'display_name':'管理员','setup_token':(config.DATA/'admin-setup.txt').read_text()})
        assert response.status_code==422
        assert response.json()['detail'][0]['msg']==message
        assert 'input' not in response.json()['detail'][0]
        if value:assert value not in response.text


@pytest.fixture
def clients(monkeypatch):
    import backend.app as application
    monkeypatch.setattr(application,'tick_users',lambda:None)
    monkeypatch.setattr(task_engine.executor,'submit',lambda *args:None)
    with TestClient(app) as owner:
        token=(config.DATA/'admin-setup.txt').read_text()
        result=owner.post('/api/auth/setup',json={'email':'owner@example.com','password':PASSWORD,'display_name':'管理员','setup_token':token})
        assert result.status_code==200,result.text
        sent={}
        monkeypatch.setattr(mail_service,'send_code',lambda email,code,purpose:sent.__setitem__((email,purpose),code))
        assert owner.put('/api/admin/smtp',json={'host':'smtp.example.com','sender':'owner@example.com','username':'owner','password':'smtp-private-secret'}).status_code==200
        other=TestClient(app)
        yield owner,other,sent
        other.close()


def signup(client,sent,email='writer@example.com'):
    body={'email':email,'password':PASSWORD,'display_name':'创作者'}
    result=client.post('/api/auth/register',json=body)
    assert result.status_code==200,result.text
    assert client.get('/api/tasks').status_code==401
    result=client.post('/api/auth/verify',json={'email':email,'code':sent[(email,'register')]})
    assert result.status_code==200,result.text
    return result.json()['user']


def test_bootstrap_is_not_first_public_registration_and_session_is_revocable(clients):
    owner,other,sent=clients
    assert not (config.DATA/'admin-setup.txt').exists()
    assert other.get('/api/tasks').status_code==401
    assert other.get('/api/models').status_code==401
    assert other.get('/api/health').json()['model'] is None
    user=signup(other,sent)
    assert user['role']=='user' and user['email_verified']
    assert other.get('/api/admin/users').status_code==403
    assert other.post('/api/auth/verify',json={'email':user['email'],'code':sent[(user['email'],'register')]}).status_code==400
    assert other.post('/api/auth/logout').status_code==200
    assert other.get('/api/tasks').status_code==401
    response=other.post('/api/auth/login',json={'email':user['email'],'password':PASSWORD})
    assert response.status_code==200
    assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
    with db.system_connection() as c:
        stored=c.execute('SELECT password_hash FROM app_users WHERE id=%s',(user['id'],)).fetchone()[0]
        assert stored.startswith('$argon2id$') and auth.verify_password(stored,PASSWORD)


def test_content_files_secrets_and_foreign_keys_are_isolated(clients):
    owner,other,sent=clients;user=signup(other,sent)
    task=owner.post('/api/tasks',json={'name':'管理员私密任务','kind':'article','request_id':'same-request-1234'}).json()
    second=other.post('/api/tasks',json={'name':'普通用户任务','kind':'article','request_id':'same-request-1234'})
    assert second.status_code==201
    assert other.get('/api/tasks/'+task['id']).status_code==404
    run=owner.post('/api/tasks/'+task['id']+'/run',json={'version':task['version'],'action':'blank','request_id':'private-run-12345'}).json()
    assert other.post('/api/task-runs/'+run['id']+'/publication',json={'version':1,'delivery':{'mode':'draft','account_id':'private-account'}}).status_code==404
    assert other.request('DELETE','/api/tasks/'+task['id'],json={'version':1}).status_code==404
    assert len(other.get('/api/tasks').json())==1
    response=owner.put('/api/model-config',json={'name':'私密模型','base_url':'https://example.com/v1','model':'private-model','protocol':'responses','output_mode':'json_schema','api_key':'owner-only-secret'})
    assert response.status_code==200
    assert not other.get('/api/model-config').json()['key_configured']
    buffer=io.BytesIO();Image.new('RGB',(8,8),'blue').save(buffer,format='PNG')
    asset=owner.post('/api/assets',files={'file':('private.png',buffer.getvalue(),'image/png')},data={'rights':'本人制作持有版权'}).json()
    assert other.get('/api/assets').json()==[]
    assert other.get('/api/assets/'+asset['id']+'/file').status_code==404
    with as_user(user['id']),db.connect() as c:
        assert c.execute('SELECT count(*) FROM creation_tasks').fetchone()[0]==1
        assert c.execute('UPDATE creation_tasks SET name=%s WHERE id=%s',('attack',task['id'])).rowcount==0
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute('INSERT INTO asset_provenance(asset_id,data) VALUES (%s,%s)',(asset['id'],'{}'))
    with db.system_connection() as c:assert c.execute('SELECT count(*) FROM creation_tasks').fetchone()[0]==0
    assert (config.DATA/'users'/LEGACY_OWNER/'model-config.json').exists()
    assert not (config.DATA/'users'/user['id']/'model-config.json').exists()


def test_codes_expire_attempt_limits_and_password_reset_revoke_sessions(clients):
    owner,other,sent=clients;user=signup(other,sent)
    old_cookie=other.cookies.get(auth.COOKIE)
    assert other.post('/api/auth/forgot',json={'email':user['email']}).status_code==200
    with db.system_connection() as c:
        c.execute("UPDATE auth_codes SET expires_at=now()-interval '1 minute' WHERE purpose='reset'")
    assert other.post('/api/auth/reset',json={'email':user['email'],'code':sent[(user['email'],'reset')],'password':'b'}).status_code==400
    with db.system_connection() as c:
        c.execute("UPDATE auth_codes SET expires_at=now()+interval '1 minute' WHERE purpose='reset'")
    reset=other.post('/api/auth/reset',json={'email':user['email'],'code':sent[(user['email'],'reset')],'password':'b'})
    assert reset.status_code==200
    assert auth.user_for_token(old_cookie) is None
    assert other.post('/api/auth/login',json={'email':user['email'],'password':PASSWORD}).status_code==401
    assert other.post('/api/auth/login',json={'email':user['email'],'password':'b'}).status_code==200
    reset_cookie=other.cookies.get(auth.COOKIE)
    assert other.post('/api/auth/password',json={'current_password':'b','new_password':'c'}).status_code==200
    assert auth.user_for_token(reset_cookie) is None
    assert other.post('/api/auth/login',json={'email':user['email'],'password':'b'}).status_code==401
    assert other.post('/api/auth/login',json={'email':user['email'],'password':'c'}).status_code==200


def test_verification_attempts_commit_even_on_error(clients):
    _,other,sent=clients
    email='tries@example.com'
    assert other.post('/api/auth/register',json={'email':email,'password':PASSWORD,'display_name':'测试'}).status_code==200
    correct=sent[(email,'register')];wrong='000000' if correct!='000000' else '111111'
    for _ in range(5):assert other.post('/api/auth/verify',json={'email':email,'code':wrong}).status_code==400
    assert other.post('/api/auth/verify',json={'email':email,'code':correct}).status_code==400
    with db.system_connection() as c:assert c.execute('SELECT attempts FROM auth_codes WHERE email=%s',(email,)).fetchone()[0]==5


def test_admin_controls_registration_disable_and_csrf(clients):
    owner,other,sent=clients;user=signup(other,sent)
    assert owner.put('/api/admin/users/'+LEGACY_OWNER,json={'role':'user','status':'active'}).status_code==400
    assert owner.put('/api/admin/users/'+user['id'],json={'role':'user','status':'disabled'}).status_code==200
    assert other.get('/api/tasks').status_code==401
    assert other.post('/api/auth/login',json={'email':user['email'],'password':PASSWORD}).status_code==401
    assert owner.put('/api/admin/registration',json={'enabled':False}).status_code==200
    assert other.post('/api/auth/register',json={'email':'third@example.com','display_name':'third','password':PASSWORD}).status_code==403
    assert owner.post('/api/tasks',json={},headers={'origin':'https://attacker.example'}).status_code==403
    assert owner.post('/api/auth/logout',headers={'sec-fetch-site':'cross-site'}).status_code==403
    assert len(owner.get('/api/admin/events').json())>=3
    data=owner.get('/api/admin/settings').text
    assert 'smtp-private-secret' not in data and 'password_configured' in data


def test_verification_is_single_use_under_concurrency(clients):
    _,other,sent=clients;email='race@example.com'
    other.post('/api/auth/register',json={'email':email,'password':PASSWORD,'display_name':'race'})
    def attempt(_):
        client=TestClient(app)
        try:return client.post('/api/auth/verify',json={'email':email,'code':sent[(email,'register')]}).status_code
        finally:client.close()
    with ThreadPoolExecutor(2) as executor:results=list(executor.map(attempt,range(2)))
    assert sorted(results)==[200,400]


def test_postgres_transactions_concurrent_versions_and_executor_identity(clients):
    owner,other,sent=clients;user=signup(other,sent)
    with as_user(user['id']):
        with pytest.raises(RuntimeError):
            with db.connect() as c:
                c.execute("INSERT INTO platform_meta(key,value) VALUES ('rollback','yes')")
                raise RuntimeError('rollback')
        with db.connect() as c:assert not c.execute("SELECT 1 FROM platform_meta WHERE key='rollback'").fetchone()
        with ContextExecutor(2) as executor:
            assert executor.submit(lambda:(user_id.get(),model_config.current()['api_key'])).result()==(user['id'],'')
    task=owner.post('/api/tasks',json={'name':'并发修改','kind':'article','request_id':'concurrent-task-123'}).json()
    cookie=owner.cookies.get(auth.COOKIE)
    def change(i):
        client=TestClient(app,cookies={auth.COOKIE:cookie})
        try:return client.put('/api/tasks/'+task['id'],json={'name':f'修改{i}','version':task['version'],'settings':task['settings']}).status_code
        finally:client.close()
    with ThreadPoolExecutor(2) as executor:results=list(executor.map(change,range(2)))
    assert sorted(results)==[200,409]


def test_sqlite_migration_preserves_content_sequences_files_and_rejects_reimport(tmp_path):
    from scripts.migrate_sqlite import migrate
    source_dir=tmp_path/'legacy';source_dir.mkdir()
    source=source_dir/'studio.sqlite3'
    with sqlite3.connect(source) as c:
        c.execute('CREATE TABLE ai_usage(id INTEGER PRIMARY KEY,job_id TEXT,day TEXT,kind TEXT,status TEXT,input_tokens INTEGER,output_tokens INTEGER,at TEXT)')
        c.execute("INSERT INTO ai_usage VALUES (92,'test','2026-09-26','article','received',12,8,'2026-09-26T00:00:00Z')")
    (source_dir/'model-config.json').write_text('{"opaque":"preserved"}')
    result=migrate(source)
    assert result['tables']['ai_usage']==1 and result['files']==1
    assert Path(result['backup']).is_file() and source.is_file()
    with as_user(LEGACY_OWNER),db.connect() as c:
        assert c.execute('SELECT input_tokens FROM ai_usage WHERE id=92').fetchone()[0]==12
        assert c.execute("INSERT INTO ai_usage(job_id,day,kind,status,at) VALUES ('new','today','test','reserved','now') RETURNING id").fetchone()[0]>92
    with pytest.raises(ValueError,match='已完成'):migrate(source)


def test_non_admin_model_requests_pin_public_ip_and_block_private_network(clients,monkeypatch):
    import httpx
    from backend import model_http
    _,other,sent=clients;user=signup(other,sent)
    with as_user(user['id']):
        transport=model_http.transport()
        assert isinstance(transport,model_http.PublicModelTransport)
        monkeypatch.setattr(model_http.socket,'getaddrinfo',lambda *args,**kwargs:[(2,1,6,'',('127.0.0.1',443))])
        with pytest.raises(ValueError,match='内网'):transport.handle_request(httpx.Request('GET','https://model.example/v1/models'))
        with pytest.raises(ValueError,match='HTTPS'):transport.handle_request(httpx.Request('GET','http://localhost/v1/models'))
        monkeypatch.setattr(model_http.socket,'getaddrinfo',lambda *args,**kwargs:[(2,1,6,'',('8.8.8.8',443))])
        observed=[]
        monkeypatch.setattr(transport.inner,'handle_request',lambda request:observed.append(request) or httpx.Response(200,json={}))
        transport.handle_request(httpx.Request('POST','https://model.example/v1/responses',json={'hello':'world'}))
        assert observed[0].url.host=='8.8.8.8' and observed[0].headers['host']=='model.example'
        assert observed[0].extensions['sni_hostname']=='model.example'
        transport.close()


def test_unauthenticated_guesses_cannot_access_any_business_router(clients):
    _,other,_=clients
    for path in ('/tasks','/task-records','/article-profile','/articles','/articles/missing/events',
                 '/jobs','/assets','/assets/missing/file','/wechat/accounts','/models',
                 '/pictures/candidates/missing/preview','/admin/settings','/admin/events','/settings'):
        assert other.get('/api'+path).status_code==401,path


def test_duplicate_application_process_is_rejected():
    with db.application_lock():
        with pytest.raises(RuntimeError,match='已有运行'):
            with db.application_lock():pass
