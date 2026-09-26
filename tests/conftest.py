"""All database tests run against a dedicated PostgreSQL database and temporary schema."""
import os
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from fastapi.testclient import TestClient
from backend import config, db, auth
from backend.tenancy import as_user, LEGACY_OWNER


@pytest.fixture(scope='session')
def pg_schema():
    url=os.environ.get('TEST_DATABASE_URL','')
    if not url:pytest.exit('请配置 TEST_DATABASE_URL（独立 PostgreSQL 测试库），测试不会使用运行数据库。')
    production=conninfo_to_dict(config.DATABASE_URL)
    target=conninfo_to_dict(url)
    if all(production.get(k)==target.get(k) for k in ('host','port','dbname')):
        pytest.exit('TEST_DATABASE_URL 必须使用不同的数据库。')
    original=(config.DATABASE_URL,config.DATABASE_SCHEMA)
    db.close();config.DATABASE_URL=url;config.DATABASE_SCHEMA='test_'+uuid.uuid4().hex
    db.init()
    try:yield
    finally:
        with db.system_connection() as c:
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(config.DATABASE_SCHEMA)))
        db.close();config.DATABASE_URL,config.DATABASE_SCHEMA=original


@pytest.fixture(autouse=True)
def isolated_database(pg_schema,tmp_path,monkeypatch,request):
    monkeypatch.setattr(config,'DATA',tmp_path)
    with db.system_connection() as c:
        c.execute('TRUNCATE app_users,server_settings,auth_limits RESTART IDENTITY CASCADE')
    auth.initialize()
    testing_auth=request.node.get_closest_marker('auth_flow') is not None
    if not testing_auth:
        with db.system_connection() as c:
            c.execute("UPDATE app_users SET email='owner@example.com',password_hash=%s,status='active' WHERE id=%s",(auth.DUMMY_HASH,LEGACY_OWNER))
            c.execute('INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES (%s,%s,%s)',
                (auth.digest('test-session-only'),LEGACY_OWNER,datetime.now(timezone.utc)+timedelta(hours=1)))
        original=TestClient.__init__
        def initialized(self,*args,**kwargs):
            kwargs.setdefault('cookies',{auth.COOKIE:'test-session-only'})
            original(self,*args,**kwargs)
        monkeypatch.setattr(TestClient,'__init__',initialized)
    with as_user(LEGACY_OWNER):
        db.init_user()
        yield
