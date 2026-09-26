from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DATA = Path(os.environ.get('STUDIO_DATA_DIR') or ROOT / 'data').resolve()
MODEL = os.environ.get('OPENAI_MODEL', '').strip()
API_KEY = os.environ.get('OPENAI_API_KEY', '').strip()
API_BASE = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/')
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
DATABASE_SCHEMA = os.environ.get('DATABASE_SCHEMA', 'studio').strip()
COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'false').lower() == 'true'
ALLOWED_HOSTS = set(os.environ.get('ALLOWED_HOSTS', '127.0.0.1,localhost,testserver').split(','))
ALLOWED_ORIGINS = set(os.environ.get('ALLOWED_ORIGINS', 'http://127.0.0.1:8765,http://localhost:8765,http://127.0.0.1:5173,http://localhost:5173').split(','))


def data_dir() -> Path:
    from .tenancy import require_user
    return DATA / 'users' / require_user()


def ai_ready() -> bool:
    from .model_config import current
    connection=current()
    return bool(connection['model'] and connection['api_key'] and connection.get('protocol') in ('responses','chat_completions'))


def ffmpeg_path() -> str:
    override = os.environ.get('FFMPEG_PATH')
    if override:
        return override
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def font_path() -> str:
    candidates = [os.environ.get('FONT_PATH', ''), 'C:/Windows/Fonts/msyh.ttc',
                  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                  '/System/Library/Fonts/PingFang.ttc']
    for name in candidates:
        if name and Path(name).is_file():
            return name
    raise RuntimeError('未找到中文字体。请在 .env 中设置 FONT_PATH 为中文字体的完整路径。')
