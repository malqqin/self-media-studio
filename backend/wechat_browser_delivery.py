"""Browser draft adapter, verified against the public-account editor.

Only new drafts are edited. Persist write intent before opening the editor,
encrypt authenticated URLs, and never replay an unknown write.
"""
import base64
import re
from contextlib import contextmanager
from urllib.parse import urlsplit,parse_qs
from . import wechat_browser, wechat_accounts, wechat_delivery, article_export, model_config
from .article_templates import decoration_id
from .wechat_declarations import label as declaration_label

TITLE='.title-editor__input .ProseMirror'
BODY='.view.rich_media_content .ProseMirror'


@contextmanager
def stage(name):
    """Report a useful step, never Playwright's authenticated URL/call log."""
    try:yield
    except ValueError:raise
    except Exception:raise wechat_accounts.WeChatError(f'{name}未完成，草稿尚未通过完整核验。',uncertain=True) from None


def seal(url):return base64.b64encode(model_config.secret_transform(url.encode())).decode()


def unseal(value):
    url=model_config.secret_transform(base64.b64decode(value),decrypt=True).decode()
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='mp.weixin.qq.com':raise ValueError('草稿地址无效。')
    return url


def dismiss_tips(page):
    tips=page.get_by_role('button',name='我知道了',exact=True).filter(visible=True)
    if tips.count()==1:tips.click()


def paste(page,body):
    dismiss_tips(page)
    page.bring_to_front()
    # Clicking a growing article can select an image or its floating toolbar.
    # Focus the editable surface directly before keyboard selection instead.
    editor=page.locator(BODY);editor.wait_for(state='visible');editor.focus()
    editor.press('Control+A');editor.press('Backspace')
    if body:
        page.evaluate("""html=>navigator.clipboard.write([new ClipboardItem({
            'text/html':new Blob([html],{type:'text/html'}),
            'text/plain':new Blob([new DOMParser().parseFromString(html,'text/html').body.textContent],{type:'text/plain'})
        })])""",body)
        editor.press('Control+V')


def verify_body(page,doc):
    """Wait for the entire article, or identify WeChat's blocking paste dialog."""
    chunks=[doc['summary'],doc.get('opening','')]
    chunks += [text for section in doc['sections'] for text in [section['heading'],*section['paragraphs']]]
    chunks += [doc.get('closing','')]
    result=page.wait_for_function("""({selector,chunks})=>{
        const visible=e=>e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
        if([...document.querySelectorAll('button,a,span,div')].some(e=>e.textContent.trim()==='内容结构检测'&&visible(e)))return 'structure';
        const normalize=s=>s.replace(/\\s+/g,' ').trim();
        const text=normalize(document.querySelector(selector)?.textContent||'');
        return chunks.filter(Boolean).every(chunk=>text.includes(normalize(chunk)))?'complete':false;
    }""",arg={'selector':BODY,'chunks':chunks},timeout=20000).json_value()
    if result=='structure':
        raise wechat_accounts.WeChatError('微信的“内容结构检测”拦住了正文插入，请检查文章排版；正文尚未完整保存。',uncertain=True)
    from playwright.sync_api import expect
    expected=sum(bool(section.get('asset_id')) for section in doc['sections'])+bool(decoration_id(doc))
    expect(page.locator(BODY+' img[src^="http"]')).to_have_count(expected)


def set_cover(page,content,name):
    from playwright.sync_api import expect
    existing=page.locator('#js_cover_area .js_cover_preview_new')
    if existing.is_visible() and 'url(' in (existing.get_attribute('style') or ''):
        existing.hover();existing.locator('.js_chooseCover').hover()
    else:page.get_by_text('拖拽或选择封面',exact=True).click()
    page.locator('a.js_imagedialog:visible').click()
    page.locator('input[type=file][accept*="image/bmp"]').set_input_files({'name':name,'mimeType':'image/jpeg','buffer':content})
    button=page.get_by_role('button',name='下一步',exact=True).filter(visible=True)
    expect(button).not_to_have_class(re.compile('.*disabled.*'),timeout=40000)
    button.click()
    page.get_by_text('确认',exact=True).filter(visible=True).click()


def fill_draft(page,data):
    with stage('填写标题和作者'):
        page.locator(TITLE).wait_for()
        dismiss_tips(page)
        page.locator(TITLE).fill(data['document']['title']);page.locator('#author').fill(data['author'])
    with stage('写入公众号正文'):
        paths=fill_body(page,data)
    with stage('填写摘要'):
        page.locator('#js_description').fill(data['document']['summary'])
    with stage('上传公众号封面'):
        set_cover(page,wechat_delivery.image_bytes(data['cover_asset_id']),'zhixu-'+data['cover_asset_id']+'.jpg')
    with stage('设置创作来源'):
        set_declaration(page,data.get('content_declaration','ai'))
    return paths


def fill_body(page,data):
    from playwright.sync_api import expect
    doc=data['document']
    # Prepare files before changing the editor; a missing local asset should
    # never leave a newly cleared body behind.
    uploads=[(ident,wechat_delivery.inline_image(ident)) for ident in article_export.body_image_ids(doc,wechat=True) if ident]
    paths={}
    for index,(ident,(name,content,mime)) in enumerate(uploads,1):
        # Each upload uses an empty editor, so image selection/replacement and
        # offscreen toolbars cannot invalidate an accumulating image count.
        with stage(f'准备第 {index}/{len(uploads)} 张正文配图的插入位置'):
            paste(page,'')
            expect(page.locator(BODY+' img[src]')).to_have_count(0)
        with stage(f'上传第 {index}/{len(uploads)} 张正文配图（等待微信确认图片插入）'):
            images=page.locator(BODY+' img[src^="http"]')
            page.locator('input[type=file][accept*="image/svg"]').set_input_files({'name':name,'mimeType':mime,'buffer':content})
            expect(images).to_have_count(1,timeout=40000)
            img=images.first
            expect(img).to_have_attribute('src',re.compile(r'https?://'),timeout=40000)
            paths[ident]=img.get_attribute('src')
    with stage('粘贴排版后的完整正文'):
        paste(page,article_export.html_body(doc,paths,wechat=True))
    with stage('核对正文文字和配图完整性'):
        verify_body(page,doc)
    return paths


def verify_declaration(page,value='ai'):
    from playwright.sync_api import expect
    label=declaration_label(value)
    selected=page.locator('.js_claim_source_selected')
    if value=='none':
        # The editor may show its empty selector again after clearing a claim.
        if selected.is_visible() and selected.inner_text().strip():expect(selected).to_have_text(label)
        else:expect(page.locator('.js_claim_source_desc')).to_be_visible()
    else:expect(selected).to_have_text(label)


def set_declaration(page,value='ai'):
    label=declaration_label(value)
    selected=page.locator('.js_claim_source_selected')
    if selected.is_visible() and selected.inner_text().strip()==label:return
    page.locator('.js_claim_source_desc').click()
    page.get_by_text(label,exact=True).filter(visible=True).last.click()
    page.get_by_role('button',name='确认',exact=True).filter(visible=True).click()
    verify_declaration(page,value)


def save_draft(page,data,checkpoint=None):
    # Never click Save on a partially inserted article.
    with stage('保存前核对正文'):verify_body(page,data['document'])
    with stage('保存并重新打开公众号草稿'):
        return _save_draft(page,data,checkpoint)


def _save_draft(page,data,checkpoint):
    from playwright.sync_api import expect
    def saved_response(response):
        parsed=urlsplit(response.url)
        return response.request.method=='POST' and parsed.path=='/cgi-bin/operate_appmsg' and parse_qs(parsed.query).get('sub',[''])[0] in ('create','update')
    # "已保存" may refer to an earlier autosave. Wait for this write's response
    # before reloading, so a stale label cannot race the current save request.
    with page.expect_response(saved_response,timeout=45000) as pending:
        page.get_by_role('button',name='保存为草稿',exact=True).click()
    response=pending.value
    if not response.ok or response.json().get('base_resp',{}).get('ret')!=0:
        raise wechat_accounts.WeChatError('微信未确认本次草稿保存成功，请到草稿箱核对。',uncertain=True)
    page.get_by_text('已保存',exact=True).filter(visible=True).wait_for(timeout=45000)
    page.wait_for_function("()=>/^\\d+$/.test(new URL(location.href).searchParams.get('appmsgid')||'')",timeout=20000)
    ids=parse_qs(urlsplit(page.url).query).get('appmsgid',[])
    if not ids or not ids[0].isdigit():raise wechat_accounts.WeChatError('未能确认草稿编号，请到公众号草稿箱核对。',uncertain=True)
    url=page.url
    if checkpoint:checkpoint(url)
    # Verify the persisted result, not merely the editor's in-memory contents.
    page.reload(wait_until='domcontentloaded')
    expect(page.locator(TITLE)).to_have_text(data['document']['title'],timeout=20000)
    verify_body(page,data['document'])
    expect(page.locator('#author')).to_have_value(data['author'])
    expect(page.locator('#js_description')).to_have_value(data['document']['summary'])
    expect(page.locator('#js_cover_area .js_cover_preview_new')).to_have_attribute('style',re.compile(r'.*url\(.*'),timeout=20000)
    verify_declaration(page,data.get('content_declaration','ai'))
    data['declaration_applied']=True
    return ids[0],url


def deliver(value):
    from playwright.sync_api import sync_playwright
    run_id=value['run_id'];data=value['data'];account_id=value['account_id']
    if data.get('media_id'):
        wechat_delivery.update(run_id,'draft',data);return
    if value['mode']!='draft':raise ValueError('扫码接入当前仅支持自动保存草稿。')
    saved=wechat_browser._load(account_id)
    if not saved:raise ValueError('公众号登录已失效，请重新扫码后重试。')
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=wechat_browser.executable())
        try:
            context=browser.new_context(storage_state=saved['storage'],viewport={'width':1280,'height':850},locale='zh-CN',permissions=['clipboard-read','clipboard-write'])
            home=context.new_page();home.set_default_timeout(20000)
            home.goto(saved['url'],wait_until='domcontentloaded')
            if not wechat_browser.logged_in(home):raise ValueError('公众号登录已失效，请在连接管理中重新扫码后重试。')
            identity=wechat_browser.identity(home)
            if identity['appid']!=data['appid']:raise ValueError('当前登录账号与任务绑定公众号不一致，已停止交付。')
            wechat_browser._save(account_id,context,home.url,identity)
            # Editor may autosave even before clicking Save: intent starts before opening it.
            wechat_delivery.update(run_id,'drafting',data)
            with context.expect_page() as opened:home.get_by_text('文章',exact=True).click()
            page=opened.value;page.set_default_timeout(20000);page.wait_for_load_state('domcontentloaded')
            data['browser_editor']=seal(page.url);wechat_delivery.update(run_id,'drafting',data)
            def checkpoint(url):
                # Store a recovery address separately: an ID alone is not proof
                # that the article body survived saving and reloading.
                data['browser_editor']=seal(url)
                data['browser_draft_id']=parse_qs(urlsplit(url).query).get('appmsgid',[''])[0]
                wechat_delivery.update(run_id,'drafting',data)
            try:
                fill_draft(page,data)
                media_id,url=save_draft(page,data,checkpoint)
            except Exception:
                checkpoint(page.url)
                raise
            data.update(media_id=media_id,browser_editor=seal(url))
            wechat_browser._save(account_id,context,home.url,identity)
            wechat_delivery.update(run_id,'draft',data)
        finally:browser.close()


def recovery_url(data):
    url=unseal(data['browser_editor'])
    ident=str(data.get('browser_draft_id',''))
    if not ident.isdigit() or parse_qs(urlsplit(url).query).get('appmsgid')!=[ident]:
        raise ValueError('原草稿地址与编号不一致，已停止恢复，请到公众号后台核对。')
    return url


def resume(value):
    """Explicitly update the identified draft, never open a new article."""
    from playwright.sync_api import sync_playwright,expect
    run_id=value['run_id'];data=value['data'];account_id=value['account_id']
    if value['mode']!='draft' or data.get('publish_id'):raise ValueError('只支持继续保存尚未发布的原草稿。')
    url=recovery_url(data)
    saved=wechat_browser._load(account_id)
    if not saved:raise ValueError('公众号登录已失效，请重新扫码后继续原草稿。')
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=wechat_browser.executable())
        try:
            context=browser.new_context(storage_state=saved['storage'],viewport={'width':1280,'height':850},locale='zh-CN',permissions=['clipboard-read','clipboard-write'])
            home=context.new_page();home.set_default_timeout(20000)
            home.goto(saved['url'],wait_until='domcontentloaded')
            if not wechat_browser.logged_in(home):raise ValueError('公众号登录已失效，请重新扫码后继续原草稿。')
            identity=wechat_browser.identity(home)
            if identity['appid']!=data['appid']:raise ValueError('当前公众号与原草稿所属账号不一致，已停止恢复。')
            page=context.new_page();page.set_default_timeout(20000)
            with stage('定位原公众号草稿'):
                page.goto(url,wait_until='domcontentloaded')
                expect(page.locator(TITLE)).to_be_visible()
                if parse_qs(urlsplit(page.url).query).get('appmsgid')!=[data['browser_draft_id']]:
                    raise ValueError('微信未打开原草稿，已停止恢复。')
                if page.locator(TITLE).inner_text().strip() not in (data.get('_resume_title'),data['title']):
                    raise ValueError('公众号草稿标题已被修改，请先到公众号后台核对，未覆盖原稿。')
                if page.get_by_text('已发表',exact=True).filter(visible=True).count():
                    raise ValueError('原稿已发表，不能作为草稿恢复，请到公众号后台处理。')
                expect(page.get_by_role('button',name='保存为草稿',exact=True)).to_be_visible()
            wechat_delivery.update(run_id,'drafting',data)
            def checkpoint(saved_url):
                data['browser_editor']=seal(saved_url)
                wechat_delivery.update(run_id,'drafting',data)
            fill_draft(page,data)
            media_id,saved_url=save_draft(page,data,checkpoint)
            if media_id!=data['browser_draft_id']:raise ValueError('草稿编号发生变化，请到公众号后台核对。')
            data.update(media_id=media_id,browser_editor=seal(saved_url))
            data.pop('_resume_browser',None);data.pop('_resume_title',None)
            wechat_browser._save(account_id,context,home.url,identity)
            wechat_delivery.update(run_id,'draft',data)
        finally:browser.close()
