from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import sqlite3

from . import config
from .models import Settings

TZ = timezone(timedelta(hours=8))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def day() -> str:
    return datetime.now(TZ).date().isoformat()


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


@contextmanager
def connect():
    conn = sqlite3.connect(config.DATA / 'studio.sqlite3', timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    config.DATA.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS topics (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL, kind TEXT NOT NULL,
          source TEXT NOT NULL, published_at TEXT, discovered_at TEXT NOT NULL,
          score INTEGER NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES topics(id), request_id TEXT UNIQUE NOT NULL,
          status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
          mode TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, settings TEXT NOT NULL,
          script TEXT, source_data TEXT, artifacts TEXT, qa TEXT, error TEXT, note TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, day TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS job_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
          stage TEXT NOT NULL, message TEXT NOT NULL, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reviews (
          id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(id),
          version INTEGER NOT NULL, decision TEXT NOT NULL, facts_checked INTEGER NOT NULL,
          rights_checked INTEGER NOT NULL, note TEXT NOT NULL, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, status TEXT NOT NULL,
          count INTEGER NOT NULL, message TEXT NOT NULL, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ai_usage (
          id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, day TEXT NOT NULL,
          kind TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS daily_runs (
          day TEXT PRIMARY KEY, status TEXT NOT NULL, message TEXT NOT NULL, job_id TEXT, at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assets (
          id TEXT PRIMARY KEY, filename TEXT NOT NULL, media_type TEXT NOT NULL,
          rights TEXT NOT NULL, credit TEXT NOT NULL, source_url TEXT NOT NULL,
          path TEXT NOT NULL, at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS jobs_day ON jobs(day);
        ''')
        c.execute('INSERT OR IGNORE INTO settings VALUES (1, ?)', (dump(Settings().model_dump()),))


def settings() -> Settings:
    with connect() as c:
        return Settings.model_validate_json(c.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])


def event(c, job_id: str, stage: str, message: str):
    c.execute('INSERT INTO job_events(job_id,stage,message,at) VALUES (?,?,?,?)', (job_id, stage, message, now()))


def topic(row):
    if row is None:
        return None
    result = dict(row)
    result.update(json.loads(result.pop('data')))
    return result


def job(row):
    if row is None:
        return None
    result = dict(row)
    for field in ('settings', 'script', 'source_data', 'artifacts', 'qa'):
        result[field] = json.loads(result[field]) if result[field] else None
    return result
