# 打包 Windows EXE 文件指南

## 前置要求

1. **Python 环境**：Python 3.8 或更高版本
2. **Windows 系统**：在 Windows 上打包（或使用 Wine 在 Linux/macOS 上交叉编译）

## 快速开始

### 方法 1：使用自动打包脚本（推荐）

```bash
# 1. 安装依赖
pip install -r requirements.txt
pip install pyinstaller

# 2. 运行打包脚本
python build_exe.py
```

打包完成后，exe 文件位于 `dist/video_concat_gui.exe`

### 方法 2：使用 spec 文件

```bash
# 1. 安装依赖
pip install -r requirements.txt
pip install pyinstaller

# 2. 使用 spec 文件打包
pyinstaller build.spec
```

## 打包选项说明

### build_exe.py 脚本参数

- `--onefile`：打包成单个 exe 文件（推荐，便于分发）
- `--windowed`：隐藏控制台窗口（GUI 应用必需）
- `--clean`：清理临时文件
- `--noconfirm`：自动覆盖已存在的输出

### 自定义选项

如果需要修改打包配置，可以编辑 `build_exe.py` 或 `build.spec`：

1. **添加图标**：在 `build_exe.py` 中设置 `ICON_PATH` 变量
2. **添加数据文件**：使用 `--add-data` 参数包含字体文件等
3. **排除模块**：使用 `--exclude-module` 减小文件大小

## 打包后的文件结构

```
dist/
├── video_concat_gui.exe    # 主程序（单文件，可直接运行）
└── 使用说明.txt            # 用户使用说明
```

## 分发注意事项

### 必需组件

1. **ffmpeg**：用户需要安装 ffmpeg 或与 exe 同目录放置 `ffmpeg.exe`
   - 下载地址：https://ffmpeg.org/download.html
   - 或使用 `imageio-ffmpeg` 自动下载（但会增加打包体积）

### 可选优化

1. **减小文件大小**：
   - 使用 `--exclude-module` 排除不需要的模块
   - 使用 UPX 压缩（已在 spec 中启用）

2. **提高兼容性**：
   - 在 Windows 7/8/10/11 上测试
   - 确保所有依赖都正确打包

3. **添加版本信息**：
   - 创建版本资源文件（.rc）
   - 在 spec 文件中引用

## 测试打包结果

1. 在干净的 Windows 虚拟机中测试
2. 确保没有安装 Python 和相关依赖
3. 只放置 exe 文件和 ffmpeg.exe（如果需要）
4. 运行并测试所有功能

## 常见问题

### Q: 打包后 exe 很大（>100MB）？

A: 这是正常的，因为包含了 Python 解释器和所有依赖。可以使用 UPX 压缩减小体积。

### Q: 运行时提示缺少模块？

A: 在 `build_exe.py` 的 `hidden_imports` 列表中添加缺失的模块。

### Q: 无法找到 ffmpeg？

A: 确保用户已安装 ffmpeg 或与 exe 同目录放置 `ffmpeg.exe`。也可以考虑使用 `imageio-ffmpeg` 自动下载。

### Q: 打包速度慢？

A: 首次打包需要分析所有依赖，后续会使用缓存加快速度。

## GitHub Actions 自动打包（可选）

可以创建 `.github/workflows/build.yml` 实现自动打包：

```yaml
name: Build Windows EXE

on:
  release:
    types: [created]

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: |
          pip install -r video_tools/requirements.txt
          pip install pyinstaller
      - name: Build exe
        run: |
          cd video_tools
          python build_exe.py
      - name: Upload artifacts
        uses: actions/upload-artifact@v2
        with:
          name: video_concat_gui
          path: video_tools/dist/video_concat_gui.exe
```

## 许可证

请确保遵守所有依赖库的许可证要求。

