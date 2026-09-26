"""PostgreSQL connections, transactional migrations and tenant row security."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import threading
from psycopg import sql
from psycopg_pool import ConnectionPool
from . import config
from .models import Settings
from .tenancy import require_user, user_id

TZ = timezone(timedelta(hours=8))
_pool = None
_pool_key = None
_pool_lock = threading.RLock()


class Record(dict):
    """Named fields with positional access for scalar aggregate queries."""
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def record_factory(cursor):
    names = [col.name for col in cursor.description] if cursor.description else []
    return lambda values: Record(zip(names, values))


def now():
    return datetime.now(timezone.utc).isoformat()


def day():
    return datetime.now(TZ).date().isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def pool():
    global _pool, _pool_key
    key = (config.DATABASE_URL, config.DATABASE_SCHEMA)
    if not key[0]:
        raise RuntimeError('请在 .env 配置 DATABASE_URL，项目现统一使用 PostgreSQL。')
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', key[1]):
        raise RuntimeError('DATABASE_SCHEMA 格式无效。')
    with _pool_lock:
        if _pool is None or _pool_key != key:
            close()
            def configure(c):
                c.execute(sql.SQL('SET search_path TO {}, pg_catalog').format(sql.Identifier(key[1])))
                c.execute("SET timezone TO 'UTC'")
                c.execute("SET lock_timeout TO '15s'")
                c.execute("SET idle_in_transaction_session_timeout TO '60s'")
                c.commit()
            _pool = ConnectionPool(key[0], min_size=1, max_size=16, timeout=15,
                kwargs={'row_factory': record_factory, 'connect_timeout': 10}, configure=configure, open=True)
            _pool_key = key
        return _pool


def close():
    global _pool, _pool_key
    with _pool_lock:
        if _pool:
            _pool.close()
        _pool = _pool_key = None


@contextmanager
def system_connection():
    """Auth/migrations only. Content tables have no visible rows without a tenant."""
    with pool().connection() as c:
        with c.transaction():
            c.execute("SELECT set_config('studio.user_id', '', true)")
            yield c


@contextmanager
def connect():
    ident = require_user()
    with pool().connection() as c:
        with c.transaction():
            c.execute("SELECT set_config('studio.user_id', %s, true)", (ident,))
            yield c


def lock(c, kind, ident=''):
    # Independent entities/users remain concurrent; collisions only delay a transaction.
    key = int.from_bytes(sha256(f'{config.DATABASE_SCHEMA}:{user_id.get()}:{kind}:{ident}'.encode()).digest()[:8], 'big', signed=True)
    c.execute('SELECT pg_advisory_xact_lock(%s)', (key,))


@contextmanager
def application_lock():
    """In-process scheduler/recovery currently supports one application process."""
    with pool().connection() as c:
        key = int.from_bytes(sha256((config.DATABASE_SCHEMA+':application').encode()).digest()[:8], 'big', signed=True)
        held = c.execute('SELECT pg_try_advisory_lock(%s)', (key,)).fetchone()[0]
        c.commit()
        if not held:
            raise RuntimeError('此数据库已有运行中的工作台；当前任务队列请使用一个应用进程。')
        try:
            yield
        finally:
            c.execute('SELECT pg_advisory_unlock(%s)', (key,))
            c.commit()


def init():
    config.DATA.mkdir(parents=True, exist_ok=True)
    with system_connection() as c:
        role = c.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        if role['rolsuper'] or role['rolbypassrls']:
            raise RuntimeError('DATABASE_URL 必须使用普通 PostgreSQL 角色，禁止 superuser / BYPASSRLS，以确保用户数据隔离。')
        lock(c, 'migrations')
        c.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(config.DATABASE_SCHEMA)))
        c.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)')
        for path in sorted((config.ROOT/'backend/migrations').glob('*.sql')):
            content = path.read_text(encoding='utf-8')
            digest = sha256(content.encode()).hexdigest()
            previous = c.execute('SELECT checksum FROM schema_migrations WHERE version=%s', (path.name,)).fetchone()
            if previous:
                if previous['checksum'] != digest:
                    raise RuntimeError('已应用的数据库迁移被修改：'+path.name)
                continue
            c.execute(content)
            c.execute('INSERT INTO schema_migrations VALUES (%s,%s,%s)', (path.name, digest, now()))


def init_user(c=None):
    from .article_models import ArticleProfile
    config.data_dir().mkdir(parents=True, exist_ok=True)
    if c is None:
        with connect() as own:return init_user(own)
    c.execute('INSERT INTO settings(id,value) VALUES (1,%s) ON CONFLICT DO NOTHING', (dump(Settings().model_dump()),))
    c.execute('INSERT INTO article_profiles(id,value,updated_at) VALUES (1,%s,%s) ON CONFLICT DO NOTHING', (dump(ArticleProfile().model_dump()), now()))


def settings(c=None):
    if c is None:
        with connect() as own:return settings(own)
    return Settings.model_validate_json(c.execute('SELECT value FROM settings WHERE id=1').fetchone()['value'])


def event(c, job_id, stage, message):
    c.execute('INSERT INTO job_events(job_id,stage,message,at) VALUES (%s,%s,%s,%s)', (job_id,stage,message,now()))


def topic(row):
    if row is None:return None
    result = dict(row)
    result.update(json.loads(result.pop('data')))
    return result


def job(row):
    if row is None:return None
    result = dict(row)
    for field in ('settings','script','source_data','artifacts','qa'):
        result[field] = json.loads(result[field]) if result[field] else None
    return result


def article(row):
    if row is None:return None
    result = dict(row)
    for field in ('profile','input_data','source_data','angles','outline','document','checks'):
        result[field] = json.loads(result[field]) if result[field] else None
    return result


def article_profile(c=None):
    from .article_models import ArticleProfile
    if c is None:
        with connect() as own:return article_profile(own)
    row = c.execute('SELECT value FROM article_profiles WHERE id=1').fetchone()
    return ArticleProfile.model_validate_json(row['value'])
