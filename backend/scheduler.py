from datetime import datetime
import logging

from . import db
from .sources import collect
from .worker import create
from .ai import curate


def tick():
    from . import task_engine
    task_engine.tick()
    prefs=db.settings();local=datetime.now(db.TZ);today=local.date().isoformat()
    if not prefs.schedule_enabled or local.strftime('%H:%M')<prefs.schedule_time:return
    with db.connect() as c:
        claimed=c.execute('INSERT OR IGNORE INTO daily_runs(day,status,message,at) VALUES (?,?,?,?)',
                          (today,'running','每日采集开始。',db.now())).rowcount
    if not claimed:return
    try:
        collect()
        selection=curate()['ids']
        with db.connect() as c:
            candidates=c.execute('SELECT t.id,t.category FROM topics t WHERE t.kind=? AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.topic_id=t.id) ORDER BY t.published_at DESC,t.score DESC,t.discovered_at DESC',
                                 ('live',)).fetchall()
        choice=next((r for ident in selection for r in candidates if r['id']==ident),None)
        if not choice:raise ValueError('没有新的合格候选，已记录缺稿；不会重复制作旧题。')
        job=create(choice['id'],'ai','daily-'+today)
        status='queued';message='已选题并加入制作队列。';job_id=job['id']
    except Exception as error:
        logging.warning('Daily run: %s',error)
        status='attention';message=str(error)[:700];job_id=None
    with db.connect() as c:
        c.execute('UPDATE daily_runs SET status=?,message=?,job_id=?,at=? WHERE day=?',
                  (status,message,job_id,db.now(),today))
