"""Native editor declarations; the official draft API exposes no equivalent field."""
import json
from typing import Literal
from .config import ROOT

Declaration = Literal['ai','news','fiction','opinion','health','finance','none']
LABELS = {v['id']:v['label'] for v in json.loads((ROOT/'shared/wechat-declarations.json').read_text(encoding='utf-8'))}


def label(value='ai'):
    if value not in LABELS:raise ValueError('请选择有效的公众号创作来源。')
    return LABELS[value]


def validate_delivery(delivery,account):
    if account.get('channel','api')=='api' and delivery.mode=='publish' and delivery.content_declaration!='none':
        raise ValueError('微信官方 API 暂未开放创作来源设置，无法带此声明自动发布。请改为保存草稿后到后台设置，或使用扫码接入自动保存声明。')
