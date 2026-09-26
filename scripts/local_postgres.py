"""Provision/start an isolated Windows development cluster using existing PG binaries.

Usage: python -m scripts.local_postgres --bin-dir path/to/pgsql/bin
Never uses or changes an existing machine-wide cluster.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import psycopg
from psycopg import sql
from dotenv import set_key, dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path)
    args = parser.parse_args()
    directory = ROOT/'data/postgres-local'
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory/'local.json'
    if manifest.exists():
        settings = json.loads(manifest.read_text())
    else:
        settings = {'port':55432, 'admin_password':secrets.token_urlsafe(36), 'app_password':secrets.token_urlsafe(36)}
        manifest.write_text(json.dumps(settings), encoding='utf-8')
    bindir = (args.bin_dir or Path(settings.get('bin_dir',ROOT/'data/postgres-runtime/pgsql/bin'))).resolve()
    if not (bindir/'initdb.exe').is_file():
        raise SystemExit('未找到 PostgreSQL binaries，请传入 --bin-dir。')
    settings['bin_dir']=str(bindir)
    manifest.write_text(json.dumps(settings),encoding='utf-8')
    manifest.chmod(0o600)
    env = {**os.environ, 'PATH':str(bindir)+os.pathsep+os.environ['PATH']}
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    def run(name, *extra, check=True):
        with (directory/'setup.log').open('ab') as log:
            return subprocess.run([str(bindir/(name+'.exe')), *map(str,extra)],env=env,check=check,
                creationflags=creationflags,stdout=log,stderr=log,stdin=subprocess.DEVNULL,timeout=90)
    cluster = directory/'cluster'
    if not (cluster/'PG_VERSION').exists():
        password_file = directory/'init-password'
        password_file.write_text(settings['admin_password'], encoding='utf-8')
        try:
            run('initdb','-D',cluster,'-U','postgres','--pwfile',password_file,'--auth=scram-sha-256','--encoding=UTF8','--locale=C')
        finally:
            password_file.unlink(missing_ok=True)
        with (cluster/'postgresql.conf').open('a') as f:
            f.write("\nlisten_addresses = '127.0.0.1'\nport = 55432\nmax_connections = 60\n")
    if run('pg_ctl','-D',cluster,'status',check=False).returncode:
        run('pg_ctl','-D',cluster,'-l',directory/'postgres.log','-w','start')
    with psycopg.connect(host='127.0.0.1',port=settings['port'],user='postgres',password=settings['admin_password'],dbname='postgres',autocommit=True) as c:
        if not c.execute("SELECT 1 FROM pg_roles WHERE rolname='studio_app'").fetchone():
            c.execute(sql.SQL('CREATE ROLE studio_app LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS').format(sql.Literal(settings['app_password'])))
        for name in ('studio','studio_test'):
            if not c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():
                c.execute(sql.SQL('CREATE DATABASE {} OWNER studio_app').format(sql.Identifier(name)))
    values = dotenv_values(ROOT/'.env')
    for key,name in (('DATABASE_URL','studio'),('TEST_DATABASE_URL','studio_test')):
        if not values.get(key):
            set_key(ROOT/'.env',key,f"postgresql://studio_app:{settings['app_password']}@127.0.0.1:{settings['port']}/{name}")
    print('本机 PostgreSQL 已就绪（127.0.0.1:55432）；连接配置已保存到 .env。')


if __name__ == '__main__':
    main()
