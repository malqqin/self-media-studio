"""Real browser checks for body insertion and false-success prevention (no WeChat writes)."""
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from backend import article_export, wechat_browser, wechat_browser_delivery as adapter


@pytest.fixture(scope='module')
def browser():
    executable=wechat_browser.executable()
    if not executable or not Path(executable).is_file():pytest.skip('Chromium executable is unavailable')
    with sync_playwright() as p:
        instance=p.chromium.launch(headless=True,executable_path=executable)
        yield instance
        instance.close()


@pytest.fixture
def editor(browser,monkeypatch):
    context=browser.new_context(permissions=['clipboard-read','clipboard-write'])
    page=context.new_page()
    # Like WeChat's editor, keep an empty body visible and editable after an
    # uploaded image is cleared; a zero-height mock loses Chromium's caret.
    page.route('http://localhost/editor*',lambda route:route.fulfill(content_type='text/html; charset=utf-8',body='''
        <style>.view .ProseMirror{min-height:100px}</style>
        <div class="title-editor__input"><div class="ProseMirror" contenteditable="true"></div></div>
        <input id="author"><textarea id="js_description"></textarea>
        <div class="view rich_media_content"><div class="ProseMirror" contenteditable="true"><p>旧正文</p></div></div>
        <div id="js_cover_area"><div class="js_cover_preview_new" style="background-image:url(cover.jpg)"></div></div>
        <div class="js_claim_source_selected">内容由AI生成</div>
        <span>已保存</span><button onclick="window.saveClicks=(window.saveClicks||0)+1;fetch('/cgi-bin/operate_appmsg?sub=update',{method:'POST'})">保存为草稿</button>
    '''))
    page.route('**/cgi-bin/operate_appmsg?sub=update',lambda route:route.fulfill(json={'base_resp':{'ret':0}}))
    page.goto('http://localhost/editor?appmsgid=123')
    wait=page.wait_for_function
    monkeypatch.setattr(page,'wait_for_function',lambda *args,**kwargs:wait(*args,**{**kwargs,'timeout':500}))
    yield page
    context.close()


@pytest.fixture
def document():
    return {'template_id':'travel','title':'古城散步','summary':'一次慢慢行走的旅程','opening':'先从一条街巷开始。',
            'sections':[{'heading':'抬头看屋檐','paragraphs':['屋檐的弧线值得停下看看。','最后一段也必须写入。'],'asset_id':''}],
            'closing':'留一点时间给下一次散步。','cover_asset_id':''}


def test_native_paste_replaces_old_body_keeps_rich_style_and_all_paragraphs(editor,document):
    adapter.paste(editor,article_export.html_body(document,wechat=True))
    adapter.verify_body(editor,document)
    expect(editor.locator(adapter.BODY)).not_to_contain_text('旧正文')
    expect(editor.locator(adapter.BODY+' h2')).to_contain_text('01 · 抬头看屋檐')
    assert 'color' in editor.locator(adapter.BODY+' h2').get_attribute('style')


def test_draft_fills_title_and_cover_separately_from_text_first_body(editor,document,monkeypatch):
    document['cover_asset_id']='cover'
    covers=[]
    monkeypatch.setattr(adapter.wechat_delivery,'image_bytes',lambda ident:b'cover-image')
    monkeypatch.setattr(adapter.wechat_delivery,'inline_image',lambda ident:pytest.fail('Cover must not be uploaded as a body image'))
    monkeypatch.setattr(adapter,'set_cover',lambda page,content,name:covers.append((content,name)))
    paths=adapter.fill_draft(editor,{'document':document,'author':'作者','cover_asset_id':'cover'})
    assert paths=={} and covers==[(b'cover-image','zhixu-cover.jpg')]
    expect(editor.locator(adapter.TITLE)).to_have_text(document['title'])
    expect(editor.locator(adapter.BODY)).not_to_contain_text(document['title'])
    expect(editor.locator(adapter.BODY+' img')).to_have_count(0)
    expect(editor.locator(adapter.BODY+' p').first).to_have_text(document['summary'])
    adapter.verify_body(editor,document)


def test_multiple_body_images_survive_editor_uploads_that_replace_selected_images(editor,document,monkeypatch):
    document['cover_asset_id']='cover'
    document['sections']=[{**document['sections'][0],'heading':f'第 {i} 节','asset_id':f'image-{i}'} for i in range(1,5)]
    monkeypatch.setattr(adapter.wechat_delivery,'inline_image',lambda ident:(ident+'.jpg',b'test-image','image/jpeg'))
    editor.route('https://mmbiz.qpic.cn/*',lambda route:route.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"/>'))
    # WeChat can replace a selected image instead of appending another one.
    # Also include its non-content separator images in the realistic DOM.
    editor.evaluate("""selector=>{
        const input=document.createElement('input');input.type='file';input.accept='image/jpeg,image/svg';
        input.onchange=()=>{
            const body=document.querySelector(selector),image=document.createElement('img');
            image.src='https://mmbiz.qpic.cn/'+input.files[0].name;
            const previous=body.querySelector('img[src]');
            if(previous)previous.replaceWith(image);
            else {body.append(image);const separator=document.createElement('img');separator.className='ProseMirror-separator';body.append(separator);}
        };
        document.body.append(input);
    }""",adapter.BODY)
    paths=adapter.fill_body(editor,{'document':document})
    assert len(paths)==4
    assert 'cover' not in paths
    adapter.verify_body(editor,document)
    expect(editor.locator(adapter.BODY+' img[src]')).to_have_count(4)
    for ident,url in paths.items():
        assert url==f'https://mmbiz.qpic.cn/{ident}.jpg'
        expect(editor.locator(adapter.BODY+f' img[src="{url}"]')).to_have_count(1)


def test_body_paste_does_not_click_embedded_image_controls(editor,document):
    editor.locator(adapter.BODY).evaluate("""e=>{
        e.style.height='600px';
        e.innerHTML='<button contenteditable="false" style="width:100%;height:600px" onclick="window.imageControlClicks=(window.imageControlClicks||0)+1">图片操作</button>';
    }""")
    adapter.paste(editor,article_export.html_body(document,wechat=True))
    adapter.verify_body(editor,document)
    assert editor.evaluate('window.imageControlClicks||0')==0


@pytest.mark.parametrize('template',['cream','sage','journal','editorial','newspaper','ink','rose','ocean','coffee','butter','postcard','midnight'])
def test_new_template_paste_verifies_decorations_and_text(editor,document,template):
    from backend.article_templates import decoration_id
    document['template_id']=template
    ornament=decoration_id(document)
    paths={ornament:'https://mmbiz.qpic.cn/decoration.jpg'} if ornament else {}
    editor.route('https://mmbiz.qpic.cn/*',lambda route:route.fulfill(status=200,content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40"/>'))
    adapter.paste(editor,article_export.html_body(document,paths,wechat=True))
    adapter.verify_body(editor,document)
    expect(editor.locator(adapter.BODY+' h1')).to_have_count(0)
    expect(editor.locator(adapter.BODY)).not_to_contain_text(document['title'])
    expect(editor.locator(adapter.BODY+' p').first).to_have_text(document['summary'])


def test_structural_dialog_is_explained_and_save_is_never_clicked(editor,document):
    editor.evaluate("document.body.insertAdjacentHTML('beforeend','<div>内容结构检测</div>')")
    with pytest.raises(ValueError,match='内容结构检测'):
        adapter.save_draft(editor,{'document':document})
    assert editor.evaluate('window.saveClicks||0')==0


def test_last_paragraph_missing_refuses_save_even_when_first_paragraph_exists(editor,document):
    partial={**document,'sections':[{**document['sections'][0],'paragraphs':document['sections'][0]['paragraphs'][:1]}]}
    adapter.paste(editor,article_export.html_body(partial,wechat=True))
    with pytest.raises(ValueError,match='保存前核对正文'):
        adapter.save_draft(editor,{'document':document})
    assert editor.evaluate('window.saveClicks||0')==0


def test_saved_label_is_insufficient_when_reload_loses_body(editor,document):
    adapter.paste(editor,article_export.html_body(document,wechat=True))
    editor.locator(adapter.TITLE).fill(document['title'])
    # Simulate a title-only persisted draft despite the editor displaying "已保存".
    editor.route('http://localhost/editor*',lambda route:route.fulfill(content_type='text/html; charset=utf-8',body=f'''
      <div class="title-editor__input"><div class="ProseMirror">{document['title']}</div></div>
      <div class="view rich_media_content"><div class="ProseMirror"></div></div>
    '''))
    checkpoints=[]
    with pytest.raises(ValueError,match='保存并重新打开公众号草稿'):
        adapter.save_draft(editor,{'document':document,'author':''},checkpoints.append)
    assert len(checkpoints)==1, 'Recovery address must survive a failed post-save verification'


def test_diagnostics_never_expose_authenticated_urls():
    with pytest.raises(ValueError) as error:
        with adapter.stage('上传公众号封面'):
            raise RuntimeError('https://mp.weixin.qq.com/?token=secret-cookie')
    assert '上传公众号封面' in str(error.value)
    assert 'secret-cookie' not in str(error.value)


@pytest.mark.parametrize('value',['ai','news','fiction','opinion','health','finance','none'])
def test_user_selected_declaration_is_applied_and_wrong_saved_value_is_rejected(editor,value):
    from backend.wechat_declarations import LABELS
    editor.evaluate("""labels=>{
      const selected=document.querySelector('.js_claim_source_selected');selected.textContent='旧声明';
      const trigger=document.createElement('button');trigger.className='js_claim_source_desc';trigger.textContent='创作来源';
      trigger.onclick=()=>{
        const dialog=document.createElement('div');dialog.id='claims';
        for(const text of labels){const option=document.createElement('button');option.textContent=text;option.onclick=()=>window.chosenClaim=text;dialog.append(option);}
        const confirm=document.createElement('button');confirm.textContent='确认';
        confirm.onclick=()=>{selected.textContent=window.chosenClaim==='无需声明'?'':window.chosenClaim;dialog.remove();};
        dialog.append(confirm);document.body.append(dialog);
      };document.body.append(trigger);
    }""",list(LABELS.values()))
    adapter.set_declaration(editor,value)
    adapter.verify_declaration(editor,value)
    assert editor.evaluate('window.chosenClaim')==LABELS[value]
    editor.locator('.js_claim_source_selected').evaluate("e=>e.textContent='错误的声明'")
    with pytest.raises(AssertionError):
        # Use the browser's fast assertion timeout for the expected failure.
        expect.set_options(timeout=300)
        try:adapter.verify_declaration(editor,value)
        finally:expect.set_options(timeout=5000)


def test_old_saved_label_does_not_mask_a_rejected_save(editor,document):
    adapter.paste(editor,article_export.html_body(document,wechat=True))
    editor.route('**/cgi-bin/operate_appmsg?sub=update',lambda route:route.fulfill(json={'base_resp':{'ret':-1}}))
    with pytest.raises(ValueError,match='微信未确认本次草稿保存成功'):
        adapter.save_draft(editor,{'document':document,'author':''})
    assert editor.evaluate('window.saveClicks')==1


@pytest.mark.parametrize('actual_title',['古城散步','公众号后台已修改的标题'])
def test_resume_only_edits_the_identified_existing_draft(editor,document,monkeypatch,actual_title):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import playwright.sync_api
    editor.locator(adapter.TITLE).fill(actual_title)
    visited=[];writes=[];states=[]
    monkeypatch.setattr(editor,'goto',lambda url,**kwargs:visited.append(url))
    home=SimpleNamespace(set_default_timeout=lambda value:None,goto=lambda *a,**k:None,url='https://mp.weixin.qq.com/cgi-bin/home')
    pages=iter([home,editor])
    context=SimpleNamespace(new_page=lambda:next(pages))
    browser=SimpleNamespace(new_context=lambda **kwargs:context,close=lambda:None)
    @contextmanager
    def mocked_playwright():yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs:browser))
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',mocked_playwright)
    monkeypatch.setattr(adapter.wechat_browser,'_load',lambda ident:{'storage':{},'url':home.url})
    monkeypatch.setattr(adapter.wechat_browser,'logged_in',lambda page:True)
    monkeypatch.setattr(adapter.wechat_browser,'identity',lambda page:{'appid':'wx-test','name':'测试号'})
    monkeypatch.setattr(adapter.wechat_browser,'_save',lambda *a:None)
    monkeypatch.setattr(adapter,'fill_draft',lambda *a:writes.append('fill'))
    monkeypatch.setattr(adapter,'save_draft',lambda *a:('123',visited[0]))
    monkeypatch.setattr(adapter.wechat_delivery,'update',lambda ident,status,data:states.append(status))
    url='https://mp.weixin.qq.com/cgi-bin/appmsg?appmsgid=123'
    value={'run_id':'run','account_id':'account','mode':'draft','data':{'document':document,'title':document['title'],'_resume_title':document['title'],
        'appid':'wx-test','browser_editor':adapter.seal(url),'browser_draft_id':'123','_resume_browser':True}}
    if actual_title==document['title']:
        adapter.resume(value)
        assert writes==['fill'] and states==['drafting','draft']
        assert value['data']['media_id']=='123' and '_resume_browser' not in value['data']
    else:
        with pytest.raises(ValueError,match='标题已被修改'):adapter.resume(value)
        assert writes==[] and states==[]
    assert visited==[url]


def test_recovery_url_rejects_mismatched_draft_id():
    with pytest.raises(ValueError,match='编号不一致'):
        adapter.recovery_url({'browser_draft_id':'123','browser_editor':adapter.seal('https://mp.weixin.qq.com/cgi-bin/appmsg?appmsgid=999')})
