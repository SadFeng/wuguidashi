#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包脚本：将 video_concat_gui.py 打包成 Windows exe 文件

使用方法：
1. 安装依赖：pip install -r requirements.txt
2. 安装 PyInstaller：pip install pyinstaller
3. 运行本脚本：python build_exe.py

输出：
- dist/video_concat_gui.exe（单文件可执行程序）
- build/（临时构建文件，可删除）

注意：
- 需要确保系统已安装 ffmpeg（moviepy 依赖）
- 打包后的 exe 需要 ffmpeg 在 PATH 中，或与 exe 同目录放置 ffmpeg.exe
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    try:
        # 尝试设置控制台为 UTF-8
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except Exception:
        # 如果失败，使用安全的打印函数
        def safe_print(*args, **kwargs):
            try:
                print(*args, **kwargs)
            except UnicodeEncodeError:
                # 将中文字符替换为 ASCII
                safe_args = []
                for arg in args:
                    if isinstance(arg, str):
                        try:
                            arg.encode('ascii')
                            safe_args.append(arg)
                        except UnicodeEncodeError:
                            safe_args.append(arg.encode('ascii', 'replace').decode('ascii'))
                    else:
                        safe_args.append(arg)
                print(*safe_args, **kwargs)
        print = safe_print

# 获取脚本所在目录
SCRIPT_DIR = Path(__file__).parent.absolute()
GUI_SCRIPT = SCRIPT_DIR / "video_concat_gui.py"
ICON_PATH = None  # 如果有图标文件，可以设置路径，例如：SCRIPT_DIR / "icon.ico"

def check_dependencies():
    """检查必要的依赖是否已安装"""
    print("检查依赖...")
    try:
        import PyInstaller
        print(f"✓ PyInstaller 已安装: {PyInstaller.__version__}")
    except ImportError:
        print("✗ PyInstaller 未安装，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✓ PyInstaller 安装完成")

def build_exe():
    """使用 PyInstaller 打包"""
    print("\n开始打包...")
    
    # PyInstaller 命令参数
    cmd = [
        "pyinstaller",
        "--name=video_concat_gui",  # 输出 exe 名称
        "--onefile",  # 打包成单文件
        "--windowed",  # 隐藏控制台窗口（GUI 应用）
        "--clean",  # 清理临时文件
        "--noconfirm",  # 覆盖已存在的输出文件
    ]
    
    # 如果有图标，添加图标参数
    if ICON_PATH and ICON_PATH.exists():
        cmd.extend(["--icon", str(ICON_PATH)])
        print(f"使用图标: {ICON_PATH}")
    
    # 添加隐藏导入（PyInstaller 可能无法自动检测的模块）
    hidden_imports = [
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
        "PIL.ImageEnhance",
        "moviepy",
        "moviepy.editor",
        "moviepy.video.fx",
        "pysrt",
        "numpy",
        "imageio",
        "imageio.plugins.ffmpeg",
        "json",
        "re",
        "pathlib",
    ]
    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])
    
    # 添加数据文件（如果需要包含字体文件等）
    # cmd.extend(["--add-data", "字体文件路径;."])
    
    # 添加主脚本
    cmd.append(str(GUI_SCRIPT))
    
    print(f"执行命令: {' '.join(cmd)}")
    print("\n" + "="*60)
    
    # 执行打包
    try:
        subprocess.check_call(cmd, cwd=str(SCRIPT_DIR))
        print("="*60)
        print("\n✓ 打包完成！")
        exe_path = SCRIPT_DIR / "dist" / "video_concat_gui.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"输出文件: {exe_path}")
            print(f"文件大小: {size_mb:.1f} MB")
            print("\n注意事项：")
            print("1. 确保目标机器已安装 ffmpeg，或与 exe 同目录放置 ffmpeg.exe")
            print("2. 首次运行可能需要几秒钟加载时间")
            print("3. 如果遇到 '找不到模块' 错误，可能需要添加更多 --hidden-import")
        else:
            print("✗ 未找到输出文件，请检查 build 目录中的错误信息")
    except subprocess.CalledProcessError as e:
        print(f"\n✗ 打包失败: {e}")
        sys.exit(1)

def create_readme():
    """创建使用说明文件"""
    readme_path = SCRIPT_DIR / "dist" / "使用说明.txt"
    readme_content = """批量视频拼接工具 - 使用说明
=====================================

一、系统要求
-----------
1. Windows 7 或更高版本
2. 需要安装 ffmpeg（moviepy 依赖）

二、ffmpeg 安装方法
------------------
方法 1：下载 ffmpeg 并添加到 PATH
- 访问 https://ffmpeg.org/download.html
- 下载 Windows 版本
- 解压后将 bin 目录添加到系统 PATH

方法 2：将 ffmpeg.exe 放在 exe 同目录
- 下载 ffmpeg.exe
- 将其放在 video_concat_gui.exe 同一文件夹中

三、使用方法
-----------
1. 双击运行 video_concat_gui.exe
2. 选择文件夹：
   - A 视频文件夹：第一个视频片段
   - B 视频文件夹：第二个视频片段（可调节亮度）
   - 字幕文件夹：包含 .srt 字幕文件
   - 音频文件夹：包含音频文件（mp3/wav 等）
   - 输出文件夹：处理后的视频保存位置
   - 字体文件（可选）：选择 .ttf 字体文件

3. 调整参数：
   - B 亮度：仅作用于 B 视频片段（>1 变亮，<1 变暗）
   - 曝光：整体亮度（正数变亮，负数变暗）
   - 对比度：>1 更硬朗，<1 更柔和
   - 饱和度：>1 更鲜艳，<1 更灰
   - 色温：-1 偏冷，+1 偏暖
   - 锐度：>1 更锐利，<1 更柔
   - 字幕字体大小和位置

4. 点击"开始处理"

四、功能说明
-----------
- 自动遍历 A 文件夹和 B 文件夹的所有视频组合
- 字幕和音频文件会循环使用（如果数量少于视频组合数）
- 支持保存/加载配置，避免每次重新选择路径
- 所有调色参数保留小数点后一位

五、常见问题
-----------
Q: 提示找不到 ffmpeg？
A: 请确保已安装 ffmpeg 并添加到 PATH，或将 ffmpeg.exe 放在 exe 同目录

Q: 处理速度慢？
A: 视频处理需要时间，请耐心等待。可以查看日志输出了解进度

Q: 字幕显示不正确？
A: 请检查字幕文件编码是否为 UTF-8，或尝试选择不同的字体文件

Q: 内存不足？
A: 尝试减少同时处理的视频数量，或使用较小的视频文件

六、技术支持
-----------
如有问题，请访问项目 GitHub 页面提交 Issue。
"""
    
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"✓ 已创建使用说明: {readme_path}")

if __name__ == "__main__":
    print("="*60)
    print("批量视频拼接工具 - Windows EXE 打包脚本")
    print("="*60)
    
    if not GUI_SCRIPT.exists():
        print(f"✗ 错误: 找不到 {GUI_SCRIPT}")
        sys.exit(1)
    
    check_dependencies()
    build_exe()
    create_readme()
    
    print("\n" + "="*60)
    print("打包流程完成！")
    print("="*60)

