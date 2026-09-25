import io
import json
import zipfile
import xml.etree.ElementTree as ET
import pytest
from PIL import Image,ImageChops
from bs4 import BeautifulSoup
from backend import article_templates,article_export,wechat_delivery,article_worker
from backend.task_models import TaskSettings
from test_platform import client,wechat,create,save,execute

MOTION=[t for t in article_templates.TEMPLATES.values() if t.get('animated')]


def document(ident):
    return {'template_id':ident,'title':'正文保持不动','summary':'动效仅用作装饰','opening':'文章开头',
            'sections':[{'heading':'第一节','paragraphs':['完整正文'],'asset_id':'','caption':''}],'closing':'结尾','cover_asset_id':''}


@pytest.mark.parametrize('template',MOTION,ids=lambda t:t['id'])
def test_animation_export_is_portable_script_free_and_preserves_gif(client,template):
    doc=document(template['id']);ident=article_templates.decoration_id(doc)
    paths=article_templates.motion_paths(ident)
    root=ET.fromstring(paths['svg'].read_text(encoding='utf-8'))
    forbidden={'script','foreignObject','image','use','a'}
    for node in root.iter():
        assert node.tag.split('}')[-1] not in forbidden
        assert not any(k.lower().startswith('on') or k.endswith('href') for k in node.attrib)
    assert 'prefers-reduced-motion' in paths['svg'].read_text(encoding='utf-8')
    filename,content,mime=wechat_delivery.inline_image(ident)
    assert filename.endswith('.gif') and mime=='image/gif' and len(content)<1_000_000
    with Image.open(io.BytesIO(content)) as image:
        assert image.is_animated and image.n_frames>=30 and image.info['loop']==0
        first=image.convert('RGB');image.seek(image.n_frames//2)
        assert ImageChops.difference(first,image.convert('RGB')).getbbox()
    with Image.open(io.BytesIO(wechat_delivery.image_bytes(ident))) as image:
        assert image.format=='JPEG', 'Cover conversion remains static'
    standalone=BeautifulSoup(article_export.html_body(doc),'html.parser')
    assert standalone.img['src'].startswith('data:image/svg+xml;base64,')
    assert standalone.source['media']=='(prefers-reduced-motion: reduce)'
    assert standalone.source['srcset'].startswith('data:image/png;base64,')
    article={'document':doc,'source_data':[],'checks':None}
    with zipfile.ZipFile(io.BytesIO(article_export.bundle(article))) as archive:
        soup=BeautifulSoup(archive.read('article.html'),'html.parser')
        assert soup.img['src'].endswith('.svg') and soup.source['srcset'].endswith('.png')
        assert soup.img['src'] in archive.namelist() and soup.source['srcset'] in archive.namelist()
        wechat_html=BeautifulSoup(archive.read('wechat.html'),'html.parser')
        assert wechat_html.img['src'].endswith('.gif') and wechat_html.img['src'] in archive.namelist()
        assert not wechat_html.select('svg,script,style,picture')
        assert json.loads(archive.read('article.json'))['template_id']==template['id']
        assert doc['title'] in soup.get_text() and '完整正文' in soup.get_text()


def test_motion_template_task_inherits_and_uploads_actual_gif_via_supported_endpoint(client,wechat,monkeypatch):
    from backend import wechat_accounts
    prefs,calls,request=wechat
    def upload(path,**kwargs):
        if path=='material/add_material' and kwargs['files']['media'][2]=='image/gif':
            calls.append((path,kwargs))
            return {'media_id':'gif-media','url':'https://mmbiz.qpic.cn/mmbiz_gif/template/0'}
        return request(path,**kwargs)
    monkeypatch.setattr(wechat_accounts,'request',upload)
    task=create(client)
    task=save(client,task,brief='读书随笔',article={**task['settings']['article'],'template_id':'firefly'},wechat_delivery={**prefs,'mode':'draft'})
    run=execute(client,task,'automatic')
    assert run['status']=='wechat_draft',run
    assert article_worker.get(run['content_id'])['document']['template_id']=='firefly'
    assert [p for p,_ in calls]==['material/add_material','material/add_material','draft/add']
    filename,content,mime=calls[1][1]['files']['media']
    assert filename.endswith('.gif') and mime=='image/gif'
    with Image.open(io.BytesIO(content)) as image:assert image.is_animated
    body=calls[-1][1]['payload']['articles'][0]['content']
    assert 'mmbiz_gif/template/0' in body and 'data:image' not in body and '<svg' not in body
    assert calls[-1][1]['payload']['articles'][0]['thumb_media_id']=='cover-media'
    saved=wechat_delivery.get(run['id']);assert saved['data']['animation_media']['template-decoration-firefly']=='gif-media'
    before=len(calls);wechat_delivery.deliver(run['id'],article_worker.get(run['content_id']),TaskSettings.model_validate(task['settings']))
    assert len(calls)==before
