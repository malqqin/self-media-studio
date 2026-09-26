"""Official Unsplash search and download tracking with a local protected key."""
import base64
import json
import os
import re
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field, SecretStr
from . import config, model_config


class Connection(BaseModel):
    access_key: SecretStr = Field(default_factory=lambda: SecretStr(''))
    clear_key: bool = False


def key():
    path=config.data_dir()/'unsplash-connection.json'
    with model_config.lock:
        if not path.exists():return ''
        try:
            value=json.loads(path.read_text(encoding='utf-8'))
            secret=base64.b64decode(value['protected_key'])
            if value['protection']=='windows-dpapi':secret=model_config.secret_transform(secret,decrypt=True)
            return secret.decode()
        except (OSError, ValueError, KeyError, UnicodeError):
            raise ValueError('Unsplash 连接配置无法读取，请重新保存 Access Key。') from None


def public():
    return {'key_configured':bool(key())}


def request(path,params=None,*,access_key=None):
    access_key=key() if access_key is None else access_key
    if not access_key:raise ValueError('请先在搜索来源下方连接 Unsplash，填写官方 Access Key。')
    if path!='search/photos' and not re.fullmatch(r'photos/[\w-]+/download',path,re.ASCII):
        raise ValueError('Unsplash 请求地址无效。')
    try:
        # A fixed official host; keys never enter URLs, logs, or redirect targets.
        with httpx.Client(timeout=httpx.Timeout(10,connect=6),follow_redirects=False,trust_env=False) as client:
            with client.stream('GET','https://api.unsplash.com/'+path,params=params,
                               headers={'Authorization':'Client-ID '+access_key,'Accept-Version':'v1'}) as response:
                if response.status_code==401:raise ValueError('Unsplash Access Key 无效，请检查是否填入了 Access Key。')
                if response.status_code==429 or (response.status_code==403 and response.headers.get('X-Ratelimit-Remaining')=='0'):
                    raise ValueError('Unsplash 请求额度已用完，请稍后再试或调整官方应用额度。')
                if response.is_redirect:raise ValueError('Unsplash 接口返回重定向，已停止请求，请稍后再试。')
                if response.status_code>=400:raise ValueError(f'Unsplash 暂不可用（HTTP {response.status_code}），请检查应用权限或稍后再试。')
                chunks=[];size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>3_000_000:raise ValueError('Unsplash 返回内容过大，请稍后重试。')
                    chunks.append(chunk)
        result=json.loads(b''.join(chunks))
        if not isinstance(result,dict):raise ValueError('Unsplash 返回内容异常。')
        return result
    except httpx.HTTPError:
        raise ValueError('暂时无法连接 Unsplash，请检查网络或选择其他图片来源。') from None
    except json.JSONDecodeError:
        raise ValueError('Unsplash 返回内容异常，请稍后重试。') from None


def save(body):
    access_key=body.access_key.get_secret_value().strip()
    if body.clear_key and access_key:raise ValueError('清除连接与填写新密钥不能同时进行。')
    if not body.clear_key:
        if not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',access_key):raise ValueError('请填写有效的 Unsplash Access Key。')
        result=request('search/photos',{'query':'nature','per_page':1,'content_filter':'high'},access_key=access_key)
        if not isinstance(result.get('results'),list):raise ValueError('Unsplash 未返回有效的搜索结果，原连接已保留。')
    with model_config.lock:
        path=config.data_dir()/'unsplash-connection.json'
        if body.clear_key:
            path.unlink(missing_ok=True)
            return {'key_configured':False}
        value={'protected_key':base64.b64encode(model_config.secret_transform(access_key.encode())).decode(),
               'protection':'windows-dpapi' if os.name=='nt' else 'file-permissions'}
        config.data_dir().mkdir(parents=True,exist_ok=True)
        temporary=config.data_dir()/('.unsplash-'+uuid.uuid4().hex+'.tmp')
        try:
            fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream)
            temporary.replace(path)
        finally:temporary.unlink(missing_ok=True)
    return {'key_configured':True}


def trusted_url(url,host):
    try:
        parsed=urlsplit(url or '')
        return parsed.scheme=='https' and parsed.hostname==host and not parsed.username and not parsed.password and parsed.port in (None,443)
    except (ValueError,TypeError):return False


def attribution_url(url):
    if not trusted_url(url,'unsplash.com'):return ''
    parsed=urlsplit(url)
    query=dict(parse_qsl(parsed.query));query.update(utm_source='self_media_studio',utm_medium='referral')
    return urlunsplit(parsed._replace(query=urlencode(query)))


def search(query,page=1):
    from .pictures import clean, SearchResults
    data=request('search/photos',{'query':query,'page':page,'per_page':24,'content_filter':'high','order_by':'relevant'})
    if not isinstance(data.get('results'),list):raise ValueError('Unsplash 未返回有效的图片列表。')
    results=[]
    for item in data['results']:
        if not isinstance(item,dict) or item.get('premium') or item.get('plus'):continue
        urls=item.get('urls') or {};links=item.get('links') or {};user=item.get('user') or {}
        ident=item.get('id','');download=links.get('download_location','')
        if not isinstance(ident,str) or not re.fullmatch(r'[\w-]+',ident,re.ASCII):continue
        if not trusted_url(download,'api.unsplash.com') or urlsplit(download).path!='/photos/'+ident+'/download':continue
        if not trusted_url(urls.get('regular'),'images.unsplash.com') or not trusted_url(urls.get('small'),'images.unsplash.com'):continue
        page_url=attribution_url(links.get('html'));author=attribution_url((user.get('links') or {}).get('html'))
        if not page_url or not author:continue
        description=clean(item.get('description') or item.get('alt_description'))
        tags=' '.join(clean(tag.get('title')) for tag in item.get('tags',[]) if isinstance(tag,dict))
        results.append({'title':description[:300] or 'Unsplash 摄影作品','description':(description+' '+tags)[:1500],
            'url':urls['regular'],'preview_url':urls['small'],'page_url':page_url,'credit':clean(user.get('name'))[:120],
            'author_url':author,'license':'Unsplash License','license_url':'https://unsplash.com/license',
            'provider':'Unsplash','license_verified':True,'unsplash_id':ident,'download_location':download})
    return SearchResults(results,page<data['total_pages'] if isinstance(data.get('total_pages'),int) else len(data['results'])>=24)


def track_download(item):
    ident=item.get('unsplash_id','');url=item.get('download_location','')
    if not isinstance(ident,str) or not re.fullmatch(r'[\w-]+',ident,re.ASCII) or not trusted_url(url,'api.unsplash.com') or urlsplit(url).path!='/photos/'+ident+'/download':
        raise ValueError('Unsplash 图片来源信息不完整，请重新搜索后选择。')
    # Keep Unsplash's ixid, but never allow a response URL to choose the host.
    params={k:v for k,v in parse_qsl(urlsplit(url).query) if k=='ixid'}
    request('photos/'+ident+'/download',params)
