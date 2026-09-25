"""Read-only model discovery. Never generate, persist keys, or follow redirects."""
import json
import re
from urllib.parse import urlsplit

import httpx

from . import config

PROVIDERS = json.loads((config.ROOT/'shared/model-providers.json').read_text(encoding='utf-8'))
TYPES = {'text', 'image', 'video', 'audio', 'embedding', 'unknown'}
DESCRIPTIONS = {
    'text': '文本创作、问答与内容改写；看图等输入能力以服务商说明为准。',
    'image': '生成图片，可用于封面和文章配图。',
    'video': '生成视频；本平台暂未接入视频生成接口，可保存连接信息。',
    'audio': '语音或音频处理；本平台暂未接入音频接口。',
    'embedding': '向量检索或重排序；不用于生成文章正文。',
    'unknown': '接口未提供明确类型，请对照服务商文档确认后选择。',
}


def provider_for(base_url):
    host = urlsplit(base_url).hostname
    return next((p['id'] for p in PROVIDERS if p['url'] and urlsplit(p['url']).hostname == host), 'custom')


def clean(value, limit=500):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', value).strip()[:limit] if isinstance(value, str) else ''


def kind_for(item):
    # Output modalities matter: image/video *inputs* still often produce text.
    architecture = item.get('architecture') if isinstance(item.get('architecture'), dict) else {}
    modalities = item.get('output_modalities', architecture.get('output_modalities', []))
    if isinstance(modalities, str):modalities = [modalities]
    if isinstance(modalities, list):
        for kind in ('video', 'image', 'audio', 'text'):
            if kind in modalities:return kind, 'api'
    task = clean(item.get('task') or item.get('type') or item.get('model_type')).lower().replace('_', '-')
    mapping = {'chat':'text', 'chat-completions':'text', 'text-generation':'text', 'text-to-image':'image',
               'image-generation':'image', 'text-to-video':'video', 'image-to-video':'video', 'video-generation':'video',
               'text-to-speech':'audio', 'speech-to-text':'audio', 'rerank':'embedding', **{k:k for k in TYPES}}
    if task in mapping:return mapping[task], 'api'
    name = clean(item.get('id'), 150).lower()
    patterns = (
        ('embedding', r'embed|rerank|bge-|bce-'),
        ('video', r'sora|cogvideo|seedance|(?:^|[/.-])wan(?:[\d.-]|$)|hunyuanvideo|minimax[-/]video|(?:^|/)t2v|(?:^|/)i2v|kling'),
        ('image', r'dall-e|gpt-image|chatgpt-image|flux|stable-diffusion|sdxl|cogview|seedream|qwen-image|glm-image|imagen|kolors|hunyuanimage'),
        ('audio', r'whisper|tts|speech|audio|realtime|asr|cosyvoice'),
        ('text', r'deepseek|qwen|qwq|qvq|glm|kimi|moonshot|doubao|gpt-|chatgpt|(?:^|/)o[134](?:-|$)|minimax-m|llama|mistral|gemini|claude|yi-|baichuan|ernie|hunyuan'),
    )
    for kind, pattern in patterns:
        if re.search(pattern, name):return kind, 'inferred'
    return 'unknown', 'unknown'


def suggested_protocol(kind, provider):
    if kind == 'text':return 'chat_completions'
    # These services expose an Images-style generation endpoint. Others need
    # dedicated adapters, even when their chat endpoint is OpenAI compatible.
    if kind == 'image' and provider in ('openai','custom','doubao','siliconflow','zhipu'):return 'images'
    return 'catalog'


def normalize(item, provider):
    ident = clean(item.get('id'), 150)
    if not ident:return None
    kind, source = kind_for(item)
    description = clean(item.get('description'))
    return {'id': ident, 'name': clean(item.get('name') or item.get('display_name'),150) or ident,
            'description': description or DESCRIPTIONS[kind], 'description_source':'api' if description else 'summary',
            'model_type':kind, 'type_source':source, 'protocol':suggested_protocol(kind,provider)}


def metadata(value):
    """Backfill old connections without changing their chosen protocol."""
    protocol = value.get('protocol', 'responses')
    kind = value.get('model_type') or ('image' if protocol == 'images' else 'text' if protocol in ('responses','chat_completions') else 'unknown')
    return {'provider': value.get('provider') or provider_for(value.get('base_url','')),
            'model_type':kind, 'description':value.get('description') or DESCRIPTIONS.get(kind,DESCRIPTIONS['unknown'])}


def discover(connection):
    key = connection.get('api_key')
    if not key:raise ValueError('请先填写 API Key，再获取模型列表。')
    url = connection['base_url'].rstrip('/')+'/models'
    try:
        with httpx.Client(timeout=httpx.Timeout(25,connect=10),follow_redirects=False) as client:
            with client.stream('GET',url,headers={'Authorization':'Bearer '+key,'Accept':'application/json'}) as response:
                status=response.status_code
                if 300 <= status < 400:raise ValueError('模型目录返回重定向，请在高级设置填写最终 API 地址后重试。')
                if status in (401,403):raise ValueError('无法读取模型目录，请检查 Key、地域和账号权限；也可手动填写已开通的模型 ID。')
                if status in (404,405):raise ValueError('此服务商未在当前地址开放模型目录，可在下方手动填写模型 ID 或专属接入点。')
                if status == 429:raise ValueError('模型目录请求过于频繁，请稍后重试。')
                if status >= 400:raise ValueError(f'获取模型目录失败（HTTP {status}），请检查地址或稍后重试。')
                chunks=[];size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>4_000_000:raise ValueError('模型目录返回内容过大，请使用更具体的 API 地址或手动填写。')
                    chunks.append(chunk)
        data=json.loads(b''.join(chunks))
    except httpx.TimeoutException:
        raise ValueError('获取模型目录超时，请检查网络后重试，也可手动填写。') from None
    except httpx.HTTPError:
        raise ValueError('无法连接模型目录，请检查网络和 API 地址。') from None
    except (json.JSONDecodeError,UnicodeError):
        raise ValueError('当前地址没有返回有效模型目录，请确认填写的是 API 地址，而不是控制台网址。') from None
    entries=data.get('data',data.get('models')) if isinstance(data,dict) else data
    if not isinstance(entries,list):raise ValueError('接口未返回可识别的模型列表，可手动填写模型 ID。')
    provider=provider_for(connection['base_url']);seen=set();result=[]
    for entry in entries[:2000]:
        item=normalize(entry,provider) if isinstance(entry,dict) else None
        if not item or item['id'] in seen:continue
        # Never reflect the submitted secret even if an upstream server echoes it.
        for field in ('id','name','description'):item[field]=item[field].replace(key,'[已隐藏]')
        seen.add(item['id']);result.append(item)
    partial = len(entries)>2000 or (isinstance(data,dict) and bool(data.get('has_more') or data.get('next_page')))
    return {'models':result,'partial':partial,'message':('目录还有更多结果，可手动填写未列出的模型。' if partial else
            '模型目录不代表调用权限；具体能力和费用以服务商为准。' if result else '当前 Key 未返回模型，请先在服务商开通模型，或手动填写专属接入点。')}
