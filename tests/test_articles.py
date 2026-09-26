import io
import json
import zipfile
import pytest
from fastapi.testclient import TestClient
from backend import config, db, article_worker as worker, article_ai, sources
from backend.app import app
from backend.article_models import Angles, Angle, ArticleProfile, ArticleOutline, ArticleDocument, ArticleCheck, ArticleSection


SOURCE_TEXT = '公开报告显示，团队在试验环境中比较了两种工作方法。作者强调结果只适用于当前任务，不代表所有人的效率都会提高。'
REAL_DOCUMENT_WRITER = article_ai.document


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA', tmp_path)
    monkeypatch.setattr(config, 'API_KEY', 'test-only')
    monkeypatch.setattr(config, 'MODEL', 'test-only')
    monkeypatch.setattr(worker.executor, 'submit', lambda *args: None)
    monkeypatch.setattr(article_ai, 'angles', lambda *args: Angles(choices=[{'title':'从一个小任务开始','angle':'用实际任务观察工具的适用边界','reason':'让普通读者知道如何开始尝试'}]))
    monkeypatch.setattr(article_ai, 'outline', lambda *args: ArticleOutline(title='从一个小任务开始',angle='理解适用边界',sections=[{'heading':'先理解任务','points':'说明方法与局限'}],source_gaps=[]))
    monkeypatch.setattr(article_ai, 'document', lambda *args: ArticleDocument(title='从一个小任务开始',titles=['从一个小任务开始'],summary='一次有边界的尝试',opening='从你熟悉的任务出发。',sections=[{'heading':'理解局限','paragraphs':['可以先描述任务，再考虑工具是否合适。'],'evidence':[]}],closing='用实际体验形成自己的判断。'))
    monkeypatch.setattr(article_ai, 'check', lambda *args,**kwargs: ArticleCheck(issues=[],note='模拟模型未发现额外问题，仍需人工核验。'))
    with TestClient(app) as c:
        yield c


def create(client, **kwargs):
    body={'mode':'original','brief':'如何开始尝试新工具','request_id':'test-article-0001',**kwargs}
    r=client.post('/api/articles',json=body)
    assert r.status_code==201,r.text
    return r.json()


def advance(client, article, action, **extra):
    r=client.post(f'/api/articles/{article["id"]}/{action}',json={'version':article['version'],**extra})
    assert r.status_code==200,r.text
    worker.run(article['id'])
    return client.get(f'/api/articles/{article["id"]}').json()


def draft(client, **kwargs):
    article=create(client,**kwargs)
    worker.run(article['id'])
    article=worker.get(article['id'])
    article=advance(client,article,'angle',choice=0)
    assert article['status']=='needs_outline'
    assert article['document'] is None
    return advance(client,article,'generate')


def revise_context(client,article,**changes):
    return client.put(f'/api/articles/{article["id"]}/context',json={'version':article['version'],'subject':'古城旅行的新方向','brief':'围绕真实建筑细节展开，不使用旧的职场案例','mode':'original','notes':'','topic_ids':[],'action':'save',**changes})


def test_context_edit_preserves_document_and_restores_original_sources_and_brief(client):
    article=draft(client,notes='这是旧版本的个人参考笔记，恢复时也应当与文章一起恢复。')
    revised=revise_context(client,article,notes='新版本参考笔记：沿着街巷介绍建筑的材料与空间特点。',query='平遥 建筑').json()
    assert revised['document']==article['document'] and revised['outline']==article['outline']
    assert revised['input_data']['_subject']=='古城旅行的新方向' and revised['input_data']['query']=='平遥 建筑'
    assert revised['source_data'][0]['text'].startswith('新版本参考笔记')
    assert revised['checks'] is None and revised['version']==article['version']+1
    assert revise_context(client,article).status_code==409
    restored=client.post(f'/api/articles/{article["id"]}/restore',json={'version':revised['version'],'target_version':article['version']}).json()
    assert restored['source_data']==article['source_data']
    assert restored['input_data']==article['input_data'] and restored['document']==article['document']
    # Save-only leaves the selected angle valid for the existing generate action.
    saved=revise_context(client,restored).json()
    generated=advance(client,saved,'generate',replace_existing=True)
    assert generated['status'] in ('needs_review','needs_revision')


@pytest.mark.parametrize('action,final_status',[('angles','needs_angle'),('outline','needs_outline'),('article','needs_review')])
def test_context_regeneration_uses_new_brief_and_sources_without_creating_article(client,monkeypatch,action,final_status):
    original=draft(client);seen=[]
    def angles(profile,brief,sources,ident):
        seen.append((brief,sources,ident))
        return Angles(choices=[Angle(title='新选题的建筑观察',angle='从屋檐和门窗理解建筑细节',reason='提供具体的旅行观察方式')])
    monkeypatch.setattr(article_ai,'angles',angles)
    response=revise_context(client,original,action=action,notes='本次参考笔记只用于新主题，请围绕建筑细节独立组织正文。')
    assert response.status_code==200,response.text
    queued=response.json();assert queued['stage']=='replan' and queued['document']==original['document']
    worker.run(original['id']);result=worker.get(original['id'])
    assert result['status']==final_status and result['id']==original['id']
    assert len(client.get('/api/articles').json())==1
    assert '古城旅行的新方向' in seen[0][0] and '旧的职场案例' in seen[0][0]
    assert seen[0][1][0]['text'].startswith('本次参考笔记')
    assert result['angles']['choices'][0]['title']=='新选题的建筑观察'
    if action in ('angles','outline'):assert result['document'] is None
    if action=='outline':assert advance(client,result,'generate')['status']=='needs_review'
    assert any(v['version']==original['version'] for v in client.get(f'/api/articles/{original["id"]}').json()['versions'])


def test_context_generation_failure_keeps_existing_body_and_can_retry(client,monkeypatch):
    original=draft(client);writer=article_ai.document
    def fail(*args):raise ValueError('simulated model interruption')
    monkeypatch.setattr(article_ai,'document',fail)
    queued=revise_context(client,original,action='article').json();worker.run(original['id'])
    failed=worker.get(original['id']);assert failed['status']=='failed' and failed['stage']=='replan'
    assert failed['document']==original['document'] and failed['outline']==original['outline']
    monkeypatch.setattr(article_ai,'document',writer)
    retried=advance(client,failed,'retry');assert retried['status']=='needs_review'


def test_context_validates_sources_and_rejects_busy_or_stale_writes(client):
    original=draft(client)
    assert revise_context(client,original,mode='reference').status_code==422
    assert revise_context(client,original,topic_ids=['missing']).status_code==400
    assert worker.get(original['id'])['version']==original['version']
    queued=revise_context(client,original,action='angles').json()
    assert revise_context(client,queued).status_code==409


def test_original_flow_profile_snapshot_versions_and_restore(client):
    profile=client.get('/api/article-profile').json()
    profile.update(direction='职场效率',audience='刚入职的年轻人',length=400)
    assert client.put('/api/article-profile',json=profile).status_code==200
    article=draft(client)
    assert article['profile']['direction']=='职场效率'
    assert article['status']=='needs_review'
    assert article['document'] and len(article['versions'])==5
    assert any('未附参考' in i['message'] for i in article['checks']['issues'])
    # Editing the account later does not mutate a production's saved preferences.
    profile['direction']='生活方式'
    client.put('/api/article-profile',json=profile)
    assert worker.get(article['id'])['profile']['direction']=='职场效率'
    path='/api/articles/'+article['id']
    doc=article['document'];doc['title']='编辑后的标题'
    edited=client.put(path+'/document',json={'version':article['version'],'document':doc})
    assert edited.status_code==200,edited.text
    assert edited.json()['checks'] is None
    assert client.put(path+'/document',json={'version':article['version'],'document':doc}).status_code==409
    restored=client.post(path+'/restore',json={'version':edited.json()['version'],'target_version':article['version']})
    assert restored.status_code==200,restored.text
    assert restored.json()['document']['title']=='从一个小任务开始'
    assert restored.json()['version']>edited.json()['version']
    assert len(client.get(path).json()['versions'])==7


def test_all_article_forms_save_and_reject_unknown_values(client):
    from backend.article_formats import ARTICLE_FORMATS
    profile=client.get('/api/article-profile').json()
    for form in ARTICLE_FORMATS:
        response=client.put('/api/article-profile',json={**profile,'format':form})
        assert response.status_code==200,response.text
        assert client.get('/api/article-profile').json()['format']==form
    assert client.put('/api/article-profile',json={**profile,'format':'unknown-form'}).status_code==422
    # Existing saved preferences continue to validate without migration.
    for form in ['解读','教程','清单','随笔']:
        assert ArticleProfile.model_validate({**profile,'format':form}).format==form


@pytest.mark.parametrize('form',['访谈','旅行攻略','产品测评','故事'])
def test_selected_form_guides_all_writing_stages(monkeypatch,form):
    from backend.article_formats import ARTICLE_FORMATS
    calls={};profile=ArticleProfile(format=form)
    angle=Angle(title='平遥',angle='认识古城的特色',reason='帮助读者理解文化')
    outline=ArticleOutline(title='平遥',angle=angle.angle,sections=[{'heading':'建筑','points':'介绍古城建筑'}])
    doc=finished_travel_document()
    def request(schema,prompt,data,job_id,kind,**kwargs):
        calls[kind]=(prompt,data)
        return {Angles:Angles(choices=[angle]),ArticleOutline:outline,ArticleDocument:doc,ArticleSection:doc.sections[0],ArticleCheck:ArticleCheck(note='检查完成')}[schema]
    monkeypatch.setattr(article_ai,'request_structured',request)
    article_ai.angles(profile,'介绍平遥',[],'form-test')
    article_ai.outline(profile,'介绍平遥',angle,[],'form-test')
    article_ai.document(profile,'介绍平遥',angle,outline,[],'form-test')
    article_ai.rewrite(profile,doc,0,'缩短',[],'form-test')
    article_ai.check(doc,[],'form-test',brief='介绍平遥',profile=profile)
    for stage in ['article_angles','article_outline','article_document','article_rewrite']:
        assert ARTICLE_FORMATS[form]['guide'] in calls[stage][0]
        assert '成品文章' in calls[stage][0]
    assert calls['article_check'][1]['profile']['format']==form
    assert ARTICLE_FORMATS[form]['guide'] in calls['article_check'][1]['format_guidance']


def test_reference_and_notes_are_frozen_and_do_not_exclude_video_topics(client):
    topic=client.post('/api/sources/import',json={'url':'https://example.com/article','title':'公开报告','text':SOURCE_TEXT}).json()['topic_id']
    with db.connect() as c:
        c.execute('INSERT INTO jobs(id,topic_id,request_id,status,stage,mode,settings,created_at,updated_at,day) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                  ('old-video',topic,'old-video-request','approved','review','ai','{}',db.now(),db.now(),db.day()))
    article=create(client,mode='reference',topic_ids=[topic],notes='这是我自己补充的一段工作实践笔记，需要一起纳入写作参考资料。')
    assert len(article['source_data'])==2
    assert article['source_data'][1]['id']=='personal-notes'
    with db.connect() as c:
        c.execute("UPDATE topics SET title='changed',data='{}' WHERE id=%s",(topic,))
    assert worker.get(article['id'])['source_data'][0]['text']==SOURCE_TEXT
    assert worker.get(article['id'])['source_data'][0]['title']=='公开报告'


def test_validation_idempotency_and_busy_mutations(client):
    assert client.post('/api/articles',json={'mode':'reference','request_id':'test-empty'}).status_code==422
    assert client.post('/api/articles',json={'mode':'original','request_id':'test-empty'}).status_code==400
    assert client.post('/api/articles',json={'mode':'reference','topic_ids':['missing'],'request_id':'test-missing'}).status_code==400
    article=create(client)
    assert create(client)['id']==article['id']
    assert client.post('/api/articles',json={'mode':'original','brief':'不同主题','request_id':'test-article-0001'}).status_code==409
    path='/api/articles/'+article['id']
    assert client.post(path+'/angle',json={'version':article['version'],'choice':0}).status_code==409
    assert client.get(path+'/export').status_code==409
    worker.run(article['id'])
    ready=worker.get(article['id'])
    assert client.post(path+'/angle',json={'version':ready['version'],'choice':4}).status_code==400
    assert client.post(path+'/angle',json={'version':ready['version'],'choice':0}).status_code==200
    assert client.post(path+'/angle',json={'version':ready['version'],'choice':0}).status_code==409


def test_resume_failed_check_without_regenerating_body(client,monkeypatch):
    def failed(*args,**kwargs):raise RuntimeError('fake-sensitive-response')
    monkeypatch.setattr(article_ai,'check',failed)
    article=draft(client)
    assert article['status']=='failed' and article['stage']=='check' and article['document']
    assert 'fake-sensitive-response' not in article['error']
    old=article['document']
    monkeypatch.setattr(article_ai,'document',lambda *args:pytest.fail('must not regenerate saved document'))
    monkeypatch.setattr(article_ai,'check',lambda *args,**kwargs:ArticleCheck(issues=[],note='检查完成'))
    article=advance(client,article,'retry')
    assert article['status']=='needs_review' and article['document']==old


def test_recovery_and_partial_outline_retries(client,monkeypatch):
    article=create(client)
    worker.run(article['id'])
    ready=worker.get(article['id'])
    monkeypatch.setattr(article_ai,'outline',lambda *args:(_ for _ in ()).throw(ValueError('failed')))
    failed=advance(client,ready,'angle',choice=0)
    assert failed['status']=='failed' and failed['angles']
    with db.connect() as c:
        c.execute("UPDATE articles SET status='running' WHERE id=%s",(article['id'],))
    worker.recover()
    assert worker.get(article['id'])['status']=='failed'
    assert '服务中断' in worker.get(article['id'])['error']
    db.init()  # additive schema initialization preserves content and profiles
    assert worker.get(article['id'])['angles']==failed['angles']


def test_quote_validation_suspicious_overlap_and_section_rewrite(client,monkeypatch):
    article=draft(client,notes=SOURCE_TEXT)
    doc=article['document'];doc['sections'][0]['evidence']=[{'source_id':'personal-notes','quote':'不存在于原文的引文，请勿当作真实引用'}]
    doc['sections'][0]['caption']='图片说明与原始署名'
    path='/api/articles/'+article['id']
    saved=client.put(path+'/document',json={'version':article['version'],'document':doc}).json()
    checked=advance(client,saved,'check')
    assert checked['status']=='needs_revision'
    assert any(i['severity']=='error' for i in checked['checks']['issues'])
    monkeypatch.setattr(article_ai,'rewrite',lambda *args:ArticleSection(heading='修改后的本节',paragraphs=['这是简短的解释。'],evidence=[]))
    changed=advance(client,checked,'rewrite',section=0,instruction='缩短')
    assert changed['document']['sections'][0]['heading']=='修改后的本节'
    assert changed['document']['opening']==article['document']['opening']
    assert changed['document']['title']==article['document']['title']
    assert changed['document']['sections'][0]['caption']=='图片说明与原始署名'


def test_safe_export_includes_images_and_sources(client):
    from PIL import Image
    image=io.BytesIO();Image.new('RGB',(30,30),'green').save(image,format='PNG')
    asset=client.post('/api/assets',files={'file':('own.png',image.getvalue(),'image/png')},data={'rights':'本人原创图片','credit':'作者'}).json()
    article=draft(client)
    path='/api/articles/'+article['id'];doc=article['document']
    doc['title']='<script>alert(1)</script>'
    doc['sections'][0]['asset_id']=asset['id'];doc['sections'][0]['caption']='本人拍摄'
    saved=client.put(path+'/document',json={'version':article['version'],'document':doc}).json()
    assert client.get(path+'/export',params={'version':article['version']}).status_code==409
    html=client.get(path+'/export').text
    assert '<script>' not in html and '&lt;script&gt;' in html and 'style=' in html
    md=client.get(path+'/export?format=markdown').text
    assert '<script>' not in md
    assert client.get(path+'/export?format=exe').status_code==400
    bundle=client.get(path+'/export?format=bundle')
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert {'article.html','article.md','sources.json','checks.json'} <= set(archive.namelist())
        assert any(name.startswith('images/') for name in archive.namelist())
        assert 'images/' in archive.read('article.html').decode()
        assert json.loads(archive.read('assets.json'))[0]['credit']=='作者'
    doc['cover_asset_id']='missing-image'
    assert client.put(path+'/document',json={'version':saved['version'],'document':doc}).status_code==400


def test_template_inherits_profile_and_survives_edit_regeneration_and_restore(client):
    profile=client.get('/api/article-profile').json();profile['template_id']='tech'
    assert client.put('/api/article-profile',json=profile).status_code==200
    article=draft(client);path='/api/articles/'+article['id']
    assert article['document']['template_id']=='tech'
    doc={**article['document'],'template_id':'travel'}
    saved=client.put(path+'/document',json={'version':article['version'],'document':doc}).json()
    assert saved['document']['title']==article['document']['title'] and saved['document']['template_id']=='travel'
    assert 'data-article-template="travel"' in client.get(path+'/export').text
    with zipfile.ZipFile(io.BytesIO(client.get(path+'/export?format=bundle').content)) as archive:
        assert 'data-article-template="travel"' in archive.read('article.html').decode()
        assert json.loads(archive.read('article.json'))['template_id']=='travel'
    # Regeneration retains the article's saved choice, independent of account defaults.
    regenerated=advance(client,saved,'generate',replace_existing=True)
    assert regenerated['document']['template_id']=='travel'
    restored=client.post(path+'/restore',json={'version':regenerated['version'],'target_version':article['version']}).json()
    assert restored['document']['template_id']=='tech'
    assert client.put(path+'/document',json={'version':restored['version'],'document':{**doc,'template_id':'unknown'}}).status_code==422


def test_each_template_exports_safe_complete_content_and_images():
    from backend import article_export,article_templates
    from bs4 import BeautifulSoup
    doc=finished_travel_document().model_dump();doc['title']='<script>alert(1)</script>'
    doc['cover_asset_id']='cover';doc['sections'][0].update(asset_id='inline',caption='图注 <img onerror="bad">')
    appearances=set()
    for ident in article_templates.TEMPLATES:
        rendered=article_export.html_body({**doc,'template_id':ident},{'cover':'images/cover.png','inline':'images/inline.png'})
        soup=BeautifulSoup(rendered,'html.parser');template=article_templates.get_template(ident)
        assert not soup.select('script,style') and soup.h1.get_text()==doc['title']
        assert soup.select_one('[data-article-template]')['data-article-template']==ident
        assert len(soup.select('figure img'))==2 and soup.figcaption.get_text()==doc['sections'][0]['caption']
        decoration=soup.select_one('img[data-template-decoration]')
        assert bool(decoration)==bool(template['decoration'])
        if decoration:assert decoration['src'].startswith('data:image/png;base64,')
        assert doc['opening'] in soup.get_text() and doc['closing'] in soup.get_text()
        assert ('01' in soup.h2.get_text())==template['numbered']
        appearances.add(soup.h1['style'])
    assert len(appearances)==len(article_templates.TEMPLATES)==18
    assert 'data-article-template="classic"' in article_export.html_body(doc)
    assert ArticleDocument.model_validate(doc).template_id=='classic'


def test_wechat_layout_keeps_all_text_images_and_colors_without_inline_heading_badges():
    from backend import article_export,article_templates
    from bs4 import BeautifulSoup
    doc=finished_travel_document().model_dump()
    doc['sections'][0].update(asset_id='inline',caption='正文配图')
    for ident in article_templates.TEMPLATES:
        doc['template_id']=ident
        original=BeautifulSoup(article_export.html_body(doc,{'inline':'https://mmbiz.qpic.cn/example.jpg'}),'html.parser')
        rendered=BeautifulSoup(article_export.html_body(doc,{'inline':'https://mmbiz.qpic.cn/example.jpg'},wechat=True),'html.parser')
        assert not rendered.select('h2 span'), 'WeChat blocks inline heading badges during paste'
        assert rendered.h2['style']==original.h2['style']
        assert rendered.select_one('figure img')['src']==original.select_one('figure img')['src']
        assert not rendered.select('img[src^="data:"]')
        assert rendered.h1.get_text()==doc['title']
        assert doc['opening'] in rendered.get_text() and doc['closing'] in rendered.get_text()
        for section in doc['sections']:
            assert section['heading'] in rendered.get_text()
            assert all(p in rendered.get_text() for p in section['paragraphs'])
        if article_templates.get_template(ident)['numbered']:
            assert rendered.h2.get_text().startswith('01 · ')
            assert original.select('h2 span'), 'Local template exports retain their badges'


def test_new_templates_save_restore_and_export_portable_decorations(client):
    from backend import article_templates,article_export,wechat_delivery
    from typing import get_args
    from backend.article_models import ArticleTemplate
    from bs4 import BeautifulSoup
    from PIL import Image
    assert set(get_args(ArticleTemplate))==set(article_templates.TEMPLATES)
    article=draft(client);path='/api/articles/'+article['id']
    for ident in ('cream','sage','journal','editorial','newspaper','ink','rose','ocean','coffee','butter','postcard','midnight'):
        original=article['document']
        response=client.put(path+'/document',json={'version':article['version'],'document':{**original,'template_id':ident}})
        assert response.status_code==200,response.text
        article=response.json();assert article['document']['title']==original['title']
        ornament=article_templates.decoration_id(article['document'])
        with zipfile.ZipFile(io.BytesIO(client.get(path+'/export?format=bundle').content)) as archive:
            soup=BeautifulSoup(archive.read('article.html'),'html.parser')
            assert json.loads(archive.read('article.json'))['template_id']==ident
            for image in soup.select('img'):
                assert image['src'] in archive.namelist()
                with Image.open(io.BytesIO(archive.read(image['src']))) as picture:assert picture.width>=400
            assert bool(soup.select('img'))==bool(ornament)
        if ornament:
            with Image.open(io.BytesIO(wechat_delivery.image_bytes(ornament))) as picture:assert picture.format=='JPEG'
            rendered=article_export.html_body(article['document'],{ornament:'https://mmbiz.qpic.cn/decoration.jpg'},wechat=True)
            assert 'https://mmbiz.qpic.cn/decoration.jpg' in rendered and 'data:image' not in rendered
    assert article_templates.decoration_path('../../private') is None


def test_link_import_reuses_safe_collector_and_keeps_manual_fallback(client,monkeypatch):
    called=[]
    monkeypatch.setattr(sources,'load_page',lambda url:called.append(url) or {'url':url,'title':'公众号正文','text':SOURCE_TEXT,'full_text':True,'published_at':None,'method':'http','images':[],'links':[]})
    r=client.post('/api/article-sources/link',json={'url':'https://mp.weixin.qq.com/s/example'})
    assert r.status_code==200,r.text
    assert r.json()['sources'][0]['text']==SOURCE_TEXT
    assert client.post('/api/article-sources/link',json={'url':'http://127.0.0.1/private'}).status_code==422
    assert len(called)==1
    def blocked(url):raise ValueError('需要验证，请导入正文。')
    monkeypatch.setattr(sources,'load_page',blocked)
    assert '导入正文' in client.post('/api/article-sources/link',json={'url':'https://example.com/article'}).json()['detail']


def test_outline_edits_are_used_by_generator(client,monkeypatch):
    article=create(client);worker.run(article['id']);article=advance(client,worker.get(article['id']),'angle',choice=0)
    outline=article['outline'];outline['sections'][0]['points']='用户补充的论述重点'
    path='/api/articles/'+article['id']
    edited=client.put(path+'/outline',json={'version':article['version'],'outline':outline}).json()
    original=article_ai.document
    def generator(*args):
        assert args[3].sections[0].points=='用户补充的论述重点'
        return original(*args)
    monkeypatch.setattr(article_ai,'document',generator)
    finished=advance(client,edited,'generate')
    assert finished['document']
    assert client.put(path+'/outline',json={'version':finished['version'],'outline':outline}).status_code==400


def test_original_from_direction_only_and_long_overlap(client):
    prefs=client.get('/api/article-profile').json();prefs['direction']='面向上班族的工作方法'
    client.put('/api/article-profile',json=prefs)
    article=create(client,brief='')
    assert article['input_data']['brief']==''
    text=SOURCE_TEXT*500
    doc=ArticleDocument(title='示例',titles=['示例'],summary='摘要',sections=[{'heading':'原文引用','paragraphs':[SOURCE_TEXT*3]}])
    issues=article_ai.local_issues(doc,[{'id':'source','title':'原始资料','text':text,'full_text':True}],400)
    assert any('60 字连续相同' in i['message'] for i in issues)


@pytest.mark.parametrize('protocol',['responses','chat_completions'])
def test_truncated_article_retains_outline_and_explains_limit(client,monkeypatch,protocol):
    import httpx
    from contextlib import contextmanager
    from backend import ai
    # Exercise the real protocol adapter, including usage accounting.
    connection={'name':'test','base_url':'https://example.com/v1','model':'test-model','protocol':protocol,'output_mode':'json_object','api_key':'test-not-real'}
    assert client.put('/api/model-config',json=connection).status_code==200
    article=create(client);worker.run(article['id']);article=advance(client,worker.get(article['id']),'angle',choice=0)
    budgets=[]
    def post(url,**kwargs):
        payload=kwargs['json'];budgets.append(payload.get('max_tokens') or payload.get('max_output_tokens'))
        response={'choices':[{'finish_reason':'length','message':{'content':'{"partial":'}}]} if protocol=='chat_completions' else {'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]}
        return httpx.Response(200,request=httpx.Request('POST',url),json=response)
    monkeypatch.setattr(ai.httpx,'post',post)
    @contextmanager
    def stream(method,url,**kwargs):yield post(url,**kwargs)
    monkeypatch.setattr(ai.httpx,'stream',stream)
    monkeypatch.setattr(article_ai,'document',REAL_DOCUMENT_WRITER)
    failed=advance(client,article,'generate')
    assert budgets==[16000]
    assert failed['status']=='failed' and failed['outline']==article['outline']
    assert failed['document'] is None and '输出达到上限' in failed['error']

def test_reselect_angle_requires_confirmation_and_retains_restorable_body(client):
    article=draft(client);path='/api/articles/'+article['id']
    assert client.post(path+'/angle',json={'version':article['version'],'choice':0}).status_code==400
    result=client.post(path+'/angle',json={'version':article['version'],'choice':0,'replace_existing':True})
    assert result.status_code==200,result.text
    assert result.json()['document'] is None and result.json()['outline'] is None
    assert result.json()['version']==article['version']+1
    assert client.post(path+'/angle',json={'version':article['version'],'choice':0,'replace_existing':True}).status_code==409
    worker.run(article['id']);updated=worker.get(article['id'])
    assert updated['status']=='needs_outline'
    restored=client.post(path+'/restore',json={'version':updated['version'],'target_version':article['version']})
    assert restored.status_code==200 and restored.json()['document']==article['document']


def test_return_to_outline_edit_and_regenerate_preserves_previous_versions(client,monkeypatch):
    article=draft(client);path='/api/articles/'+article['id']
    outline=article['outline'];outline['sections'][0]['points']='返回修改后的结构要点'
    result=client.put(path+'/outline',json={'version':article['version'],'outline':outline,'replace_existing':True})
    assert result.status_code==200,result.text
    assert result.json()['document'] is None and result.json()['status']=='needs_outline'
    seen=[];original=article_ai.document
    def write(*args):seen.append(args[3].sections[0].points);return original(*args)
    monkeypatch.setattr(article_ai,'document',write)
    generated=advance(client,result.json(),'generate')
    assert seen==['返回修改后的结构要点'] and generated['document']
    assert client.post(path+'/generate',json={'version':generated['version']}).status_code==400
    second=advance(client,generated,'generate',replace_existing=True)
    assert second['document'] and second['version']>generated['version']
    history=client.get(path).json()['versions']
    assert any(v['version']==article['version'] and v['restorable'] for v in history)


def unfinished_travel_document():
    return ArticleDocument(title='早上七点前后，平遥和游客看到的不是同一个城',titles=['早上七点前后，平遥和游客看到的不是同一个城'],
        summary='因目前没有来源材料和实地记录，正文以可编辑占位和采访问题为主。',
        opening='这篇先从一个假设的场景开始。开头只建立场景和问题，不展开。',
        sections=[{'heading':'天亮前后：居民的时间表','paragraphs':['这一节要分几条线记：买菜或早市、学生上学。现在这些信息我都没有，所以只能先留占位：【待核实：早市位置与时间】。']},
                  {'heading':'结尾','paragraphs':['画面待定：可能是某条巷子。结尾约100字，留白给读者。']}])


def finished_travel_document():
    return ArticleDocument(title='在平遥，把脚步放慢一点',titles=['在平遥，把脚步放慢一点'],summary='一座古城的趣味，藏在街巷与建筑之间。',
        opening='游览平遥，不妨给自己留一点慢慢走路的时间。城墙、街巷和院落，让古城的轮廓变得具体。',
        sections=[{'heading':'从街巷认识古城','paragraphs':['城墙把目光引向远处，街巷则把人带回细节。与其急着赶往下一处景点，不如放慢脚步，看看建筑之间的关系。']}],closing='一次旅行未必要装满行程。留一点空闲，古城也就多了一种读法。')


def test_plan_is_rewritten_once_as_finished_content(monkeypatch):
    calls=[];bad=unfinished_travel_document();good=finished_travel_document()
    def request(schema,prompt,data,job_id,kind,**options):
        calls.append((kind,data,options))
        return bad if len(calls)==1 else good
    monkeypatch.setattr(article_ai,'request_structured',request)
    outline=ArticleOutline(title=bad.title,angle='居民的一天',sections=[{'heading':'采访居民','points':'先采访再填写'}],source_gaps=['没有实地记录'])
    doc=REAL_DOCUMENT_WRITER(ArticleProfile(), '介绍一处山西旅游景点', Angle(title='平遥',angle='通过街巷介绍古城',reason='适合旅行读者'),outline,[],'quality-test')
    assert doc==good
    assert [c[0] for c in calls]==['article_document','article_document_repair']
    assert calls[1][1]['previous_draft']['summary']==bad.summary
    assert calls[1][1]['quality_issues'] and calls[1][1]['brief']=='介绍一处山西旅游景点'


def test_repeated_plan_fails_without_publishing_placeholders(client,monkeypatch):
    calls=[]
    def request(schema,prompt,data,job_id,kind,**options):
        calls.append(kind);return unfinished_travel_document()
    monkeypatch.setattr(article_ai,'request_structured',request)
    monkeypatch.setattr(article_ai,'document',REAL_DOCUMENT_WRITER)
    result=draft(client)
    assert calls==['article_document','article_document_repair']
    assert result['status']=='failed' and result['stage']=='article'
    assert result['outline'] and result['document'] is None
    assert '写作方案' in result['error'] and '自动修正一次' in result['error']


def test_content_checks_detect_plans_but_allow_reader_facing_tutorials():
    assert len(article_ai.unfinished_issues(unfinished_travel_document()))==3
    travel=finished_travel_document()
    assert article_ai.unfinished_issues(travel)==[]
    tutorial=travel.model_copy(update={'title':'如何写出清楚的旅行笔记','summary':'先确定主题，再整理自己的观察。',
        'sections':[ArticleSection(heading='先选一个具体主题',paragraphs=['写游记时，可以先选一个具体主题，再把自己拍下的照片按时间排列。不要为了凑字数编造没有发生的经历。'])]})
    assert article_ai.unfinished_issues(tutorial)==[]
    assert any(i['severity']=='error' for i in article_ai.local_issues(unfinished_travel_document(),[],800))


def test_duplicate_opening_and_closing_are_not_rendered_as_extra_sections():
    doc=finished_travel_document();body=doc.sections[0]
    doc.sections=[ArticleSection(heading='开头',paragraphs=[doc.opening]),body,ArticleSection(heading='结尾',paragraphs=[doc.closing])]
    result=article_ai.remove_repeated_edges(doc)
    assert result.sections==[body]
    assert result.opening==doc.opening and result.closing==doc.closing
    assert len(doc.sections)==3 # The caller's input is not mutated.


def test_check_receives_actual_brief_and_account_context(client,monkeypatch):
    contexts=[]
    def check(*args,**kwargs):
        contexts.append(kwargs);return ArticleCheck(issues=[{'severity':'error','section':0,'message':'返回的是采访方案而非景点介绍。'}],note='需要调整成品内容')
    monkeypatch.setattr(article_ai,'check',check)
    result=draft(client,brief='介绍一处山西景点，不要写采访计划')
    assert contexts[0]['brief']=='介绍一处山西景点，不要写采访计划'
    assert contexts[0]['profile'].name==result['profile']['name']
    assert result['status']=='needs_revision'


@pytest.mark.parametrize('target,extra',[
    ('title',{}),('summary',{}),('opening',{}),('closing',{}),
    ('heading',{'section':0}),('paragraphs',{'section':0}),('paragraph',{'section':0,'paragraph':1}),
])
def test_custom_rewrite_changes_only_selected_field_and_preserves_history(client,monkeypatch,target,extra):
    from copy import deepcopy
    from backend.article_models import RewrittenText
    article=draft(client);path='/api/articles/'+article['id'];doc=deepcopy(article['document'])
    doc['sections'][0]['paragraphs']=['第一段保留','第二段的原文']
    doc['sections'].append({**deepcopy(doc['sections'][0]),'heading':'其他章节'})
    article=client.put(path+'/document',json={'version':article['version'],'document':doc}).json()
    original=deepcopy(article['document']);observed=[]
    def rewrite(profile,brief,document,scope,sources,ident):
        observed.append(scope)
        return RewrittenText(text='按照提示重写的内容')
    monkeypatch.setattr(article_ai,'rewrite_part',rewrite)
    response=client.post(path+'/rewrite',json={'version':article['version'],'target':target,**extra,'instruction':'改成具体的用途说明，不要抽象议论'})
    assert response.status_code==200,response.text
    assert response.json()['document']==original
    worker.run(article['id']);result=worker.get(article['id'])
    expected=deepcopy(original)
    if target=='heading':expected['sections'][0]['heading']='按照提示重写的内容'
    elif target=='paragraphs':expected['sections'][0]['paragraphs']=['按照提示重写的内容']
    elif target=='paragraph':expected['sections'][0]['paragraphs'][1]='按照提示重写的内容'
    else:expected[target]='按照提示重写的内容'
    assert result['document']==expected
    assert observed[0]['instruction']=='改成具体的用途说明，不要抽象议论'
    restored=client.post(path+'/restore',json={'version':result['version'],'target_version':article['version']}).json()
    assert restored['document']==original


def test_local_rewrite_atomically_saves_unsaved_content_and_rejects_stale_or_invalid_target(client,monkeypatch):
    from backend.article_models import RewrittenText
    article=draft(client);path='/api/articles/'+article['id'];doc=article['document'];doc['summary']='用户尚未保存的摘要'
    body={'version':article['version'],'target':'paragraph','section':0,'paragraph':9,'instruction':'改写','document':doc}
    assert client.post(path+'/rewrite',json=body).status_code==400
    assert worker.get(article['id'])['document']['summary']!='用户尚未保存的摘要'
    body.update(paragraph=0)
    result=client.post(path+'/rewrite',json=body)
    assert result.status_code==200 and result.json()['document']['summary']=='用户尚未保存的摘要'
    assert client.post(path+'/rewrite',json=body).status_code==409
    monkeypatch.setattr(article_ai,'rewrite_part',lambda *a:RewrittenText(text='【待填写：新正文】'))
    worker.run(article['id']);failed=worker.get(article['id'])
    assert failed['status']=='failed' and failed['document']==doc
    assert client.post(path+'/rewrite',json={'version':failed['version'],'target':'title','instruction':' '*4}).status_code==422
    assert client.post(path+'/rewrite',json={'version':failed['version'],'target':'title','instruction':'x'*2001}).status_code==422
    assert client.post(path+'/rewrite',json={'version':failed['version'],'target':'paragraph','section':-1,'paragraph':0,'instruction':'润色'}).status_code==422


@pytest.mark.parametrize('protocol',['responses','chat_completions'])
def test_real_provider_stream_is_incremental_and_records_usage(client,monkeypatch,protocol):
    import httpx
    from backend import ai,ai_stream,article_stream
    from backend.article_models import RewrittenText
    received=[];calls=[]
    if protocol=='chat_completions':
        packets=[{'choices':[{'index':0,'delta':{'content':'{"text":"实时'},'finish_reason':None}]},
                 {'choices':[{'index':0,'delta':{'content':'文字"}'},'finish_reason':'stop'}]},
                 {'choices':[],'usage':{'prompt_tokens':12,'completion_tokens':8}}]
    else:
        packets=[{'type':'response.output_text.delta','delta':'{"text":"实时'},
                 {'type':'response.output_text.delta','delta':'文字"}'},
                 {'type':'response.completed','response':{'status':'completed','usage':{'input_tokens':12,'output_tokens':8},'output':[]}}]
    class Bytes(httpx.SyncByteStream):
        def __iter__(self):
            for packet in packets:
                raw=('data: '+json.dumps(packet,ensure_ascii=False)+'\n\n').encode()
                for offset in range(0,len(raw),7):yield raw[offset:offset+7]
                received.append(article_stream.get('live-test'))
            yield b'data: [DONE]\n\n'
    def handler(request):
        calls.append(json.loads(request.content));return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Bytes())
    transport=httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ai_stream.httpx,'stream',transport.stream)
    with article_stream.capture('live-test'):
        result=ai.request_structured(RewrittenText,'返回内容',{},'live-test','article_rewrite',connection={
            'model':'test','api_key':'test-private','base_url':'https://example.com/v1','protocol':protocol,'output_mode':'json_schema'})
    assert result.text=='实时文字' and len(calls)==1 and calls[0]['stream']
    assert received[0]['partial']['text']=='实时'
    assert article_stream.get('live-test')['partial']['text']=='实时文字'
    with db.connect() as c:
        usage=c.execute("SELECT status,input_tokens,output_tokens FROM ai_usage WHERE job_id='live-test'").fetchone()
        assert tuple(usage.values())==('received',12,8)
    transport.close()


@pytest.mark.parametrize('body',[
    'data: {"choices":[{"delta":{"content":"{\\"text\\":\\"看似完整\\"}"}}]}\n\n',
    'data: {"error":{"message":"do-not-echo-private-token"}}\n\n',
])
def test_broken_stream_never_returns_success_or_raw_provider_errors(client,monkeypatch,body):
    import httpx
    from backend import ai,ai_stream,article_stream
    from backend.article_models import RewrittenText
    transport=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=body)))
    monkeypatch.setattr(ai_stream.httpx,'stream',transport.stream)
    with article_stream.capture('broken-test'),pytest.raises(ValueError) as error:
        ai.request_structured(RewrittenText,'返回内容',{},'broken-test','article_rewrite',connection={
            'model':'test','api_key':'test-private','base_url':'https://example.com/v1','protocol':'chat_completions','output_mode':'json_object'})
    assert 'do-not-echo-private-token' not in str(error.value)
    transport.close()


@pytest.mark.parametrize('protocol',['chat_completions','responses'])
@pytest.mark.parametrize('case,expected,usage_status',[
    ('timeout','等待模型响应超时','timeout'),
    ('connection','模型连接失败或中断','unknown'),
    ('http','HTTP 429','http_error'),
    ('interrupted','模型流式连接提前中断','stream_interrupted'),
    ('provider','模型服务返回流式生成错误','stream_error'),
    ('schema','不符合所需 JSON 格式','invalid_output'),
    ('malformed','非 JSON 内容','invalid_response'),
])
def test_rewrite_failure_reports_safe_specific_reason_and_preserves_original(client,monkeypatch,protocol,case,expected,usage_status):
    import httpx
    from backend import ai_stream
    article=draft(client);original=article['document'];calls=[]
    connection={'name':'test','model':'test','api_key':'test-private','base_url':'https://example.com/v1','protocol':protocol,'output_mode':'json_object'}
    assert client.put('/api/model-config',json=connection).status_code==200
    def respond(request):
        calls.append(request)
        if case=='timeout':raise httpx.ReadTimeout('do-not-echo-private-token',request=request)
        if case=='connection':raise httpx.ConnectError('do-not-echo-private-token',request=request)
        if case=='http':return httpx.Response(429,text='do-not-echo-private-token')
        if case=='malformed':return httpx.Response(200,text='do-not-echo-private-token')
        if case=='schema':
            answer='{"wrong_field":"do-not-echo-private-token"}'
            result={'choices':[{'message':{'content':answer},'finish_reason':'stop'}]} if protocol=='chat_completions' else {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':answer}]}]}
            return httpx.Response(200,json=result)
        packet={'error':{'message':'do-not-echo-private-token'}} if case=='provider' else {'choices':[],'type':'response.created'}
        return httpx.Response(200,headers={'content-type':'text/event-stream'},text='data: '+json.dumps(packet)+'\n\n')
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        monkeypatch.setattr(ai_stream.httpx,'stream',transport.stream)
        result=advance(client,article,'rewrite',target='opening',instruction='开头写得具体一点')
    assert result['status']=='failed' and result['stage']=='section'
    assert expected in result['error'] and '已保存的大纲和正文保留' in result['error']
    assert 'do-not-echo-private-token' not in json.dumps(result) and 'test-private' not in json.dumps(result)
    assert result['document']==original and len(calls)==1
    with db.connect() as c:
        assert c.execute('SELECT status FROM ai_usage WHERE job_id=%s ORDER BY id DESC LIMIT 1',(article['id'],)).fetchone()[0]==usage_status


def test_article_event_endpoint_replays_current_preview_then_finishes(client,monkeypatch):
    from backend import article_stream
    from backend.ai_stream import stream_sink
    article=create(client)
    with article_stream.capture(article['id']):stream_sink.get()('article_angles','{"choices":[{"title":"正在写的标题"}]}',True)
    states=iter([{**article,'status':'running'},{**article,'status':'needs_angle'}])
    monkeypatch.setattr(worker,'get',lambda ident:next(states))
    response=client.get('/api/articles/'+article['id']+'/events')
    assert response.headers['content-type'].startswith('text/event-stream')
    assert 'event: snapshot' in response.text and '正在写的标题' in response.text and 'event: complete' in response.text
    assert client.get('/api/articles/missing/events').status_code==404


def test_edit_angle_preserves_body_requires_fresh_version_and_rebuilds_selected_outline(client):
    original=draft(client);path='/api/articles/'+original['id']
    angle={'title':'换一个具体问题','angle':'解释日常场景中容易忽略的细节','reason':'让读者理解新的观察方法'}
    saved=client.put(path+'/angles',json={'version':original['version'],'choice':0,'angle':angle})
    assert saved.status_code==200,saved.text
    value=saved.json()
    assert value['document']==original['document'] and value['outline']==original['outline']
    assert value['angles']['choices'][0]==angle and value['input_data']['_angle_outline_stale']
    assert client.put(path+'/angles',json={'version':original['version'],'choice':0,'angle':angle}).status_code==409
    rebuilt=advance(client,value,'angle',choice=0,replace_existing=True)
    assert not rebuilt['input_data'].get('_angle_outline_stale') and rebuilt['document'] is None
    restored=client.post(path+'/restore',json={'version':rebuilt['version'],'target_version':original['version']}).json()
    assert restored['angles']==original['angles'] and restored['document']==original['document']


@pytest.mark.parametrize('choice',[0,None])
def test_regenerate_angles_uses_instruction_preserves_text_and_handles_retry(client,monkeypatch,choice):
    original=draft(client);path='/api/articles/'+original['id'];seen=[]
    with db.connect() as c:
        choices=original['angles']['choices']*2
        worker.update(c,original['id'],angles=db.dump({'choices':choices}))
    def fail(*args):raise ValueError('simulated interruption')
    monkeypatch.setattr(article_ai,'angles',fail)
    queued=client.post(path+'/angles/regenerate',json={'version':original['version'],'choice':choice,'instruction':'从读者误解切入'}).json()
    worker.run(original['id']);failed=worker.get(original['id'])
    assert failed['status']=='failed' and failed['document']==original['document'] and failed['angles']['choices']==choices
    def generate(profile,brief,sources,ident):
        seen.append(brief)
        return Angles(choices=[{'title':'从一个常见误解开始','angle':'解释一个常见误解背后的原因','reason':'帮助读者理解实际问题'}])
    monkeypatch.setattr(article_ai,'angles',generate)
    value=advance(client,failed,'retry')
    assert '从读者误解切入' in seen[0]
    assert value['document']==original['document'] and value['outline']==original['outline']
    assert value['angles']['choices'][0]['title']=='从一个常见误解开始'
    assert len(value['angles']['choices'])==(2 if choice==0 else 1)
    assert value['input_data']['_angle_outline_stale']
    if choice==0:assert value['angles']['choices'][1]==choices[1]


def test_angle_only_history_can_be_restored_and_invalid_choice_is_rejected(client):
    original=create(client);worker.run(original['id']);original=worker.get(original['id']);path='/api/articles/'+original['id']
    body={'version':original['version'],'choice':4,'angle':original['angles']['choices'][0]}
    assert client.put(path+'/angles',json=body).status_code==400
    body.update(choice=0,angle={**body['angle'],'title':'手动修改后的角度'})
    saved=client.put(path+'/angles',json=body).json()
    assert client.get(path).json()['versions'][1]['restorable']
    restored=client.post(path+'/restore',json={'version':saved['version'],'target_version':original['version']})
    assert restored.status_code==200,restored.text
    assert restored.json()['status']=='needs_angle' and restored.json()['angles']==original['angles']
