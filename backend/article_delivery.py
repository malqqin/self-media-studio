"""Explicit, durable delivery of an already saved article, without generation."""
import json
from fastapi import HTTPException
from . import db, task_store, article_worker, wechat_delivery
from .task_models import TaskSettings


def queue(run_id, body):
    with db.connect() as c:
        row=c.execute('SELECT * FROM task_runs WHERE id=%s',(run_id,)).fetchone()
        if not row:raise HTTPException(404,'创作记录不存在。')
        db.lock(c,'task',row['task_id'])
        task=task_store.require(c,row['task_id'])
        row=c.execute('SELECT * FROM task_runs WHERE id=%s',(run_id,)).fetchone()
        if task['kind']!='article' or not row['content_id']:raise ValueError('请先完成并保存文章正文。')
        if body.delivery.mode not in ('draft','publish'):raise ValueError('请选择保存草稿或发布到公众号。')
        previous=wechat_delivery.get(run_id,c)
        if previous and previous['status'] in ('queued','preparing','drafting','submitting','publishing','draft','published'):
            data=previous['data']
            if (data['article_version']==body.version and previous['account_id']==body.delivery.account_id
                    and previous['mode']==body.delivery.mode and data.get('author','')==body.delivery.author
                    and data.get('content_declaration','ai')==body.delivery.content_declaration
                    and data.get('cover_asset_id','')==body.delivery.cover_asset_id):
                return wechat_delivery.public(previous)
            raise HTTPException(409,'本次文章正在交付或已交付，请查看交付记录和公众号后台。')
        if any(r['status'] in ('queued','running','publishing') for r in task_store.runs(c,task)):
            raise HTTPException(409,'任务仍在处理中，请等待完成后发送。')
        db.lock(c,'article',row['content_id'])
        article=article_worker.require(c,row['content_id'],body.version)
        raw=json.loads(row['settings'])
        settings=TaskSettings.model_validate({k:v for k,v in raw.items() if not k.startswith('_')})
        settings.wechat_delivery=body.delivery
        recovery=None
        if previous:
            if wechat_delivery.can_resume(previous):
                if not body.resume:raise HTTPException(409,'微信已有待核对草稿，请选择“继续保存原草稿”。')
                if body.delivery.account_id!=previous['account_id'] or body.delivery.mode!='draft':
                    raise HTTPException(409,'继续原草稿时不能更换公众号或改为公开发布。')
                recovery={k:previous['data'][k] for k in ('browser_editor','browser_draft_id')}
                recovery['_resume_title']=previous['data'].get('_resume_title',previous['data']['title'])
                recovery['_resume_browser']=True
            elif previous['status']=='uncertain' or previous['data'].get('publish_id'):
                raise HTTPException(409,'上次提交结果尚未确认，且无法安全定位原草稿；请到公众号后台核对，系统不会新建重复稿件。')
            elif previous['data'].get('media_id'):
                raise HTTPException(409,'已有微信草稿，请在公众号后台继续处理，系统不会重复提交。')
            c.execute('DELETE FROM wechat_deliveries WHERE run_id=%s',(run_id,))
        elif body.resume:
            raise HTTPException(409,'没有可以继续保存的公众号草稿。')
        # Snapshot validation and queue claim commit together. The background
        # worker reads only this frozen document, never generates an article.
        prepared=wechat_delivery._prepare(run_id,article,settings,c)
        data=prepared['data']
        if recovery:data.update(recovery)
        c.execute("UPDATE wechat_deliveries SET status='queued',data=%s WHERE run_id=%s",(db.dump(data),run_id))
        raw=json.loads(row['settings']);raw['_delivery_only']=True
        c.execute("UPDATE task_runs SET status='queued',stage='delivery',settings=%s,error=NULL,updated_at=%s WHERE id=%s",
                  (db.dump(raw),db.now(),run_id))
        result=wechat_delivery.public(wechat_delivery.get(run_id,c))
    from .task_engine import executor,run
    executor.submit(run,run_id)
    return result


def execute(run_id):
    value=wechat_delivery.get(run_id)
    if not value:raise ValueError('未找到本次交付快照，请重新选择发送文章。')
    data=value['data']
    if data.get('_resume_browser'):
        from . import wechat_browser_delivery
        try:wechat_browser_delivery.resume(value)
        except Exception as error:
            message=str(error) if isinstance(error,ValueError) else '继续保存原草稿未完成，请检查公众号连接后重试。'
            wechat_delivery.update(run_id,'uncertain',data,message+' 原草稿编号已保留，不会新建重复稿件。')
        return
    settings=TaskSettings(wechat_delivery={'mode':value['mode'],'account_id':value['account_id'],
                                         'author':data['author'],'cover_asset_id':data['cover_asset_id'],
                                         'content_declaration':data.get('content_declaration','ai')})
    article={'id':value['article_id'],'version':data['article_version'],'document':data['document'],
             'status':'needs_review','checks':data.get('checks'),'source_data':data.get('source_data',[])}
    wechat_delivery.deliver(run_id,article,settings)
