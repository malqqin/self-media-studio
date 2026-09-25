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
    editor=page.locator(BODY);editor.click();editor.press('Control+A');editor.press('Backspace')
    if body:
        page.evaluate("""html=>navigator.clipboard.write([new ClipboardItem({
            'text/html':new Blob([html],{type:'text/html'}),
            'text/plain':new Blob([new DOMParser().parseFromString(html,'text/html').body.textContent],{type:'text/plain'})
        })])""",body)
        editor.press('Control+V')


def verify_body(page,doc):
    """Wait for the entire article, or identify WeChat's blocking paste dialog."""
    chunks=[doc['title'],doc['summary'],doc.get('opening','')]
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
    expected=sum(bool(section.get('asset_id')) for section in doc['sections'])+bool(doc.get('cover_asset_id'))+bool(decoration_id(doc))
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
    with stage('设置 AI 创作声明'):
        declare_ai(page)
    return paths


def fill_body(page,data):
    from playwright.sync_api import expect
    doc=data['document']
    paste(page,'')
    expect(page.locator(BODY+' img[src]')).to_have_count(0)
    paths={}
    for ident in article_export.body_image_ids(doc):
        if not ident:continue
        dismiss_tips(page)
        name,content,mime=wechat_delivery.inline_image(ident)
        images=page.locator(BODY+' img[src^="http"]');before=images.count()
        page.locator(BODY).click();page.keyboard.press('Control+End')
        page.locator('input[type=file][accept*="image/svg"]').set_input_files({'name':name,'mimeType':mime,'buffer':content})
        expect(images).to_have_count(before+1,timeout=40000)
        img=images.nth(before)
        expect(img).to_have_attribute('src',re.compile(r'https?://'),timeout=40000)
        paths[ident]=img.get_attribute('src')
    paste(page,article_export.html_body(doc,paths,wechat=True))
    verify_body(page,doc)
    return paths


def declare_ai(page):
    selected=page.locator('.js_claim_source_selected')
    if selected.is_visible() and selected.inner_text().strip()=='内容由AI生成':return
    page.locator('.js_claim_source_desc').click()
    page.get_by_text('内容由AI生成',exact=True).click()
    page.get_by_role('button',name='确认',exact=True).filter(visible=True).click()
    from playwright.sync_api import expect
    expect(page.locator('.js_claim_source_selected')).to_have_text('内容由AI生成')


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
    expect(page.locator('.js_claim_source_selected')).to_have_text('内容由AI生成')
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
