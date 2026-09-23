from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from .network import public_url


class CollectionSource(BaseModel):
    id: str = Field(pattern=r'^custom-[a-zA-Z0-9-]{1,64}$')
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=8, max_length=2000)
    kind: Literal['auto', 'rss', 'page', 'browser'] = 'auto'
    enabled: bool = True

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):return public_url(value)

    @field_validator('name')
    @classmethod
    def valid_name(cls,value):
        if not value.strip():raise ValueError('来源名称不能为空。')
        return value.strip()


class SourceConfiguration(BaseModel):
    sources: list[Literal['nasa', 'esa', 'cern', 'nature']] = []
    custom_sources: list[CollectionSource] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def valid_sources(self):
        self.sources=list(dict.fromkeys(self.sources))
        identifiers=[s.id for s in self.custom_sources]
        urls=[s.url for s in self.custom_sources]
        if len(identifiers)!=len(set(identifiers)) or len(urls)!=len(set(urls)):
            raise ValueError('自定义资料源的编号和网址不能重复。')
        return self


class Settings(SourceConfiguration):
    account_name: str = Field(default='知序', min_length=1, max_length=24)
    schedule_enabled: bool = False
    schedule_time: str = Field(default='07:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    production_mode: Literal['ai'] = 'ai'
    duration_seconds: Literal[10] = 10
    audio_mode: Literal['silent'] = 'silent'
    resolution: Literal['720p', '1080p'] = '1080p'

    @field_validator('production_mode', mode='before')
    @classmethod
    def legacy_production_mode(cls, value):
        return 'ai' if value == 'sample' else value


class ModelConnection(BaseModel):
    name: str = Field(default='自定义模型', min_length=1, max_length=60)
    base_url: str = Field(default='https://api.openai.com/v1', max_length=2000)
    model: str = Field(default='', max_length=150)
    protocol: Literal['responses', 'chat_completions'] = 'responses'
    output_mode: Literal['json_schema', 'json_object', 'text'] = 'json_schema'
    api_key: str = Field(default='', max_length=4096, repr=False)
    clear_key: bool = False

    @field_validator('base_url')
    @classmethod
    def valid_base(cls,value):
        from urllib.parse import urlsplit
        value=value.strip().rstrip('/')
        try:
            p=urlsplit(value)
            if not p.hostname or p.username or p.password or p.query or p.fragment or '\\' in value or any(ord(c)<32 for c in value):raise ValueError()
            if p.scheme!='https' and not (p.scheme=='http' and p.hostname in ('localhost','127.0.0.1','::1')):raise ValueError()
            if p.port is not None and not 1<=p.port<=65535:raise ValueError()
        except ValueError:
            raise ValueError('接口地址需为 HTTPS；本机模型可用 HTTP。不要在网址中填写密钥。') from None
        for suffix in ('/chat/completions','/responses'):
            if value.endswith(suffix):value=value[:-len(suffix)]
        return value

    @field_validator('api_key','model','name')
    @classmethod
    def strip_value(cls,value):
        if any(ord(c)<32 for c in value):raise ValueError('配置不能含换行或控制字符。')
        return value.strip()


class ImportPage(BaseModel):
    url: str = Field(min_length=8,max_length=2000)
    title: str = Field(min_length=1,max_length=240)
    text: str = Field(min_length=20,max_length=60000)

    @field_validator('url')
    @classmethod
    def valid_url(cls,value):return public_url(value)

    @field_validator('title','text')
    @classmethod
    def nonempty(cls,value):
        if not value.strip():raise ValueError('标题和正文不能为空。')
        return value.strip()


class CreateJob(BaseModel):
    topic_id: str = Field(min_length=1, max_length=120)
    mode: Literal['ai'] = 'ai'
    request_id: str = Field(min_length=8, max_length=100)


class Review(BaseModel):
    decision: Literal['approve', 'revise']
    version: int = Field(ge=1)
    facts_checked: bool = False
    rights_checked: bool = False
    note: str = Field(default='', max_length=2000)


class Scene(BaseModel):
    heading: str = Field(min_length=1, max_length=32)
    source_id: str = Field(min_length=1, max_length=120)
    evidence: str = Field(min_length=5, max_length=1200)
    visual: Literal['orbit', 'spectrum', 'particle', 'question']
    asset_id: str = Field(default='', max_length=64)
    clip_start: float = Field(default=0, ge=0, le=600)


class Script(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=500)
    title_lines: list[str] = Field(min_length=1, max_length=2)
    scenes: list[Scene] = Field(min_length=1, max_length=5)

    @model_validator(mode='before')
    @classmethod
    def legacy_script(cls, value):
        # Old saved productions remain viewable; re-edits become short visual stories.
        if isinstance(value, dict) and 'title_lines' not in value:
            value = dict(value)
            value['title_lines'] = [value.get('title', '')[:28]]
            value['scenes'] = value.get('scenes', [])[:5]
        return value

    @field_validator('title_lines')
    @classmethod
    def short_titles(cls, value):
        value = [line.strip() for line in value]
        if any(not line or len(line) > 28 or '\n' in line or '\r' in line for line in value):
            raise ValueError('请填写 1–2 句简短标题，每句最多 28 字。')
        return value


class EditScript(BaseModel):
    version: int = Field(ge=1)
    script: Script
    note: str = Field(default='手动修改脚本', max_length=2000)


class TopicChoice(BaseModel):
    topic_id: str
    headline: str = Field(min_length=1,max_length=60)
    angle: str = Field(min_length=5,max_length=300)
    reason: str = Field(min_length=5,max_length=300)
    evidence: str = Field(min_length=12,max_length=1000)


class Curation(BaseModel):
    choices: list[TopicChoice] = Field(max_length=5)
    note: str


class FactCheck(BaseModel):
    supported: bool
    issues: list[str]
