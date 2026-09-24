"""Bounded, transient previews. Only validated final content enters article storage."""
from collections import OrderedDict
from contextlib import contextmanager
import re
import threading
import time
from itertools import count
from pydantic_core import from_json
from . import config
from .ai_stream import stream_sink

lock = threading.RLock()
previews = OrderedDict()
revisions = count(1)


def key(ident):return (str(config.DATA), ident)


def reset(ident):
    with lock:previews.pop(key(ident), None)


def get(ident):
    with lock:return previews.get(key(ident))


@contextmanager
def capture(ident):
    last = 0
    def receive(kind, text, force=False):
        nonlocal last
        now = time.monotonic()
        if not force and now-last < .08:return
        last = now if text else 0
        try:partial = from_json(re.sub(r'^```(?:json)?\s*', '', text.lstrip()), allow_partial='trailing-strings') if text else {}
        except ValueError:return
        if not isinstance(partial, dict):return
        with lock:
            previews[key(ident)]={'revision':next(revisions),'kind':kind,'partial':partial}
            previews.move_to_end(key(ident))
            while len(previews)>64:previews.popitem(last=False)
    token=stream_sink.set(receive)
    try:yield
    finally:stream_sink.reset(token)
