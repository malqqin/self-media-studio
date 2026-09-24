"""Escaped, inline-styled exports. Image assets travel with the ZIP delivery."""
import html
import io
import zipfile
from . import db
from .media import asset_path
from .article_templates import get_template, styles


def images(doc):
    ids = list(dict.fromkeys([doc.get('cover_asset_id','')]+[s.get('asset_id','') for s in doc['sections']]))
    found = {}
    with db.connect() as c:
        for ident in filter(None, ids):
            row = c.execute('SELECT * FROM assets WHERE id=?', (ident,)).fetchone()
            if row and row['media_type'].startswith('image/'):
                path = asset_path(dict(row))
                if not path.is_file():
                    raise ValueError('所选图片文件不存在，请重新上传或移除后导出。')
                found[ident] = (f'images/{ident}{path.suffix}', path)
            else:
                raise ValueError('所选配图已不存在，请重新选择后导出。')
    return found


def html_body(doc, image_paths=None, *, wechat=False):
    paths = image_paths or {}
    esc = html.escape
    template=get_template(doc.get('template_id'));css=styles(template['id'])
    def style(part):return esc(css[part],quote=True)
    def paragraph(value,part='paragraph'):
        return f'<p style="{style(part)}">{esc(value)}</p>'
    def image(ident, caption=''):
        if ident not in paths:
            return ''
        return f'<figure style="{style("figure")}"><img src="{esc(paths[ident],quote=True)}" alt="{esc(caption,quote=True)}" style="{style("image")}"/>'+ (f'<figcaption style="{style("caption")}">{esc(caption)}</figcaption>' if caption else '')+'</figure>'
    body = [f'<section data-article-template="{template["id"]}" style="{style("root")}">',
            f'<h1 style="{style("title")}">{esc(doc["title"])}</h1>',
            image(doc.get('cover_asset_id','')), paragraph(doc['summary'],'summary')]
    if doc.get('opening'):
        body.append(paragraph(doc['opening']))
    for index,section in enumerate(doc['sections'],1):
        # WeChat's paste importer flags inline-block number badges as overlapping
        # lines and stops insertion behind a modal. Keep numbers in the heading's
        # own text flow for delivery; retain the original badges in local exports.
        number=(f'{index:02d} · ' if wechat else f'<span style="{style("number")}">{index:02d}</span>') if template['numbered'] else ''
        body.append(f'<h2 style="{style("heading")}">{number}{esc(section["heading"])}</h2>')
        body.extend(paragraph(p) for p in section['paragraphs'])
        body.append(image(section.get('asset_id',''), section.get('caption','')))
    if doc.get('closing'):
        body.append(paragraph(doc['closing'],'closing'))
    return ''.join(body)+ '</section>'


def markdown(doc, image_paths=None):
    paths = image_paths or {}
    # Escape HTML and Markdown controls; exported text must not turn into raw HTML.
    def esc(value):
        value = html.escape(value)
        for char in ('\\','`','*','_','[',']','#','>'):
            value = value.replace(char, '\\'+char)
        return value
    chunks = ['# '+esc(doc['title']), esc(doc['summary'])]
    if doc.get('cover_asset_id') in paths:
        chunks.append(f'![封面]({paths[doc["cover_asset_id"]]})')
    chunks.append(esc(doc.get('opening','')))
    for section in doc['sections']:
        chunks += ['## '+esc(section['heading']), *[esc(p) for p in section['paragraphs']]]
        if section.get('asset_id') in paths:
            chunks.append(f'![{esc(section.get("caption",""))}]({paths[section["asset_id"]]})')
    chunks.append(esc(doc.get('closing','')))
    return '\n\n'.join(chunks)


def bundle(article):
    doc = article['document']
    assets = images(doc)
    paths = {ident: value[0] for ident,value in assets.items()}
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('article.html','<!doctype html><meta charset="utf-8">'+html_body(doc,paths))
        archive.writestr('article.md', markdown(doc,paths))
        archive.writestr('sources.json',db.dump(article['source_data']))
        archive.writestr('checks.json',db.dump(article['checks']))
        with db.connect() as c:
            metadata = [{key: row[key] for key in ('id','filename','rights','credit','source_url')}
                        for ident in assets for row in c.execute('SELECT * FROM assets WHERE id=?',(ident,))]
        archive.writestr('assets.json',db.dump(metadata))
        archive.writestr('article.json',db.dump(doc))
        archive.writestr('README.txt','打开 article.html 查看排版。图片位于 images 目录；粘贴到公众号后需上传图片并检查排版。来源与检查报告仅供编辑核验，不会自动发布。')
        for name,path in assets.values():
            archive.write(path,name)
    return output.getvalue()
