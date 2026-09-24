"""Isolated QR login. This module performs no draft or publish writes.

Playwright stays on its owning thread. Only encrypted storage state is persisted;
no normal browser profile, tokens, raw URLs or cookies reach the public API.
"""
import base64
import json
import os
import queue
import re
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
from . import config, db, model_config, wechat_accounts

lock=threading.RLock()
sessions={}
LOGIN='https://mp.weixin.qq.com/'
QR='img.login__type__container__scan__qrcode'
ACTIVE=('starting','waiting_scan')
TTL=300


def executable():
    candidates=[os.getenv('STUDIO_BROWSER_PATH',''),
                r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
                r'C:\Program Files\Google\Chrome\Application\chrome.exe']
    return next((p for p in candidates if p and Path(p).is_file()),None)


def _key(ident):return (str(config.DATA),ident)


def _require(ident):
    if wechat_accounts.current(ident).get('channel')!='browser':raise ValueError('此账号使用官方 API，请使用接口检测。')


def public(value):
    return {k:value.get(k) for k in ('status','message','updated_at','has_qr','has_preview')}


def status(ident):
    _require(ident)
    with lock:
        value=sessions.get(_key(ident))
        return public(value) if value else {'status':'idle','message':'点击扫码登录，检查或建立独立登录会话。','has_qr':False,'updated_at':None}


def _set(value,status,message,qr=None,preview=None):
    with lock:
        if value['stop'].is_set() and status!='idle':return
        value.update(status=status,message=message,updated_at=db.now(),qr=qr,has_qr=bool(qr),preview=preview,has_preview=bool(preview))


def _load(ident):
    with wechat_accounts.lock:
        value=wechat_accounts.read().get(ident,{})
        if not value.get('protected_session'):return None
        try:
            raw=base64.b64decode(value['protected_session'])
            if value.get('session_protection')=='windows-dpapi':raw=model_config.secret_transform(raw,decrypt=True)
            state=json.loads(raw)
            if urlsplit(state['url']).hostname!='mp.weixin.qq.com':raise ValueError()
            return state
        except (ValueError,KeyError,UnicodeError):raise ValueError('本机登录状态无法读取，请清除登录状态后重新扫码。') from None


def _save(ident,context,url,identity=None):
    raw=json.dumps({'storage':context.storage_state(),'url':url}).encode()
    with wechat_accounts.lock:
        values=wechat_accounts.read()
        if identity:
            old_appid=values[ident].get('appid')
            if old_appid and old_appid!=identity['appid']:raise wechat_accounts.WeChatError('扫码登录的公众号与原连接不一致，请使用原公众号登录，或新增连接。')
            values[ident].update(appid=identity['appid'],actual_name=identity['name'],draft_ready=True)
        values[ident].update(protected_session=base64.b64encode(model_config.secret_transform(raw)).decode(),
                             session_protection='windows-dpapi' if os.name=='nt' else 'file-permissions',checked_at=db.now())
        wechat_accounts.write(values)


def logged_in(page):
    location=urlsplit(page.url)
    # A QR scan or a token alone is not proof of a completed sign-in.
    return location.hostname=='mp.weixin.qq.com' and location.path=='/cgi-bin/home' and page.get_by_text(re.compile(r'^退出(登录)?$')).count()>0


def identity(page):
    """Read the immutable AppID from the account's visible settings page."""
    home=page.url
    name=page.locator('.acount_box-nickname').inner_text().strip()
    page.locator('.acount_box-nickname').click()
    page.get_by_text('账号详情',exact=True).click()
    page.get_by_text('AppID',exact=True).wait_for(timeout=15000)
    match=re.search(r'AppID\s*(wx[a-zA-Z0-9]{16})',page.locator('body').inner_text())
    if not match:raise wechat_accounts.WeChatError('无法确认公众号的 AppID，请稍后重新连接。')
    page.goto(home,wait_until='domcontentloaded')
    return {'appid':match[1],'name':name}


def _run(ident,value):
    try:
        from playwright.sync_api import sync_playwright
        saved=_load(ident)
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=executable())
            try:
                context=browser.new_context(storage_state=saved['storage'] if saved else None,viewport={'width':1280,'height':850},locale='zh-CN')
                page=context.new_page();page.set_default_timeout(6000)
                page.goto(saved['url'] if saved else LOGIN,wait_until='domcontentloaded',timeout=30000)
                deadline=time.monotonic()+TTL
                while not value['stop'].is_set() and time.monotonic()<deadline:
                    while not value['actions'].empty():
                        x,y=value['actions'].get_nowait()
                        if urlsplit(page.url).hostname=='mp.weixin.qq.com':page.mouse.click(x,y)
                    if logged_in(page):
                        verified=identity(page)
                        with lock:
                            if value['stop'].is_set():return
                            _save(ident,context,page.url,verified)
                            _set(value,'connected','扫码登录成功，已核对公众号身份，可以自动保存草稿。登录状态已加密保存在本机。')
                        return
                    qr=page.locator(QR)
                    if qr.count() and qr.is_visible():
                        picture=qr.screenshot(timeout=5000)
                        _set(value,'waiting_scan','请用管理员微信扫码，并在手机上选择公众号、确认登录。二维码失效时点击“重新扫码”。',picture)
                    else:
                        _set(value,'waiting_scan','请完成手机确认；如果下方出现账号选择或验证页面，可直接点击页面继续。',preview=page.screenshot())
                    value['stop'].wait(2)
                if not value['stop'].is_set():_set(value,'expired','本次扫码已超时，请重新扫码。')
            finally:browser.close()
    except Exception as error:
        # Playwright errors can contain authenticated URLs; never propagate them.
        if not value['stop'].is_set():_set(value,'failed',str(error) if isinstance(error,wechat_accounts.WeChatError) else '公众号登录未完成。请检查网络及本机 Edge / Chrome，或到微信公众平台完成验证后重试。')


def start(ident):
    _require(ident)
    with lock:old=sessions.get(_key(ident))
    if old and old['stop'].is_set():
        old['thread'].join(timeout=8)
        if old['thread'].is_alive():raise ValueError('上次登录正在关闭，请稍后重新扫码。')
    with lock:
        key=_key(ident);old=sessions.get(key)
        if old and old['thread'].is_alive():return public(old)
        if sum(v['thread'].is_alive() for v in sessions.values())>=2:raise ValueError('已有两个公众号正在扫码，请先完成或取消登录。')
        value={'stop':threading.Event(),'actions':queue.Queue(maxsize=10)}
        _set(value,'starting','正在打开微信官方扫码登录页…')
        thread=threading.Thread(target=_run,args=(ident,value),daemon=True,name='wechat-login')
        value['thread']=thread;sessions[key]=value;thread.start()
        return public(value)


def qr_image(ident):
    _require(ident)
    with lock:
        value=sessions.get(_key(ident),{})
        if not value.get('qr'):raise ValueError('二维码尚未就绪，请等待或重新扫码。')
        return value['qr']


def preview(ident):
    _require(ident)
    with lock:
        value=sessions.get(_key(ident),{})
        if not value.get('preview'):raise ValueError('当前没有待处理的登录页面。')
        return value['preview']


def click(ident,x,y):
    _require(ident)
    if not 0<=x<1280 or not 0<=y<850:raise ValueError('点击位置超出页面。')
    with lock:
        value=sessions.get(_key(ident),{})
        if value.get('status')!='waiting_scan' or not value.get('preview') or value['stop'].is_set():raise ValueError('登录页面已更新，请稍后再试。')
        try:value['actions'].put_nowait((x,y))
        except queue.Full:raise ValueError('正在处理上次操作，请稍后。') from None
    return {'message':'已提交操作'}


def cancel(ident,forget=False):
    _require(ident)
    with lock:
        value=sessions.get(_key(ident))
        if value:
            value['stop'].set();_set(value,'idle','登录已取消。')
        if forget:
            with wechat_accounts.lock:
                values=wechat_accounts.read()
                for key in ('protected_session','session_protection','checked_at'):values[ident].pop(key,None)
                values[ident].update(draft_ready=False,publish_ready=False)
                wechat_accounts.write(values)
    return status(ident)


def shutdown():
    with lock:
        for value in sessions.values():value['stop'].set()
