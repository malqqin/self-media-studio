"""Non-admin model requests cannot reach the server's private network."""
from contextlib import contextmanager
import ipaddress
import socket
import httpx
from . import db
from .tenancy import require_user


def is_admin():
    with db.system_connection() as c:
        return bool(c.execute("SELECT 1 FROM app_users WHERE id=%s AND role='admin' AND status='active'",(require_user(),)).fetchone())


class PublicModelTransport(httpx.BaseTransport):
    def __init__(self):
        self.inner=httpx.HTTPTransport()

    def handle_request(self,request):
        original=request.url;host=original.host
        if original.scheme!='https' or original.userinfo:
            raise ValueError('普通用户的模型接口必须使用公网 HTTPS 地址。')
        try:
            addresses=list(dict.fromkeys(r[4][0] for r in socket.getaddrinfo(host,original.port or 443,type=socket.SOCK_STREAM)))
        except OSError:
            raise ValueError('无法解析模型接口地址，请检查地址。') from None
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError('模型接口不能访问服务器本机或内网地址。')
        headers=httpx.Headers(request.headers);headers['Host']=original.netloc.decode()
        pinned=httpx.Request(request.method,original.copy_with(host=addresses[0]),headers=headers,
            stream=request.stream,extensions={**request.extensions,'sni_hostname':host})
        return self.inner.handle_request(pinned)

    def close(self):
        self.inner.close()


def transport():
    return None if is_admin() else PublicModelTransport()


def client_options():
    selected=transport()
    return {} if selected is None else {'transport':selected,'trust_env':False}


def post(url,**kwargs):
    if is_admin():return httpx.post(url,**kwargs)
    timeout=kwargs.pop('timeout',150)
    with httpx.Client(transport=PublicModelTransport(),trust_env=False,timeout=timeout) as client:
        return client.post(url,**kwargs)


@contextmanager
def stream(method,url,**kwargs):
    if is_admin():
        with httpx.stream(method,url,**kwargs) as response:yield response
    else:
        timeout=kwargs.pop('timeout',150)
        with httpx.Client(transport=PublicModelTransport(),trust_env=False,timeout=timeout) as client:
            with client.stream(method,url,**kwargs) as response:yield response
