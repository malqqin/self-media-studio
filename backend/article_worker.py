"""Persisted article stages, independent of the video renderer."""
from .tenancy import ContextExecutor as ThreadPoolExecutor
import logging
import uuid
import json
import re
from fastapi import HTTPException
from . import db, config, article_ai, article_stream, article_pictures
from .ai import ModelOutputLimitError, ModelRequestError
from .article_models import ArticleInput, ArticleProfile, Angle, ArticleOutline, ArticleDocument

executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='studio-articles')
BUSY = ('queued', 'running')


def get(article_id):
    with db.connect() as c:
        return db.article(c.execute('SELECT * FROM articles WHERE id=%s', (article_id,)).fetchone())


def require(c, article_id, version=None):
    if version is not None:db.lock(c,'article',article_id)
    value = db.article(c.execute('SELECT * FROM articles WHERE id=%s', (article_id,)).fetchone())
    if not value:
        raise HTTPException(404, '文章不存在。')
    if version is not None and value['version'] != version:
        raise HTTPException(409, '文章版本已更新，请刷新后再操作。')
    if version is not None and value['status'] in BUSY:
        raise HTTPException(409, '文章正在生成或检查，请等待完成。')
    if version is not None and c.execute("SELECT 1 FROM wechat_deliveries WHERE article_id=%s AND status IN ('queued','preparing','drafting','submitting','publishing')",(article_id,)).fetchone():
        raise HTTPException(409, '文章正在发送到公众号，请等待交付完成后再编辑。')
    return value


def update(c, article_id, **values):
    values['updated_at'] = db.now()
    c.execute('UPDATE articles SET '+','.join(f'{key}=%s' for key in values)+' WHERE id=%s', (*values.values(), article_id))


def snapshot(c, article_id, note):
    value = require(c, article_id)
    payload = {key: value[key] for key in ('angles', 'outline', 'document', 'checks', 'input_data','source_data','mode')}
    payload['note'] = note
    c.execute('INSERT INTO article_versions(article_id,version,stage,payload,at) VALUES (%s,%s,%s,%s,%s)',
              (article_id, value['version'], value['stage'], db.dump(payload), db.now()))


def create(body: ArticleInput, *, submit=True, profile_override=None, model_id=None, illustration=None):
    with db.connect() as c:
        db.lock(c,'article-create',body.request_id)
        existing = c.execute('SELECT * FROM articles WHERE request_id=%s', (body.request_id,)).fetchone()
        if existing:
            previous = db.article(existing)
            original = {key: previous['input_data'].get(key) for key in body.model_dump()}
            if original != body.model_dump():
                raise HTTPException(409, '此请求编号已用于另一篇文章。')
            return previous
        from . import model_library
        if not (model_library.ready(model_id) if model_id else config.ai_ready()):
            raise ValueError('请先在“我的模型”配置连接，并在任务中选择。')
        profile = profile_override or db.article_profile(c)
        if body.mode == 'original' and not (body.brief or profile.direction or len(body.notes) >= 20):
            raise ValueError('请填写公众号方向、写作主题或至少 20 字的笔记。')
        source_data = []
        for topic_id in body.topic_ids:
            topic = db.topic(c.execute('SELECT * FROM topics WHERE id=%s', (topic_id,)).fetchone())
            if not topic:
                raise ValueError('所选资料已不存在，请重新选择。')
            for source in topic.get('sources', []):
                if not any(s['id'] == source['id'] for s in source_data):
                    source_data.append({**source, 'full_text': topic.get('page_data', {}).get('full_text', False),
                                        'captured_at': topic.get('page_data', {}).get('captured_at'),
                                        'method': topic.get('page_data', {}).get('method', 'rss')})
        if body.notes:
            source_data.append({'id': 'personal-notes', 'title': '用户提供的笔记', 'publisher': '手动提供 · 待核验',
                                'text': body.notes, 'url': '', 'full_text': True, 'method': 'notes', 'captured_at': db.now()})
        article_id = 'article-'+uuid.uuid4().hex[:18]
        now = db.now()
        input_data=body.model_dump()
        if model_id:input_data['_model_id']=model_id
        if illustration is not None:input_data['_illustration']=illustration.model_dump()
        c.execute('INSERT INTO articles(id,request_id,status,stage,progress,mode,version,profile,input_data,source_data,created_at,updated_at,note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                  (article_id, body.request_id, 'queued', 'angles', 5, body.mode, 1, db.dump(profile.model_dump()),
                   db.dump(input_data), db.dump(source_data), now, now, '正在准备写作角度。'))
        snapshot(c, article_id, '创建文章，保存定位与来源快照')
    if submit:
        executor.submit(run, article_id)
    return get(article_id)


def enqueue(article_id, version, action, *, choice=None, section=None, instruction=None, submit=True, replace_existing=False,
            target='section',paragraph=None,document_value=None):
    with db.connect() as c:
        db.lock(c,'article',article_id)
        value = require(c, article_id, version)
        from . import model_library
        if not model_library.ready(value['input_data'].get('_model_id','default')):
            raise ValueError('请先在“我的模型”配置连接，并在任务中选择。')
        inp = value['input_data']
        reset={}
        if action in ('outline','article') and value['document']:
            inp['_picture_previous']=value['document']
        if action == 'outline':
            choices = (value['angles'] or {}).get('choices', [])
            if choice is None or not 0 <= choice < len(choices):
                raise ValueError('请选择一个已有的写作角度。')
            if value['outline'] or value['document']:
                if not replace_existing:raise ValueError('重新选择角度会重新生成大纲与正文，请先确认；原有内容保留在版本记录中。')
                reset=dict(outline=None,document=None,checks=None,version=version+1,progress=25)
            inp['angle_index'] = choice
            inp.pop('_angle_outline_stale',None)
        elif action == 'article':
            if not value['outline']:raise ValueError('请先完成大纲。')
            if value['document']:
                if not replace_existing:raise ValueError('重新生成正文需要先确认；原有正文保留在版本记录中。')
                reset=dict(document=None,checks=None,version=version+1,progress=45)
        elif action == 'illustrate':
            if not value['document']:raise ValueError('还没有可配图的正文。')
            if not inp.get('_illustration',{}).get('enabled'):raise ValueError('本次创作没有开启任务配图配置。')
            inp.pop('_picture_plan',None);inp.pop('_picture_cycle',None)
        elif action == 'check':
            if not value['document']:
                raise ValueError('还没有可检查的正文。')
        elif action == 'section':
            if not value['document']:raise ValueError('正文尚未生成。')
            base=document_value.model_dump() if document_value is not None else value['document']
            if target in ('section','heading','paragraphs','paragraph'):
                if section is None or not 0 <= section < len(base['sections']):raise ValueError('章节不存在。')
                if target=='paragraph' and (paragraph is None or not 0 <= paragraph < len(base['sections'][section]['paragraphs'])):
                    raise ValueError('段落不存在。')
            if document_value is not None:
                validate_assets(c,document_value)
                inp['_template_id']=document_value.template_id
                update(c,article_id,document=db.dump(base),version=version+1,checks=None,input_data=db.dump(inp))
                snapshot(c,article_id,'局部调整前保存手动修改')
            inp['_rewrite'] = {'target':target,'section':section,'paragraph':paragraph,'instruction':instruction}
        elif action == 'retry':
            if value['status'] != 'failed':
                raise ValueError('当前文章无需重试。')
            action = value['stage']
        else:
            raise ValueError('未知写作步骤。')
        update(c, article_id, status='queued', stage=action, error=None, note='已加入文章队列。', input_data=db.dump(inp),**reset)
        if reset:snapshot(c,article_id,'重新选择角度' if action=='outline' else '按大纲重新生成正文')
        article_stream.reset(article_id)
    if submit:
        executor.submit(run, article_id)
    return get(article_id)


def validate_assets(c, doc):
    for ident in [doc.cover_asset_id]+[s.asset_id for s in doc.sections]:
        if ident:
            asset = c.execute('SELECT media_type FROM assets WHERE id=%s', (ident,)).fetchone()
            if not asset or not asset['media_type'].startswith('image/'):
                raise ValueError('文章配图必须选择已有图片素材。')


def edit(article_id, version, *, outline_value=None, document_value=None, replace_existing=False):
    with db.connect() as c:
        db.lock(c,'article',article_id)
        value = require(c, article_id, version)
        fields = {'version': version+1, 'checks': None, 'error': None}
        if outline_value is not None:
            if not value['outline']:raise ValueError('还没有可修改的大纲。')
            if value['document'] and not replace_existing:raise ValueError('修改大纲需要重新生成正文，请先确认；原有正文保留在版本记录中。')
            if value['document']:fields['input_data']=db.dump({**value['input_data'],'_picture_previous':value['document']})
            fields['document']=None
            fields.update(outline=db.dump(outline_value.model_dump()), status='needs_outline', stage='outline', progress=45, note='大纲已保存，可生成正文。')
        if document_value is not None:
            if not value['document']:
                raise ValueError('正文尚未生成。')
            validate_assets(c, document_value)
            fields['input_data']=db.dump({**value['input_data'],'_template_id':document_value.template_id})
            fields.update(document=db.dump(document_value.model_dump()), status='draft', stage='review', progress=100, note='修改已保存，需重新检查。')
        update(c, article_id, **fields)
        snapshot(c, article_id, '手动保存')
    return get(article_id)


def restore(article_id, version, target_version):
    with db.connect() as c:
        db.lock(c,'article',article_id)
        require(c, article_id, version)
        row = c.execute('SELECT payload FROM article_versions WHERE article_id=%s AND version=%s', (article_id, target_version)).fetchone()
        if not row:
            raise ValueError('历史版本不存在。')
        old = json.loads(row['payload'])
        if not any(old.get(k) for k in ('angles','outline','document')):
            raise ValueError('此版本还没有可恢复的内容。')
        update(c, article_id, version=version+1, document=db.dump(old['document']) if old['document'] else None,
               outline=db.dump(old['outline']), angles=db.dump(old['angles']), input_data=db.dump(old['input_data']),
               **({'source_data':db.dump(old['source_data']),'mode':old['mode']} if 'source_data' in old else {}),
               checks=None, error=None, status='draft' if old['document'] else 'needs_outline' if old['outline'] else 'needs_angle',
               stage='review' if old['document'] else 'outline' if old['outline'] else 'angles', progress=100 if old['document'] else 45 if old['outline'] else 25,
               note=f'已从 v{target_version} 恢复，原有历史保留。')
        snapshot(c, article_id, f'从 v{target_version} 恢复')
    return get(article_id)


def finish(article_id, **fields):
    with db.connect() as c:
        db.lock(c,'article',article_id)
        value = require(c, article_id)
        update(c, article_id, version=value['version']+1, **fields)
        snapshot(c, article_id, fields.get('note', '生成完成'))


def run(article_id):
    from .model_library import use
    value=get(article_id)
    if not value:return
    with use(value['input_data'].get('_model_id','default')),article_stream.capture(article_id):
        _run(article_id)


def _run(article_id):
    with db.connect() as c:
        claimed = c.execute("UPDATE articles SET status='running',error=NULL,updated_at=%s WHERE id=%s AND status='queued'", (db.now(), article_id)).rowcount
    if not claimed:
        return
    value = get(article_id)
    try:
        profile = ArticleProfile.model_validate(value['profile'])
        inp = value['input_data']
        brief = ('本次主题：'+inp['_subject']+'\n' if inp.get('_subject') else '')+inp.get('brief', '')
        sources = value['source_data']
        stage = value['stage']
        if stage == 'angle_refresh':
            request=inp['_angle_request'];choice=request['choice']
            previous=(value['angles'] or {}).get('choices',[])
            instruction=request['instruction'] or '换一种切入方式，避免重复原有角度。'
            context=previous if choice is None else [previous[choice]]
            prompt=brief+'\n本次调整要求：'+instruction+'\n原有候选（仅作修改参照）：'+db.dump(context)
            if choice is not None:prompt+='\n仅给出 1 个修改后的角度。'
            result=article_ai.angles(profile,prompt,sources,article_id).model_dump()
            if choice is not None:
                previous[choice]=result['choices'][0];result={'choices':previous}
            if value['outline'] and (choice is None or choice==inp.get('angle_index',0)):inp['_angle_outline_stale']=True
            if choice is None:inp['angle_index']=0
            inp.pop('_angle_request',None)
            finish(article_id,angles=db.dump(result),input_data=db.dump(inp),status='draft' if value['document'] else 'needs_outline' if value['outline'] else 'needs_angle',
                   stage='review' if value['document'] else 'outline' if value['outline'] else 'angles',progress=100 if value['document'] else 45 if value['outline'] else 25,
                   note='新的写作角度已生成。现有大纲和正文保留，选用新角度后可重建大纲。')
        elif stage == 'replan':
            action=inp['_context_action']
            angles=article_ai.angles(profile,brief,sources,article_id)
            if action=='angles':
                finish(article_id,angles=db.dump(angles.model_dump()),outline=None,document=None,checks=None,status='needs_angle',stage='angles',progress=25,note='新选题的写作角度已生成，请选择后继续。')
                return
            with db.connect() as c:update(c,article_id,progress=30,note='已确定新的写作角度，正在重建大纲。')
            selected=angles.choices[0]
            outline=article_ai.outline(profile,brief,selected,sources,article_id)
            if action=='outline':
                finish(article_id,angles=db.dump(angles.model_dump()),outline=db.dump(outline.model_dump()),document=None,checks=None,status='needs_outline',stage='outline',progress=45,note='新选题的大纲已生成，确认后可继续写正文。')
                return
            with db.connect() as c:update(c,article_id,progress=50,note='新大纲已准备好，正在按新选题重写全文。')
            doc=article_ai.document(profile,brief,selected,outline,sources,article_id)
            doc.template_id=inp.get('_template_id', (value.get('document') or {}).get('template_id',profile.template_id))
            doc=article_pictures.prepare(doc,value.get('document') or inp.get('_picture_previous'))
            inp.pop('_picture_plan',None);inp.pop('_picture_cycle',None);inp.pop('_picture_previous',None)
            if article_ai.unfinished_issues(doc):raise article_ai.ArticleContentError('重新生成的内容未通过成品检查，原有正文保留。请调整选题要求后重试。')
            # Replace only after the new body is complete; failures during planning
            # or generation leave the previous outline and document intact.
            finish(article_id,angles=db.dump(angles.model_dump()),outline=db.dump(outline.model_dump()),document=db.dump(doc.model_dump()),input_data=db.dump(inp),checks=None,status='running',stage='illustrate',progress=75,note='新正文已保存，正在处理配图。')
            doc,warnings=article_pictures.apply(article_id)
            with db.connect() as c:update(c,article_id,stage='check',progress=85)
            result=article_ai.check(doc,sources,article_id,brief=brief,profile=profile).model_dump()
            result['issues']=article_ai.local_issues(doc,sources,profile.length)+result['issues']+[{'severity':'warning','section':0,'message':w} for w in warnings]
            finish(article_id,status='needs_revision' if any(i['severity']=='error' for i in result['issues']) else 'needs_review',stage='review',progress=100,checks=db.dump(result),note='已按新选题完成创作，请核对事实与配图。')
        elif stage == 'angles':
            result = article_ai.angles(profile, brief, sources, article_id)
            finish(article_id, status='needs_angle', progress=25, angles=db.dump(result.model_dump()), note='选择一个写作角度，接着生成大纲。')
        elif stage == 'outline':
            selected = Angle.model_validate(value['angles']['choices'][inp['angle_index']])
            result = article_ai.outline(profile, brief, selected, sources, article_id)
            finish(article_id, status='needs_outline', progress=45, outline=db.dump(result.model_dump()), note='大纲已保存，确认或编辑后生成正文。')
        elif stage in ('article', 'section', 'check', 'illustrate'):
            warnings=[]
            if stage == 'article':
                selected = Angle.model_validate(value['angles']['choices'][inp['angle_index']]) if value['angles'] else Angle(title=value['outline']['title'],angle=('按手动大纲展开：'+value['outline']['angle'])[:600],reason='根据已确认的大纲继续写作')
                doc = article_ai.document(profile, brief, selected, ArticleOutline.model_validate(value['outline']), sources, article_id)
                doc.template_id = inp.get('_template_id',profile.template_id)
                doc=article_pictures.prepare(doc,inp.get('_picture_previous'))
                inp.pop('_picture_plan',None);inp.pop('_picture_cycle',None);inp.pop('_picture_previous',None)
                finish(article_id, document=db.dump(doc.model_dump()),input_data=db.dump(inp), status='running', stage='illustrate', progress=75, note='正文已保存，正在处理配图。')
                doc,warnings=article_pictures.apply(article_id)
                with db.connect() as c:update(c,article_id,stage='check',progress=85)
            elif stage == 'illustrate':
                doc,warnings=article_pictures.apply(article_id)
                with db.connect() as c:update(c,article_id,stage='check',progress=85)
            elif stage == 'section':
                doc = ArticleDocument.model_validate(value['document'])
                rewrite = inp['_rewrite']
                index = rewrite.get('section');target=rewrite.get('target','section')
                if target=='section':
                    revised = article_ai.rewrite(profile, doc, index, rewrite['instruction'], sources, article_id)
                    revised.asset_id = doc.sections[index].asset_id
                    revised.caption = doc.sections[index].caption
                    revised.image_hint = doc.sections[index].image_hint
                    revised.image_locked = doc.sections[index].image_locked
                    doc.sections[index] = revised
                else:
                    revised=article_ai.rewrite_part(profile,brief,doc,rewrite,sources,article_id).text
                    if target=='heading':doc.sections[index].heading=revised
                    elif target=='paragraphs':doc.sections[index].paragraphs=[p.strip() for p in re.split(r'\n\s*\n',revised) if p.strip()]
                    elif target=='paragraph':doc.sections[index].paragraphs[rewrite['paragraph']]=revised
                    else:setattr(doc,target,revised)
                doc = ArticleDocument.model_validate(doc.model_dump())
                if article_ai.unfinished_issues(doc):raise article_ai.ArticleContentError('局部调整返回了写作方案或占位内容，未替换原文。请修改提示词后重试。')
                finish(article_id, document=db.dump(doc.model_dump()), checks=None, status='running', stage='check', progress=80, note='局部修改已保存，正在重新核对。')
            else:
                doc = ArticleDocument.model_validate(value['document'])
            result = article_ai.check(doc, sources, article_id, brief=brief, profile=profile).model_dump()
            result['issues'] = article_ai.local_issues(doc, sources, profile.length)+result['issues']+[{'severity':'warning','section':0,'message':w} for w in warnings]
            finish(article_id, status='needs_revision' if any(i['severity']=='error' for i in result['issues']) else 'needs_review',
                   stage='review', progress=100, checks=db.dump(result), note='检查完成，请核对事实、配图与排版后导出。')
        else:
            raise ValueError('无法继续此写作步骤。')
    except (ModelOutputLimitError, article_ai.ArticleContentError, article_pictures.IllustrationError) as error:
        with db.connect() as c:
            note='配图已暂停，已完成的正文和图片保留。' if isinstance(error,article_pictures.IllustrationError) else '内容未通过成品检查；已保存内容和历史版本保留。' if isinstance(error,article_ai.ArticleContentError) else '模型输出被截断；此前保存的角度、大纲和正文保留。'
            update(c, article_id, status='failed', error=str(error), note=note)
    except ModelRequestError as error:
        with db.connect() as c:
            update(c, article_id, status='failed', error=str(error)+' 已保存的大纲和正文保留。', note='模型请求未完成，文章任务已暂停。')
    except Exception:
        logging.exception('Article stage failed: %s', article_id)
        with db.connect() as c:
            update(c, article_id, status='failed', error='此步骤未完成，请检查模型连接与输出格式后重试。已保存的大纲和正文会保留。', note='文章任务已暂停。')


def recover():
    from .task_store import owns_queued
    with db.connect() as c:
        c.execute("UPDATE articles SET status='failed',error=%s,updated_at=%s WHERE status='running'",
                  ('服务中断，已保存内容保留。可从中断步骤重试。', db.now()))
        queued = [r['id'] for r in c.execute("SELECT id FROM articles WHERE status='queued'").fetchall() if not owns_queued(c,r['id'])]
    for article_id in queued:
        executor.submit(run, article_id)
