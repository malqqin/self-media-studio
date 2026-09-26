"""Request identity follows work into thread pools; missing identity fails closed."""
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from concurrent.futures import ThreadPoolExecutor

user_id = ContextVar('studio_user_id', default=None)
LEGACY_OWNER = 'legacy-owner'


def require_user():
    ident = user_id.get()
    if not ident:
        raise RuntimeError('数据库操作缺少用户身份。')
    return ident


@contextmanager
def as_user(ident):
    token = user_id.set(ident)
    try:
        yield
    finally:
        user_id.reset(token)


class ContextExecutor(ThreadPoolExecutor):
    def submit(self, fn, /, *args, **kwargs):
        context = copy_context()
        def invoke():
            from .auth import is_active
            if not is_active(require_user()):
                return None
            return fn(*args, **kwargs)
        return super().submit(context.run, invoke)
