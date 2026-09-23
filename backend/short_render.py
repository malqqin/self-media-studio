"""Ten-second, silent visual stories. No speech or timed subtitles."""
from dataclasses import dataclass
from pathlib import Path
import json
import math
import os
import re
import subprocess
import zipfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from . import config
from .models import Script

W, H, FPS, DURATION = 720, 1280, 25, 10


@dataclass
class Rendered:
    video: Path
    cover: Path
    script: Path
    manifest: Path
    duration: float
    qa: dict


def run_command(args, *, cwd=None, timeout=600):
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=timeout, creationflags=flags)
    if result.returncode:
        raise ValueError('视频处理失败：' + result.stderr[-700:])
    return result


def duration_from_log(log):
    match = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', log)
    return int(match[1])*3600 + int(match[2])*60 + float(match[3]) if match else 0


def probe_video(path):
    result = run_command([config.ffmpeg_path(), '-hide_banner', '-protocol_whitelist', 'file,pipe',
        '-format_whitelist', 'mov,matroska,webm', '-i', str(path), '-map', '0:v:0',
        '-frames:v', '1', '-an', '-f', 'null', '-'], timeout=45)
    stream = next((line for line in result.stderr.splitlines() if 'Video:' in line), '')
    size = re.search(r'\b(\d{2,5})x(\d{2,5})\b', stream)
    if not size or not duration_from_log(result.stderr):
        raise ValueError('视频没有可解码的画面或有效时长。')
    return {'duration': duration_from_log(result.stderr), 'width': int(size[1]), 'height': int(size[2])}


def wrap(text, font, width):
    lines = []; line = ''
    for char in text:
        if font.getlength(line + char) > width and line:
            lines.append(line); line = ''
        line += char
    return lines + ([line] if line else [])


def illustration(visual, index):
    image = Image.new('RGB', (W, 850), '#142E32'); d = ImageDraw.Draw(image)
    for i in range(65):
        x = (i * 131 + index * 23) % W; y = (i * 79) % 850
        d.ellipse((x, y, x+2, y+2), fill='#688B87')
    if visual in ('orbit', 'question'):
        d.ellipse((80, 270, 640, 610), outline='#8ABCB0', width=3)
        d.ellipse((245, 315, 475, 545), fill='#477F79', outline='#A6CBC0', width=3)
        d.arc((275, 340, 430, 520), 100, 260, fill='#84AC8B', width=42)
        x = 355 + math.cos(index * 1.5) * 275; y = 430 + math.sin(index * 1.5) * 160
        d.ellipse((x-12, y-12, x+12, y+12), fill='#EDC565')
    elif visual == 'particle':
        for i in range(32):
            a = i / 32 * math.tau
            x = 360 + math.cos(a) * 235; y = 425 + math.sin(a) * 235
            d.ellipse((x-7, y-7, x+7, y+7), fill='#EDC565')
        d.ellipse((320, 385, 400, 465), fill='#A6CBC0')
    else:
        for i, color in enumerate(['#CB897C', '#DDAB7F', '#EDC565', '#A1BAA0', '#68A1B1', '#868CBF']):
            d.rounded_rectangle((105+i*88, 300-i*20, 159+i*88, 550+i*20), radius=25, fill=color)
    return image


def image_canvas(original):
    # Only the blurred background is cropped; the scientific image remains complete.
    background = ImageOps.fit(original, (W, H)).filter(ImageFilter.GaussianBlur(38))
    background = Image.blend(background, Image.new('RGB', (W, H), '#091C22'), .66)
    fitted = ImageOps.contain(original, (W, 960), Image.Resampling.LANCZOS)
    background.paste(fitted, ((W-fitted.width)//2, 125+(960-fitted.height)//2))
    return background


def title_overlay(script):
    layer = Image.new('RGBA', (W, H)); draw = ImageDraw.Draw(layer)
    font = ImageFont.truetype(config.font_path(), 47 if len(script.title_lines) == 1 else 40)
    lines = [line for title in script.title_lines for line in wrap(title, font, W-100)]
    top = 76
    fade_start = top + len(lines) * 57 + 20
    fade_end = fade_start + 120
    for y in range(fade_end):
        opacity = 200 if y <= fade_start else int(200 * (fade_end-y) / (fade_end-fade_start))
        draw.line((0, y, W, y), fill=(7, 23, 29, opacity))
    for i, line in enumerate(lines):
        draw.text((50, top+i*57), line, font=font, fill='#F9F5E8', stroke_width=1)
    return layer


def encode_scene(scene, script, asset, folder, index, frames, resolution):
    from .media import asset_path
    scale = '1080:1920' if resolution == '1080p' else '720:1280'
    is_video = asset and asset['media_type'].startswith('video/')
    overlay = title_overlay(script)
    target = folder / f'segment-{index:02d}.mp4'; seconds = frames / FPS
    if is_video:
        source = asset_path(asset); info = probe_video(source)
        if scene.clip_start >= info['duration']:
            raise ValueError(f'第 {index+1} 个画面的截取起点超出了视频长度。')
        overlay_path = folder / f'overlay-{index:02d}.png'; overlay.save(overlay_path)
        inputs = ['-protocol_whitelist', 'file,pipe', '-ss', str(scene.clip_start), '-i', str(source),
                  '-loop', '1', '-i', str(overlay_path)]
        graph = (f'[0:v]setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=decrease,'
                 f'pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x091c22,setsar=1,'
                 f'tpad=stop_mode=clone:stop_duration={seconds},fps={FPS}[base];'
                 f'[base][1:v]overlay=0:0,scale={scale},format=yuv420p[v]')
    else:
        if asset:
            with Image.open(asset_path(asset)) as original:
                base = image_canvas(original.convert('RGB'))
        else:
            base = image_canvas(illustration(scene.visual, index))
        frame = Image.alpha_composite(base.convert('RGBA'), overlay).convert('RGB')
        frame_path = folder / f'frame-{index:02d}.png'; frame.save(frame_path)
        inputs = ['-loop', '1', '-framerate', str(FPS), '-i', str(frame_path)]
        graph = f'[0:v]scale={scale},setsar=1,format=yuv420p[v]'
    run_command([config.ffmpeg_path(), '-y', *inputs, '-filter_complex', graph, '-map', '[v]',
        '-an', '-frames:v', str(frames), '-r', str(FPS), '-c:v', 'libx264', '-preset', 'fast',
        '-crf', '21', '-threads', '2', '-filter_complex_threads', '1', '-movflags', '+faststart', str(target)])
    return target


def render(script: Script, job_dir: Path, resolution='1080p', sources=None, assets=None, progress=None) -> Rendered:
    script = Script.model_validate(script.model_dump())
    job_dir.mkdir(parents=True, exist_ok=True)
    assets = assets or {}; total_frames = DURATION * FPS
    counts = [total_frames // len(script.scenes) + (i < total_frames % len(script.scenes)) for i in range(len(script.scenes))]
    segments = []; timeline = []; cursor = 0
    for i, (scene, count) in enumerate(zip(script.scenes, counts)):
        if progress: progress('render', 40 + int(i/len(script.scenes)*40), f'正在制作画面 {i+1}/{len(script.scenes)}，叠加简短标题。')
        asset = assets.get(scene.asset_id)
        if scene.asset_id and not asset: raise ValueError('镜头引用的素材不存在。')
        segments.append(encode_scene(scene, script, asset, job_dir, i, count, resolution))
        end = cursor + count / FPS
        timeline.append({'scene': i, 'start': cursor, 'end': end, 'asset_id': scene.asset_id,
                         'kind': asset['media_type'].split('/')[0] if asset else 'illustration', 'clip_start': scene.clip_start})
        cursor = end
    concat = job_dir / 'segments.txt'
    concat.write_text('\n'.join(f"file '{p.name}'" for p in segments), encoding='utf-8')
    video = job_dir / 'science-fieldnotes.mp4'
    run_command([config.ffmpeg_path(), '-y', '-f', 'concat', '-safe', '1', '-i', concat.name,
        '-map', '0:v:0', '-an', '-c:v', 'copy', '-movflags', '+faststart', video.name], cwd=job_dir)
    cover = job_dir / 'cover.jpg'
    run_command([config.ffmpeg_path(), '-y', '-i', str(video), '-frames:v', '1', '-q:v', '2', str(cover)])
    script_path = job_dir / 'script.json'; script_path.write_text(script.model_dump_json(indent=2), encoding='utf-8')
    manifest = job_dir / 'manifest.json'
    manifest.write_text(json.dumps({'format': 'visual-short-v1', 'video': video.name, 'cover': cover.name,
        'script': script_path.name, 'duration': DURATION, 'audio_mode': 'silent', 'title_lines': script.title_lines,
        'layout': {'title_position': 'top', 'brand_watermark': False, 'credits': 'delivery_files'},
        'timeline': timeline, 'sources': sources or [],
        'assets': [{k:v for k,v in asset.items() if k != 'path'} for asset in assets.values()],
        'visual_notice': '图片保持完整比例；视频不足分镜时长时定格最后一帧；timeline 中 illustration 为原创原理示意，非实拍且不按实际比例。'}, ensure_ascii=False, indent=2), encoding='utf-8')
    credits = '\n\n'.join('\n'.join(filter(None, [asset.get('filename'), asset.get('credit'), asset.get('source_url'), asset.get('rights')])) for asset in assets.values())
    if any(not scene.asset_id for scene in script.scenes):
        credits += '\n原创科学示意 · 非实拍 / 不按实际比例'
    (job_dir / 'description.txt').write_text(script.title+'\n\n'+'\n'.join(script.title_lines)+'\n\n'+script.description+'\n\n资料来源：\n'+'\n'.join(s['title']+'\n'+s['url'] for s in (sources or []))+'\n\n素材署名与说明：\n'+credits, encoding='utf-8')
    if progress: progress('quality', 90, '检查 10 秒时长、无音轨、画面解码与黑帧。')
    quality = qa(video)
    (job_dir / 'quality.json').write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding='utf-8')
    with zipfile.ZipFile(job_dir / 'delivery.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
        for file in [video, cover, script_path, manifest, job_dir/'description.txt', job_dir/'quality.json']:
            bundle.write(file, file.name)
    return Rendered(video, cover, script_path, manifest, DURATION, quality)


def qa(video: Path):
    result = run_command([config.ffmpeg_path(), '-hide_banner', '-i', str(video),
        '-map', '0:v:0', '-vf', 'blackdetect=d=0.4:pix_th=0.10:pic_th=0.98', '-f', 'null', '-'])
    duration = duration_from_log(result.stderr)
    checks = {'video_exists': video.stat().st_size > 5000, 'duration_seconds': duration,
        'duration_reasonable': abs(duration-DURATION) <= 1/FPS, 'expected_duration': DURATION,
        'audio_present': 'Audio:' in result.stderr, 'audio_mode': 'silent',
        'black_frames': len(re.findall('black_start:', result.stderr)), 'decoded': True,
        'human_checks': ['简短标题与原文一致', '图片或视频与选题相关', '素材使用权与署名正确']}
    checks['passed'] = bool(checks['video_exists'] and checks['duration_reasonable'] and not checks['audio_present'] and checks['black_frames'] == 0)
    return checks
