export type Page = 'home' | 'topics' | 'review' | 'flow';
export interface Source { id: string; title: string; publisher: string; url: string; text: string }
export interface Scene { heading: string; narration?: string; source_id: string; evidence: string; visual: 'orbit'|'spectrum'|'particle'|'question'; asset_id: string; clip_start: number }
export interface Script { title: string; description: string; title_lines: string[]; scenes: Scene[] }
export interface Topic { id: string; title: string; category: string; kind: 'sample'|'live'; source: string; angle: string; sources: Source[]; published_at: string|null; discovered_at: string; rights: string; evidence_status: string; seed_script?: Script; page_data?:{method:string;full_text:boolean;images:string[];links:{title:string;url:string}[];captured_at:string}; curation?: {rank:number;reason:string;evidence:string;at:string} }
export type BuiltinSource = 'nasa'|'esa'|'cern'|'nature';
export interface CollectionSource { id:string;name:string;url:string;kind:'auto'|'rss'|'page'|'browser';enabled:boolean }
export interface SourceCatalog { id:BuiltinSource;name:string;url:string;kind:'rss';description:string }
export interface SourcePreview { kind:string;count:number;note:string;items:{title:string;url:string;summary:string}[] }
export interface ModelConnection { name:string;base_url:string;model:string;protocol:'responses'|'chat_completions';output_mode:'json_schema'|'json_object'|'text';key_configured:boolean;ready:boolean;origin:string }
export interface CollectionResult { added:number;reports:{source:string;status:string;count:number;message:string;url?:string;code?:string|null}[] }
export interface Settings { account_name: string; schedule_enabled: boolean; schedule_time: string; sources: BuiltinSource[]; custom_sources:CollectionSource[]; production_mode: 'ai'; duration_seconds: 10; audio_mode: 'silent'; resolution: '720p'|'1080p' }
export interface Health { ok: boolean; ai_ready: boolean; model: string|null; audio_mode: 'silent'; duration_seconds: 10; local_only: boolean }
export interface QA { passed: boolean; duration_seconds: number; audio_present: boolean; audio_mode?: 'silent'; black_frames: number; human_checks: string[] }
export interface Job { id: string; topic_id: string; status: 'queued'|'running'|'needs_review'|'approved'|'failed'|'changes_requested'|'draft'; stage: string; progress: number; mode: string; version: number; script: Script|null; source_data: Source[]; settings: Settings; artifacts: Record<string,string>|null; qa: QA|null; error: string|null; note: string; created_at: string; updated_at: string; events?: {id:number; stage:string;message:string;at:string}[]; manifest?: {duration:number;timeline:{scene:number;start:number;end:number}[];cues:{scene:number;start:number;end:number;text:string}[]} }
export interface Asset { id:string;filename:string;media_type:string;rights:string;credit:string;source_url:string }
export interface Activity { sources:{id:number;source:string;status:string;count:number;message:string;at:string}[];daily:{day:string;status:string;message:string}[];ai_calls:number;jobs_today:number }
