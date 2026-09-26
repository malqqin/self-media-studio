"""Keep internal asset review statuses out of reader-facing image captions."""
import json
from .config import ROOT

INTERNAL_STATUSES = frozenset(json.loads((ROOT / 'shared/article-caption-statuses.json').read_text(encoding='utf-8')))


def display_caption(value):
    # Older articles joined credits and license status with this separator.
    # Only remove whole status labels; preserve descriptions and attribution.
    return ' · '.join(part.strip() for part in (value or '').split(' · ')
                      if part.strip() and part.strip() not in INTERNAL_STATUSES)
