"""One-way, verified SQLite import. Stop the old app before running this command.

python -m scripts.migrate_sqlite --source data/studio.sqlite3
SQLite is read only. A consistent backup is retained; an existing PostgreSQL
workspace cannot be overwritten. An interrupted import may safely be retried.
"""
import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
from psycopg import sql
from backend import config, db
from backend.tenancy import as_user, LEGACY_OWNER

TABLES=('settings','topics','jobs','job_events','reviews','source_runs','ai_usage','daily_runs','assets',
        'article_profiles','articles','article_versions','creation_tasks','task_runs','task_sources',
        'deleted_tasks','image_jobs','platform_meta','picture_candidates','asset_provenance','picture_jobs','wechat_deliveries')
FILES=('assets','jobs','images','reviews','model-config.json','model-library.json','wechat-accounts.json','unsplash-connection.json')


def file_digest(path):
    with path.open('rb') as stream:
        digest=sha256()
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        return digest.hexdigest()


def copy_files(source_dir,destination):
    copied=0
    for name in FILES:
        source=source_dir/name
        if not source.exists():continue
        paths=source.rglob('*') if source.is_dir() else [source]
        for path in paths:
            if not path.is_file():continue
            if path.is_symlink() or not path.resolve().is_relative_to(source_dir.resolve()):
                raise ValueError('迁移目录中存在外部链接，请先处理：'+path.name)
            target=destination/path.relative_to(source_dir)
            if target.exists() and file_digest(target)!=file_digest(path):
                raise ValueError('目标文件与原文件不同，未覆盖：'+str(target.relative_to(destination)))
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
            if file_digest(target)!=file_digest(path):raise ValueError('文件复制校验失败。')
            copied+=1
    return copied


def migrate(source, *, allow_incomplete=False):
    source=Path(source).resolve()
    if not source.is_file():raise ValueError('SQLite 源文件不存在。')
    db.init()
    config.DATA.mkdir(parents=True,exist_ok=True)
    backup_dir=config.DATA/'backups';backup_dir.mkdir(exist_ok=True)
    backup=backup_dir/('before-postgresql-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.sqlite3')
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as original,sqlite3.connect(backup) as target:
        original.backup(target)
    fingerprint=file_digest(backup)
    report={'source_sha256':fingerprint,'backup':str(backup),'tables':{},'files':0}
    with sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True) as old:
        old.row_factory=sqlite3.Row
        if old.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite 完整性检查失败。')
        names={r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not allow_incomplete:
            for table in ('jobs','articles','task_runs','picture_jobs','wechat_deliveries'):
                if table in names and old.execute(f"SELECT 1 FROM {table} WHERE status IN ('queued','running','publishing','drafting','submitting') LIMIT 1").fetchone():
                    raise ValueError('存在未完成任务：'+table+'。请先停止旧服务并处理任务；如确认按现有恢复规则保留，请显式传入 --allow-incomplete。')
        with db.system_connection() as c:
            if c.execute("SELECT 1 FROM server_settings WHERE key='sqlite_import'").fetchone():
                raise ValueError('此数据库已完成 SQLite 导入，不会重复导入。')
            c.execute("INSERT INTO app_users(id,display_name,role,status) VALUES (%s,'管理员','admin','pending_setup') ON CONFLICT DO NOTHING",(LEGACY_OWNER,))
        with as_user(LEGACY_OWNER),db.connect() as c:
            db.lock(c,'sqlite-import')
            for table in TABLES:
                count=c.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]
                if count and table not in ('settings','article_profiles'):
                    raise ValueError('目标工作区已有数据，未覆盖：'+table)
            report['files']=copy_files(source.parent,config.data_dir())
            for table in TABLES:
                if table not in names:continue
                rows=old.execute(f'SELECT * FROM {table}').fetchall()
                columns=[r[1] for r in old.execute(f'PRAGMA table_info({table})')]
                if table in ('settings','article_profiles'):
                    c.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(table)))
                values=[list(r) for r in rows]
                if table=='assets':
                    index=columns.index('path')
                    for value in values:
                        path=Path(value[index])
                        if path.is_absolute():
                            if not path.resolve().is_relative_to(source.parent):raise ValueError('素材路径位于数据目录外，请先迁移外部素材。')
                            value[index]=path.resolve().relative_to(source.parent).as_posix()
                insert=sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns))
                if values:
                    with c.cursor() as cursor:cursor.executemany(insert,values)
                selected=c.execute(sql.SQL('SELECT {} FROM {}').format(sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table))).fetchall()
                # Compare all fields, not only counts. Canonical sorting is independent of row order.
                canonical=lambda data:sorted(db.dump(list(row)) for row in data)
                if canonical(values)!=canonical([list(r.values()) for r in selected]):
                    raise ValueError('迁移内容校验失败：'+table)
                report['tables'][table]=len(values)
            for row in c.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema=%s AND is_identity='YES'",(config.DATABASE_SCHEMA,)).fetchall():
                if row['table_name'] not in TABLES:continue
                table=row['table_name'];column=row['column_name']
                largest=c.execute(sql.SQL('SELECT max({}) FROM {}').format(sql.Identifier(column),sql.Identifier(table))).fetchone()[0]
                if largest is not None:
                    c.execute('SELECT setval(pg_get_serial_sequence(%s,%s),%s,true)',(config.DATABASE_SCHEMA+'.'+table,column,largest))
            c.execute("INSERT INTO server_settings(key,value) VALUES ('sqlite_import',%s)",(db.dump(report),))
    (backup_dir/'postgresql-import-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=config.DATA/'studio.sqlite3')
    parser.add_argument('--allow-incomplete',action='store_true')
    args=parser.parse_args()
    with db.application_lock():
        result=migrate(args.source,allow_incomplete=args.allow_incomplete)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    db.close()


if __name__=='__main__':main()
