"""Hot-reloaded model connection; secrets never enter public settings or jobs."""
import base64
import ctypes
import json
import os
import threading
import uuid

from . import config
from .models import ModelConnection

lock=threading.RLock()


def secret_transform(value: bytes, decrypt=False):
    if os.name!='nt':return value
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=ctypes.create_string_buffer(value)
    source=Blob(len(value),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    output=Blob()
    function=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output)):
        raise ValueError('无法读取或保存本机密钥，请重新填写 API Key。')
    try:return ctypes.string_at(output.data,output.size)
    finally:ctypes.windll.kernel32.LocalFree(output.data)


def current():
    path=config.DATA/'model-config.json'
    with lock:
        if not path.exists():
            return {'name':'环境变量配置','base_url':config.API_BASE,'model':config.MODEL,
                'protocol':'responses','output_mode':'json_schema','api_key':config.API_KEY,'origin':'environment'}
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            secret=base64.b64decode(data.pop('protected_key',''))
            if data.pop('protection',None)=='windows-dpapi':secret=secret_transform(secret,decrypt=True)
            data['api_key']=secret.decode('utf-8');data['origin']='page'
            return data
        except (OSError, ValueError, UnicodeError):
            raise ValueError('模型配置文件无法读取，请在页面重新保存配置。') from None


def public(data=None):
    from .model_directory import metadata
    data=data if data is not None else current()
    return {**{k:v for k,v in data.items() if k in ('name','base_url','model','protocol','output_mode','origin','image_edit')},
            **metadata(data),
            'key_configured':bool(data.get('api_key')),
            'ready':bool(data.get('api_key') and data.get('model') and data.get('protocol') != 'catalog')}


def resolve(body: ModelConnection):
    old=current()
    if body.clear_key and body.api_key:raise ValueError('清除密钥与填写新密钥不能同时选择。')
    if old.get('api_key') and not body.api_key and not body.clear_key and body.base_url!=old['base_url'].rstrip('/'):
        raise ValueError('更换接口地址时请重新填写 API Key，避免把旧密钥发送到新服务。')
    return {**body.model_dump(exclude={'clear_key','api_key'}),
            'api_key':'' if body.clear_key else body.api_key or old.get('api_key',''), 'origin':'page'}


def save(body):
    with lock:
        data=resolve(body)
        secret=data['api_key'].encode()
        stored={k:v for k,v in data.items() if k not in ('api_key','origin')}
        stored['protected_key']=base64.b64encode(secret_transform(secret)).decode()
        stored['protection']='windows-dpapi' if os.name=='nt' else 'file-permissions'
        config.DATA.mkdir(parents=True,exist_ok=True)
        temporary=config.DATA/('.model-'+uuid.uuid4().hex+'.tmp')
        try:
            fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(stored,stream,ensure_ascii=False,indent=2)
            temporary.replace(config.DATA/'model-config.json')
        finally:temporary.unlink(missing_ok=True)
        return public(data)
