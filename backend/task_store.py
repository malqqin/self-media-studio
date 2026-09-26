"""Task definitions and immutable execution snapshots sit above individual media jobs."""
import json
import uuid
import threading
from contextlib import contextmanager
from fastapi import HTTPException
from . import db
from .task_models import TaskSettings

collection_lock=threading.RLock()
collecting=set()


@contextmanager
def collection(ident,version):
    with collection_lock:
        with db.connect() as c:task=require(c,ident,version)
        if ident in collecting:raise HTTPException(409,'任务正在采集资料，请等待完成。')
        collecting.add(ident)
    try:yield task
    finally:
        with collection_lock:collecting.discard(ident)


def init():
    with db.connect() as c:
        from . import wechat_delivery
        wechat_delivery.init(c)
        # Existing creations appear on the task homepage. No content is moved or regenerated.
        for kind,table,column in [('article','articles','document'),('video','jobs','script')]:
            rows=c.execute(f'SELECT * FROM {table} WHERE id NOT IN (SELECT content_id FROM task_runs WHERE content_id IS NOT NULL)').fetchall()
            for row in rows:
                ident='task-'+uuid.uuid4().hex[:16];settings=TaskSettings()
                doc=json.loads(row[column] or 'null') or {}
                name=doc.get('title') or ('历史文章' if kind=='article' else '历史视频')
                if kind=='article':
                    from .article_models import ArticleProfile
                    settings.article=ArticleProfile.model_validate_json(row['profile'])
                    inp=json.loads(row['input_data']);settings.brief=inp.get('brief','')
                    settings.model_id=inp.get('_model_id','default')
                    settings.materials.notes=inp.get('notes','')
                    settings.materials.topic_ids=inp.get('topic_ids',[])
                    settings.materials.mode=inp.get('mode','original')
                else:
                    settings.materials.mode='reference';settings.materials.topic_ids=[row['topic_id']]
                    settings.video.resolution=json.loads(row['settings']).get('resolution','1080p')
                c.execute('INSERT INTO creation_tasks(id,request_id,name,kind,version,settings,archived,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(ident,'import-'+row['id'],name[:80],kind,1,settings.model_dump_json(),0,row['created_at'],row['updated_at']))
                c.execute('INSERT INTO task_runs(id,task_id,request_id,schedule_slot,action,status,stage,settings,content_id,error,reports,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                          ('run-'+uuid.uuid4().hex[:16],ident,'import-'+row['id'],None,'assist','ready','content',settings.model_dump_json(),row['id'],None,'[]',row['created_at'],row['updated_at']))
        if not c.execute("SELECT 1 FROM platform_meta WHERE key='legacy-schedule'").fetchone():
            old=db.settings(c)
            if old.schedule_enabled:
                settings=TaskSettings(execution='automatic');settings.schedule.time=old.schedule_time
                settings.materials.mode='reference'
                from .sources import FEEDS
                settings.materials.urls=[FEEDS[x]['url'] for x in old.sources]+[x.url for x in old.custom_sources if x.enabled]
                settings.materials.urls=settings.materials.urls[:10]
                ident='task-'+uuid.uuid4().hex[:16]
                c.execute('INSERT INTO creation_tasks(id,request_id,name,kind,version,settings,archived,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(ident,'legacy-schedule','原视频自动计划','video',1,settings.model_dump_json(),0,db.now(),db.now()))
                old.schedule_enabled=False
                c.execute('UPDATE settings SET value=%s WHERE id=1',(old.model_dump_json(),))
            c.execute("INSERT INTO platform_meta(key,value) VALUES ('legacy-schedule','migrated')")


def decode(row):
    if not row:return None
    value=dict(row);value['settings']=json.loads(value['settings'])
    return value


def require(c, ident, version=None, *, include_deleted=False):
    if version is not None:db.lock(c,'task',ident)
    value=decode(c.execute('SELECT * FROM creation_tasks WHERE id=%s',(ident,)).fetchone())
    if not value:raise HTTPException(404,'创作任务不存在。')
    deleted=c.execute('SELECT deleted_at FROM deleted_tasks WHERE task_id=%s',(ident,)).fetchone()
    if deleted and not include_deleted:raise HTTPException(404,'任务已删除，可到任务列表的回收站恢复。')
    value['deleted_at']=deleted['deleted_at'] if deleted else None
    if version is not None and version!=value['version']:raise HTTPException(409,'任务配置已更新，请刷新后再操作。')
    return value


def content_status(c, task_kind, run):
    if not run['content_id']:return run
    table={'article':'articles','video':'jobs','image':'image_jobs'}[task_kind]
    column='script' if task_kind=='video' else 'document'
    content=c.execute(f'SELECT status,error,{column} AS content FROM {table} WHERE id=%s',(run['content_id'],)).fetchone()
    if content:run['title']=(json.loads(content['content'] or 'null') or {}).get('title','')
    # Orchestration stays active while it is advancing an automatic workflow.
    if content and run['status'] not in ('queued','running') and run['stage']=='content':
        run['status']=content['status']
        run['error']=content['error']
    return run


def runs(c, task):
    from . import wechat_delivery
    values=[]
    for row in c.execute('SELECT * FROM task_runs WHERE task_id=%s ORDER BY created_at DESC,id DESC',(task['id'],)):
        value=decode(row);value['reports']=json.loads(value['reports'] or '[]')
        value['publication']=wechat_delivery.public(wechat_delivery.get(value['id'],c))
        values.append(content_status(c,task['kind'],value))
    return values


def active(task,history):
    return task['id'] in collecting or any(r['status'] in ('queued','running','publishing') or (task['kind']=='image' and r['status']=='draft') for r in history)


def detail(ident):
    with db.connect() as c:
        value=require(c,ident);value['runs']=runs(c,value)
        value['is_running']=active(value,value['runs'])
        value['topics']=[db.topic(row) for row in c.execute('SELECT t.* FROM topics t JOIN task_sources s ON s.topic_id=t.id WHERE s.task_id=%s ORDER BY s.at DESC LIMIT 100',(ident,))]
    return value


def listing(deleted=False):
    with db.connect() as c:
        result=[]
        for row in c.execute('''SELECT t.*,d.deleted_at FROM creation_tasks t LEFT JOIN deleted_tasks d ON d.task_id=t.id
                              WHERE (d.task_id IS NOT NULL)=%s ORDER BY COALESCE(d.deleted_at,t.created_at) DESC,t.id DESC''',(deleted,)).fetchall():
            value=decode(row);history=runs(c,value);value['latest_run']=history[0] if history else None
            value['is_running']=active(value,history)
            value['run_count']=c.execute('SELECT count(*) FROM task_runs WHERE task_id=%s',(value['id'],)).fetchone()[0]
            result.append(value)
    return result


def records():
    """Public record summaries, excluding deleted tasks and private settings."""
    with db.connect() as c:
        result=[]
        for row in c.execute('SELECT * FROM creation_tasks WHERE id NOT IN (SELECT task_id FROM deleted_tasks)').fetchall():
            task=decode(row)
            for run in runs(c,task):
                result.append({**{k:run[k] for k in ('id','task_id','action','status','created_at','content_id')},
                               'title':run.get('title',''),'task_name':task['name'],'kind':task['kind'],'archived':bool(task['archived'])})
    return sorted(result,key=lambda r:(r['created_at'],r['id']),reverse=True)


def delete(ident,version):
    # Keep content ownership and publication records intact; startup migration
    # must not re-import a deleted task's media as a new task.
    with collection_lock,db.connect() as c:
        db.lock(c,'task',ident);task=require(c,ident,version)
        if ident in collecting:raise HTTPException(409,'任务正在采集资料，请等待完成后再删除。')
        if active(task,runs(c,task)):
            raise HTTPException(409,'任务正在生成或发布，请等待完成后再删除。')
        now=db.now()
        c.execute('INSERT INTO deleted_tasks(task_id,deleted_at) VALUES (%s,%s)',(ident,now))
        c.execute('UPDATE creation_tasks SET archived=1,version=version+1,updated_at=%s WHERE id=%s',(now,ident))
    return {'id':ident,'deleted_at':now,'message':'任务已移入回收站，定时执行已停止。'}


def restore(ident,version):
    with db.connect() as c:
        db.lock(c,'task',ident);task=require(c,ident,version,include_deleted=True)
        if not task['deleted_at']:raise HTTPException(409,'任务不在回收站中。')
        c.execute('DELETE FROM deleted_tasks WHERE task_id=%s',(ident,))
        # Restore into archive so an overdue schedule cannot fire immediately.
        c.execute('UPDATE creation_tasks SET archived=1,version=version+1,updated_at=%s WHERE id=%s',(db.now(),ident))
    return detail(ident)


def owns_queued(c, content_id):
    """The task orchestrator, rather than media recovery, advances its own queue."""
    return bool(c.execute("SELECT 1 FROM task_runs WHERE content_id=%s AND status IN ('queued','running')",(content_id,)).fetchone())
