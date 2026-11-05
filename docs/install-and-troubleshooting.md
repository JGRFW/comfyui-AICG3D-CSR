# 安装、FFmpeg 与故障排查

本页是 `comfyui-AICG3D-CSR` 的安装前检查清单。视频裁剪、分段、音频剥离、视频预览、最终合并和提示词视觉分析都依赖 FFmpeg，因此必须同时安装 `ffmpeg` 与配套的 `ffprobe`。

## 最常见的报错

如果 `MiniMax H3 Aicg 视频裁剪 · CSR独立版` 显示：

```text
需要与 FFmpeg 配套的 ffprobe，请把二者加入 PATH。
```

通常不是节点本身损坏，而是下面某一种情况：

- 只安装了 `ffmpeg`，没有安装 `ffprobe`；
- `ffmpeg` 和 `ffprobe` 来自不同版本或不同目录；
- FFmpeg 的 `bin` 目录没有加入系统 `PATH`；
- 加入 `PATH` 后没有完全退出并重启 ComfyUI，旧进程仍然使用旧环境变量；
- Python 环境安装了 `imageio-ffmpeg`，但它只提供 ffmpeg 二进制，不能替代独立的 `ffprobe`。

## 正确安装方式

### Windows

1. 安装一个同时包含 `ffmpeg.exe` 和 `ffprobe.exe` 的完整 FFmpeg 构建。
2. 找到包含这两个文件的 `bin` 目录，例如：

```text
C:\ffmpeg\bin\
```

3. 将该目录加入 Windows 用户或系统环境变量 `PATH`。
4. 完全退出 ComfyUI Desktop，包括托盘中的后台进程，然后重新启动。
5. 新开 PowerShell 验证：

```powershell
where.exe ffmpeg
where.exe ffprobe
ffmpeg -version
ffprobe -version
```

四条命令都必须成功。`where.exe` 显示的两个文件应当位于同一个 FFmpeg 安装目录。

如果使用包管理器安装，也仍需重新打开终端并重启 ComfyUI，让新的 `PATH` 生效。

### macOS

使用 Homebrew：

```bash
brew install ffmpeg
```

验证：

```bash
which ffmpeg
which ffprobe
ffmpeg -version
ffprobe -version
```

### Linux

Debian / Ubuntu：

```bash
sudo apt update
sudo apt install ffmpeg
```

验证：

```bash
which ffmpeg
which ffprobe
ffmpeg -version
ffprobe -version
```

### Docker 或便携环境

FFmpeg 必须安装在 ComfyUI 实际运行的容器或运行环境中，而不是只安装在宿主机。安装后需要重启容器，让环境变量生效。

## 关于 imageio-ffmpeg

本项目的视频处理优先使用系统 `ffmpeg`，并允许 `imageio-ffmpeg` 作为 ffmpeg 的可选回退来源。但 `imageio-ffmpeg` 不会自动提供 `ffprobe`，所以：

- 可以使用 `imageio-ffmpeg` 提供的 ffmpeg；
- 仍然必须在 `PATH` 中提供可执行的 ffprobe；
- 最稳妥的方式是直接使用同一个完整 FFmpeg 构建中的 `ffmpeg` 和 `ffprobe`。

## 安装 Python 依赖

在 ComfyUI 使用的 Python 环境中执行：

```powershell
python -m pip install -r requirements.txt
```

不要在系统 Python、ComfyUI 便携环境之外的 Python 或另一个虚拟环境中安装后误以为已经生效。

## 提示词优化器

`CSR ③` 内的“提示词优化”支持两类运行方式。

### OpenAI 兼容 API

适用于 Ollama、LM Studio、llama.cpp server、LocalAI、vLLM 等兼容 `/v1/models` 和 `/v1/chat/completions` 的本地服务。

默认只允许本机、回环地址、私有局域网 IP、`.local` 和 `host.docker.internal`。远程 API 需要部署者显式设置：

```text
AICG3D_CSR_ALLOW_REMOTE_PROMPT_API=1
```

API Key 保存在本机 ComfyUI 用户配置目录中，配置接口不会返回明文密钥。

### 本地 GGUF

直接加载 GGUF 需要可选安装 `llama-cpp-python`：

```powershell
python -m pip install llama-cpp-python
```

模型可以放在：

```text
ComfyUI/models/llm/
ComfyUI/models/LLM/
ComfyUI/models/prompt_optimizers/
ComfyUI/models/language_models/
```

纯文本优化不需要 `mmproj`。本地视觉分析需要主 GGUF 和匹配的 `mmproj` 视觉投影文件。

### 可选视觉模型

视觉分析默认关闭：

- 不勾选视觉分析：只发送文字，不读取视频或图片；
- 勾选视觉分析但未选择 API 视觉模型或本地 `mmproj`：仍按纯文本处理；
- 选择对应视觉模型后：最多读取 6 张低清图片，包括目标段首/中/尾帧和最多 3 张资源库参考图；
- 图片最长边压缩到 512 像素；
- 所有素材必须位于 ComfyUI `input`、`output` 或 `temp` 目录；
- API 模式会把压缩图片发送给用户选择的 API 服务；
- 本地 GGUF 模式仅在当前设备处理图片，并在请求结束后卸载视觉模型。

视觉分析从视频中抽帧时同样需要 FFmpeg 和 ffprobe。

完整配置说明见 [prompt-optimizer.md](prompt-optimizer.md)。

## 仍然无法解决时

请提供以下信息，但不要公开 API Key、客户素材或私密视频：

```powershell
where.exe ffmpeg
where.exe ffprobe
ffmpeg -version
ffprobe -version
python --version
python -m pip show filelock numpy Pillow
```

同时提供 ComfyUI 启动日志中与 `ffmpeg`、`ffprobe` 或 `AICG3D-CSR` 相关的错误段落。
