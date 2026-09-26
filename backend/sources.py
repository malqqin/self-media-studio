from datetime import datetime, timezone
from hashlib import sha256
from urllib.parse import urljoin, urldefrag, urlsplit
import re
import threading
from bs4 import BeautifulSoup
import feedparser
import httpx
from . import db
from .network import public_url, fetch_public
from .browser_fetch import render_public
from .web_extract import extract, plain

FEEDS={
 'nasa':{'id':'nasa','name':'NASA','url':'https://www.nasa.gov/feed/','kind':'rss','description':'NASA 官方新闻与科学动态'},
 'esa':{'id':'esa','name':'ESA','url':'https://www.esa.int/rssfeed/Our_Activities/Space_Science','kind':'rss','description':'欧洲航天局空间科学动态'},
 'cern':{'id':'cern','name':'CERN','url':'https://home.cern/feed/','kind':'rss','description':'欧洲核子研究中心新闻'},
 'nature':{'id':'nature','name':'Nature','url':'https://www.nature.com/nature.rss','kind':'rss','description':'Nature 文章摘要，部分正文需要订阅'},
}
collection_lock=threading.Lock()


def safe_url(url):
    try:public_url(url);return True
    except ValueError:return False


def download(url,limit=3_000_000):return fetch_public(url,limit)[0]


class PageAccessError(ValueError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


def check_page(item):
    code=item.get('blocked')
    if code=='verification_required':
        raise PageAccessError(code,'网站向采集浏览器返回了验证页，尚未取得正文。你的日常浏览器可能已有访问状态；可打开原文后使用“导入网页正文”。')
    if code=='login_required':
        raise PageAccessError(code,'网站要求登录或订阅，采集浏览器没有对应访问状态。可在有权访问的浏览器中打开，再导入网页正文。')
    if code=='unavailable':raise PageAccessError(code,'网站提示该内容已删除或无法查看。')
    if len(item['text'].strip())<20 and len(item.get('candidates',[]))<2:
        raise PageAccessError('no_content','网页已打开，但没有提取到可读内容；可能是图片/视频页或尚未加载。可选择“浏览器加载”，或导入网页正文。')


def load_page(url,content=None,force_browser=False):
    item=None
    if not force_browser:
        if content is None:
            try:content=download(url)
            except httpx.HTTPError:content=b''
        item=extract(content,url);item['method']='http'
    if force_browser or item.get('blocked') or (len(item['text'])<80 and len(item.get('candidates',[]))<2 and (not item.get('is_article') or len(item['text'])<20)):
        try:
            html,final_url=render_public(url)
            rendered=extract(html,final_url);rendered['method']='browser'
            if force_browser or rendered.get('blocked') or len(rendered['text'])>=len(item['text']):item=rendered
        except ValueError as error:
            if not item or item.get('blocked') or len(item['text'])<20:
                if item and item.get('blocked'):check_page(item)
                raise error
    check_page(item)
    return item


def article(content,url):return extract(content,url)


def read_source(source):
    url=source['url'];kind=source.get('kind','auto');content=b''
    if kind!='browser':
        try:content=download(url)
        except httpx.HTTPError:
            if kind=='rss':raise
    parsed=feedparser.parse(content) if kind in ('auto','rss') else None
    preliminary=extract(content,url)
    # A specific article remains an article, even if the site advertises a feed.
    if not (parsed and parsed.entries) and kind=='auto' and not preliminary['is_article'] and not preliminary['blocked']:
        soup=BeautifulSoup(content,'html.parser')
        link=soup.find('link',attrs={'type':re.compile(r'application/(rss|atom)\+xml')})
        if link and link.get('href'):
            discovered=urldefrag(urljoin(url,link['href']))[0]
            if safe_url(discovered):
                try:parsed=feedparser.parse(download(discovered))
                except (ValueError,httpx.HTTPError):pass
    if parsed and parsed.entries:
        candidates=[]
        for entry in parsed.entries[:20]:
            target=urldefrag(urljoin(url,entry.get('link','')))[0]
            if not entry.get('link') or not safe_url(target):continue
            title=plain(entry.get('title',''))[:240]
            content_text=(entry.get('content') or [{}])[0].get('value','')
            summary=plain(entry.get('summary') or content_text)[:6000]
            if not title:continue
            if len(summary)<20:
                try:candidates.append(load_page(target));continue
                except (ValueError,httpx.HTTPError):continue
            published=None
            stamp=entry.get('published_parsed') or entry.get('updated_parsed')
            if stamp:
                try:published=datetime(*stamp[:6],tzinfo=timezone.utc).isoformat()
                except ValueError:pass
            candidates.append({'title':title,'url':target,'text':summary,'published_at':published,'full_text':False,'method':'rss'})
        if not candidates:raise ValueError('订阅源有条目，但暂未取得可读摘要或正文。')
        return {'kind':'rss','items':candidates,'note':'按原文链接去重；已保存摘要，制作时补充正文。'}
    if kind=='rss':raise ValueError('没有找到 RSS/Atom 条目，可以改用自动识别或浏览器加载。')
    item=load_page(url,content,force_browser=kind=='browser')
    items=[];failed=0
    if len(item['candidates'])>=2:
        for target in item['candidates']:
            try:items.append(load_page(target,force_browser=kind=='browser'))
            except (ValueError,httpx.HTTPError):failed+=1
    if not items:items=[item]
    methods={'http':'网页直读','browser':'浏览器加载','rss':'订阅摘要'}
    modes='、'.join(sorted({methods.get(i['method'],i['method']) for i in items}))
    note=f'{modes}；已保存正文、图片地址和链接，不限制内容领域。'
    if failed:note+=f' {failed} 个子页面未能读取。'
    if any(not i['full_text'] for i in items):note+=' 部分内容仅取得页面摘要，制作前需核验。'
    return {'kind':'page','items':items,'note':note}


def preview(source):
    try:
        result=read_source(source)
        return {'kind':result['kind'],'count':len(result['items']),'note':result['note'],
                'items':[{'title':i['title'],'url':i['url'],'summary':i['text'][:350],
                          'method':i.get('method','http'),'image_count':len(i.get('images',[]))} for i in result['items'][:5]]}
    except httpx.HTTPStatusError as error:raise ValueError(f'来源返回 HTTP {error.response.status_code}，请检查地址或访问条件。') from None
    except httpx.RequestError:raise ValueError('来源连接失败或超时，请检查网址与网络。') from None


def enabled_sources():
    prefs=db.settings()
    return [FEEDS[ident] for ident in prefs.sources]+[s.model_dump() for s in prefs.custom_sources if s.enabled]


def save_item(c,item,label,source_id):
    link=item['url'];ident='feed-'+sha256(item.get('dedup_key',link).encode()).hexdigest()[:24]
    source={'id':ident,'title':item['title'],'url':link,'publisher':item.get('publisher') or label,'text':item['text']}
    data={'angle':item['text'][:400],'sources':[source],'source_config_id':source_id,
          'rights':'来源页图片需核对相关性、署名与使用条件',
          'evidence_status':'手动导入正文 · 待核验' if item.get('method')=='manual' else '网页正文快照' if item['full_text'] else '页面摘要 · 制作时补充正文',
          'page_data':{'method':item.get('method','http'),'full_text':item['full_text'],'images':item.get('images',[]),'links':item.get('links',[]),'captured_at':db.now(),
                       **{k:item[k] for k in ('platform','heat','relevance_reason','access_note') if k in item}}}
    if item['full_text']:
        data['media']=[{'url':u,'page_url':link,'credit':label,'rights':'来源页关联图片；发布前核对图片署名与使用条件','filename':label+' 来源图片'} for u in item.get('images',[])[:5]]
    count=c.execute('INSERT INTO topics(id,title,category,kind,source,published_at,discovered_at,score,data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                    (ident,item['title'],'general','live',label,item['published_at'],db.now(),70,db.dump(data))).rowcount
    return count,ident


def import_page(body):
    # An explicit import is a snapshot, not a claim that a crawler verified the text.
    item={'url':body.url,'title':body.title,'text':body.text,'published_at':None,'full_text':True,'method':'manual'}
    updated=False
    with db.connect() as c:
        db.lock(c,'topic-import',body.url)
        added,ident=save_item(c,item,urlsplit(body.url).hostname,'manual')
        if not added:
            existing=db.topic(c.execute('SELECT * FROM topics WHERE id=%s',(ident,)).fetchone())
            if not existing.get('page_data',{}).get('full_text'):
                for key in ('id','title','category','kind','source','published_at','discovered_at','score'):existing.pop(key,None)
                existing.pop('curation',None)
                existing.update(angle=body.text[:400],evidence_status='手动导入正文 · 待核验',
                    page_data={'method':'manual','full_text':True,'images':[],'links':[],'captured_at':db.now()})
                existing['sources'][0].update(text=body.text,title=body.title)
                c.execute('UPDATE topics SET title=%s,score=70,data=%s WHERE id=%s',(body.title,db.dump(existing),ident))
                updated=True
    message='正文已导入，保留原文链接，请核对内容与素材。' if added else '已为该网址补充完整正文，已有成片及审核记录保留。' if updated else '该网址已收录完整正文，未覆盖已有资料。'
    return {'added':added,'updated':updated,'topic_id':ident,'message':message}


def collect():
    if not collection_lock.acquire(blocking=False):raise ValueError('采集正在进行，请稍后查看结果。')
    reports=[]
    try:
        sources=enabled_sources()
        if not sources:raise ValueError('还没有配置采集源，请在素材库输入网址并点击“保存并采集”。')
        for source_config in sources:
            count=0;source_id=source_config['id'];label=source_config['name'];code=None
            try:
                result=read_source(source_config)
                with db.connect() as c:
                    for item in result['items']:count+=save_item(c,item,label,source_id)[0]
                status='success';message=f'{label}：新增 {count} 条资料，按链接去重。{result["note"]}'
            except Exception as error:
                status='error';code=getattr(error,'code','fetch_failed')
                reason=str(error) if isinstance(error,ValueError) else f'HTTP {error.response.status_code}' if isinstance(error,httpx.HTTPStatusError) else '网络连接失败或来源无法读取'
                message=f'{label}：{reason}'
            with db.connect() as c:
                c.execute('INSERT INTO source_runs(source,status,count,message,at) VALUES (%s,%s,%s,%s,%s)',(source_id,status,count,message,db.now()))
            reports.append({'source':source_id,'url':source_config['url'],'status':status,'count':count,'message':message,'code':code})
        return {'reports':reports,'added':sum(r['count'] for r in reports)}
    finally:collection_lock.release()


def hydrate(topic):
    # Reuse the full snapshot so browser-only pages do not fail again at production.
    snapshot=topic.get('page_data',{})
    if snapshot.get('full_text'):
        topic.setdefault('media',[])
        return topic
    source=topic['sources'][0].copy();item=load_page(source['url'])
    source['text']=item['text'];source['url']=item['url']
    if not item['full_text']:raise ValueError('目前仅取得页面摘要。可导入完整正文后再制作，避免基于不足的资料编写文案。')
    topic['sources']=[source]
    topic['media']=[{'url':u,'page_url':item['url'],'credit':source['publisher'],
                     'rights':'来源页关联图片；发布前核对图片署名与使用条件','filename':source['publisher']+' 来源图片'} for u in item['images'][:5]]
    return topic
