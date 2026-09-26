import internalStatuses from '../shared/article-caption-statuses.json';

// Also handles captions saved before asset review statuses were kept separate.
export const displayCaption=(value?:string)=> (value||'').split(' · ').map(part=>part.trim()).filter(part=>part&&!internalStatuses.includes(part)).join(' · ');
