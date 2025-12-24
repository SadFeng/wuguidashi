def apply_brightness(clip, factor: float):
    """调节亮度；moviepy 1.0.3 使用 clip.fx(vfx.colorx, factor)"""
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
    exposure: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    temperature: float = 0.0,
    sharpness: float = 1.0,
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
            r_mul = 1.0 + max(0.0, temperature) * 0.3
            b_mul = 1.0 + max(0.0, -temperature) * 0.3
            r = img.getchannel("R").point(lambda x: max(0, min(255, int(x * r_mul))))
            g = img.getchannel("G")
            b = img.getchannel("B").point(lambda x: max(0, min(255, int(x * b_mul))))
            img = Image.merge("RGB", (r, g, b))
        return np.array(img)

    return clip.fl_image(_fn)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可视化批量视频拼接工具

功能（与 concat_videos_with_subtitles.py 相同）：
- A 文件夹：视频片段 A
- B 文件夹：视频片段 B（可调节亮度）
- 字幕文件夹：.srt
- 音频文件夹：mp3/wav 等
- 输出到指定文件夹

依赖：
    pip install moviepy pysrt
还需要 ffmpeg 在 PATH 中可用（MoviePy 调用）。
字幕渲染使用 TextClip，部分环境需要安装 ImageMagick（macOS: brew install imagemagick；
Ubuntu: sudo apt-get install -y imagemagick fonts-dejavu-core）。
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import List, Tuple
import re
import json

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


# ---------------------- 复用的基础函数 ---------------------- #
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
    """寻找一个可用的系统字体路径，优先指定的字体列表。"""
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
    """使用 PIL 渲染字幕，避免 TextClip 字体兼容问题，返回 CompositeVideoClip。"""
    entries = load_subtitles(srt_path)
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
                "或在 GUI/环境变量中指定字体文件路径。"
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

        # 强制无描边
        effective_stroke = 0
        lines_count = text_wrapped.count("\n") + 1
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


def process_batch(
    folder_a: Path,
    folder_b: Path,
    folder_subs: Path,
    folder_audios: Path,
    output_dir: Path,
    brightness_b: float = 1.0,
    font_size: int = 48,
    subtitle_position: str = "bottom",  # bottom/top/center/custom
    subtitle_pos_xy: Tuple[float, float] = (0.5, 0.85),
    font_path: "str | None" = None,
    exposure: float = 0.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
    temperature: float = 0.0,
    sharpness: float = 1.0,
    logger=None,
):
    """批量处理核心逻辑。"""
    def log(msg: str):
        if logger:
            logger(msg)
        else:
            print(msg)

    video_exts = (".mp4", ".mov", ".mkv", ".avi")
    audio_exts = (".mp3", ".wav", ".m4a", ".aac")

    videos_a = list_files_sorted(folder_a, video_exts)
    videos_b = list_files_sorted(folder_b, video_exts)
    subs_files = list_files_sorted(folder_subs, (".srt",))
    audio_files = list_files_sorted(folder_audios, audio_exts)

    if not videos_a or not videos_b or not subs_files or not audio_files:
        raise RuntimeError("A/B 视频、字幕、音频文件夹都需要至少各有 1 个文件。")

    log(f"发现 A 视频 {len(videos_a)} 个, B 视频 {len(videos_b)} 个, 字幕 {len(subs_files)} 个, 音频 {len(audio_files)} 个")
    combo_idx = 0

    output_dir.mkdir(parents=True, exist_ok=True)

    for ia, va in enumerate(videos_a):
        for ib, vb in enumerate(videos_b):
            srt_path = subs_files[combo_idx % len(subs_files)]
            audio_path = audio_files[combo_idx % len(audio_files)]

            combo_idx += 1
            log(f"\n=== 处理第 {combo_idx} 组 ===")
            log(f"A 视频: {va.name}")
            log(f"B 视频: {vb.name}")
            log(f"字幕:   {srt_path.name}")
            log(f"音频:   {audio_path.name}")

            # 加载视频
            clip_a = VideoFileClip(str(va))
            clip_b = VideoFileClip(str(vb))

            # 调整 B 亮度
            if brightness_b != 1.0:
                clip_b = apply_brightness(clip_b, brightness_b)

            # 尺寸统一（将 B 缩放到 A 的尺寸）
            if clip_b.size != clip_a.size:
                clip_b = clip_b.resize(clip_a.size)

            # 拼接视频：A + B
            merged_clip = concatenate_videoclips([clip_a, clip_b])

            # 调色
            merged_clip = apply_color_adjustments(
                merged_clip,
                exposure=exposure,
                contrast=contrast,
                saturation=saturation,
                temperature=temperature,
                sharpness=sharpness,
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
                font_size=font_size,
                color="white",
                stroke_color="black",
                stroke_width=2,
                subtitle_position=subtitle_position,
                subtitle_pos_xy=subtitle_pos_xy,
                font_path=font_path,
            ).set_duration(merged_clip.duration)

            # 将字幕叠加到视频
            final_clip = CompositeVideoClip([merged_clip, subtitles])

            # 输出文件名：ia_ib_原始A_B.mp4
            base_name = f"{ia+1:03d}_{ib+1:03d}_{va.stem}_{vb.stem}"
            out_path = output_dir / f"{base_name}.mp4"

            log(f"导出到: {out_path}")
            final_clip.write_videofile(
                str(out_path),
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=str(output_dir / f".temp_audio_{combo_idx}.m4a"),
                remove_temp=True,
                threads=os.cpu_count() or 4,
                fps=merged_clip.fps,
            )

            # 释放资源
            final_clip.close()
            merged_clip.close()
            clip_a.close()
            clip_b.close()
            audio_clip.close()

    log("\n全部处理完成。")


# ---------------------- 简易 GUI ---------------------- #
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("批量视频拼接（A+B + 字幕 + 音频）")
        self.geometry("720x520")
        self.config_path = Path.home() / ".video_concat_gui_config.json"

        # 变量
        self.var_folder_a = tk.StringVar()
        self.var_folder_b = tk.StringVar()
        self.var_subs = tk.StringVar()
        self.var_audios = tk.StringVar()
        self.var_output = tk.StringVar()
        self.var_brightness = tk.DoubleVar(value=1.0)
        self.var_font_size = tk.IntVar(value=48)
        self.var_position = tk.StringVar(value="bottom")
        self.var_pos_x = tk.DoubleVar(value=0.5)
        self.var_pos_y = tk.DoubleVar(value=0.85)
        self.var_font_path = tk.StringVar()
        self.var_exposure = tk.DoubleVar(value=0.0)
        self.var_contrast = tk.DoubleVar(value=1.0)
        self.var_saturation = tk.DoubleVar(value=1.0)
        self.var_temperature = tk.DoubleVar(value=0.0)
        self.var_sharpness = tk.DoubleVar(value=1.0)

        self._build_ui()
        self._load_config()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        def row(label, var, btn_text="选择"):
            frame = ttk.Frame(self)
            frame.pack(fill="x", **pad)
            ttk.Label(frame, text=label, width=16, anchor="w").pack(side="left")
            entry = ttk.Entry(frame, textvariable=var)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
            ttk.Button(frame, text=btn_text, command=lambda v=var: self._choose_dir(v)).pack(side="left")

        def row_file(label, var, btn_text="选择文件"):
            frame = ttk.Frame(self)
            frame.pack(fill="x", **pad)
            ttk.Label(frame, text=label, width=16, anchor="w").pack(side="left")
            entry = ttk.Entry(frame, textvariable=var)
            entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
            ttk.Button(
                frame,
                text=btn_text,
                command=lambda v=var: self._choose_file(v),
            ).pack(side="left")

        row("A 视频文件夹", self.var_folder_a)
        row("B 视频文件夹", self.var_folder_b)
        row("字幕文件夹 (.srt)", self.var_subs)
        row("音频文件夹", self.var_audios)
        row("输出文件夹", self.var_output, btn_text="选择/创建")
        row_file("字体文件 (.ttf/.otf 可选)", self.var_font_path, btn_text="选择文件")

        # 亮度、字体、字幕位置
        frame_opt = ttk.Frame(self)
        frame_opt.pack(fill="x", **pad)

        ttk.Label(frame_opt, text="B 亮度").grid(row=0, column=0, sticky="w")
        ttk.Scale(frame_opt, from_=0.2, to=2.0, orient="horizontal",
                  variable=self.var_brightness).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(frame_opt, textvariable=self.var_brightness, width=6).grid(row=0, column=2, sticky="w")

        ttk.Label(frame_opt, text="字幕字体大小").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(frame_opt, from_=10, to=96, textvariable=self.var_font_size, width=6).grid(
            row=1, column=1, sticky="w", padx=6, pady=(6, 0)
        )

        ttk.Label(frame_opt, text="字幕位置").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(frame_opt, values=["bottom", "top", "center", "custom"], textvariable=self.var_position,
                     state="readonly", width=12).grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))

        ttk.Label(frame_opt, text="自定义 X (0-1)").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(frame_opt, textvariable=self.var_pos_x, width=10).grid(
            row=3, column=1, sticky="w", padx=6, pady=(6, 0)
        )
        ttk.Label(frame_opt, text="自定义 Y (0-1)").grid(row=4, column=0, sticky="w")
        ttk.Entry(frame_opt, textvariable=self.var_pos_y, width=10).grid(
            row=4, column=1, sticky="w", padx=6
        )

        frame_opt.columnconfigure(1, weight=1)

        # 按钮
        # 调色参数
        frame_color = ttk.LabelFrame(self, text="调色")
        frame_color.pack(fill="x", **pad)
        ttk.Label(frame_color, text="曝光").grid(row=0, column=0, sticky="w")
        ttk.Scale(frame_color, from_=-1.0, to=1.0, orient="horizontal",
                  variable=self.var_exposure).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Label(frame_color, textvariable=self.var_exposure, width=6).grid(row=0, column=2)

        ttk.Label(frame_color, text="对比度").grid(row=1, column=0, sticky="w")
        ttk.Scale(frame_color, from_=0.2, to=2.5, orient="horizontal",
                  variable=self.var_contrast).grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Label(frame_color, textvariable=self.var_contrast, width=6).grid(row=1, column=2)

        ttk.Label(frame_color, text="饱和度").grid(row=2, column=0, sticky="w")
        ttk.Scale(frame_color, from_=0.0, to=2.5, orient="horizontal",
                  variable=self.var_saturation).grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Label(frame_color, textvariable=self.var_saturation, width=6).grid(row=2, column=2)

        ttk.Label(frame_color, text="色温(-冷 +暖)").grid(row=3, column=0, sticky="w")
        ttk.Scale(frame_color, from_=-1.0, to=1.0, orient="horizontal",
                  variable=self.var_temperature).grid(row=3, column=1, sticky="ew", padx=6)
        ttk.Label(frame_color, textvariable=self.var_temperature, width=6).grid(row=3, column=2)

        ttk.Label(frame_color, text="锐度").grid(row=4, column=0, sticky="w")
        ttk.Scale(frame_color, from_=0.2, to=3.0, orient="horizontal",
                  variable=self.var_sharpness).grid(row=4, column=1, sticky="ew", padx=6)
        ttk.Label(frame_color, textvariable=self.var_sharpness, width=6).grid(row=4, column=2)
        frame_color.columnconfigure(1, weight=1)

        frame_btn = ttk.Frame(self)
        frame_btn.pack(fill="x", **pad)
        self.btn_start = ttk.Button(frame_btn, text="开始处理", command=self._on_start)
        self.btn_start.pack(side="left")
        ttk.Button(frame_btn, text="保存配置", command=self._save_config).pack(side="left", padx=(8, 0))

        # 日志输出
        self.txt_log = tk.Text(self, height=14, wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=8, pady=8)

    def _choose_dir(self, var: tk.StringVar):
        path = filedialog.askdirectory()
        if path:
            var.set(path)

    def _choose_file(self, var: tk.StringVar):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Font files", "*.ttf *.otf"),
                ("TrueType", "*.ttf"),
                ("OpenType", "*.otf"),
                ("All files", "*.*"),
            ]
        )
        if path:
            var.set(path)

    def _save_config(self):
        data = {
            "folder_a": self.var_folder_a.get(),
            "folder_b": self.var_folder_b.get(),
            "folder_subs": self.var_subs.get(),
            "folder_audios": self.var_audios.get(),
            "folder_output": self.var_output.get(),
            "font_path": self.var_font_path.get(),
            "brightness": round(float(self.var_brightness.get()), 1),
            "font_size": self.var_font_size.get(),
            "position": self.var_position.get(),
            "pos_x": self.var_pos_x.get(),
            "pos_y": self.var_pos_y.get(),
            "exposure": round(float(self.var_exposure.get()), 1),
            "contrast": round(float(self.var_contrast.get()), 1),
            "saturation": round(float(self.var_saturation.get()), 1),
            "temperature": round(float(self.var_temperature.get()), 1),
            "sharpness": round(float(self.var_sharpness.get()), 1),
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._log(f"配置已保存到 {self.config_path}")
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}")

    def _load_config(self):
        if not self.config_path.exists():
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.var_folder_a.set(data.get("folder_a", ""))
            self.var_folder_b.set(data.get("folder_b", ""))
            self.var_subs.set(data.get("folder_subs", ""))
            self.var_audios.set(data.get("folder_audios", ""))
            self.var_output.set(data.get("folder_output", ""))
            self.var_font_path.set(data.get("font_path", ""))
            self.var_brightness.set(round(float(data.get("brightness", 1.0)), 1))
            self.var_font_size.set(int(data.get("font_size", 48)))
            self.var_position.set(data.get("position", "bottom"))
            self.var_pos_x.set(float(data.get("pos_x", 0.5)))
            self.var_pos_y.set(float(data.get("pos_y", 0.85)))
            self.var_exposure.set(round(float(data.get("exposure", 0.0)), 1))
            self.var_contrast.set(round(float(data.get("contrast", 1.0)), 1))
            self.var_saturation.set(round(float(data.get("saturation", 1.0)), 1))
            self.var_temperature.set(round(float(data.get("temperature", 0.0)), 1))
            self.var_sharpness.set(round(float(data.get("sharpness", 1.0)), 1))
            self._log(f"已加载配置: {self.config_path}")
        except Exception as e:
            self._log(f"加载配置失败，使用默认值: {e}")

    def _log(self, msg: str):
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.update_idletasks()

    def _on_start(self):
        try:
            folder_a = Path(self.var_folder_a.get()).expanduser()
            folder_b = Path(self.var_folder_b.get()).expanduser()
            folder_subs = Path(self.var_subs.get()).expanduser()
            folder_audios = Path(self.var_audios.get()).expanduser()
            output_dir = Path(self.var_output.get()).expanduser()

            if not (folder_a and folder_b and folder_subs and folder_audios and output_dir):
                messagebox.showwarning("提示", "请先选择所有文件夹路径")
                return

            brightness = float(self.var_brightness.get())
            font_size = int(self.var_font_size.get())
            position = self.var_position.get()
            pos_xy = (float(self.var_pos_x.get()), float(self.var_pos_y.get()))
            font_path = self.var_font_path.get().strip() or None
            exposure = round(float(self.var_exposure.get()), 1)
            contrast = round(float(self.var_contrast.get()), 1)
            saturation = round(float(self.var_saturation.get()), 1)
            temperature = round(float(self.var_temperature.get()), 1)
            sharpness = round(float(self.var_sharpness.get()), 1)

            # 禁用按钮，开线程避免阻塞 GUI
            self.btn_start.config(state="disabled")
            self._log("开始处理...")

            def worker():
                try:
                    process_batch(
                        folder_a,
                        folder_b,
                        folder_subs,
                        folder_audios,
                        output_dir,
                        brightness_b=brightness,
                        font_size=font_size,
                        subtitle_position=position,
                        subtitle_pos_xy=pos_xy,
                        font_path=font_path,
                        exposure=exposure,
                        contrast=contrast,
                        saturation=saturation,
                        temperature=temperature,
                        sharpness=sharpness,
                        logger=self._log,
                    )
                    messagebox.showinfo("完成", "全部处理完成")
                except Exception as e:
                    self._log(f"发生错误: {e}")
                    messagebox.showerror("错误", str(e))
                finally:
                    self.btn_start.config(state="normal")

            threading.Thread(target=worker, daemon=True).start()

        except Exception as e:
            messagebox.showerror("错误", str(e))
            self.btn_start.config(state="normal")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()


