#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量视频拼接小工具

功能：
- 文件夹 A：视频片段 A
- 文件夹 B：视频片段 B（可调节亮度）
- 字幕文件夹：若干 .srt 字幕文件
- 音频文件夹：若干音频文件（mp3/wav 等）

处理逻辑（按文件名排序后逐一配对）：
- 取第 i 个 A 视频 + 第 i 个 B 视频 → 先 A 后 B 进行拼接
- 取第 i 个字幕文件 + 第 i 个音频文件
- 将字幕与音频叠加到拼接后的视频上
- 导出到目标输出文件夹

依赖：
    pip install moviepy pysrt

示例：
    python concat_videos_with_subtitles.py \
        --folder-a /path/to/A \
        --folder-b /path/to/B \
        --subtitles /path/to/subs \
        --audios /path/to/audios \
        --output /path/to/output \
        --brightness-b 1.2 \
        --font-size 48 \
        --subtitle-position bottom
"""

import argparse
import os
import re
from pathlib import Path
from typing import List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
# 兼容 Pillow 10+ 移除 ANTIALIAS 的问题
try:
    if not hasattr(Image, "ANTIALIAS") and hasattr(Image, "Resampling"):
        Image.ANTIALIAS = Image.Resampling.LANCZOS
        Image.BICUBIC = Image.Resampling.BICUBIC
        Image.BILINEAR = Image.Resampling.BILINEAR
except Exception:
    pass

# 优先指定本机的 ImageMagick 二进制，避免 TextClip 使用 pillow 路径导致字体错误
_MAGICK_CANDIDATES = [
    "/opt/homebrew/bin/magick",  # macOS (Homebrew, Apple Silicon 常见)
    "/usr/local/bin/magick",     # macOS Intel 常见
    "/usr/bin/magick",           # Linux 常见
]
for _bin in _MAGICK_CANDIDATES:
    if os.path.exists(_bin):
        os.environ["IMAGEMAGICK_BINARY"] = _bin
        break

PREFERRED_FONT_NAMES = [
    "Sylfaen",
    "Palatino Linotype",
    "Mongolian Baiti",
    "Arial",
    "Arial Unicode",
    "DejaVuSans",
    "FreeSans",
]

from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    concatenate_videoclips,
    CompositeVideoClip,
    TextClip,
    ImageClip,
    vfx,
)
import pysrt


def list_files_sorted(folder: Path, exts: Tuple[str, ...]) -> List[Path]:
    """按文件名排序列出指定后缀的文件。"""
    if not folder.exists():
        raise FileNotFoundError(f"文件夹不存在: {folder}")
    files = [
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in exts
    ]
    return sorted(files, key=lambda p: p.name)


def load_subtitles(srt_path: Path):
    """将 .srt 文件转换为 SubtitlesClip 可用的格式。"""
    subs = pysrt.open(str(srt_path), encoding="utf-8")
    entries = []
    for item in subs:
        start = item.start.ordinal / 1000.0  # ms → s
        end = item.end.ordinal / 1000.0
        text = item.text.replace("\n", " ")
        entries.append(((start, end), text))
    return entries


def find_default_font() -> str:
    """寻找可用字体路径，优先指定的字体列表。"""
    candidates: list[str] = []
    for name in PREFERRED_FONT_NAMES:
        base = name.replace(" ", "")
        candidates.extend(
            [
                f"/System/Library/Fonts/Supplemental/{name}.ttf",
                f"/System/Library/Fonts/Supplemental/{name}.otf",
                f"/System/Library/Fonts/{name}.ttf",
                f"/Library/Fonts/{name}.ttf",
                f"/Library/Fonts/{name}.otf",
                f"/usr/share/fonts/truetype/{base.lower()}/{name}.ttf",
                f"/usr/share/fonts/truetype/{name}.ttf",
                f"/usr/share/fonts/{name}.ttf",
                f"C:\\Windows\\Fonts\\{name}.ttf",
                f"C:\\Windows\\Fonts\\{name}.otf",
            ]
        )
    # 兜底旧路径
    candidates.extend(
        [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\ARIALUNI.TTF",
        ]
    )
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""


def apply_brightness(clip, factor: float):
    """调节亮度；使用 moviepy 1.0.3 的 clip.fx(vfx.colorx, factor)。"""
    factor = round(float(factor), 1)
    if factor == 1.0:
        return clip
    try:
        return clip.fx(vfx.colorx, factor)
    except Exception:
        print("亮度调整未生效：clip.fx(vfx.colorx) 调用失败。")
        return clip


def apply_color_adjustments(
    clip,
    exposure: float = 0.0,       # 正数变亮，负数变暗（以 0.1 为步进）
    contrast: float = 1.0,       # 1.0 不变
    saturation: float = 1.0,     # 1.0 不变
    temperature: float = 0.0,    # -1.0 冷色，+1.0 暖色
    sharpness: float = 1.0,      # 1.0 不变
):
    """基于 Pillow 的简单调色，使用 clip.fl_image 应用于每帧。"""
    exposure = round(float(exposure), 1)
    contrast = round(float(contrast), 1)
    saturation = round(float(saturation), 1)
    temperature = round(float(temperature), 1)
    sharpness = round(float(sharpness), 1)
    if (
        exposure == 0.0
        and contrast == 1.0
        and saturation == 1.0
        and temperature == 0.0
        and sharpness == 1.0
    ):
        return clip

    def _fn(frame):
        img = Image.fromarray(frame)
        # 曝光：用亮度增强模拟，按 1 + exposure*0.5 计算
        if exposure != 0.0:
            factor = max(0.0, 1.0 + exposure * 0.5)
            img = ImageEnhance.Brightness(img).enhance(factor)
        if contrast != 1.0:
            img = ImageEnhance.Contrast(img).enhance(contrast)
        if saturation != 1.0:
            img = ImageEnhance.Color(img).enhance(saturation)
        if sharpness != 1.0:
            img = ImageEnhance.Sharpness(img).enhance(sharpness)
        if temperature != 0.0:
            # 简单按通道系数调整 R/B，G 基本不动
            r_mul = 1.0 + max(0.0, temperature) * 0.3
            b_mul = 1.0 + max(0.0, -temperature) * 0.3
            r = img.getchannel("R").point(lambda x: max(0, min(255, int(x * r_mul))))
            g = img.getchannel("G")
            b = img.getchannel("B").point(lambda x: max(0, min(255, int(x * b_mul))))
            img = Image.merge("RGB", (r, g, b))
        return np.array(img)

    return clip.fl_image(_fn)


def build_subtitles_clip_pil(
    srt_path: Path,
    video_size: Tuple[int, int],
    font_size: int = 48,
    color: str = "white",
    stroke_color: str = "black",
    stroke_width: int = 0,
    subtitle_position: str = "bottom",  # bottom/top/center/custom
    subtitle_pos_xy: Tuple[float, float] = (0.5, 0.85),
    font_path: "str | None" = None,
):
    """
    使用 PIL 手工渲染字幕，避免 TextClip 在部分环境下的字体兼容问题。
    返回一个 CompositeVideoClip。
    """
    entries = load_subtitles(srt_path)
    # 优先使用参数/环境变量指定的字体
    env_font = os.environ.get("SUBTITLE_FONT_PATH", "").strip()
    chosen_font = font_path or env_font
    if chosen_font:
        if not os.path.exists(chosen_font):
            raise RuntimeError(f"指定的字体文件不存在: {chosen_font}")
    else:
        chosen_font = find_default_font()
        if not chosen_font:
            raise RuntimeError(
                "未找到可用的系统字体，请安装/指定常见字体（例如 Sylfaen/Palatino/MongolianBaiti/Arial/DejaVuSans），"
                "或在代码中通过 --font-path 指定字体文件路径。"
            )

    font = ImageFont.truetype(chosen_font, font_size)

    def wrap_text_by_width(txt: str, max_width: int) -> str:
        """按宽度自动换行（支持中英文混排）。"""
        temp_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        lines = []
        current = ""
        for ch in txt:
            test = current + ch
            w = temp_draw.textbbox((0, 0), test, font=font, stroke_width=stroke_width)[2]
            if w > max_width and current:
                lines.append(current)
                current = ch
            else:
                current = test
        if current:
            lines.append(current)
        return "\n".join(lines)

    def format_text(txt: str) -> str:
        # 每个单词首字母大写（保留空白分隔）
        parts = re.split(r"(\s+)", txt)
        def _cap(token: str) -> str:
            return token[:1].upper() + token[1:] if token and not token.isspace() else token
        return "".join(_cap(p) for p in parts)

    clips = []
    vw, vh = video_size
    margin = int(font_size * 0.6)
    max_line_width = int(vw * 0.8)  # 预留 20% 边距，适配 9:16 竖屏

    for (start, end), text in entries:
        duration = max(0.01, end - start)
        text_wrapped = wrap_text_by_width(format_text(text), max_line_width)

        # 估算高度：按行数 * 行高 + 上下 margin
        lines_count = text_wrapped.count("\n") + 1
        # stroke_width 强制 0，避免黑色描边
        effective_stroke = 0
        line_h = font_size + effective_stroke * 2
        img_h = lines_count * line_h + margin * 2
        img = Image.new("RGBA", (vw, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        y = margin
        for line in text_wrapped.split("\n"):
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=effective_stroke)
            tw = bbox[2] - bbox[0]
            x = (vw - tw) // 2
            draw.text((x, y), line, font=font, fill=color)
            y += line_h

        clip = ImageClip(np.array(img)).set_duration(duration).set_start(start)
        if subtitle_position == "top":
            clip = clip.set_position(("center", "top"))
        elif subtitle_position == "center":
            clip = clip.set_position(("center", "center"))
        elif subtitle_position == "custom":
            x_rel, y_rel = subtitle_pos_xy
            x_px = int(vw * x_rel)
            y_px = int(vh * y_rel)
            clip = clip.set_position((x_px, y_px))
        else:
            clip = clip.set_position(("center", "bottom"))
        clips.append(clip)

    return CompositeVideoClip(clips, size=video_size)


def main():
    parser = argparse.ArgumentParser(description="批量视频拼接 + 字幕 + 音频")
    parser.add_argument("--folder-a", required=True, help="视频文件夹 A 路径")
    parser.add_argument("--folder-b", required=True, help="视频文件夹 B 路径")
    parser.add_argument("--subtitles", required=True, help="字幕文件夹（srt）路径")
    parser.add_argument("--audios", required=True, help="音频文件夹路径（mp3/wav 等）")
    parser.add_argument("--output", required=True, help="输出视频文件夹路径")

    parser.add_argument(
        "--brightness-b",
        type=float,
        default=1.0,
        help="视频 B 亮度系数（>1 变亮，<1 变暗，默认 1.0 不变）",
    )
    parser.add_argument("--exposure", type=float, default=0.0, help="曝光，正数整体变亮，负数整体变暗（步进 0.1）")
    parser.add_argument("--contrast", type=float, default=1.0, help="对比度，>1 更硬朗，<1 更柔和（步进 0.1，1 不变）")
    parser.add_argument("--saturation", type=float, default=1.0, help="饱和度，>1 更鲜艳，<1 更灰（步进 0.1，1 不变）")
    parser.add_argument("--temperature", type=float, default=0.0, help="色温，-1 偏冷，+1 偏暖（步进 0.1）")
    parser.add_argument("--sharpness", type=float, default=1.0, help="锐度，>1 更锐利，<1 更柔（步进 0.1，1 不变）")
    parser.add_argument(
        "--font-size",
        type=int,
        default=48,
        help="字幕字体大小（默认 48）",
    )
    parser.add_argument(
        "--font-path",
        type=str,
        default=None,
        help="字体文件路径（.ttf/.otf）。未指定则按 PREFERRED_FONT_NAMES 自动查找，可用环境变量 SUBTITLE_FONT_PATH 覆盖。",
    )
    parser.add_argument(
        "--subtitle-position",
        choices=["bottom", "top", "center", "custom"],
        default="bottom",
        help="字幕位置：bottom/top/center/custom（默认 bottom；custom 需配合 --subtitle-pos-x/y）",
    )
    parser.add_argument(
        "--subtitle-pos-x",
        type=float,
        default=0.5,
        help="subtitle-position=custom 时，字幕相对 X 位置（0-1，默认 0.5）",
    )
    parser.add_argument(
        "--subtitle-pos-y",
        type=float,
        default=0.85,
        help="subtitle-position=custom 时，字幕相对 Y 位置（0-1，默认 0.85）",
    )
    args = parser.parse_args()

    folder_a = Path(args.folder_a).expanduser().resolve()
    folder_b = Path(args.folder_b).expanduser().resolve()
    folder_subs = Path(args.subtitles).expanduser().resolve()
    folder_audios = Path(args.audios).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    video_exts = (".mp4", ".mov", ".mkv", ".avi")
    audio_exts = (".mp3", ".wav", ".m4a", ".aac")

    videos_a = list_files_sorted(folder_a, video_exts)
    videos_b = list_files_sorted(folder_b, video_exts)
    subs_files = list_files_sorted(folder_subs, (".srt",))
    audio_files = list_files_sorted(folder_audios, audio_exts)

    if not videos_a or not videos_b or not subs_files or not audio_files:
        raise RuntimeError("A/B 视频、字幕、音频文件夹都需要至少各有 1 个文件。")

    print(f"发现 A 视频 {len(videos_a)} 个, B 视频 {len(videos_b)} 个, 字幕 {len(subs_files)} 个, 音频 {len(audio_files)} 个")
    combo_idx = 0

    for ia, va in enumerate(videos_a):
        for ib, vb in enumerate(videos_b):
            srt_path = subs_files[combo_idx % len(subs_files)]
            audio_path = audio_files[combo_idx % len(audio_files)]

            combo_idx += 1
            print(f"\n=== 处理第 {combo_idx} 组 ===")
            print(f"A 视频: {va}")
            print(f"B 视频: {vb}")
            print(f"字幕:   {srt_path}")
            print(f"音频:   {audio_path}")

            # 加载视频
            clip_a = VideoFileClip(str(va))
            clip_b = VideoFileClip(str(vb))

            # 调整 B 亮度
            if args.brightness_b != 1.0:
                clip_b = apply_brightness(clip_b, args.brightness_b)

            # 尺寸统一（将 B 缩放到 A 的尺寸）
            if clip_b.size != clip_a.size:
                clip_b = clip_b.resize(clip_a.size)

            # 拼接视频：A + B
            merged_clip = concatenate_videoclips([clip_a, clip_b])

            # 颜色调整（应用在整体拼接后的视频上）
            merged_clip = apply_color_adjustments(
                merged_clip,
                exposure=args.exposure,
                contrast=args.contrast,
                saturation=args.saturation,
                temperature=args.temperature,
                sharpness=args.sharpness,
            )

            # 加载音频
            audio_clip = AudioFileClip(str(audio_path))
            # 以音频时长为总时长，视频若更长则截断到音频时长
            target_duration = min(merged_clip.duration, audio_clip.duration)
            merged_clip = merged_clip.subclip(0, target_duration)
            audio_clip = audio_clip.subclip(0, target_duration)
            # moviepy 1.0.3 使用 set_audio
            merged_clip = merged_clip.set_audio(audio_clip)

            # 构建字幕（使用 PIL 渲染，避免 TextClip 字体兼容问题）
            subtitles = build_subtitles_clip_pil(
                srt_path,
                video_size=merged_clip.size,
                font_size=args.font_size,
                color="white",
                stroke_color="black",
                stroke_width=2,
                subtitle_position=args.subtitle_position,
                subtitle_pos_xy=(args.subtitle_pos_x, args.subtitle_pos_y),
                font_path=args.font_path,
            ).set_duration(merged_clip.duration)

            # 将字幕叠加到视频
            final_clip = CompositeVideoClip([merged_clip, subtitles])

            # 输出文件名：ia_ib_原始A_B.mp4
            base_name = f"{ia+1:03d}_{ib+1:03d}_{va.stem}_{vb.stem}"
            out_path = output_dir / f"{base_name}.mp4"

            print(f"导出到: {out_path}")
            # 使用较兼容的设置导出
            # 禁用进度条（logger=None），避免在打包后 GUI 应用中 tqdm 写入 None 的 sys.stdout
            final_clip.write_videofile(
                str(out_path),
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=str(output_dir / f".temp_audio_{combo_idx}.m4a"),
                remove_temp=True,
                threads=os.cpu_count() or 4,
                fps=merged_clip.fps,
                logger=None,  # 禁用进度条
            )

            # 释放资源
            final_clip.close()
            merged_clip.close()
            clip_a.close()
            clip_b.close()
            audio_clip.close()

    print("\n全部处理完成。")


if __name__ == "__main__":
    main()


