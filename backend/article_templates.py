"""Shared, trusted style catalog for previews and WeChat-compatible HTML."""
import json
import re
from pathlib import Path

CATALOG=json.loads((Path(__file__).resolve().parents[1]/'shared/article-templates.json').read_text(encoding='utf-8'))
TEMPLATES={item['id']:item for item in CATALOG['templates']}
DECORATIONS={'template-decoration-'+item['decoration']:Path(__file__).resolve().parents[1]/'public/article-decorations'/ (item['decoration']+('.gif' if item.get('animated') else '.png'))
             for item in TEMPLATES.values() if item.get('decoration')}


def get_template(ident=None):
    return TEMPLATES.get(ident,TEMPLATES['classic'])


def decoration_id(doc):
    name=get_template(doc.get('template_id')).get('decoration')
    return 'template-decoration-'+name if name else ''


def decoration_path(ident):
    return DECORATIONS.get(ident)


def motion_paths(ident):
    path=decoration_path(ident)
    return {'svg':path.with_suffix('.svg'),'png':path.with_suffix('.png')} if path and path.suffix=='.gif' else {}


def styles(ident=None):
    template=get_template(ident)
    def css(values):
        return ';'.join(re.sub(r'[A-Z]',lambda match:'-'+match[0].lower(),key)+':'+value for key,value in values.items())
    return {part:css({**base,**template['styles'].get(part,{})}) for part,base in CATALOG['base'].items()}
