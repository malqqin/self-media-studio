"""Direct official-account connections. Credentials never enter task snapshots."""
import base64
from hashlib import sha256
import ipaddress
import json
import os
import re
import threading
import time
import uuid

import httpx
from pydantic import Field
from pydantic import model_validator
from typing import Literal
from . import config, db, model_config
from .article_models import TextModel

lock = threading.RLock()
tokens = {}
API = 'https://api.weixin.qq.com/cgi-bin/'


class AccountInput(TextModel):
    name: str = Field(min_length=1, max_length=40)
    channel: Literal['api','browser'] = 'api'
    subject: Literal['unknown','personal','organization'] = 'unknown'
    appid: str = Field(default='', max_length=18)
    secret: str = Field(default='', max_length=256)

    @model_validator(mode='after')
    def connection_fields(self):
        if self.channel=='api' and not re.fullmatch(r'wx[a-zA-Z0-9]{16}',self.appid):
            raise ValueError('官方 API 接入需要有效的 AppID。')
        if self.channel=='browser' and (self.appid or self.secret):
            raise ValueError('扫码接入不需要 AppID 或 AppSecret。')
        return self


class WeChatError(ValueError):
    def __init__(self, message, *, uncertain=False, code=None):
        super().__init__(message)
        self.uncertain = uncertain
        self.code = code


def whitelist_ip(message):
    """Extract only the rejected IP, never expose the rest of WeChat's diagnostic."""
    match=re.search(r'\binvalid\s+ip\s+([0-9a-fA-F:.]+)(?=[\s,;]|$)',str(message),re.I)
    if not match:return None
    try:
        address=ipaddress.ip_address(match[1])
        if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped:address=address.ipv4_mapped
        return str(address) if address.is_global else None
    except ValueError:return None


def read():
    path = config.DATA / 'wechat-accounts.json'
    if not path.exists():return {}
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):raise ValueError('公众号账号配置无法读取。') from None


def write(values):
    config.DATA.mkdir(parents=True, exist_ok=True)
    path = config.DATA / ('.wechat-'+uuid.uuid4().hex+'.tmp')
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(values, stream, ensure_ascii=False)
        path.replace(config.DATA / 'wechat-accounts.json')
    finally:path.unlink(missing_ok=True)


def public(ident, value):
    return {'id':ident, **{k:value.get(k) for k in ('name','appid','checked_at','draft_ready','publish_ready')},
            'channel':value.get('channel','api'),'subject':value.get('subject','unknown'),
            'session_saved':bool(value.get('protected_session')),
            'secret_configured':bool(value.get('protected_secret'))}


def catalog():
    with lock:return [public(k,v) for k,v in read().items()]


def current(ident):
    with lock:
        value = read().get(ident)
        if not value:raise ValueError('请先连接公众号并选择发布账号。')
        value = dict(value)
        if value.get('channel','api')=='browser':
            value['session_saved']=bool(value.get('protected_session'))
            return {k:v for k,v in value.items() if k not in ('protected_session','session_protection')}
        try:
            secret = base64.b64decode(value.pop('protected_secret'))
            if value.pop('protection') == 'windows-dpapi':secret = model_config.secret_transform(secret, decrypt=True)
            value['secret'] = secret.decode()
        except (ValueError, KeyError, UnicodeError):raise ValueError('公众号密钥无法读取，请重新保存 AppSecret。') from None
        return value


def save(body, ident=None):
    with lock:
        values = read()
        if ident and ident not in values:raise ValueError('公众号账号不存在。')
        old = values.get(ident, {})
        if old and old.get('channel','api')!=body.channel:raise ValueError('已有连接不能更换接入方式，请新增连接。')
        if body.channel=='browser':
            value={**old,'name':body.name,'channel':'browser','subject':body.subject,'appid':old.get('appid',''),
                   'draft_ready':old.get('draft_ready',False),'publish_ready':old.get('publish_ready',False)}
            ident=ident or 'wechat-'+uuid.uuid4().hex[:16]
            values[ident]=value;write(values)
            return public(ident,value)
        if old and old['appid'] != body.appid:raise ValueError('已有连接不能更换 AppID，请新增公众号连接，避免旧任务发到其他账号。')
        if not body.secret and not old.get('protected_secret'):raise ValueError('首次连接需要填写 AppSecret。')
        value = {**old, 'name':body.name, 'appid':body.appid,'channel':body.channel,'subject':body.subject}
        if body.secret:
            value.update(protected_secret=base64.b64encode(model_config.secret_transform(body.secret.encode())).decode(),
                         protection='windows-dpapi' if os.name=='nt' else 'file-permissions',
                         checked_at=None, draft_ready=False, publish_ready=False)
        ident = ident or 'wechat-'+uuid.uuid4().hex[:16]
        values[ident] = value;write(values)
        return public(ident,value)


def request(path, *, token=None, payload=None, files=None, params=None):
    query = dict(params or {})
    if token:query['access_token'] = token
    try:
        with httpx.Client(timeout=httpx.Timeout(40, connect=12), follow_redirects=False) as client:
            # Serialize actual UTF-8 rather than escaped Chinese text.
            method='GET' if path=='draft/count' else 'POST'
            response = client.request(method, API+path, params=query, files=files,
                content=None if files or method=='GET' else db.dump(payload or {}).encode('utf-8'),
                headers={} if files else {'Content-Type':'application/json; charset=utf-8'})
            response.raise_for_status()
            result = response.json()
            if not isinstance(result,dict):raise ValueError()
    except (httpx.HTTPError, ValueError):
        # Never include URLs (access tokens), payloads or raw server messages in errors.
        raise WeChatError('微信接口未返回可确认的结果，请检查网络与公众号后台。', uncertain=True) from None
    code = result.get('errcode',0)
    if code:
        messages = {40013:'AppID 无效。',40125:'AppSecret 无效，请重新填写。',
            40164:'当前服务器公网 IP 不在微信白名单，请在公众号后台配置 IP 白名单后重试。',
            48001:'该公众号尚未获得此接口权限，请检查微信认证与开发者接口权限。',
            40001:'调用凭据失效，请重新检测连接。',40014:'调用凭据失效，请重新检测连接。',42001:'调用凭据已过期，请重试。',
            45009:'微信接口今日额度已用完。',45011:'微信接口调用过于频繁，请稍后再试。',
            89503:'微信要求管理员确认本次接口调用，请在微信中完成确认。',
            53503:'草稿未通过微信发布检查，请到公众号后台查看。',
            53504:'微信要求在公众号后台手动处理此草稿。',53505:'微信要求在公众号后台手动保存后再发表。'}
        message=messages.get(code,'微信接口拒绝了本次请求。')
        if code==40164:
            address=whitelist_ip(result.get('errmsg',''))
            if address:message=f'微信检测到的当前出口 IP：{address}。请在公众号后台的开发配置中，将该 IP 添加到“IP 白名单”，保留原有条目；保存后重新检测连接。'
        raise WeChatError(message+f'（错误码 {code}）',code=code)
    return result


def access_token(account):
    key = (str(config.DATA), account['appid'], sha256(account['secret'].encode()).hexdigest())
    with lock:
        cached = tokens.get(key)
        if cached and cached[1] > time.monotonic()+60:return cached[0]
        result = request('stable_token',payload={'grant_type':'client_credential','appid':account['appid'],
                                               'secret':account['secret'],'force_refresh':False})
        if not result.get('access_token'):raise WeChatError('微信没有返回有效的调用凭据。')
        tokens[key] = (result['access_token'],time.monotonic()+int(result.get('expires_in',7200)))
        return result['access_token']


def call(account, path, *, payload=None, files=None, params=None):
    for attempt in range(2):
        try:return request(path,token=access_token(account),payload=payload,files=files,params=params)
        except WeChatError as error:
            # A definite credential rejection has no side effect; only this case can be replayed.
            if error.code not in (40001,40014,42001) or attempt:raise
            with lock:tokens.clear()


def probe(ident):
    account = current(ident);permissions = {};notes = []
    if account.get('channel')=='browser':
        raise ValueError('扫码连接请使用“扫码登录 / 检查登录”，无需检测 API 或配置 IP 白名单。')
    for mode,path,payload in [('draft','draft/count',{}),('publish','freepublish/batchget',{'offset':0,'count':1,'no_content':1})]:
        try:
            call(account,path,payload=payload);permissions[mode+'_ready'] = True
        except WeChatError as error:
            if error.code != 48001:raise
            permissions[mode+'_ready'] = False;notes.append(('草稿' if mode=='draft' else '发布')+'接口未授权')
    with lock:
        values=read();latest=current(ident)
        if latest['secret'] != account['secret']:raise ValueError('连接已更新，请重新检测。')
        values[ident].update(permissions,checked_at=db.now());write(values)
        return {'account':public(ident,values[ident]),'message':'连接成功。'+('；'.join(notes) if notes else '草稿和发布权限检测通过。')}


def require_ready(ident, mode):
    account = current(ident)
    if mode=='handoff':return account
    if account.get('channel')=='browser':
        if mode=='publish':raise ValueError('扫码自动发布尚未完成验证；可以先选择“保存到公众号草稿箱”。')
        if not account.get('session_saved') or not account.get('appid') or not account.get('draft_ready'):
            raise ValueError('请先扫码登录并确认公众号身份，登录后可自动保存到草稿箱。')
        return account
    if not account.get('draft_ready') or (mode=='publish' and not account.get('publish_ready')):
        raise ValueError('请先检测公众号连接，确认草稿和所需发布权限。')
    return account
