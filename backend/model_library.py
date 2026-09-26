"""Named model connections. Secrets stay in local protected files, never tasks."""
import base64
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
import uuid
from . import config, model_config
from .models import ModelConnection

selected = ContextVar('selected_model_connection', default=None)


def read():
    path = config.data_dir()/'model-library.json'
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('模型库无法读取，请检查本地配置文件。') from None


def write(data):
    config.data_dir().mkdir(parents=True, exist_ok=True)
    path = config.data_dir()/('.models-'+uuid.uuid4().hex+'.tmp')
    try:
        fd = os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2)
        path.replace(config.data_dir()/'model-library.json')
    finally:
        path.unlink(missing_ok=True)


def current(model_id='default'):
    if model_id == 'default':
        return model_config.current()
    with model_config.lock:
        data = dict(read().get(model_id) or {})
        if not data:
            raise ValueError('所选模型不存在，请到“我的模型”重新配置。')
        try:
            secret = base64.b64decode(data.pop('protected_key'))
            if data.pop('protection') == 'windows-dpapi' and secret:
                secret = model_config.secret_transform(secret, decrypt=True)
            return {**data, 'api_key': secret.decode(), 'origin':'library'}
        except (ValueError, KeyError, UnicodeError):
            raise ValueError('无法解密所选模型，请重新填写密钥。') from None


def catalog():
    from .model_directory import metadata
    # Listing names does not decrypt each key and never returns ciphertext.
    with model_config.lock:
        result = [{'id':'default', **model_config.public()}]
        for ident, value in read().items():
            configured = bool(value.get('protected_key'))
            result.append({'id':ident, **{k:value[k] for k in ('name','base_url','model','protocol','output_mode')},
                           **metadata(value), 'image_edit':value.get('image_edit',False),'key_configured':configured,
                           'ready':configured and bool(value.get('model')) and value.get('protocol')!='catalog','origin':'library'})
    return result


def resolve(body: ModelConnection, model_id=None):
    old = current(model_id) if model_id else {}
    if body.clear_key and body.api_key:
        raise ValueError('清除密钥与填写新密钥不能同时选择。')
    if old.get('api_key') and not body.api_key and not body.clear_key and old['base_url'] != body.base_url:
        raise ValueError('更换 API 地址时必须重新填写密钥，避免将旧密钥发送到新地址。')
    return {**body.model_dump(exclude={'clear_key','api_key'}),
            'api_key':'' if body.clear_key else body.api_key or old.get('api_key',''),'origin':'library'}


def save(body, model_id=None):
    with model_config.lock:
        if model_id == 'default':
            return {'id':'default', **model_config.save(body)}
        value = resolve(body,model_id)
        ident = model_id or 'model-'+uuid.uuid4().hex[:16]
        stored = {k:v for k,v in value.items() if k not in ('api_key','origin')}
        stored['protected_key'] = base64.b64encode(model_config.secret_transform(value['api_key'].encode())).decode() if value['api_key'] else ''
        stored['protection'] = 'windows-dpapi' if os.name=='nt' else 'file-permissions'
        library = read(); library[ident] = stored; write(library)
        return {'id':ident, **model_config.public(value)}


def ready(model_id):
    value = current(model_id)
    return bool(value.get('model') and value.get('api_key') and value.get('protocol')!='catalog')


@contextmanager
def use(model_id='default'):
    token = selected.set(model_id)
    try:
        yield
    finally:
        selected.reset(token)


def connection():
    ident = selected.get()
    return current(ident) if ident else model_config.current()
