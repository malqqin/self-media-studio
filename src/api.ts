export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch('/api' + path, { ...options, headers: { ...(options?.body instanceof FormData ? {} : {'Content-Type':'application/json'}), ...options?.headers } });
  } catch { throw new Error('暂时连接不到工作台服务，请确认服务已启动。'); }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if(response.status===401&&!path.startsWith('/auth/'))window.dispatchEvent(new Event('studio-session-expired'));
    const detail = data?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: {msg:string}) => item.msg).join('；') : `请求失败（${response.status}）`);
  }
  return data as T;
}
export const send = (method: string, body?: unknown): RequestInit => ({method, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
export const fileUrl = (id:string,kind:string,version=1) => `/api/jobs/${id}/files/${kind}?v=${version}`;
export function dateText(value:string|null) { return value ? new Intl.DateTimeFormat('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Shanghai'}).format(new Date(value)) : '常青选题'; }
export function timeText(seconds:number) {return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;}
