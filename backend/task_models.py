from typing import Annotated, Literal
from pydantic import Field, field_validator
from .article_models import TextModel, ArticleProfile
from .network import public_url
from .picture_models import IllustrationSettings


class MaterialSettings(TextModel):
    mode: Literal['original','reference'] = 'original'
    discover: bool = False
    query: str = Field(default='',max_length=200)
    urls: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list,max_length=10)
    topic_ids: list[Annotated[str, Field(max_length=120)]] = Field(default_factory=list,max_length=20)
    notes: str = Field(default='',max_length=20000)
    search_scope: Literal['web','wechat'] = 'web'
    max_age_days: Literal[0,7,30,90,365] = 0
    reference_style: Literal['facts','structure','tone'] = 'facts'

    @field_validator('urls')
    @classmethod
    def public_urls(cls,values):
        return list(dict.fromkeys(public_url(url) for url in values))


class Schedule(TextModel):
    time: str = Field(default='09:00',pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    weekdays: list[Annotated[int,Field(ge=1,le=7)]] = Field(default_factory=lambda:list(range(1,8)),min_length=1,max_length=7)

    @field_validator('weekdays')
    @classmethod
    def unique_days(cls,values):
        return sorted(set(values))


class ArticlePlanning(TextModel):
    mode: Literal['fixed','direction'] = 'fixed'
    avoid_days: int = Field(default=30,ge=1,le=90)


class WeChatDelivery(TextModel):
    mode: Literal['local','handoff','draft','publish'] = 'local'
    account_id: str = Field(default='',max_length=80)
    cover_asset_id: str = Field(default='',max_length=64)
    author: str = Field(default='',max_length=16)


class VideoSettings(TextModel):
    resolution: Literal['720p','1080p'] = '1080p'
    visual_style: str = Field(default='相关画面，简短标题，完整保留素材比例',max_length=600)
    asset_ids: list[Annotated[str,Field(max_length=64)]] = Field(default_factory=list,max_length=5)


class ImageSettings(TextModel):
    format: Literal['poster','carousel'] = 'carousel'
    ratio: Literal['portrait','square','landscape'] = 'portrait'
    theme: Literal['forest','paper','night'] = 'forest'
    count: int = Field(default=3,ge=1,le=6)
    style: str = Field(default='简洁易读，每页表达一个重点',max_length=600)
    asset_id: str = Field(default='',max_length=64)


class TaskSettings(TextModel):
    model_id: str = Field(default='default',max_length=80)
    execution: Literal['manual','automatic'] = 'manual'
    schedule: Schedule = Field(default_factory=Schedule)
    brief: str = Field(default='',max_length=2000)
    materials: MaterialSettings = Field(default_factory=MaterialSettings)
    article: ArticleProfile = Field(default_factory=ArticleProfile)
    article_plan: ArticlePlanning = Field(default_factory=ArticlePlanning)
    illustration: IllustrationSettings = Field(default_factory=IllustrationSettings)
    wechat_delivery: WeChatDelivery = Field(default_factory=WeChatDelivery)
    video: VideoSettings = Field(default_factory=VideoSettings)
    image: ImageSettings = Field(default_factory=ImageSettings)


class CreateTask(TextModel):
    name: str = Field(min_length=1,max_length=80)
    kind: Literal['video','article','image']
    request_id: str = Field(min_length=8,max_length=100)


class EditTask(TextModel):
    name: str = Field(min_length=1,max_length=80)
    version: int = Field(ge=1)
    settings: TaskSettings


class ExecuteTask(TextModel):
    version: int = Field(ge=1)
    request_id: str = Field(min_length=8,max_length=100)
    action: Literal['assist','blank','automatic'] = 'assist'


class ImageCard(TextModel):
    heading: str = Field(min_length=1,max_length=48)
    body: str = Field(default='',max_length=400)
    footer: str = Field(default='',max_length=100)


class ImageDocument(TextModel):
    title: str = Field(min_length=1,max_length=100)
    cards: list[ImageCard] = Field(min_length=1,max_length=6)


class EditImage(TextModel):
    version: int = Field(ge=1)
    document: ImageDocument
    settings: ImageSettings
