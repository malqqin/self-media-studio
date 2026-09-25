"""Revise one article's brief and frozen sources without changing its task schedule."""
import json
from fastapi import HTTPException
from . import db, article_worker as worker, article_stream, model_library
from .article_models import ArticleProfile


def require_editable(c,ident,version):
    value=worker.require(c,ident,version)
    run=c.execute('SELECT * FROM task_runs WHERE content_id=?',(ident,)).fetchone()
    if run:
        from . import task_store
        task_store.require(c,run['task_id'])
        if run['status'] in ('queued','running','publishing'):
            raise HTTPException(409,'本次作品正在自动执行或交付公众号，请等待完成后修改选题。')
    return value,run


def source_snapshot(c,body):
    result=[]
    for ident in body.topic_ids:
        topic=db.topic(c.execute('SELECT * FROM topics WHERE id=?',(ident,)).fetchone())
        if not topic:raise ValueError('所选资料已不存在，请重新选择。')
        for source in topic.get('sources',[]):
            if not any(s['id']==source['id'] for s in result):
                page=topic.get('page_data') or {}
                result.append({**source,'full_text':page.get('full_text',False),'captured_at':page.get('captured_at'),'method':page.get('method','rss')})
    if body.notes:
        result.append({'id':'personal-notes','title':'用户提供的笔记','publisher':'手动提供 · 待核验','text':body.notes,'url':'','full_text':True,'method':'notes','captured_at':db.now()})
    return result


def save(ident,body):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        value,run=require_editable(c,ident,body.version)
        if body.action!='save' and not model_library.ready(value['input_data'].get('_model_id','default')):
            raise ValueError('请先配置本次作品使用的 AI 模型。')
        sources=source_snapshot(c,body)
        # Older versions predate source editing: they all used this same source
        # snapshot. Enrich them before the first change so restoration stays exact.
        for row in c.execute('SELECT version,payload FROM article_versions WHERE article_id=?',(ident,)).fetchall():
            payload=json.loads(row['payload'])
            if 'source_data' not in payload:
                payload.update(source_data=value['source_data'],mode=value['mode'])
                c.execute('UPDATE article_versions SET payload=? WHERE article_id=? AND version=?',(db.dump(payload),ident,row['version']))
        inp={**value['input_data'],**body.model_dump(exclude={'version','action','subject'}),'_subject':body.subject}
        for key in ('_rewrite','_context_action','_angle_request','_angle_outline_stale'):inp.pop(key,None)
        inp['_context_revision']=body.version+1
        if body.action!='save':inp.update(_context_action=body.action,angle_index=0)
        if body.action!='save' and value['document']:inp['_picture_previous']=value['document']
        status='draft' if value['document'] else 'needs_outline' if value['outline'] else 'needs_angle'
        stage='review' if value['document'] else 'outline' if value['outline'] else 'angles'
        worker.update(c,ident,version=body.version+1,mode=body.mode,input_data=db.dump(inp),source_data=db.dump(sources),
                      checks=None,error=None,status='queued' if body.action!='save' else status,
                      stage='replan' if body.action!='save' else stage,progress=5 if body.action!='save' else value['progress'],
                      note='选题与资料已保存，正在重新创作。' if body.action!='save' else '选题与资料已更新，当前内容保留，可按新方向重新生成。')
        worker.snapshot(c,ident,'修改本次选题与资料'+('，重新生成'+{'angles':'角度','outline':'大纲','article':'全文'}[body.action] if body.action!='save' else ''))
        if run:
            for topic_id in body.topic_ids:c.execute('INSERT OR IGNORE INTO task_sources VALUES (?,?,?)',(run['task_id'],topic_id,db.now()))
        article_stream.reset(ident)
    if body.action!='save':worker.executor.submit(worker.run,ident)
    return worker.get(ident)


def collect(ident,body):
    from . import task_sources, task_store
    from .task_models import TaskSettings
    with db.connect() as c:
        value,run=require_editable(c,ident,body.version)
        if not run:raise ValueError('请在任务工作台中搜索资料，或直接导入文章链接。')
        task=task_store.require(c,run['task_id'])
    settings=TaskSettings.model_validate({key:value for key,value in json.loads(run['settings']).items() if key in TaskSettings.model_fields})
    settings.brief=body.brief;settings.article=ArticleProfile.model_validate(value['profile'])
    settings.materials.query=body.query;settings.materials.search_scope=body.search_scope;settings.materials.max_age_days=body.max_age_days
    settings.materials.discover=True;settings.materials.urls=[];settings.materials.topic_ids=[]
    settings.model_id=value['input_data'].get('_model_id','default')
    with task_store.collection(run['task_id'],task['version']):
        ids,reports=task_sources.collect(run['task_id'],settings)
        with db.connect() as c:
            topics=[db.topic(c.execute('SELECT * FROM topics WHERE id=?',(i,)).fetchone()) for i in ids]
    return {'topics':topics,'reports':reports}
