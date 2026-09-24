"""Shared article forms and writing guidance for manual and scheduled creation."""
import json
from pathlib import Path

ARTICLE_FORMATS = json.loads((Path(__file__).resolve().parents[1] / 'shared' / 'article-formats.json').read_text(encoding='utf-8'))


def format_instructions(name):
    value = ARTICLE_FORMATS[name]
    return (f'文章形式「{name}」：{value["description"]}\n结构与表达要求：{value["guide"]}\n'
            '形式决定如何组织内容，用户具体主题决定写什么；按目标字数取舍，不必机械套用所有环节。'
            '除用户明确要求写作教学外，交付该形式的成品文章，不讲解如何撰写这种文章。')
