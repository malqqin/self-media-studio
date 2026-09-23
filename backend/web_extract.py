"""Pure extraction for public pages, independent of topic/domain filters."""
from urllib.parse import urljoin, urldefrag, urlsplit
from datetime import datetime
import json
import re
from bs4 import BeautifulSoup
from .network import public_url


def clean(value):return re.sub(r'\s+',' ',value).strip()


def plain(html):
    soup=BeautifulSoup(html,'html.parser')
    for node in soup(['script','style','noscript','nav','footer','form']):node.decompose()
    return clean(soup.get_text(' ',strip=True))


def valid_link(base,value):
    if not value or str(value).startswith(('#','javascript:','mailto:','tel:','data:')):return None
    try:return public_url(urldefrag(urljoin(base,str(value)))[0])
    except ValueError:return None


def extract(content,url):
    soup=BeautifulSoup(content,'html.parser')
    def meta(*names):
        for name in names:
            node=soup.find('meta',attrs={'property':name}) or soup.find('meta',attrs={'name':name})
            if node and node.get('content'):return clean(node['content'])
        return ''
    heading=soup.select_one('#activity-name, h1')
    title=clean(heading.get_text(' ',strip=True)) if heading else meta('og:title','twitter:title')
    title=title or (clean(soup.title.get_text()) if soup.title else urlsplit(url).hostname)
    dedicated=soup.select_one('#js_content, [itemprop="articleBody"], .entry-content, .post-content, .article-content, .rich_media_content')
    articles=soup.find_all('article')
    if dedicated is None and len(articles)==1:dedicated=articles[0]
    main=dedicated if dedicated is not None else soup.find('main') or soup.select_one('[role="main"]') or soup.body or soup
    text=plain(str(main));raw_text=plain(str(soup.body or soup));blocked=None
    # Avoid classifying an article discussing captchas as an access interstitial.
    if (dedicated is None or len(text)<80) and len(raw_text)<1500:
        if any(x in raw_text.casefold() for x in ('当前环境异常','完成验证后即可','verify you are human','checking your browser','人机验证','安全验证','访问过于频繁')):blocked='verification_required'
        elif any(x in raw_text.casefold() for x in ('登录后阅读全文','请登录后查看','sign in to continue','log in to continue','subscribe to continue','订阅后阅读全文')):blocked='login_required'
        elif any(x in raw_text for x in ('该内容已被发布者删除','此内容因违规无法查看','该内容已被删除')):blocked='unavailable'
    structured=[]
    def walk(value):
        if isinstance(value,list):
            for item in value:walk(item)
        elif isinstance(value,dict):
            if isinstance(value.get('articleBody'),str):structured.append(value)
            for key in ('@graph','mainEntity'):walk(value.get(key))
    for script in soup.select('script[type="application/ld+json"]')[:12]:
        try:walk(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError):pass
    if structured:
        item=max(structured,key=lambda x:len(x['articleBody']));body=plain(item['articleBody'])
        if len(body)>len(text):text=body
        if not heading:title=clean(str(item.get('headline') or title))
    description=meta('description','og:description','twitter:description')
    full_text=bool(dedicated is not None or len(text)>=80 or structured)
    if len(text)<40 and description:text=description;full_text=False
    images=[]
    for candidate in [meta('og:image','twitter:image')]+[img.get('data-src') or img.get('data-original') or img.get('src') for img in main.select('img')[:30]]:
        target=valid_link(url,candidate)
        if target and target not in images and not any(word in target.lower() for word in ('logo','avatar','icon','placeholder')):images.append(target)
    links=[]
    for anchor in main.select('a[href]'):
        if anchor.find_parent(['nav','footer','header','form']):continue
        target=valid_link(url,anchor['href']);label=clean(anchor.get_text(' ',strip=True))
        if target and target!=urldefrag(url)[0] and label and not any(x['url']==target for x in links):links.append({'title':label[:240],'url':target})
    is_article=dedicated is not None or meta('og:type')=='article' or bool(structured)
    if not is_article and heading:
        paragraphs=sum(len(p.get_text(' ',strip=True)) for p in main.select('p'))
        is_article=paragraphs>200 and paragraphs>len(text)*.45
    candidates=[]
    if not is_article:
        for anchor in main.select('article a[href], h2 a[href], h3 a[href], .card a[href], .post a[href], .entry a[href], li a[href]'):
            target=valid_link(url,anchor.get('href'))
            if target and target!=url and urlsplit(target).hostname==urlsplit(url).hostname and target not in candidates and len(clean(anchor.get_text()))>=4:candidates.append(target)
    published=meta('article:published_time')
    try:published=datetime.fromisoformat(published.replace('Z','+00:00')).isoformat() if published else None
    except ValueError:published=None
    return {'title':title[:240],'url':url,'text':text[:24000],'published_at':published,
            'full_text':full_text,'images':images[:8],'links':links[:50],'is_article':is_article,
            'candidates':candidates[:8],'blocked':blocked}
