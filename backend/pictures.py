"""Bounded image search, immutable derivatives and persisted image requests."""
import base64
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import io
import json
import re
import uuid
import threading
from urllib.parse import urlencode,urlsplit
import httpx
from bs4 import BeautifulSoup
from PIL import Image
from fastapi import HTTPException
from . import db,media,model_library,unsplash
from .network import fetch_public, public_url
from .picture_models import PictureRequest

executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='studio-pictures')
search_executor=ThreadPoolExecutor(max_workers=4,thread_name_prefix='studio-picture-search')
preview_slots=threading.BoundedSemaphore(4)


class SearchResults(list):
    """A provider page before cross-provider filtering; empty matches can have a next page."""
    def __init__(self,items,has_more):
        super().__init__(items)
        self.has_more=bool(has_more)


def init(c=None):
    """Create the durable image tables using the caller's transaction when given."""
    if c is None:
        with db.connect() as own:
            init(own)
        return
    c.executescript('''CREATE TABLE IF NOT EXISTS picture_candidates(id TEXT PRIMARY KEY,data TEXT NOT NULL,at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS asset_provenance(asset_id TEXT PRIMARY KEY REFERENCES assets(id),data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS picture_jobs(id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,request TEXT NOT NULL,status TEXT NOT NULL,asset_id TEXT,error TEXT,at TEXT NOT NULL,updated_at TEXT NOT NULL);''')


def asset(ident):
    with db.connect() as c:
        row=c.execute('SELECT * FROM assets WHERE id=?',(ident,)).fetchone()
        if not row or not row['media_type'].startswith('image/'):raise ValueError('图片素材不存在，请重新选择。')
        meta=c.execute('SELECT data FROM asset_provenance WHERE asset_id=?',(ident,)).fetchone()
    return {**{k:v for k,v in dict(row).items() if k!='path'},'provenance':json.loads(meta['data']) if meta else {'kind':'upload'}}


def path(ident):
    with db.connect() as c:row=c.execute('SELECT * FROM assets WHERE id=?',(ident,)).fetchone()
    if not row:raise ValueError('原图不存在。')
    return media.asset_path(dict(row))


def record(value,metadata):
    with db.connect() as c:c.execute('INSERT OR IGNORE INTO asset_provenance VALUES (?,?)',(value['id'],db.dump(metadata)))
    return asset(value['id'])


def clean(value):
    return BeautifulSoup(str(value or ''),'html.parser').get_text(' ',strip=True)


@lru_cache(maxsize=96)
def preview(ident):
    """Fallback for saved search candidates only, never an arbitrary URL proxy."""
    with db.connect() as c:row=c.execute('SELECT data FROM picture_candidates WHERE id=?',(ident,)).fetchone()
    if not row:raise HTTPException(404,'搜索结果已不存在，请重新搜索。')
    item=json.loads(row['data'])
    if item.get('provider')=='Unsplash':raise HTTPException(400,'Unsplash 预览请使用官方图片地址。')
    if not preview_slots.acquire(timeout=1):raise HTTPException(503,'预览请求较多，请稍后重试。')
    try:
        for url in dict.fromkeys(filter(None,[item.get('url'),item.get('preview_url')])):
            try:
                public_url(url)
                content,_=fetch_public(url,8_000_000,timeout=6)
                with Image.open(io.BytesIO(content)) as original:
                    if original.format not in ('JPEG','PNG','WEBP','GIF') or original.width*original.height>24_000_000:continue
                    original.thumbnail((640,480))
                    output=io.BytesIO();original.convert('RGB').save(output,format='JPEG',quality=80)
                    return output.getvalue()
            except Exception:continue
        raise HTTPException(502,'缩略图和原图均无法加载，可能链接失效或来源网站限制访问。')
    finally:preview_slots.release()


def search_commons(query,page=1):
    params={'action':'query','format':'json','generator':'search','gsrsearch':query,'gsrnamespace':6,'gsrlimit':12,
            'gsroffset':(page-1)*12,'prop':'imageinfo','iiprop':'url|size|extmetadata|mime','iiurlwidth':900}
    data=json.loads(fetch_public('https://commons.wikimedia.org/w/api.php?'+urlencode(params),timeout=6)[0])
    if 'error' in data:raise ValueError('图库查询失败。')
    results=[]
    for page in sorted(data.get('query',{}).get('pages',{}).values(),key=lambda p:p.get('index',0)):
        info=(page.get('imageinfo') or [{}])[0];ext=info.get('extmetadata',{})
        val=lambda k:clean((ext.get(k) or {}).get('value',''))
        license=val('LicenseShortName');url=info.get('thumburl') or info.get('url','')
        # Keep reusable images with explicit license information, not search thumbnails of unknown origin.
        reusable=bool(re.fullmatch(r'CC BY(?:-SA)?(?: \d\.\d)?|CC0(?: \d\.\d)?|Public domain|PD',license,re.I))
        if not (reusable and info.get('mime') in ('image/jpeg','image/png','image/webp')):continue
        if min(info.get('width',0),info.get('height',0))<400 or urlsplit(url).hostname!='upload.wikimedia.org':continue
        value={'id':'pic-'+uuid.uuid4().hex,'title':clean(page.get('title','')).removeprefix('File:'),'url':url,
               'page_url':info.get('descriptionurl',''),'credit':val('Artist')[:300],'license':license,
               'license_url':val('LicenseUrl'),'description':val('ImageDescription')[:1000],
               'width':info.get('width'),'height':info.get('height'),'provider':'Wikimedia Commons'}
        value['license_verified']=True
        results.append(value)
    return SearchResults(results,'gsroffset' in data.get('continue',{}))


def search_openverse(query,page=1):
    params={'q':query,'page':page,'page_size':12,'license':'by,by-sa,cc0,pdm','filter_dead':True}
    data=json.loads(fetch_public('https://api.openverse.org/v1/images/?'+urlencode(params),timeout=6)[0])
    if not isinstance(data.get('results'),list):raise ValueError('图库返回内容异常。')
    results=[]
    for item in data['results']:
        license=item.get('license','').lower()
        if license not in ('by','by-sa','cc0','pdm'):continue
        width,height=item.get('width') or 0,item.get('height') or 0
        if width and height and min(width,height)<400:continue
        labels={'by':'CC BY','by-sa':'CC BY-SA','cc0':'CC0','pdm':'Public domain'}
        results.append({'title':clean(item.get('title')),'url':item.get('url',''),
            'preview_url':item.get('thumbnail',''),'page_url':item.get('foreign_landing_url',''),
            'credit':clean(item.get('creator'))[:300],'license':(labels[license]+' '+(item.get('license_version') or '')).strip(),
            'license_url':item.get('license_url',''),'description':clean(item.get('title')),
            'width':width,'height':height,'provider':'Openverse','license_verified':True})
    return SearchResults(results,page<data['page_count'] if isinstance(data.get('page_count'),int) else bool(data.get('next')))


def search_bing(query,page=1):
    params={'q':query,'count':24,'first':(page-1)*24+1,'adlt':'strict'}
    content,_=fetch_public('https://www.bing.com/images/search?'+urlencode(params),timeout=6)
    soup=BeautifulSoup(content,'html.parser');results=[]
    for node in soup.select('a.iusc[m]'):
        try:item=json.loads(node['m'])
        except (ValueError,TypeError):continue
        if not isinstance(item,dict):continue
        results.append({'title':clean(item.get('t'))[:300],'url':item.get('murl',''),
            'preview_url':item.get('turl',''),'page_url':item.get('purl',''),
            'credit':'','license':'授权待核对','license_url':'',
            'description':clean(item.get('desc'))[:1000],'provider':'必应图片','license_verified':False})
    if not results and not (soup.select_one('#b_results') or soup.select_one('.dgControl')):
        raise ValueError('图片搜索未返回可解析的结果，可能需要验证或搜索页面已变化。')
    # The HTML source has no reliable total. Allow one more request until it
    # returns no images; do not invent a total number of pages.
    return SearchResults(results,bool(results))


def search_360(query,page=1):
    data=json.loads(fetch_public('https://image.so.com/j?'+urlencode({'q':query,'sn':(page-1)*24,'pn':24}),timeout=6)[0])
    if not isinstance(data.get('list'),list):raise ValueError('360 图片未返回搜索结果，可能需要验证。')
    results=[{'title':clean(i.get('title')),'url':i.get('img') or i.get('imgurl',''),
             'preview_url':i.get('thumb',''),'page_url':i.get('link') or i.get('purl',''),
             'description':clean(i.get('title')),'provider':'360 图片','credit':'','license':'授权待核对',
             'license_url':'','license_verified':False} for i in data['list']]
    return SearchResults(results,not data['end'] if 'end' in data else len(data['list'])>=24)


def search_baidu(query,page=1):
    data=json.loads(fetch_public('https://image.baidu.com/search/acjson?'+urlencode({'tn':'resultjson_com','ipn':'rj','word':query,'pn':(page-1)*24,'rn':24}),timeout=6)[0])
    if not isinstance(data.get('data'),list):raise ValueError('百度图片限制了自动访问，请换一个来源。')
    results=[]
    for i in data['data']:
        if not i:continue
        urls=i.get('replaceUrl') or [{}];original=urls[0]
        results.append({'title':clean(i.get('fromPageTitleEnc') or i.get('fromPageTitle')),
            'url':original.get('ObjURL') or i.get('middleURL',''),'preview_url':i.get('thumbURL',''),
            'page_url':original.get('FromURL') or i.get('fromURLHost',''),
            'description':clean(i.get('fromPageTitle')),'provider':'百度图片','credit':'',
            'license':'授权待核对','license_url':'','license_verified':False})
    return SearchResults(results,page*24<data['displayNum'] if isinstance(data.get('displayNum'),int) else len(results)>=24)


def relevant(query,item):
    """Reject unrelated fallback/trending results using available title and description."""
    text=(item.get('title','')+' '+item.get('description','')).casefold()
    subject=re.sub(r'图片|配图|照片|高清|壁纸','',query.casefold()).strip()
    if not subject:return False
    if any(term in subject for term in ('大模型','人工智能','llm')) or re.search(r'\bai\b',subject):
        return bool(re.search(r'\b(?:ai|llm|gpt|chatgpt|deepseek)\b|人工智能|大模型|神经网络|机器学习|语言模型|artificial intelligence|language model',text))
    tokens=re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]+',subject)
    return any((token in text if token.isascii() else any(token[i:i+2] in text for i in range(max(1,len(token)-1)))) for token in tokens)


def search_report(query,source='web',sources=None,page=1):
    """Keep provider failures distinct from zero matches; never relabel web results as licensed."""
    if source not in ('web','licensed'):raise ValueError('不支持的图片来源。')
    if not 1<=page<=50:raise ValueError('图片搜索页码应在 1 到 50 之间。')
    providers=[];results=[];seen=set()

    def collect(name,fetch):
        try:
            candidates=fetch.result();accepted=[];excluded=0
            for item in candidates:
                if not relevant(query,item):excluded+=1;continue
                try:
                    public_url(item.get('url',''));public_url(item.get('page_url',''))
                    if item.get('preview_url'):public_url(item['preview_url'])
                    if item.get('license_url'):public_url(item['license_url'])
                except (ValueError,TypeError):continue
                if item['url'] in seen:continue
                seen.add(item['url']);accepted.append(item)
            results.extend(accepted)
            note=f'已排除 {excluded} 张标题或描述与搜索主题不匹配的图片' if excluded else ''
            if name=='Unsplash' and not accepted:note+='；推荐使用准确的英文主体名称搜索，例如 mountain、city。'
            providers.append({'name':name,'status':'success' if accepted else 'empty','count':len(accepted),'excluded':excluded,
                              'message':note.lstrip('；'),'has_more':page<50 and getattr(candidates,'has_more',bool(candidates))})
        except ValueError as error:
            providers.append({'name':name,'status':'error','count':0,'message':str(error)[:180]})
        except Exception:
            providers.append({'name':name,'status':'error','count':0,'message':'连接超时、服务限制或暂不可用'})

    registry={'bing':('必应图片',search_bing),'360':('360 图片',search_360),'baidu':('百度图片',search_baidu),
              'unsplash':('Unsplash',unsplash.search),'commons':('Wikimedia Commons',search_commons),'openverse':('Openverse',search_openverse)}
    def submit(fetch):return search_executor.submit(fetch,query) if page==1 else search_executor.submit(fetch,query,page=page)
    if sources:
        if any(s not in registry for s in sources):raise ValueError('不支持的图片来源。')
        requests=[(registry[s][0],submit(registry[s][1])) for s in dict.fromkeys(sources)]
        for name,request in requests:collect(name,request)
    elif source=='web':collect('必应图片',submit(search_bing))
    if not sources and (source=='licensed' or not results):
        requests=[(name,submit(fetch)) for name,fetch in [('Wikimedia Commons',search_commons),('Openverse',search_openverse)]]
        for name,request in requests:collect(name,request)
    with db.connect() as c:
        for item in results:
            item['id']='pic-'+uuid.uuid4().hex
            c.execute('INSERT INTO picture_candidates VALUES (?,?,?)',(item['id'],db.dump(item),db.now()))
    return {'items':results,'providers':providers,'query':query,'source':source,'sources':sources or [],
            'page':page,'has_more':any(p.get('has_more',False) for p in providers)}


def search(query,source='licensed',sources=None,page=1):
    report=search_report(query,source,sources,page)
    if report['providers'] and all(p['status']=='error' for p in report['providers']):
        raise ValueError('当前图片来源均无法连接。'+('可在配图配置中改用“必应图片”，或选择 AI 生成。' if source=='licensed' else '请稍后重试，或上传图片、使用 AI 生成。'))
    return report['items']


def image_connection(model_id,edit=False):
    if not model_id:raise ValueError('请先选择图片模型。')
    value=model_library.current(model_id)
    if value.get('protocol')!='images' or not value.get('model') or not value.get('api_key'):
        raise ValueError('请在“我的模型”添加 Images 图片模型，并在配图配置中选择。')
    if edit and not value.get('image_edit'):raise ValueError('该模型未启用图片编辑能力，请换一个支持编辑的图片模型。')
    return value


def generate(body,job_id,connection=None):
    connection=connection or image_connection(body.model_id,body.action=='edit')
    sizes={'landscape':'1536x1024','square':'1024x1024','portrait':'1024x1536'}
    payload={'model':connection['model'],'prompt':body.prompt,'size':sizes[body.ratio],'n':1}
    headers={'Authorization':'Bearer '+connection['api_key']}
    kwargs={'json':payload};suffix='/images/generations'
    if body.action=='edit':
        original=asset(body.asset_id);content=path(body.asset_id).read_bytes()
        kwargs={'data':{k:str(v) for k,v in payload.items()},'files':{'image':('image.jpg',content,original['media_type'])}};suffix='/images/edits'
    with db.connect() as c:
        usage=c.execute('INSERT INTO ai_usage(job_id,day,kind,status,at) VALUES (?,?,?,?,?)',(job_id,db.day(),'picture_'+body.action,'reserved',db.now())).lastrowid
    try:
        # One billable request only. Never retry automatically or forward keys across redirects.
        with httpx.Client(timeout=httpx.Timeout(240,connect=15),follow_redirects=False) as client:
            with client.stream('POST',connection['base_url'].rstrip('/')+suffix,headers=headers,**kwargs) as response:
                if response.is_redirect:raise ValueError('图片接口返回重定向，请填写最终 API 地址。')
                if response.status_code>=400:raise ValueError(f'图片接口请求失败（HTTP {response.status_code}），请检查模型名称、权限和图片尺寸。')
                chunks=[];size=0
                for part in response.iter_bytes():
                    size+=len(part)
                    if size>32_000_000:raise ValueError('图片接口返回内容过大。')
                    chunks.append(part)
        result=json.loads(b''.join(chunks));item=(result.get('data') or [{}])[0]
        if item.get('b64_json'):content=base64.b64decode(item['b64_json'],validate=True)
        elif item.get('url'):content=media.fetch_image(item['url'])
        else:raise ValueError('图片接口没有返回图片，请确认使用 Images 兼容接口。')
        value=media.store_asset(content,'AI 配图.jpg','AI 生成图片；模型：'+connection['model']+'；请求：'+job_id,'AI 生成')
        with db.connect() as c:c.execute('UPDATE ai_usage SET status=? WHERE id=?',('received',usage))
        return record(value,{'kind':'ai','model':connection['model'],'prompt':body.prompt,'parent_asset_id':body.asset_id,'at':db.now()})
    except ValueError:
        with db.connect() as c:c.execute('UPDATE ai_usage SET status=? WHERE id=?',('failed',usage))
        raise
    except Exception:
        with db.connect() as c:c.execute('UPDATE ai_usage SET status=? WHERE id=?',('failed',usage))
        raise ValueError('图片生成未完成，可能仍在服务商侧处理。未自动重复请求；请检查连接或稍后重新生成。') from None


def produce(body,job_id):
    if body.action in ('generate','edit'):return generate(body,job_id)
    if body.action=='import':
        with db.connect() as c:row=c.execute('SELECT data FROM picture_candidates WHERE id=?',(body.candidate_id,)).fetchone()
        if not row:raise ValueError('搜索结果已不存在，请重新搜索。')
        source=json.loads(row['data'])
        if source.get('provider')=='Unsplash':unsplash.track_download(source)
        try:content=media.fetch_image(source['url'])
        except Exception:raise ValueError('原图暂时无法下载，请换一张或稍后重试。') from None
        value=media.store_asset(content,source['title'],source['license']+'；'+source['license_url'],source['credit'],source['page_url'])
        return record(value,{'kind':'web',**source})
    original=asset(body.asset_id)
    with Image.open(path(body.asset_id)) as picture:
        w,h=picture.size
        box=(round(body.x*w),round(body.y*h),round((body.x+body.width)*w),round((body.y+body.height)*h))
        if box[2]-box[0]<100 or box[3]-box[1]<100:raise ValueError('裁剪后的图片至少需要 100 × 100 像素。')
        output=io.BytesIO();picture.crop(box).convert('RGB').save(output,format='JPEG',quality=93)
    value=media.store_asset(output.getvalue(),'裁剪-'+original['filename'],original['rights'],original['credit'],original['source_url'])
    return record(value,{**original['provenance'],'parent_asset_id':original['id'],'crop':body.model_dump(include={'x','y','width','height'}),'at':db.now()})


def get(ident):
    with db.connect() as c:row=c.execute('SELECT * FROM picture_jobs WHERE id=?',(ident,)).fetchone()
    if not row:raise HTTPException(404,'图片处理记录不存在。')
    return {'id':ident,'status':row['status'],'error':row['error'],'asset':asset(row['asset_id']) if row['asset_id'] else None}


def create(body,*,submit=True):
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT * FROM picture_jobs WHERE request_id=?',(body.request_id,)).fetchone()
        if old:
            if json.loads(old['request'])!=body.model_dump():raise HTTPException(409,'此图片请求编号已用于其他操作。')
            ident=old['id']
        else:
            if body.action in ('generate','edit'):image_connection(body.model_id,body.action=='edit')
            ident='picture-'+uuid.uuid4().hex[:18]
            c.execute('INSERT INTO picture_jobs VALUES (?,?,?,?,?,?,?,?)',(ident,body.request_id,body.model_dump_json(),'queued',None,None,db.now(),db.now()))
    if submit:executor.submit(run,ident)
    return get(ident)


def run(ident):
    with db.connect() as c:
        if not c.execute("UPDATE picture_jobs SET status='running',updated_at=? WHERE id=? AND status='queued'",(db.now(),ident)).rowcount:return
        body=PictureRequest.model_validate_json(c.execute('SELECT request FROM picture_jobs WHERE id=?',(ident,)).fetchone()[0])
    try:
        value=produce(body,ident)
        with db.connect() as c:c.execute("UPDATE picture_jobs SET status='ready',asset_id=?,updated_at=? WHERE id=?",(value['id'],db.now(),ident))
    except Exception as error:
        message=str(error) if isinstance(error,ValueError) else '图片处理未完成，请稍后重试。'
        with db.connect() as c:c.execute("UPDATE picture_jobs SET status='failed',error=?,updated_at=? WHERE id=?",(message,db.now(),ident))


def recover():
    with db.connect() as c:
        c.execute("UPDATE picture_jobs SET status='failed',error=? WHERE status='running'",('服务中断，图片处理结果未确认，未自动重复请求。',))
        queued=[r['id'] for r in c.execute("SELECT id FROM picture_jobs WHERE status='queued'")]
    for ident in queued:executor.submit(run,ident)
