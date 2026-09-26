"""Durable draft/publish state. Unknown write outcomes are never blindly retried."""
from datetime import datetime, timedelta, timezone
import io
import json
import re
import threading
from urllib.parse import urlsplit

from PIL import Image, ImageOps
from . import db, article_export, wechat_accounts, wechat_declarations
from .media import asset_path
from .article_templates import decoration_path

lock = threading.RLock()


def init(c):
    return  # Managed by versioned migrations.


def get(run_id, c=None):
    if c is None:
        with db.connect() as conn:return get(run_id,conn)
    row=c.execute('SELECT * FROM wechat_deliveries WHERE run_id=%s',(run_id,)).fetchone()
    if not row:return None
    value=dict(row);value['data']=json.loads(value['data']);return value


def public(value):
    if not value:return None
    data=value['data']
    return {**{k:value[k] for k in ('mode','status','error','updated_at')},
            **{k:data.get(k) for k in ('account_name','appid','article_version','title','media_id','publish_id','article_url')},
            'channel':data.get('channel','api'), 'account_id':value['account_id'],
            'author':data.get('author',''),'cover_asset_id':data.get('cover_asset_id',''),
            'content_declaration':data.get('content_declaration','ai'),
            'declaration_applied':data.get('declaration_applied',False),
            'can_resume':can_resume(value),
            'can_retry':value['status']=='failed' and not data.get('publish_id')}


def can_resume(value):
    data=value['data']
    return (value['status'] in ('uncertain','failed') and data.get('channel')=='browser'
            and value['mode']=='draft' and not data.get('publish_id')
            and bool(re.fullmatch(r'\d+',str(data.get('browser_draft_id','')))) and bool(data.get('browser_editor')))


def update(run_id,status,data,error=None):
    states={'queued':'queued','preparing':'running','drafting':'running','submitting':'running','publishing':'publishing',
            'draft':'wechat_draft','published':'published','failed':'failed','uncertain':'failed','awaiting_publish':'awaiting_publish'}
    with db.connect() as c:
        c.execute('UPDATE wechat_deliveries SET status=%s,data=%s,error=%s,updated_at=%s WHERE run_id=%s',
                  (status,db.dump(data),error,db.now(),run_id))
        c.execute('UPDATE task_runs SET status=%s,stage=%s,error=%s,updated_at=%s WHERE id=%s',
                  (states[status],'delivery',error if states[status]=='failed' else None,db.now(),run_id))


def image_bytes(ident):
    path=decoration_path(ident)
    if not path:
        with db.connect() as c:row=c.execute('SELECT * FROM assets WHERE id=%s',(ident,)).fetchone()
        if not row or not row['media_type'].startswith('image/'):raise ValueError('请为自动发布选择有效的默认封面图片。')
        path=asset_path(dict(row))
    if not path.is_file():raise ValueError('所选发布图片文件不存在，请重新上传。')
    with Image.open(path) as original:
        picture=ImageOps.exif_transpose(original).convert('RGB');picture.thumbnail((1600,1600))
        for quality in (90,80,65):
            output=io.BytesIO();picture.save(output,format='JPEG',quality=quality)
            if output.tell()<1_000_000:return output.getvalue()
    raise ValueError('发布图片压缩后仍然过大，请选择较小的图片。')


def inline_image(ident):
    """Prepare a WeChat-compatible body image."""
    return ident+'.jpg',image_bytes(ident),'image/jpeg'


def validate(settings):
    delivery=settings.wechat_delivery
    if delivery.mode=='local':return
    account=wechat_accounts.require_ready(delivery.account_id,delivery.mode)
    wechat_declarations.validate_delivery(delivery,account)
    if account.get('channel')=='browser' and delivery.mode!='handoff' and len(delivery.author)>8:
        raise ValueError('公众号网页版署名最多 8 字，请缩短署名。')
    generated_cover=settings.illustration.enabled and settings.illustration.cover
    if delivery.cover_asset_id or (delivery.mode!='handoff' and not generated_cover):image_bytes(delivery.cover_asset_id)


def _prepare(run_id,article,settings,c=None):
    delivery=settings.wechat_delivery
    account=wechat_accounts.require_ready(delivery.account_id,delivery.mode)
    wechat_declarations.validate_delivery(delivery,account)
    if not article.get('document') or article['status'] in ('queued','running','needs_angle','needs_outline'):
        raise ValueError('文章尚未生成完成，未发送到公众号。')
    if delivery.mode=='publish' and (article['status'] not in ('needs_review','needs_revision','approved') or not article.get('checks') or any(i['severity']=='error' for i in article['checks']['issues'])):
        raise ValueError('文章检查存在未解决的问题，已保留本地正文，未自动发布。请修订并完成检查后重试。')
    doc=article['document']
    if delivery.mode!='handoff':image_bytes(doc.get('cover_asset_id') or delivery.cover_asset_id)
    if len(doc['title'])>32:raise ValueError('微信标题不能超过 32 字，请缩短标题并完成检查后重试。')
    if len(doc['summary'])>120:raise ValueError('微信摘要不能超过 120 字，请缩短摘要并完成检查后重试。')
    if account.get('channel')=='browser' and len(delivery.author)>8:raise ValueError('公众号网页版署名最多 8 字，请缩短署名。')
    data={'account_name':account['name'],'appid':account['appid'],'article_version':article['version'],
          'channel':account.get('channel','api'),'source_data':article.get('source_data',[]),'checks':article.get('checks'),
          'title':doc['title'],'document':doc,'author':delivery.author,'content_declaration':delivery.content_declaration,
          'cover_asset_id':doc.get('cover_asset_id') or delivery.cover_asset_id,'images':{}}
    def insert(conn):
        conn.execute('INSERT INTO wechat_deliveries(run_id,article_id,account_id,mode,status,data,error,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                  (run_id,article['id'],delivery.account_id,delivery.mode,'preparing',db.dump(data),None,db.now(),db.now()))
        return get(run_id,conn)
    if c is not None:return insert(c)
    with db.connect() as conn:return insert(conn)


def deliver(run_id,article,settings):
    with lock:
        value=get(run_id)
        if value and value['status']=='failed' and not value['data'].get('media_id') and value['data']['article_version']!=article['version']:
            # No draft was accepted: an explicitly edited/rechecked revision may replace the failed snapshot.
            with db.connect() as c:c.execute('DELETE FROM wechat_deliveries WHERE run_id=%s',(run_id,))
            value=None
        value=value or _prepare(run_id,article,settings)
        data=value['data'];status=value['status']
        if value['mode']=='handoff':
            update(run_id,'awaiting_publish',data);return
        if status in ('published','draft') and (status=='published' or value['mode']=='draft'):
            update(run_id,status,data);return
        if status in ('uncertain','drafting','submitting'):
            update(run_id,'uncertain',data,'上次提交结果未确认，请到公众号后台核对；为避免重复文章，不会自动重新提交。');return
        if data.get('publish_id'):
            if status=='failed':
                update(run_id,'failed',data,value['error']);return
            update(run_id,'publishing',data);return
        try:
            account=wechat_accounts.require_ready(value['account_id'],value['mode'])
            if account['appid']!=data['appid']:raise ValueError('发布账号与本次执行记录不一致。')
            # Apply capability checks to resumed snapshots too, before any write.
            from .task_models import WeChatDelivery
            wechat_declarations.validate_delivery(WeChatDelivery(mode=value['mode'],content_declaration=data.get('content_declaration','ai')),account)
            if data.get('channel')=='browser':
                from . import wechat_browser_delivery
                wechat_browser_delivery.deliver(value);return
            if not data.get('media_id'):
                update(run_id,'preparing',data)
                doc=data['document']
                body_ids=article_export.body_image_ids(doc,wechat=True)
                ids=list(dict.fromkeys([data['cover_asset_id'],*body_ids]))
                for ident in filter(None,ids):
                    if ident==data['cover_asset_id'] and not data.get('thumb_media_id'):
                        content=image_bytes(ident)
                        result=wechat_accounts.call(account,'material/add_material',params={'type':'image'},files={'media':('cover.jpg',content,'image/jpeg')})
                        if not result.get('media_id'):raise ValueError('微信未返回封面素材编号。')
                        data['thumb_media_id']=result['media_id'];update(run_id,'preparing',data)
                    if ident not in data['images'] and ident in body_ids:
                        media=inline_image(ident)
                        result=wechat_accounts.call(account,'media/uploadimg',files={'media':media})
                        if urlsplit(result.get('url','')).scheme not in ('https','http'):raise ValueError('微信未返回有效的正文图片地址。')
                        data['images'][ident]=result['url'];update(run_id,'preparing',data)
                body=article_export.html_body(doc,data['images'],wechat=True)
                if len(body)>=20000 or len(body.encode())>=1_000_000:raise ValueError('文章排版超过微信接口长度限制，请缩短后重新执行。')
                payload={'articles':[{'article_type':'news','title':doc['title'],'author':data['author'],
                    'digest':doc['summary'],'content':body,'thumb_media_id':data['thumb_media_id'],'need_open_comment':0}]}
                # Commit intent before the write, so crashes cannot trigger a duplicate draft.
                update(run_id,'drafting',data)
                result=wechat_accounts.call(account,'draft/add',payload=payload)
                if not result.get('media_id'):raise wechat_accounts.WeChatError('微信未返回草稿编号，提交结果未确认。',uncertain=True)
                data['media_id']=result['media_id'];update(run_id,'preparing',data)
            if value['mode']=='draft':
                update(run_id,'draft',data);return
            update(run_id,'submitting',data)
            result=wechat_accounts.call(account,'freepublish/submit',payload={'media_id':data['media_id']})
            if not result.get('publish_id'):raise wechat_accounts.WeChatError('微信未返回发布任务编号，提交结果未确认。',uncertain=True)
            data['publish_id']=str(result['publish_id']);update(run_id,'publishing',data)
        except Exception as error:
            phase=get(run_id)['status']
            unknown=phase in ('drafting','submitting') and (data.get('channel')=='browser' or not isinstance(error,ValueError) or getattr(error,'uncertain',False))
            message=str(error) if isinstance(error,ValueError) else '公众号处理未完成，请检查连接后重试。'
            if unknown:message+=' 请到公众号后台核对，系统不会重复提交。'
            update(run_id,'uncertain' if unknown else 'failed',data,message)


def refresh(run_id):
    with lock:
        value=get(run_id)
        if not value or value['status']!='publishing':return public(value)
        data=value['data']
        try:
            account=wechat_accounts.current(value['account_id'])
            result=wechat_accounts.call(account,'freepublish/get',payload={'publish_id':data['publish_id']})
            status=result.get('publish_status')
            if status==0:
                items=(result.get('article_detail') or {}).get('item',[])
                url=next((v.get('article_url','') for v in items if v.get('article_url')),'')
                if urlsplit(url).hostname!='mp.weixin.qq.com' or urlsplit(url).scheme not in ('http','https'):
                    raise ValueError('微信已处理发布，文章链接尚未完整返回，将继续查询。')
                data['article_url']=url;data['article_id']=result.get('article_id');update(run_id,'published',data)
            elif status==1:update(run_id,'publishing',data)
            elif status in (2,3,4,5,6):
                messages={2:'原创检查未通过',3:'发布失败',4:'平台审核未通过',5:'文章已被删除',6:'文章已被平台封禁'}
                update(run_id,'failed',data,'微信返回：'+messages[status]+'。请到公众号后台查看；本次不会重新提交。')
            else:raise ValueError('微信返回的发布状态暂无法识别，将继续查询。')
        except Exception as error:
            message=str(error) if isinstance(error,ValueError) else '暂未取得微信发布结果。'
            update(run_id,'publishing',data,message+' 稍后自动继续查询，不会重复发布。')
        return public(get(run_id))


def handoff_article(run_id):
    value=get(run_id)
    if not value or value['mode']!='handoff' or value['status']!='awaiting_publish':
        raise ValueError('本次执行没有待发布稿件。')
    data=value['data']
    doc={**data['document'],'cover_asset_id':data['document'].get('cover_asset_id') or data.get('cover_asset_id','')}
    return {'document':doc,'source_data':data.get('source_data',[]),'checks':data.get('checks')}


def handoff_content(run_id):
    article=handoff_article(run_id)
    return {'title':article['document']['title'],'html':article_export.html_body(article['document'],wechat=True),
            'text':article_export.markdown(article['document'],wechat=True),
            'content_declaration':get(run_id)['data'].get('content_declaration','ai')}


def tick():
    if not lock.acquire(blocking=False):return
    try:
        cutoff=(datetime.now(timezone.utc)-timedelta(seconds=25)).isoformat()
        with db.connect() as c:
            ids=[r['run_id'] for r in c.execute("SELECT run_id FROM wechat_deliveries WHERE status='publishing' AND updated_at<%s ORDER BY updated_at LIMIT 5",(cutoff,))]
        for ident in ids:refresh(ident)
    finally:lock.release()


def recover():
    with db.connect() as c:
        queued=[get(r['run_id'],c) for r in c.execute("SELECT d.run_id FROM wechat_deliveries d JOIN task_runs r ON r.id=d.run_id AND r.owner_id=d.owner_id WHERE d.status='queued' AND r.status!='queued'").fetchall()]
        values=[get(r['run_id'],c) for r in c.execute("SELECT run_id FROM wechat_deliveries WHERE status IN ('preparing','drafting','submitting','publishing')").fetchall()]
    for value in queued:
        update(value['run_id'],'failed',value['data'],'交付启动前服务中断，文章快照已保留，可继续发送当前文章。')
    for value in values:
        if value['status']=='preparing':
            update(value['run_id'],'failed',value['data'],'服务在准备素材期间中断，可重试继续本次交付。');continue
        status='publishing' if value['data'].get('publish_id') else 'uncertain'
        update(value['run_id'],status,value['data'],None if status=='publishing' else '服务在提交期间中断，请到公众号后台核对；不会自动重复提交。')
