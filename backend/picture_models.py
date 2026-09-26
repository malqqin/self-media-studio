from typing import Literal, Annotated
import json
from pydantic import Field, model_validator, field_validator
from urllib.parse import urlsplit,urlunsplit,unquote
from .network import public_url
from .article_models import TextModel
from .config import ROOT

PictureSource = Literal['bing','360','sogou']
DEFAULT_PICTURE_SOURCES = [s['id'] for s in json.loads((ROOT/'shared/picture-sources.json').read_text(encoding='utf-8')) if s['recommended']]


def normalize_picture_site(value):
    value=value.strip()
    if not value:raise ValueError('请填写自定义图片网站。')
    value=public_url(value if '://' in value else 'https://'+value)
    parsed=urlsplit(value)
    decoded=unquote(value)
    if any(c.isspace() for c in decoded) or any(c in decoded for c in ('"',"'",'{','}')):
        raise ValueError('请填写网站或栏目网址，不要填写搜索语句或模板。')
    return urlunsplit((parsed.scheme,parsed.hostname.lower(),parsed.path.rstrip('/'),'',''))


PictureSite = Annotated[str,Field(min_length=1,max_length=2000)]


class IllustrationSettings(TextModel):
    enabled: bool = False
    mode: Literal['manual','web','ai','smart'] = 'smart'
    web_source: Literal['web','licensed'] = 'web'
    web_sources: list[PictureSource] = Field(default_factory=list,max_length=7)
    custom_sites: list[PictureSite] = Field(default_factory=list,max_length=5)
    cover: bool = True
    count: int = Field(default=3,ge=0,le=6)
    style: str = Field(default='自然、简洁，与文章内容一致，不添加文字或水印',max_length=600)
    model_id: str = Field(default='',max_length=80)
    ratio: Literal['landscape','square','portrait'] = 'landscape'
    failure: Literal['skip','pause','ai'] = 'skip'
    asset_ids: list[Annotated[str,Field(max_length=64)]] = Field(default_factory=list,max_length=20)

    @property
    def selected_sources(self):
        # Old tasks had no explicit list and inherited the overseas default.
        # Explicit multi-selections remain intact; automatic defaults now match UI.
        return list(dict.fromkeys(self.web_sources or ([] if self.custom_sites else DEFAULT_PICTURE_SOURCES)))

    @field_validator('web_sources',mode='before')
    @classmethod
    def remove_retired_sources(cls,values):
        # Persisted legacy tasks must remain editable after providers are removed.
        if isinstance(values,list):return [v for v in values if v not in ('baidu','unsplash','commons','openverse')]
        return values

    @field_validator('custom_sites')
    @classmethod
    def normalize_sites(cls,values):
        return list(dict.fromkeys(normalize_picture_site(v) for v in values))


class PictureSearch(TextModel):
    query: str = Field(min_length=2,max_length=160)
    source: Literal['web','licensed'] = 'web'
    custom_sites: list[PictureSite] = Field(default_factory=list,max_length=5)

    @field_validator('custom_sites')
    @classmethod
    def normalize_sites(cls,values):
        return list(dict.fromkeys(normalize_picture_site(v) for v in values))


class PictureRequest(TextModel):
    request_id: str = Field(min_length=8,max_length=120)
    action: Literal['generate','edit','remove_watermark','enhance','import','crop']
    model_id: str = Field(default='',max_length=80)
    prompt: str = Field(default='',max_length=4000)
    ratio: Literal['landscape','square','portrait'] = 'landscape'
    asset_id: str = Field(default='',max_length=64)
    candidate_id: str = Field(default='',max_length=80)
    # Normalized crop rectangle, independent of preview size.
    x: float = Field(default=0,ge=0,lt=1)
    y: float = Field(default=0,ge=0,lt=1)
    width: float = Field(default=1,gt=0,le=1)
    height: float = Field(default=1,gt=0,le=1)
    strength: float = Field(default=1.5,ge=.5,le=3)
    scale: Literal[1,2] = 2

    @model_validator(mode='after')
    def valid(self):
        if self.action in ('generate','edit') and not self.prompt:raise ValueError('请填写图片描述或修改要求。')
        if self.action in ('edit','remove_watermark','enhance','crop') and not self.asset_id:raise ValueError('请选择需要编辑的原图。')
        if self.action=='import' and not self.candidate_id:raise ValueError('请选择搜索结果中的图片。')
        if self.x+self.width>1.000001 or self.y+self.height>1.000001:raise ValueError('裁剪范围超出了原图。')
        return self
