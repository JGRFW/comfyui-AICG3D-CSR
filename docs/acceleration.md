# 第三方模型加速接入

CSR 不直接内置或复制第三方加速插件。加载器额外提供一个原始 `MODEL` 输出，视频裁剪节点提供一个可选 `model_patch` 输入，用来把任意兼容的 ComfyUI 模型补丁接回 CSR 任务包。

## 推荐连接方式

主数据线保持不变：

```text
CSRModelLoader.model_bundle -> CSRVideoCrop.model_bundle
```

只有需要第三方加速时，再增加一条模型支线：

```text
CSRModelLoader.MODEL -> third-party acceleration -> CSRVideoCrop.model_patch
```

完整形式：

```text
model_bundle -> CSRVideoCrop.model_bundle
MODEL -> third-party acceleration -> CSRVideoCrop.model_patch
```

未连接 `model_patch` 时，视频裁剪节点继续使用加载器内部原始模型，行为和旧版完全一致。

## 支持的节点类型

只要第三方节点的输入和输出都是 ComfyUI `MODEL`，就可以放在这条支线中，例如：

- SageAttention 补丁
- FlashAttention 补丁
- TorchCompile 模型编译
- MiniMax H3 专用注意力补丁
- 模型 Patch 顺序调整
- 采样 Sigmas 或 Shift 调整
- 其他不改变 CLIP、VAE 和文本条件的模型补丁

加载器中的 LoRA 会先应用，再将应用 LoRA 后的 `MODEL` 送入第三方加速支线。

## 使用步骤

1. 从 `MiniMax H3 Aicg 加载器 · CSR独立版` 的 `model` 输出连接第一个第三方节点。
2. 按第三方插件要求连接完整的加速节点链。
3. 把加速链最后一个 `MODEL` 输出接到 `MiniMax H3 Aicg 视频裁剪 · CSR独立版` 的 `model_patch` 输入。
4. 保持 `model_bundle` 主线继续连接视频裁剪节点。
5. 首次使用先运行 2 到 5 秒测试段，对比开关加速前后的速度、显存和画面一致性。

## 重要限制

- CSR 只验证数据类型和模型回填，不会自动修复第三方节点自身的不兼容。
- 不要同时启用多个作用相同的注意力后端或重复 SageAttention 补丁。
- 如果 ComfyUI 已使用 `--use-sage-attention` 启动，再接入 SageAttention 补丁可能重复作用。
- 第三方节点如果修改模型结构、通道数量或 Patch 顺序，可能与 MiniMax H3 AV 双通道不兼容。
- `model_patch` 只替换任务包中的 `MODEL`，不会替换 CLIP、视频 VAE、音频 VAE 或参考条件。
- 第三方节点必须位于加速支线中；不要尝试把 `MODEL` 直接接到 `model_bundle`。
- 断开 `model_patch` 后会自动恢复加载器原始模型。

## 排错

如果连接第三方节点后报模型类型或采样错误：

1. 断开 `model_patch`，确认原始 CSR 链正常。
2. 逐个连接加速节点，找出冲突节点。
3. 关闭 ComfyUI 启动参数中的重复注意力后端。
4. 检查第三方节点是否支持 MiniMax H3，而不是只支持 Wan、LTX 或 Flux。
5. 查看 ComfyUI 日志中的 `external MODEL patch applied` 记录，确认补丁已接回 CSR。

建议只在测试通过后使用 `resume_completed` 复用分段。修改加速节点参数后应重新生成目标测试段，再判断是否真的加速以及画质是否可接受。
