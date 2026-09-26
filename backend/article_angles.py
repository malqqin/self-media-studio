"""Edit candidate angles independently of already written content."""
from . import db, article_worker as worker, article_stream, model_library
from .article_context import require_editable


def revise(ident,body,*,generate=False):
    with db.connect() as c:
        db.lock(c,'article',ident)
        value,_=require_editable(c,ident,body.version)
        choices=(value['angles'] or {}).get('choices',[])
        if body.choice is not None and body.choice>=len(choices):raise ValueError('写作角度不存在，请刷新后重试。')
        inp={**value['input_data']}
        inp.pop('_rewrite',None)
        if generate:
            if not model_library.ready(inp.get('_model_id','default')):raise ValueError('请先配置本次作品使用的 AI 模型。')
            inp['_angle_request']={'choice':body.choice,'instruction':body.instruction}
            worker.update(c,ident,status='queued',stage='angle_refresh',error=None,input_data=db.dump(inp),note='正在重新构思写作角度，现有大纲和正文保留。')
            article_stream.reset(ident)
        else:
            choices[body.choice]=body.angle.model_dump()
            if value['outline'] and inp.get('angle_index',0)==body.choice:inp['_angle_outline_stale']=True
            worker.update(c,ident,angles=db.dump({'choices':choices}),input_data=db.dump(inp),version=body.version+1,
                          status='draft' if value['document'] else 'needs_outline' if value['outline'] else 'needs_angle',
                          stage='review' if value['document'] else 'outline' if value['outline'] else 'angles',error=None,
                          note='写作角度已保存；选用修改后的角度可重新生成大纲。')
            worker.snapshot(c,ident,f'编辑写作角度 {body.choice+1}')
    if generate:worker.executor.submit(worker.run,ident)
    return worker.get(ident)
