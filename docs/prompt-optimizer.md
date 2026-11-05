# CSR 提示词优化器

`CSR ③` 的“提示词优化”按钮用于把当前替换描述整理成更明确的 MiniMax H3 指令。优化器属于 CSR 独立命名空间，不导入原 `comfyui-AICG3D` 的节点或 GPL 代码。

提示词优化器本身可以在纯文本模式下工作，不需要 FFmpeg。只有开启视觉分析并从视频中抽帧时，才需要可用的 `ffmpeg` 和 `ffprobe`。安装和排查方法见 [install-and-troubleshooting.md](install-and-troubleshooting.md)。

## 两种运行方式

### OpenAI 兼容 API

适用于：

- Ollama
- LM Studio
- llama.cpp server
- LocalAI
- vLLM
- text-generation-webui OpenAI API
- 其他兼容 `/v1/models` 和 `/v1/chat/completions` 的本地服务

默认地址：

```text
http://127.0.0.1:11434/v1
```

Ollama 示例：

```powershell
ollama pull qwen2.5:7b
ollama serve
```

LM Studio 示例：

1. 在 LM Studio 加载一个中文指令模型。
2. 启动 Local Server。
3. CSR 中填写类似 `http://127.0.0.1:1234/v1`。
4. 模型名填写 LM Studio 显示的模型 ID。

为降低服务端被滥用的风险，CSR 默认只允许本机、回环地址、私有局域网 IP、`.local` 和 `host.docker.internal`。如果确实需要远程 API，部署者必须显式设置：

```text
AICG3D_CSR_ALLOW_REMOTE_PROMPT_API=1
```

### 本地 GGUF

直接加载 GGUF 需要可选安装 `llama-cpp-python`。

```powershell
python -m pip install llama-cpp-python
```

它不是本项目的强制依赖。若 `llama-cpp-python` 需要与本机 CUDA 版本匹配的预编译轮子，请按该项目文档安装对应版本。

模型放在以下任一目录：

```text
ComfyUI/models/llm/
ComfyUI/models/LLM/
ComfyUI/models/prompt_optimizers/
ComfyUI/models/language_models/
```

在优化器中选择“本地 GGUF”、模型、上下文和 GPU 层数。`GPU 层数 -1` 表示尽量交给 llama.cpp 自动分配。

## 可选视觉分析

视觉分析默认关闭。关闭时，优化器只把文字描述、替换标签和方案规则发送给模型，不读取视频、参考图或本地素材路径。

用户主动勾选“启用视觉分析（读取参考素材）”并选择对应的 API 视觉模型或本地 `mmproj` 后，CSR 才会从当前单线链路上游读取有限视觉证据：

- 从视频目标段的首帧、中间帧和尾帧最多取 3 张画面；
- 从资源库最多取 3 张参考图，排序优先背景、物品/产品、人物；
- 单张图片最长边缩到 512 像素，再使用 JPEG 压缩；
- 所有文件必须位于当前 ComfyUI 的 `input`、`output` 或 `temp` 目录；
- 视觉分析最多发送 6 张图片，不把视频原文件发送给模型。

### API 模式
"视觉模型（可选）"单独填写。留空时保持纯文本，不读取素材；填写后，该请求使用此模型读取视觉素材。模型服务必须支持 OpenAI 兼容的 `image_url` 多模态消息。

### 本地 GGUF 模式
本地视觉需要一个能与主 GGUF 配套的 `mmproj` 视觉投影文件。CSR 会扫描：

```text
ComfyUI/models/llm/
ComfyUI/models/LLM/
ComfyUI/models/prompt_optimizers/
ComfyUI/models/language_models/
```

当前直接视觉加载支持 Qwen2.5-VL、Qwen3-VL、Qwen3.5/Qwen3.8 以及 Gemma3/Gemma4 GGUF。主模型与 `mmproj` 必须经过同一套 llama.cpp 视觉处理器兼容。纯文本模式不需要 `mmproj`，其他多模态 GGUF 可通过兼容 OpenAI 多模态接口的本地服务接入。

视觉模型不是必选项。它通常更擅长确认画面中实际存在的人物、产品和场景特征，但会占用额外显存、增加处理时间，也可能从参考图里误读无关细节。需要稳定、低开销的文字扩写时，不勾选视觉分析并使用一个可靠的文本模型即可。

## 视觉开关与模型分工

| 模式 | 关闭视觉 | 开启视觉 |
|---|---|---|
| OpenAI 兼容 API | 只发送文字，使用普通模型 | 发送文字与最多 6 张低清图，优先使用视觉模型 |
| 本地 GGUF | 只发送文字，不需要 mmproj | 发送文字与最多 6 张低清图，加载主模型 + mmproj |

如果未选择对应视觉模型、未选择 `mmproj`，或上游没有可用的视频/参考图，视觉开关即使开启也会退回纯文本请求。

## 提示词方案

| 方案 | 用途 |
|---|---|
| 跟随替换标签 | 根据人物、背景、物品或组合标签自动选择 |
| 背景彻底替换 | 用于普通背景替换 |
| 场景结构重建 | 要求完全重建空间、家具、材质和透视 |
| 人物身份替换 | 只换指定人物 |
| 物品/产品替换 | 只换指定物品、产品、背包或道具 |
| 人物 + 场景 | 同时强制替换人物和完整环境 |
| 人物 + 物品 | 同时替换人物和产品，保留背景 |
| 综合替换 | 同时处理人物、场景和物品 |
| 修复：背景没有被替换 | 对失败结果使用更强的删除旧场景约束 |
| 修复：前景人物被误改 | 对误改人物或物品使用更强的前景保持约束 |

## 背景替换失败时

推荐顺序：

1. 标签选择“背景/场景替换”。
2. 点击“应用模板”。
3. 打开“提示词优化”。
4. 方案选择“修复：背景没有被替换”。
5. 细节强度选择“强化”。
6. 生成本地优化提示词。
7. 检查结果后点击“应用到描述”。
8. 降低测试时长，先验证一个 2–3 秒片段。

提示词会特别强调：

- 背景参考是唯一环境来源；
- 旧墙体、地面、家具和房间结构必须删除；
- 不允许只调色、模糊或局部修补；
- 参考图中的人物、文字和水印不能进入成片；
- 人物身份、动作、口型、镜头和时长保持不变。

## 安全边界

- API Key 仅保存在本机 ComfyUI 用户配置目录中。
- 配置接口不会返回明文 API Key。
- 纯文字模式不会读取或上传视频、图片；视觉模式只有在用户选择 API 视觉模型或本地 `mmproj` 后才会读取素材。
- 视觉分析默认关闭；开启后只读取 ComfyUI `input`、`output`、`temp` 内经过范围校验的素材。
- API 模式开启视觉分析时，最多 6 张压缩图片会发送给用户选择的 API 服务。远程 API 仍需显式设置 `AICG3D_CSR_ALLOW_REMOTE_PROMPT_API=1`；本地模型模式不会把图片发到外部服务。
- 本地模型质量会影响优化结果；应用前应人工检查。
- 优化提示词不能保证所有生成模型都成功执行背景替换。
