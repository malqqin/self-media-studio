"""Render public pages in an isolated browser through a DNS-pinned public proxy."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import os
import select
import socket
import threading
import time

from .network import public_url, public_addresses

BROWSER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'


def connect_public(host, port):
    scheme='https' if port==443 else 'http'
    url=public_url(f'{scheme}://{host}:{port}/')
    addresses=public_addresses(url)
    return socket.create_connection((addresses[0],port),timeout=8)


class PublicProxy(BaseHTTPRequestHandler):
    # The browser never resolves destination hosts itself. CONNECT pins the checked
    # public IP while Chromium retains end-to-end TLS and hostname verification.
    protocol_version='HTTP/1.1'

    def log_message(self,*args):pass

    def relay(self,remote):
        deadline=time.monotonic()+30;size=0
        while time.monotonic()<deadline and size<15_000_000:
            readable,_,_=select.select([self.connection,remote],[],[],.5)
            for stream in readable:
                chunk=stream.recv(65536)
                if not chunk:return
                size+=len(chunk)
                (remote if stream is self.connection else self.connection).sendall(chunk)

    def do_CONNECT(self):
        try:
            parsed=urlsplit('https://'+self.path)
            if parsed.port!=443 or not parsed.hostname:raise ValueError('Unsupported tunnel')
            with connect_public(parsed.hostname,443) as remote:
                self.send_response(200,'Connection established');self.end_headers()
                self.relay(remote)
        except (ValueError,OSError):
            self.close_connection=True

    def do_GET(self):
        try:
            parsed=urlsplit(public_url(self.path))
            if parsed.scheme!='http':raise ValueError('Unsupported proxy URL')
            with connect_public(parsed.hostname,parsed.port or 80) as remote:
                target=(parsed.path or '/')+('?' + parsed.query if parsed.query else '')
                headers={k:v for k,v in self.headers.items() if k.lower() not in ('proxy-connection','connection','host','proxy-authorization')}
                headers.update(Host=parsed.netloc,Connection='close')
                payload=f'{self.command} {target} HTTP/1.1\r\n'+''.join(f'{k}: {v}\r\n' for k,v in headers.items())+'\r\n'
                remote.sendall(payload.encode('latin-1'));self.relay(remote)
        except (ValueError,OSError):
            self.close_connection=True

    do_HEAD=do_GET


def render_public(url):
    """Return final URL and rendered HTML; never borrow the user's browser profile."""
    public_url(url);public_addresses(url)
    try:
        from playwright.sync_api import sync_playwright, Error, TimeoutError as BrowserTimeout
    except ImportError:
        raise ValueError('浏览器采集组件未安装，请运行 pip install -r requirements.txt。') from None
    proxy=ThreadingHTTPServer(('127.0.0.1',0),PublicProxy)
    proxy.daemon_threads=True
    thread=threading.Thread(target=proxy.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as playwright:
            candidates=[os.environ.get('STUDIO_BROWSER_PATH',''),
                        'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
                        'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
                        'C:/Program Files/Google/Chrome/Application/chrome.exe']
            executable=next((p for p in candidates if p and Path(p).is_file()),None)
            browser=playwright.chromium.launch(headless=True,executable_path=executable,
                proxy={'server':f'http://127.0.0.1:{proxy.server_port}','bypass':'<-loopback>'},
                args=['--disable-quic','--disable-background-networking','--force-webrtc-ip-handling-policy=disable_non_proxied_udp'],timeout=15000)
            try:
                context=browser.new_context(user_agent=BROWSER_AGENT,locale='zh-CN',service_workers='block',accept_downloads=False)
                requests=0
                def guard(route):
                    nonlocal requests
                    requests+=1
                    request=route.request
                    try:
                        public_url(request.url)
                        if requests>100 or request.method not in ('GET','HEAD') or request.resource_type in ('image','media','font'):raise ValueError()
                    except ValueError:return route.abort()
                    route.continue_()
                context.route('**/*',guard)
                context.route_web_socket('**/*',lambda ws:ws.close())
                page=context.new_page()
                page.on('dialog',lambda dialog:dialog.dismiss())
                try:response=page.goto(url,wait_until='domcontentloaded',timeout=25000)
                except BrowserTimeout:response=None
                if page.url=='about:blank':raise ValueError('浏览器未能打开网页，请检查网址或网络。')
                if response and response.status>=400:raise ValueError(f'浏览器访问返回 HTTP {response.status}。')
                # Allow client-side fetch/hydration without waiting forever on trackers.
                try:page.wait_for_load_state('networkidle',timeout=4000)
                except BrowserTimeout:pass
                html=page.evaluate('''() => {
                    const copy=document.documentElement.cloneNode(true);
                    copy.querySelectorAll('script:not([type="application/ld+json"]),style,noscript,iframe').forEach(el=>el.remove());
                    return '<!doctype html>'+copy.outerHTML;
                }''')
                if len(html)>3_000_000:raise ValueError('渲染后的页面过大，超出本次采集限制。')
                final_url=public_url(page.url)
                return html,final_url
            finally:browser.close()
    except Error as error:
        if 'Executable doesn' in str(error):
            raise ValueError('未找到浏览器；请安装 Edge/Chrome，或运行 python -m playwright install chromium。') from None
        raise ValueError('浏览器加载失败或超时；可在浏览器确认网址后重试，或导入正文。') from None
    finally:
        proxy.shutdown();proxy.server_close();thread.join(timeout=2)
