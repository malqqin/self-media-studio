from typing import Literal, Annotated
from pydantic import Field, model_validator
from .article_models import TextModel


class IllustrationSettings(TextModel):
    enabled: bool = False
    mode: Literal['manual','web','ai','smart'] = 'smart'
    web_source: Literal['web','licensed'] = 'licensed'
    cover: bool = True
    count: int = Field(default=3,ge=0,le=6)
    style: str = Field(default='自然、简洁，与文章内容一致，不添加文字或水印',max_length=600)
    model_id: str = Field(default='',max_length=80)
    ratio: Literal['landscape','square','portrait'] = 'landscape'
    failure: Literal['skip','pause','ai'] = 'skip'
    asset_ids: list[Annotated[str,Field(max_length=64)]] = Field(default_factory=list,max_length=20)


class PictureSearch(TextModel):
    query: str = Field(min_length=2,max_length=160)
    source: Literal['web','licensed'] = 'web'


class PictureRequest(TextModel):
    request_id: str = Field(min_length=8,max_length=120)
    action: Literal['generate','edit','import','crop']
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

    @model_validator(mode='after')
    def valid(self):
        if self.action in ('generate','edit') and not self.prompt:raise ValueError('请填写图片描述或修改要求。')
        if self.action in ('edit','crop') and not self.asset_id:raise ValueError('请选择需要编辑的原图。')
        if self.action=='import' and not self.candidate_id:raise ValueError('请选择搜索结果中的图片。')
        if self.x+self.width>1.000001 or self.y+self.height>1.000001:raise ValueError('裁剪范围超出了原图。')
        return self
