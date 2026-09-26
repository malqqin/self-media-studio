from urllib.parse import urlencode, urlsplit
from hashlib import sha256
from datetime import datetime, timedelta, timezone
import threading
from . import db, sources
from .task_models import TaskSettings

lock=threading.Lock()


def date_rejection(item,start,end):
    if start is None:return ''
    try:
        stamp=datetime.fromisoformat((item.get('published_at') or '').replace('Z','+00:00'))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError,AttributeError):return '没有可核验的发布时间'
    if stamp>end:return '发布时间晚于本次采集时间'
    if stamp<start:return '超过设置的发布时间范围'
    return ''


def collect(task_id, settings: TaskSettings, *, intent=None):
    from . import editorial, wechat_search
    lock.acquire()
    reports=[];ids=[]
    try:
        collected_at=datetime.now(timezone.utc)
        start=collected_at-timedelta(days=settings.materials.max_age_days) if settings.materials.max_age_days else None
        targets=[{'url':u,'kind':'auto','name':urlsplit(u).hostname} for u in settings.materials.urls]
        if settings.materials.discover:
            intent=intent or editorial.search_intent(settings)
            query=intent['query']
            target={'discovery':True,'name':('公众号文章' if settings.materials.search_scope=='wechat' else '公开网页')+' · '+query[:40]}
            if settings.materials.search_scope=='wechat':target.update(wechat=True,url='https://weixin.sogou.com/weixin?'+urlencode({'type':2,'query':query}))
            else:target.update(url='https://www.bing.com/news/search?'+urlencode({'q':query,'format':'rss','setlang':'zh-cn'}),kind='rss',fallback='https://cn.bing.com/search?'+urlencode({'q':query,'format':'rss'}))
            targets.insert(0,target)
        for target in targets:
            added=0;items=[];excluded=[]
            report={'source':target['name'],'status':'success','count':0,'items':items,'collected_at':collected_at.isoformat()}
            if target.get('discovery'):
                report.update(query=intent['query'],required_terms=intent['required_terms'],search_url=target['url'],heat_note='搜索来源不提供可核验阅读量，不标记为爆款。',
                              date_filter={'max_age_days':settings.materials.max_age_days,'from':start.isoformat() if start else None,'to':collected_at.isoformat()},
                              date_excluded_count=0,relevance_excluded_count=0)
                if target.get('wechat') and start:report['search_note']='搜狗微信当前公开搜索不提供可靠的时间筛选；平台按文章标注的发布时间核验，日期不明的结果不计入近期资料。'
            try:
                fallback=False
                try:result=wechat_search.search(intent['query']) if target.get('wechat') else sources.read_source(target)
                except Exception:
                    if not target.get('fallback'):raise
                    result=sources.read_source({**target,'url':target['fallback']});fallback=True
                    report['search_url']=target['fallback']
                if result.get('pages_searched') is not None:report['pages_searched']=result['pages_searched']
                if result.get('search_note'):report['search_note']=report.get('search_note','')+result['search_note']
                candidates=list({item.get('dedup_key') or item['url']:item for item in result['items']}.values())[:30]
                report['candidate_count']=len(candidates)
                if target.get('discovery'):
                    relevant=[]
                    for item in candidates:
                        reason=date_rejection(item,start,collected_at)
                        if reason:excluded.append(editorial.excluded_item(item,reason,'date'))
                        else:relevant.append(item)
                    report['date_excluded_count']=len(excluded)
                    candidates,rejected=editorial.rank_candidates(relevant,settings,intent)
                    excluded.extend(rejected)
                    report['relevance_excluded_count']=len(rejected)
                report['deferred_count']=max(0,len(candidates)-8)
                wechat_gated=False
                for item in candidates[:8]:
                    # Read full text only for the few selected candidates; gated pages remain clearly marked summaries.
                    if target.get('discovery') and not item.get('full_text'):
                        try:
                            if target.get('wechat'):
                                if wechat_gated:raise ValueError('该搜索来源需要验证，未继续请求其他跳转页。')
                                from .network import fetch_public
                                from .web_extract import extract
                                content,final=fetch_public(item['url'])
                                if urlsplit(final).hostname!='mp.weixin.qq.com':raise ValueError('公众号原文链接需要在浏览器打开，暂仅保存搜索摘要。')
                                full=extract(content,final);full['method']='http';sources.check_page(full)
                            else:full=sources.load_page(item['url'])
                            if full.get('full_text'):
                                item={**item,**full,'published_at':full.get('published_at') or item.get('published_at')}
                        except Exception:
                            if target.get('wechat'):wechat_gated=True
                            item={**item,'access_note':'暂未取得全文，可打开原文后导入正文；目前只使用搜索摘要'}
                    # The article itself may contradict the search listing's date.
                    if target.get('discovery'):
                        reason=date_rejection(item,start,collected_at)
                        if reason:
                            excluded.append(editorial.excluded_item(item,reason,'date'));report['date_excluded_count']+=1
                            continue
                    with db.connect() as c:
                        count,ident=sources.save_item(c,item,target['name'],'task-'+task_id)
                        c.execute('INSERT INTO task_sources(task_id,topic_id,at) VALUES (%s,%s,%s) ON CONFLICT(owner_id,task_id,topic_id) DO UPDATE SET at=excluded.at',(task_id,ident,db.now()))
                        added+=count;ids.append(ident)
                        saved=db.topic(c.execute('SELECT * FROM topics WHERE id=%s',(ident,)).fetchone())
                        items.append({'topic_id':ident,'title':saved['title'],'url':item['url'],
                                      'summary':saved['sources'][0]['text'][:600],'full_text':saved.get('page_data',{}).get('full_text',False),
                                      'publisher':item.get('publisher',saved['sources'][0].get('publisher','')),'published_at':item.get('published_at'),
                                      'platform':item.get('platform','web'),'heat':'unknown','relevance_reason':item.get('relevance_reason','用户指定来源'),
                                      'access_note':item.get('access_note','')})
                empty_note=''
                if not items:
                    if report['candidate_count'] and report.get('date_excluded_count')==report['candidate_count']:
                        empty_note='本次搜索候选均未通过发布时间核验，没有取得所选时间范围内的资料；这不代表全网没有相关文章。可调整检索词、时间范围或导入指定文章。'
                    else:empty_note='本次搜索没有符合主题及时间要求的结果，可调整关键词或导入指定文章。'
                limit_note=f'另有 {report["deferred_count"]} 篇通过筛选，本次最多采集 8 篇。' if report['deferred_count'] else ''
                report.update(count=len(items),excluded=excluded,message=('资讯接口不可用，已使用公开网页搜索；' if fallback else '')+f'检索到 {report["candidate_count"]} 条候选，排除 {len(excluded)} 条，保留 {len(items)} 篇相关资料，新增 {added} 篇。'+limit_note+empty_note)
                if target.get('wechat'):report['message']+=' 公众号结果不等于高阅读爆款；未取得全文的文章不能用于结构或文风模仿。'
            except Exception as error:
                message=str(error) if isinstance(error,ValueError) else '网络或来源暂时无法读取，可导入正文。'
                report.update(status='error',message=message,count=len(items),excluded=excluded,
                              unprocessed_count=max(0,report.get('candidate_count',0)-len(items)-len(excluded)))
            reports.append(report)
        with db.connect() as c:
            for ident in settings.materials.topic_ids:
                if c.execute('SELECT 1 FROM topics WHERE id=%s',(ident,)).fetchone():
                    c.execute('INSERT INTO task_sources(task_id,topic_id,at) VALUES (%s,%s,%s) ON CONFLICT(owner_id,task_id,topic_id) DO UPDATE SET at=excluded.at',(task_id,ident,db.now()))
                    ids.append(ident)
        return list(dict.fromkeys(ids)),reports
    finally:lock.release()


def material_topics(task_id, settings, collected_ids, automatic=False):
    ids=list(dict.fromkeys(settings.materials.topic_ids+collected_ids))
    if automatic and settings.materials.mode=='reference':
        # Only suppress sources used by successful previous executions of this task.
        with db.connect() as c:
            import json
            used=set()
            for row in c.execute("SELECT r.settings FROM task_runs r LEFT JOIN articles a ON a.id=r.content_id LEFT JOIN jobs j ON j.id=r.content_id LEFT JOIN image_jobs i ON i.id=r.content_id WHERE r.task_id=%s AND r.status NOT IN ('queued','running') AND COALESCE(a.status,j.status,i.status) IN ('needs_review','needs_revision','approved')",(task_id,)):
                used.update(json.loads(row['settings']).get('_used_topic_ids',[]))
        ids=[ident for ident in ids if ident not in used]
    if settings.materials.mode=='reference' and settings.materials.reference_style!='facts':
        with db.connect() as c:
            ids=[ident for ident in ids if (db.topic(c.execute('SELECT * FROM topics WHERE id=%s',(ident,)).fetchone()) or {}).get('page_data',{}).get('full_text')]
    return ids[:5]


def note_topic(task_id, brief, notes):
    value='\n\n'.join(v.strip() for v in (brief,notes) if v.strip())
    if len(value)<20:raise ValueError('视频原创制作需要至少 20 字的内容依据，可填写个人笔记或选择参考资料。')
    ident='note-'+sha256((task_id+value).encode()).hexdigest()[:24]
    source={'id':ident,'title':brief[:100] or '创作笔记','text':value,'url':'','publisher':'用户提供的创作笔记'}
    data={'sources':[source],'angle':value[:400],'rights':'用户上传素材，需核对使用权','evidence_status':'手动笔记',
          'page_data':{'full_text':True,'method':'manual','captured_at':db.now(),'images':[],'links':[]},'media':[]}
    with db.connect() as c:
        c.execute('INSERT INTO topics(id,title,category,kind,source,published_at,discovered_at,score,data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',(ident,source['title'],'general','live','创作笔记',None,db.now(),70,db.dump(data)))
        c.execute('INSERT INTO task_sources(task_id,topic_id,at) VALUES (%s,%s,%s) ON CONFLICT(owner_id,task_id,topic_id) DO UPDATE SET at=excluded.at',(task_id,ident,db.now()))
    return ident
