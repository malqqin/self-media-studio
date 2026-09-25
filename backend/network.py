"""Bounded public-web fetches, including redirects and DNS address pinning."""
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx


def public_url(value: str) -> str:
    value = value.strip()
    try:
        p = urlsplit(value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            raise ValueError()
        if p.port not in (None, 80, 443) or '\\' in value or any(ord(c)<32 for c in value):
            raise ValueError()
        host = p.hostname.lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if '.' not in host: raise ValueError()
        else:
            if not address.is_global: raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('请填写公开的 HTTP/HTTPS 网址，不支持本机、内网地址、账号密码或特殊端口。') from None
    return value


def public_addresses(url):
    parsed = urlsplit(public_url(url))
    try:
        addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme=='https' else 80), type=socket.SOCK_STREAM)))
    except OSError:
        raise ValueError('无法解析网址域名，请检查拼写或网络。') from None
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('网址解析到了本机或内网地址，无法采集。')
    return addresses


def fetch_public(url, limit=3_000_000, *, timeout=25):
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(12,timeout)), follow_redirects=False, trust_env=False) as client:
        for _ in range(5):
            addresses = public_addresses(url)
            original = httpx.URL(url)
            # Pin the checked public IP while retaining TLS hostname verification and Host.
            request = client.build_request('GET', original.copy_with(host=addresses[0]),
                headers={'Host': original.netloc.decode(), 'User-Agent':'ScienceFieldnotes/0.2'},
                extensions={'sni_hostname':original.host})
            response = client.send(request, stream=True)
            try:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get('location', ''))
                    continue
                response.raise_for_status()
                chunks=[]; size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>limit:raise ValueError('来源内容过大，请选择文章或订阅源网址。')
                    chunks.append(chunk)
                return b''.join(chunks), url
            finally:
                response.close()
    raise ValueError('来源网址重定向次数过多。')
