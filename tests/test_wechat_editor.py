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
    page.route('http://localhost/editor*',lambda route:route.fulfill(content_type='text/html; charset=utf-8',body='''
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


def test_old_saved_label_does_not_mask_a_rejected_save(editor,document):
    adapter.paste(editor,article_export.html_body(document,wechat=True))
    editor.route('**/cgi-bin/operate_appmsg?sub=update',lambda route:route.fulfill(json={'base_resp':{'ret':-1}}))
    with pytest.raises(ValueError,match='微信未确认本次草稿保存成功'):
        adapter.save_draft(editor,{'document':document,'author':''})
    assert editor.evaluate('window.saveClicks')==1
