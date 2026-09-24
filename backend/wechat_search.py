"""Public WeChat search listings, without fabricating readership or bypassing gates."""
from datetime import datetime,timezone
from urllib.parse import urlencode,urljoin,urlsplit,parse_qs
import re
from bs4 import BeautifulSoup
from .network import fetch_public,public_url


def parse_listing(content,url):
    soup=BeautifulSoup(content,'html.parser')
    if '/antispider' in url or '用户您好，您的访问过于频繁' in soup.get_text():
        raise ValueError('公众号搜索要求验证，未取得结果。可打开搜狗微信搜索，找到文章后导入公众号原文链接。')
    items=[]
    for entry in soup.select('ul.news-list li')[:20]:
        anchor=entry.select_one('h3 a[href]');summary=entry.select_one('.txt-info');publisher=entry.select_one('.all-time-y2,.account')
        if not anchor or not summary:continue
        target=public_url(urljoin(url,anchor['href']))
        host=urlsplit(target).hostname
        if host not in ('weixin.sogou.com','mp.weixin.qq.com'):continue
        published=None;stamp=re.search(r"timeConvert\(['\"](\d{10})['\"]\)",str(entry))
        if stamp:published=datetime.fromtimestamp(int(stamp[1]),timezone.utc).isoformat()
        title=anchor.get_text('',strip=True)[:240];account=publisher.get_text(' ',strip=True) if publisher else ''
        text=summary.get_text('',strip=True)
        items.append({'title':title,'url':target,'text':text,'published_at':published,'full_text':False,'method':'wechat-search',
                      'publisher':account,'platform':'wechat','heat':'unknown','dedup_key':'wechat:'+account+':'+title+':'+(published or ''),
                      'access_note':'搜索摘要；原文可能需要验证，阅读量未提供'})
    return items


def search(query, *, max_pages=3):
    url='https://weixin.sogou.com/weixin?'+urlencode({'type':'2','query':query})
    current=url;items=[];seen=set();pages=0;note=''
    # The public site currently redirects requests with tsn/ft/et to its home page.
    # Keep search bounded and enforce the requested date window in task_sources.
    for page in range(1,min(max_pages,3)+1):
        try:
            content,final=fetch_public(current)
            batch=parse_listing(content,final)
            if urlsplit(final).path.rstrip('/')!='/weixin':
                raise ValueError('搜狗没有返回文章搜索页，请打开搜索页面检查后重试。')
        except Exception as error:
            if not pages:raise
            note=(str(error) if isinstance(error,ValueError) else '后续搜索页暂时无法读取。')+' 已停止翻页，仅筛选已取得的结果。'
            break
        pages+=1;added=0
        for item in batch:
            key=item.get('dedup_key') or item['url']
            if key not in seen:
                seen.add(key);items.append(item);added+=1
        if not added or len(items)>=30:break
        soup=BeautifulSoup(content,'html.parser');link=soup.select_one('#sogou_next[href]')
        if not link:break
        next_url=urljoin(final,link['href']);parts=urlsplit(next_url);params=parse_qs(parts.query)
        if (parts.scheme!='https' or parts.netloc!='weixin.sogou.com' or parts.path!='/weixin'
            or params.get('query')!=[query] or params.get('type')!=['2'] or params.get('page')!=[str(page+1)]):break
        current=next_url
    return {'items':items[:30],'search_url':url,'pages_searched':pages,'search_note':note}
