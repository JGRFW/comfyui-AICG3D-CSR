# 贡献指南

感谢参与 `comfyui-AICG3D-CSR`。提交代码、文档、工作流或示例即表示你有权提供该内容，并同意其按本仓库的 MIT 许可证发布。

## 可以贡献的内容

- Bug 修复；
- ComfyUI 与 H3 兼容性改进；
- 性能和显存优化；
- 节点 UI 与可用性改进；
- 文档、截图和示例；
- 测试、虚拟媒体样本和可复现问题；
- 安全检查与合规改进。

## 不应提交的内容

- 未经授权的影视片段、音乐、图片、人脸或品牌素材；
- 真实人物的私密视频、声音或无同意素材；
- 模型权重、LoRA、VAE 或其他大型第三方二进制文件，除非已明确讨论并符合许可；
- GitHub 令牌、API 密钥、Cookie、会话文件或私有配置；
- 含私人路径、客户数据或个人信息的日志；
- 用于绕过模型或平台安全系统的代码；
- 违法、欺骗、骚扰、剥削或高风险滥用示例。

## 开发要求

1. 只修改与问题相关的文件。
2. 保持 `CSR`、`/aicg3d_csr`、`AICG3D.CSR.*` 命名空间。
3. 不要全局修改 ComfyUI 节点、采样器、注意力后端或画布行为。
4. 新增文件访问必须限制在 ComfyUI 的 `input`、`output`、`temp` 目录。
5. 外部命令必须使用参数数组，避免 shell 字符串拼接。
6. 新增第三方代码时同步更新 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
7. 涉及隐私、肖像或真实人物功能时同步更新 [LEGAL.md](LEGAL.md) 和 [PRIVACY.md](PRIVACY.md)。

## 提交前检查

```powershell
python -m unittest discover -s tests -v
ruff check --no-cache .
node --check web/csr_model_loader.js
node --check web/csr_video_crop.js
node --check web/csr_media_assets.js
node --check web/csr_media_library.js
node --check web/csr_segment_preview.js
node --check web/csr_second_pass.js
```

如某项检查无法运行，请在 pull request 中说明原因和环境。

## Pull Request 说明

请提供：

- 问题和目标；
- 实现范围；
- 对缓存、工作流兼容性或输出的影响；
- 测试结果；
- 已知限制；
- 是否使用或改编了第三方代码；
- 截图或短视频，但必须使用你有权公开的素材。

## 许可与署名

除非你明确书面反对，提交内容将按 MIT License 授权。不要把原作者、ComfyUI、MiniMax、AICG3D 或第三方模型作者错误描述为你的修改背书。

## 行为边界

讨论应保持技术性、可验证和尊重。安全、隐私和版权问题会优先审查。
