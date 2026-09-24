"""Read provider SSE without leaking raw provider errors or reasoning tokens."""
from contextvars import ContextVar
import json
import httpx

stream_sink = ContextVar('article_stream_sink', default=None)


def streamed_result(url, headers, payload, chat, emit):
    payload = {**payload, 'stream': True}
    if chat:payload['stream_options'] = {'include_usage': True}
    answer = ''; usage = {}; finish = None; terminal = None
    with httpx.stream('POST', url, headers=headers, json=payload,
                      timeout=httpx.Timeout(150, connect=15), follow_redirects=False) as response:
        if 300 <= response.status_code < 400:raise ValueError('接口返回重定向，请填写最终 API 地址后再试。')
        response.raise_for_status()
        if 'text/event-stream' not in response.headers.get('content-type', ''):
            # Some compatible gateways ignore stream=true and send one JSON object.
            response.read()
            return response.json()
        def events():
            lines = []; size = 0
            for line in response.iter_lines():
                if not line:
                    if lines:yield '\n'.join(lines)
                    lines = []; size = 0
                elif line.startswith('data:'):
                    value = line[5:].lstrip(); size += len(value)
                    if size > 300000:raise ValueError('模型流式消息过长，未保存为成稿。')
                    lines.append(value)
            if lines:yield '\n'.join(lines)
        for raw in events():
            if raw == '[DONE]':break
            event = json.loads(raw)
            if not isinstance(event, dict):raise ValueError('模型流式响应格式不兼容。')
            if event.get('error') or event.get('type') in ('error','response.failed'):
                raise ValueError('模型流式生成失败，已保存内容保留，请检查模型连接后重试。')
            delta = ''
            if chat:
                usage = event.get('usage') or usage
                choice = next((v for v in event.get('choices', []) if v.get('index',0)==0), None)
                if choice:
                    delta = (choice.get('delta') or {}).get('content') or ''
                    if (choice.get('delta') or {}).get('refusal'):raise ValueError('模型未返回可用内容。')
                    finish = choice.get('finish_reason') or finish
            else:
                if event.get('type') == 'response.output_text.delta':delta = event.get('delta','')
                if event.get('type') in ('response.completed','response.incomplete'):
                    terminal = event['response']; break
            if delta:
                if not isinstance(delta, str):raise ValueError('模型流式文字格式不兼容。')
                answer += delta
                if len(answer) > 240000:raise ValueError('模型输出过长，未保存为成稿。')
                emit(answer, False)
    if chat:
        if finish is None:raise ValueError('模型流式连接提前中断，未覆盖已保存内容，请重试。')
        return {'choices':[{'finish_reason':finish,'message':{'content':answer}}], 'usage':usage}
    if terminal is None:raise ValueError('模型流式连接提前中断，未覆盖已保存内容，请重试。')
    if not terminal.get('output') and answer:
        terminal['output']=[{'type':'message','content':[{'type':'output_text','text':answer}]}]
    return terminal
