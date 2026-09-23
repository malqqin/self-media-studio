"""Bounded image imports and local image/video uploads for visual stories."""
from hashlib import sha256
from pathlib import Path
import io
import uuid
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from PIL import Image, ImageOps, UnidentifiedImageError

from . import config, db
from .network import public_url, fetch_public

MAX_UPLOAD = 100_000_000


def asset_path(asset):
    path = Path(asset['path'])
    return path if path.is_absolute() else config.DATA / path


def safe_media_url(url):
    try:
        public_url(url)
        return True
    except ValueError:
        return False


def fetch_image(url):
    return fetch_public(url,20_000_000)[0]


def article_images(html, page_url, publisher):
    soup = BeautifulSoup(html, 'html.parser')
    images = []
    for meta in soup.select('meta[property="og:image"]'):
        url = urljoin(page_url, meta.get('content', ''))
        if safe_media_url(url) and not any(word in url.lower() for word in ['logo', 'placeholder', '404-bg']):
            images.append({'url': url, 'page_url': page_url, 'credit': publisher,
                           'rights': '来源页关联图片；发布前核对图片署名与使用条件',
                           'filename': publisher + ' 来源图片'})
    return images[:1]


def store_asset(content, filename, rights, credit='', source_url=''):
    if len(content) > MAX_UPLOAD:
        raise ValueError('素材不能超过 100 MB。')
    directory = config.DATA / 'assets'; directory.mkdir(parents=True, exist_ok=True)
    digest = sha256(content).hexdigest()[:24]
    ident = 'asset-' + digest
    suffix = Path(filename).suffix.lower()
    if suffix in ('.mp4', '.mov', '.webm'):
        from .short_render import probe_video
        temporary = directory / ('.upload-' + uuid.uuid4().hex + suffix)
        try:
            temporary.write_bytes(content)
            info = probe_video(temporary)
            if not 0 < info['duration'] <= 600 or info['width'] * info['height'] > 16_800_000:
                raise ValueError('视频需在 10 分钟以内，画面尺寸不超过 4K。')
            target = directory / (ident + suffix)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        media_type = {'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm'}[suffix]
    else:
        if len(content) > 20_000_000:
            raise ValueError('图片不能超过 20 MB。')
        try:
            with Image.open(io.BytesIO(content)) as original:
                if original.width * original.height > 24_000_000:
                    raise ValueError('图片像素过大，请压缩后上传。')
                original.load()
                normalized = ImageOps.exif_transpose(original).convert('RGB')
                normalized.thumbnail((3840, 3840))
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValueError('请选择有效的 JPG、PNG、WebP 图片或 MP4、MOV、WebM 视频。') from None
        target = directory / (ident + '.jpg'); normalized.save(target, quality=93)
        media_type = 'image/jpeg'
    # Rights and credits can differ for the same bytes; do not overwrite another record.
    ident += '-' + sha256((rights + credit + source_url).encode()).hexdigest()[:8]
    with db.connect() as c:
        c.execute('INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?,?,?,?)',
                  (ident, filename[:150], media_type, rights, credit, source_url,
                   target.relative_to(config.DATA).as_posix(), db.now()))
        return dict(c.execute('SELECT * FROM assets WHERE id=?', (ident,)).fetchone())


def prepare_assets(script, topic):
    automatic = []
    if any(not scene.asset_id for scene in script.scenes):
        for item in topic.get('media', [])[:5]:
            # Cache by source page AND image URL so different views retain their identity.
            origin = item['url']
            with db.connect() as c:
                cached = c.execute('SELECT * FROM assets WHERE source_url=?', (origin,)).fetchone()
            if cached and asset_path(dict(cached)).is_file():
                automatic.append(dict(cached))
            else:
                automatic.append(store_asset(fetch_image(origin), item['filename'] + '.jpg',
                    item['rights'] + '；来源页：' + item.get('page_url', origin), item['credit'], origin))
        for i, scene in enumerate(script.scenes):
            if not scene.asset_id and automatic:
                scene.asset_id = automatic[i % len(automatic)]['id']
    assets = {}
    with db.connect() as c:
        for scene in script.scenes:
            if scene.asset_id:
                row = c.execute('SELECT * FROM assets WHERE id=?', (scene.asset_id,)).fetchone()
                if not row: raise ValueError('引用素材不存在。')
                assets[scene.asset_id] = dict(row)
    if topic['kind'] == 'live' and not assets:
        raise ValueError('来源页暂无可用图片，请在“编辑文案与画面”上传相关图片或视频后重试。')
    return assets
