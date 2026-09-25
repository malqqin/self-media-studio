"""公众号写作的数据结构，与视频脚本独立。"""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from .network import public_url
from .article_formats import ARTICLE_FORMATS

ArticleTemplate = Literal['classic','tech','travel','guide','opinion','minimal','cream','sage','journal','editorial','newspaper','ink','rose','ocean','coffee','butter','postcard','midnight']


class TextModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')


class ArticleProfile(TextModel):
    template_id: ArticleTemplate = 'classic'
    name: str = Field(default='我的公众号', min_length=1, max_length=40)
    direction: str = Field(default='', max_length=500)
    audience: str = Field(default='', max_length=300)
    style: str = Field(default='清晰自然，有具体解释，避免夸张和套话', max_length=1000)
    length: int = Field(default=1500, ge=400, le=4000)
    format: str = Field(default='解读', json_schema_extra={'enum': list(ARTICLE_FORMATS)})
    preferences: str = Field(default='', max_length=2000)

    @field_validator('format')
    @classmethod
    def supported_format(cls, value):
        if value not in ARTICLE_FORMATS:
            raise ValueError('请选择支持的文章形式。')
        return value


class ArticleInput(TextModel):
    mode: Literal['original', 'reference']
    brief: str = Field(default='', max_length=2000)
    topic_ids: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(default_factory=list, max_length=5)
    notes: str = Field(default='', max_length=20000)
    request_id: str = Field(min_length=8, max_length=100)

    @model_validator(mode='after')
    def valid_input(self):
        self.topic_ids = list(dict.fromkeys(self.topic_ids))
        if self.mode == 'reference' and not self.topic_ids and len(self.notes) < 20:
            raise ValueError('参考创作需要选择资料，或提供至少 20 字的参考笔记。')
        return self


class ArticleLink(TextModel):
    url: str = Field(min_length=8, max_length=2000)

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        return public_url(value)


class Angle(TextModel):
    title: str = Field(min_length=1, max_length=100)
    angle: str = Field(min_length=5, max_length=600)
    reason: str = Field(min_length=5, max_length=600)


class Angles(TextModel):
    choices: list[Angle] = Field(min_length=1, max_length=5)


class OutlineSection(TextModel):
    heading: str = Field(min_length=1, max_length=120)
    points: str = Field(min_length=1, max_length=1800)


class ArticleOutline(TextModel):
    title: str = Field(min_length=1, max_length=100)
    angle: str = Field(min_length=1, max_length=1000)
    sections: list[OutlineSection] = Field(min_length=1, max_length=12)
    source_gaps: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(default_factory=list, max_length=15)


class Evidence(TextModel):
    source_id: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=8, max_length=1000)


class ArticleSection(TextModel):
    heading: str = Field(min_length=1, max_length=120)
    paragraphs: list[Annotated[str, Field(min_length=1, max_length=3000)]] = Field(min_length=1, max_length=12)
    evidence: list[Evidence] = Field(default_factory=list, max_length=8)
    image_hint: str = Field(default='', max_length=500)
    asset_id: str = Field(default='', max_length=64)
    image_locked: bool = False
    caption: str = Field(default='', max_length=300)


class ArticleDocument(TextModel):
    template_id: ArticleTemplate = 'classic'
    title: str = Field(min_length=1, max_length=100)
    titles: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(min_length=1, max_length=5)
    summary: str = Field(min_length=1, max_length=300)
    opening: str = Field(default='', max_length=3000)
    sections: list[ArticleSection] = Field(min_length=1, max_length=12)
    closing: str = Field(default='', max_length=3000)
    cover_hint: str = Field(default='', max_length=500)
    cover_asset_id: str = Field(default='', max_length=64)
    cover_image_locked: bool = False
    cover_caption: str = Field(default='',max_length=1000)

    @model_validator(mode='after')
    def bounded_size(self):
        if len(self.model_dump_json()) > 60000:
            raise ValueError('文章内容过长，请缩短到 3 万字以内。')
        return self


class ArticleIssue(TextModel):
    severity: Literal['warning', 'error']
    section: int = Field(ge=0, le=12, description='0 表示全文、标题或摘要；正文节从 1 开始')
    message: str = Field(min_length=1, max_length=1000)


class ArticleCheck(TextModel):
    issues: list[ArticleIssue] = Field(default_factory=list, max_length=40)
    note: str = Field(min_length=1, max_length=1000)


class ArticleVersion(TextModel):
    version: int = Field(ge=1)


class EditAngle(ArticleVersion):
    choice: int = Field(ge=0,le=4)
    angle: Angle


class RegenerateAngles(ArticleVersion):
    choice: int | None = Field(default=None,ge=0,le=4)
    instruction: str = Field(default='',max_length=2000)


class EditArticleContext(ArticleVersion):
    subject: str = Field(default='',max_length=160)
    brief: str = Field(default='',max_length=2000)
    mode: Literal['original','reference'] = 'original'
    topic_ids: list[Annotated[str,Field(min_length=1,max_length=120)]] = Field(default_factory=list,max_length=5)
    notes: str = Field(default='',max_length=20000)
    query: str = Field(default='',max_length=100)
    search_scope: Literal['web','wechat'] = 'wechat'
    max_age_days: Literal[0,7,30,90,365] = 30
    action: Literal['save','angles','outline','article'] = 'save'

    @model_validator(mode='after')
    def valid_context(self):
        self.topic_ids=list(dict.fromkeys(self.topic_ids))
        if not self.subject and not self.brief:raise ValueError('请填写本次选题或写作要求。')
        if self.mode=='reference' and not self.topic_ids and len(self.notes)<20:
            raise ValueError('参考创作需要选择资料，或提供至少 20 字的参考笔记。')
        return self


class CollectArticleContext(ArticleVersion):
    brief: str = Field(min_length=1,max_length=2200)
    query: str = Field(min_length=2,max_length=100)
    search_scope: Literal['web','wechat'] = 'wechat'
    max_age_days: Literal[0,7,30,90,365] = 30


class ChooseAngle(ArticleVersion):
    choice: int = Field(ge=0, le=4)
    replace_existing: bool = False


class EditOutline(ArticleVersion):
    outline: ArticleOutline
    replace_existing: bool = False


class GenerateArticle(ArticleVersion):
    replace_existing: bool = False


class EditArticle(ArticleVersion):
    document: ArticleDocument


class RestoreArticle(ArticleVersion):
    target_version: int = Field(ge=1)


class RewriteSection(ArticleVersion):
    target: Literal['section','title','summary','opening','closing','heading','paragraphs','paragraph'] = 'section'
    section: int | None = Field(default=None, ge=0, le=11)
    paragraph: int | None = Field(default=None, ge=0, le=11)
    instruction: str = Field(min_length=1, max_length=2000)
    document: ArticleDocument | None = None

    @model_validator(mode='after')
    def valid_target(self):
        if self.target in ('section','heading','paragraphs','paragraph') and self.section is None:
            raise ValueError('请选择需要调整的章节。')
        if self.target=='paragraph' and self.paragraph is None:raise ValueError('请选择需要调整的段落。')
        if self.target not in ('section','heading','paragraphs','paragraph') and self.section is not None:
            raise ValueError('当前调整范围不需要章节编号。')
        if self.target!='paragraph' and self.paragraph is not None:raise ValueError('当前调整范围不需要段落编号。')
        return self


class RewrittenText(TextModel):
    text: str = Field(min_length=1, max_length=20000)
