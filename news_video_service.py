import json
import re
import subprocess
import uuid
import wave
from pathlib import Path
from typing import Callable

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageOps

from news_images import publication_images
from siliconflow_client import SiliconFlowClient
from ttapi_veo_client import TTAPIVeoClient, TTAPIVeoError


ProgressCallback = Callable[[str, str, str], None] | None


class NewsVideoError(RuntimeError):
    pass


def _notify(callback: ProgressCallback, message: str, state: str) -> None:
    if callback:
        callback("AI 新闻视频", message, state)


def _plain_article(result: dict) -> tuple[str, str]:
    reviewer = result.get("reviewer_result", {})
    writer = result.get("writer_result", {})
    title = reviewer.get("final_title") or writer.get("title") or "新闻播报"
    article = reviewer.get("final_article") or writer.get("full_article", "")
    article = re.split(r"\n\s*来源：\s*\n", article, maxsplit=1)[0]
    article = re.sub(r"(?m)^#{1,6}\s*", "", article)
    article = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", article)
    article = re.sub(r"\s+", " ", article).strip()
    return str(title).strip(), article


def _target_characters(target_seconds: int) -> int:
    if target_seconds == 30:
        return 150
    if target_seconds == 60:
        return 280
    return 650


def build_broadcast_script(
    client: SiliconFlowClient,
    result: dict,
    target_seconds: int,
) -> tuple[str, str]:
    title, article = _plain_article(result)
    if not article:
        raise NewsVideoError("当前结果没有可用于播报的新闻正文")
    target_chars = _target_characters(target_seconds)
    duration_text = "完整播报" if target_seconds <= 0 else f"约{target_seconds}秒"
    system_prompt = (
        "你是中文电视新闻播音编辑。将已审校新闻稿改写为可直接朗读的播报稿。"
        "不得增加原稿没有的事实、数字、引语或身份判断；保留必要的待核实表述；"
        "去掉Markdown、链接、来源列表和编辑说明。句子应自然、简洁，数字适合口播。"
        "只返回JSON对象，字段为broadcast_title和broadcast_script。"
    )
    user_prompt = (
        f"目标时长：{duration_text}\n"
        f"建议正文长度：约{target_chars}个中文字符\n"
        f"新闻标题：{title}\n"
        f"已审校新闻稿：{article[:9000]}"
    )
    payload, _ = client.call_json_model(
        client.settings.chat_model,
        system_prompt,
        user_prompt,
        temperature=0.2,
        max_tokens=1800,
    )
    broadcast_title = re.sub(r"\s+", " ", str(payload.get("broadcast_title", ""))).strip()
    broadcast_script = re.sub(r"\s+", " ", str(payload.get("broadcast_script", ""))).strip()
    if not broadcast_script:
        raise NewsVideoError("播报稿模型没有返回有效正文")
    return broadcast_title or title, broadcast_script


def split_broadcast_script(text: str, max_chars: int = 26) -> list[str]:
    sentences = [
        item.strip()
        for item in re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
        if item.strip()
    ]
    segments: list[str] = []
    for sentence in sentences:
        current = sentence
        while len(current) > max_chars:
            split_at = max(
                current.rfind(mark, 0, max_chars + 1)
                for mark in ["，", "、", ",", " "]
            )
            if split_at < max_chars // 2:
                split_at = max_chars
            else:
                split_at += 1
            segments.append(current[:split_at].strip())
            current = current[split_at:].strip()
        if current:
            segments.append(current)
    return segments or [text.strip()]


def subtitle_entries(text: str, duration: float) -> list[dict]:
    segments = split_broadcast_script(text)
    weights = [max(1, len(re.sub(r"\s+", "", item))) for item in segments]
    total_weight = sum(weights)
    cursor = 0.0
    entries = []
    for index, (segment, weight) in enumerate(zip(segments, weights), 1):
        end = duration if index == len(segments) else cursor + duration * weight / total_weight
        entries.append(
            {
                "index": index,
                "start": cursor,
                "end": end,
                "duration": max(0.04, end - cursor),
                "text": segment,
            }
        )
        cursor = end
    return entries


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def write_srt(entries: list[dict], output_path: Path) -> None:
    blocks = []
    for item in entries:
        blocks.append(
            f"{item['index']}\n{_srt_time(item['start'])} --> "
            f"{_srt_time(item['end'])}\n{item['text']}"
        )
    output_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def _run_ffmpeg(arguments: list[str], cwd: Path) -> None:
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", *arguments]
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "未知错误")[-1200:]
        raise NewsVideoError(f"FFmpeg 合成失败：{detail.strip()}")


def convert_speech_to_wav(source_path: Path, output_path: Path) -> None:
    _run_ffmpeg(
        ["-y", "-i", source_path.name, "-ac", "1", "-ar", "24000", output_path.name],
        source_path.parent,
    )


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        frame_rate = audio.getframerate()
        if not frame_rate:
            raise NewsVideoError("生成的语音没有有效采样率")
        return audio.getnframes() / frame_rate


def _font(size: int, bold: bool = False):
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _cover_image(path: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def render_news_frame(
    output_path: Path,
    size: tuple[int, int],
    title: str,
    subtitle: str,
    image_record: dict | None,
    anchor_path: Path | None,
) -> None:
    width, height = size
    if image_record:
        canvas = _cover_image(Path(image_record["path"]), size)
    else:
        canvas = Image.new("RGB", size, "#173b30")
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((0, 0, width, height), fill=(4, 20, 16, 42))

    if anchor_path:
        portrait_width = int(width * (0.30 if width > height else 0.42))
        portrait_height = int(height * (0.72 if width > height else 0.40))
        portrait = _cover_image(anchor_path, (portrait_width, portrait_height))
        portrait = portrait.convert("RGBA")
        x = width - portrait_width - int(width * 0.045)
        y = int(height * (0.12 if width > height else 0.08))
        overlay_draw.rounded_rectangle(
            (x - 8, y - 8, x + portrait_width + 8, y + portrait_height + 8),
            radius=18,
            fill=(248, 248, 241, 225),
        )
        overlay.alpha_composite(portrait, (x, y))

    lower_top = int(height * 0.70)
    overlay_draw.rectangle((0, lower_top, width, height), fill=(7, 28, 22, 225))
    overlay_draw.rectangle((0, lower_top, int(width * 0.018), height), fill=(216, 232, 98, 255))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(canvas)

    small_font = _font(max(20, int(height * 0.027)), bold=True)
    title_font = _font(max(28, int(height * 0.045)), bold=True)
    subtitle_font = _font(max(32, int(height * 0.055)), bold=True)
    margin = int(width * 0.045)
    draw.text((margin, int(height * 0.045)), "2026 WORLD CUP NEWSROOM", font=small_font, fill="#D8E862")
    title_width = int(width * (0.58 if anchor_path and width > height else 0.88))
    title_lines = _wrap_text(draw, title, title_font, title_width)[:2]
    title_y = int(height * 0.105)
    for line in title_lines:
        draw.text((margin, title_y), line, font=title_font, fill="white", stroke_width=1, stroke_fill="#173b30")
        title_y += int(height * 0.060)

    subtitle_lines = _wrap_text(draw, subtitle, subtitle_font, width - margin * 2)[:2]
    line_height = int(height * 0.075)
    subtitle_y = lower_top + int((height - lower_top - line_height * len(subtitle_lines)) / 2)
    for line in subtitle_lines:
        draw.text((margin, subtitle_y), line, font=subtitle_font, fill="white")
        subtitle_y += line_height

    if image_record:
        if image_record.get("kind") == "source":
            disclosure = f"图片来源：{image_record.get('credit') or '用户提供'}"
        else:
            disclosure = image_record.get("ai_disclosure") or "AI生成示意图"
        disclosure_font = _font(max(16, int(height * 0.020)))
        text_width = draw.textlength(disclosure, font=disclosure_font)
        draw.text(
            (width - margin - text_width, height - int(height * 0.035)),
            disclosure,
            font=disclosure_font,
            fill="#D8E862",
        )
    canvas.convert("RGB").save(output_path, format="PNG", optimize=True)


def compose_video(
    work_dir: Path,
    entries: list[dict],
    frame_paths: list[Path],
    audio_path: Path,
    output_path: Path,
) -> None:
    concat_path = work_dir / "frames.txt"
    lines: list[str] = []
    for entry, frame_path in zip(entries, frame_paths):
        lines.append(f"file '{frame_path.name}'")
        lines.append(f"duration {entry['duration']:.6f}")
    lines.append(f"file '{frame_paths[-1].name}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _run_ffmpeg(
        [
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_path.name,
            "-i",
            audio_path.name,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-r",
            "25",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            output_path.name,
        ],
        work_dir,
    )
    if not output_path.is_file() or output_path.stat().st_size < 1024:
        raise NewsVideoError("FFmpeg 没有生成有效的视频文件")


def compose_veo_video(
    work_dir: Path,
    clip_paths: list[Path],
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    size: tuple[int, int],
    duration: float,
) -> None:
    if not clip_paths:
        raise NewsVideoError("没有可用于合成的 Veo 视频片段")
    concat_path = work_dir / "veo_clips.txt"
    concat_path.write_text(
        "\n".join(f"file '{path.name}'" for path in clip_paths) + "\n",
        encoding="utf-8",
    )
    broll_path = work_dir / "veo_broll.mp4"
    width, height = size
    _run_ffmpeg(
        [
            "-y",
            "-stream_loop",
            "-1",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_path.name,
            "-t",
            f"{duration:.3f}",
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=25",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            broll_path.name,
        ],
        work_dir,
    )
    subtitle_filter = (
        "subtitles=subtitles.srt:charenc=UTF-8:"
        "force_style='FontName=Microsoft YaHei,FontSize=24,Alignment=2,MarginV=30,Outline=2',"
        "drawtext=text='AI GENERATED MATCH REENACTMENT':x=20:y=20:fontsize=18:"
        "fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=8"
    )
    _run_ffmpeg(
        [
            "-y",
            "-i",
            broll_path.name,
            "-i",
            audio_path.name,
            "-vf",
            subtitle_filter,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            output_path.name,
        ],
        work_dir,
    )
    if not output_path.is_file() or output_path.stat().st_size < 1024:
        raise NewsVideoError("FFmpeg 没有生成有效的 Veo 新闻视频")


def build_veo_prompts(title: str, script: str, clip_count: int) -> list[str]:
    segments = split_broadcast_script(script, max_chars=90)
    selected = [segments[min(index * len(segments) // clip_count, len(segments) - 1)] for index in range(clip_count)]
    prompts = []
    for index, segment in enumerate(selected, 1):
        prompts.append(
            "Cinematic football match reenactment for a news package, "
            "dynamic broadcast camera, natural stadium lighting, realistic ball motion, "
            "diverse generic football players, no logos, no identifiable real athletes, "
            "no text, no scoreboard, no watermark. "
            f"Scene {index} inspired by this news context: {title}. {segment}"
        )
    return prompts


def generate_veo_clips(
    settings,
    work_dir: Path,
    title: str,
    script: str,
    aspect_ratio: str,
    model: str,
    clip_count: int,
    progress_callback: ProgressCallback,
) -> list[Path]:
    client = TTAPIVeoClient(settings)
    clips: list[Path] = []
    for index, prompt in enumerate(build_veo_prompts(title, script, clip_count), 1):
        _notify(progress_callback, f"正在提交 Veo 比赛镜头 {index}/{clip_count}", "running")
        job_id = client.create_video(prompt, aspect_ratio, model)
        _notify(progress_callback, f"Veo 镜头 {index}/{clip_count} 正在生成", "running")
        video_url, _ = client.poll_until_ready(job_id)
        clip_path = work_dir / f"veo_clip_{index:02}.mp4"
        client.download_video(video_url, clip_path)
        clips.append(clip_path)
        _notify(progress_callback, f"Veo 镜头 {index}/{clip_count} 已完成", "completed")
    return clips


def create_news_video(
    settings,
    result: dict,
    aspect_ratio: str = "16:9",
    target_seconds: int = 60,
    voice: str = "",
    speed: float = 1.0,
    visual_mode: str = "newsroom",
    veo_model: str = "veo-3.1-fast",
    veo_clip_count: int = 1,
    progress_callback: ProgressCallback = None,
) -> dict:
    run_dir = Path(result.get("run_dir", ""))
    if not run_dir.is_dir():
        raise NewsVideoError("新闻运行目录不存在，无法生成视频")
    work_dir = run_dir / "video" / uuid.uuid4().hex[:10]
    work_dir.mkdir(parents=True, exist_ok=False)
    client = SiliconFlowClient(settings)

    _notify(progress_callback, "正在把新闻稿改写为播报稿", "running")
    title, script = build_broadcast_script(client, result, target_seconds)
    script_path = work_dir / "broadcast_script.txt"
    script_path.write_text(f"{title}\n\n{script}\n", encoding="utf-8")
    _notify(progress_callback, "播报稿已生成", "completed")

    speech_path = work_dir / "narration.mp3"
    _notify(progress_callback, "正在生成 AI 主播语音", "running")
    client.synthesize_speech(script, speech_path, voice=voice, speed=speed)
    wav_path = work_dir / "narration.wav"
    convert_speech_to_wav(speech_path, wav_path)
    duration = wav_duration(wav_path)
    _notify(progress_callback, f"主播语音已生成，共 {duration:.1f} 秒", "completed")

    entries = subtitle_entries(script, duration)
    subtitle_path = work_dir / "subtitles.srt"
    write_srt(entries, subtitle_path)
    _notify(progress_callback, f"已生成 {len(entries)} 条同步字幕", "completed")

    size = (1280, 720) if aspect_ratio == "16:9" else (720, 1280)
    image_records = publication_images(result, run_dir)
    output_path = work_dir / "news_video.mp4"
    veo_clips: list[Path] = []
    veo_error = ""
    if visual_mode == "veo":
        try:
            veo_clips = generate_veo_clips(
                settings,
                work_dir,
                title,
                script,
                aspect_ratio,
                veo_model,
                max(1, min(3, int(veo_clip_count))),
                progress_callback,
            )
            _notify(progress_callback, "正在合成 Veo 比赛镜头、配音和字幕", "running")
            compose_veo_video(
                work_dir, veo_clips, wav_path, subtitle_path, output_path, size, duration
            )
        except (TTAPIVeoError, TimeoutError, OSError, NewsVideoError) as error:
            veo_error = str(error)
            _notify(progress_callback, "Veo 镜头不可用，已切换为新闻版式", "failed")

    if not output_path.is_file():
        frame_paths: list[Path] = []
        _notify(progress_callback, "正在编排新闻画面和字幕", "running")
        for index, entry in enumerate(entries):
            frame_path = work_dir / f"frame_{index:04d}.png"
            image_record = image_records[index % len(image_records)] if image_records else None
            render_news_frame(
                frame_path, size, title, entry["text"], image_record, None
            )
            frame_paths.append(frame_path)
        compose_video(work_dir, entries, frame_paths, wav_path, output_path)
    _notify(progress_callback, "AI 新闻视频已生成", "completed")
    return {
        "title": title,
        "script": script,
        "aspect_ratio": aspect_ratio,
        "target_seconds": target_seconds,
        "duration_seconds": round(duration, 3),
        "voice": voice or settings.tts_voice,
        "video_path": str(output_path),
        "audio_path": str(speech_path),
        "subtitle_path": str(subtitle_path),
        "script_path": str(script_path),
        "visual_mode": "veo" if veo_clips and not veo_error else "newsroom",
        "veo_model": veo_model if veo_clips else "",
        "veo_clip_paths": [str(path) for path in veo_clips],
        "veo_error": veo_error,
        "image_count": len(image_records),
    }


def persist_video_result(run_dir: Path, video: dict) -> None:
    result_path = run_dir / "result.json"
    if not result_path.is_file():
        raise FileNotFoundError(f"找不到结果文件：{result_path}")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    payload["video"] = video
    result_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
