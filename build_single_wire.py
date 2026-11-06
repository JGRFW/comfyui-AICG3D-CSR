"""Build the standalone single-wire AICG3D-CSR workflow."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKFLOWS = ROOT / "workflows"
H3_MODEL = "MiniMax\\DasiwaMinimaxH3_dasiwaREF2VAHybridV1_0.safetensors"
CLIP_MODEL = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
CHARACTER_LORA = "minimax\\h3_character_swap_pro4500_1000.safetensors"
TURBO_LORA = "minimax\\minimax_h3_turbo_v4_step600_ema_DasiwaREF2VAHybridV1_0_curveproj1025_compat_v001.safetensors"
NOTE = """AICG3D-CSR 单线人物场景替换

这是一条完全独立的 CSR 节点链，不依赖原来的 comfyui-AICG3D 节点：
MiniMax H3 Aicg 加载器 -> MiniMax H3 Aicg资源库 -> CSR ③ 逐段替换 -> CSR ④ 无缝合并 -> 保存。

1. 所有主模型、文本编码器、视频 VAE、音频 VAE 和 LoRA 都在独立加载器中设置。
2. 源视频、替换参考 1-9、背景图和参考首帧都在独立资源库中上传，缩略图完整显示。
3. 资源库先用时长和滑块选择任意目标裁剪段，例如 10 秒或 15 秒；目标窗口内仍可继续自由分段。
3.1 加载器额外提供原始 MODEL 输出；可接入第三方加速链，再把最终 MODEL 接回视频裁剪的 model_patch。未连接时完全沿用原始模型。
4. 每个节点之间只有一根线：模型包 -> 任务包 -> 分段结果 -> 最终视频。
5. CSR ③ 底部显示当前段、采样步数、剩余时间和实时画面；每段完成后直接播放该段 MP4。
6. 音频在资源库阶段自动剥离，不进入任何分段；CSR ④ 合并完成后才把 source_audio.wav 封装进去。
7. CSR ③ 的“替换标签”可选择人物、背景、物品或组合场景，并一键应用对应提示词模板。
8. CSR ④ 默认开启跨段曝光锁定，匹配相邻片段的亮度基线和段首低频光影；硬切镜头会自动跳过混合。

推荐先用 480 短边和 8 步预览；身份不稳时优先缩短单段、更换参考图和 seed。
"""

SPLIT_NOTE = """AICG3D-CSR 双节点素材工作流

这是一条完全独立的 CSR 单线节点链，不依赖原来的 comfyui-AICG3D 节点：
MiniMax H3 Aicg 加载器 -> MiniMax H3 Aicg 视频裁剪 -> MiniMax H3 Aicg资源库 -> CSR ③ -> CSR ③B 二采（可选） -> CSR ④ -> 保存。

1. 视频裁剪节点只负责源视频上传、音轨剥离、目标时长、滑块定位和自由分段。
2. 资源库节点负责替换参考 1-9（人物或物品）、背景图和参考首帧；所有图片使用完整缩略图显示。
2.1 加载器额外提供原始 MODEL 输出；可接第三方加速节点，最终 MODEL 接回视频裁剪节点的 model_patch。未连接时保持原始单线行为。
3. 主数据链仍然只有一根视频任务包连线；加载器额外的 MODEL 输出只用于可选第三方加速支线。
4. CSR ③ 底部显示当前段、采样步数、剩余时间和实时画面；每段完成后直接播放该段 MP4。
5. 音频在视频裁剪阶段自动剥离，不进入任何分段；CSR ④ 合并完成后才把 source_audio.wav 封装进去。
6. CSR ③ 的“替换标签”可选择人物、背景、物品或组合场景，并一键应用对应提示词模板。
7. CSR ③B 默认关闭并直接透传；打开后才展开二采模型、Latent 放大器、倍率、步数、采样器、调度器、denoise、seed 和断点续跑参数。
8. CSR ④ 默认开启跨段曝光锁定，匹配相邻片段的亮度基线和段首低频光影；硬切镜头会自动跳过混合。

推荐先用 480 短边和 8 步预览；复杂多人建议拆成多个 CSR ③ 节点顺序替换。
"""

DEFAULT_BINDINGS = "\n".join([
    "the leftmost designated source subject, corresponding to replacement reference 1; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 2; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 3; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 4; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 5; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 6; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 7; track this exact target in every frame",
])


class Builder:
    def __init__(self):
        self.nodes = []
        self.links = []
        self.api = {}

    def add(self, identifier, kind, title, pos, size, widgets=None, inputs=None, outputs=None):
        widgets = widgets or {}
        node = {
            "id": identifier, "type": kind, "title": title, "pos": list(pos), "size": list(size),
            "flags": {}, "order": len(self.nodes), "mode": 0,
            "inputs": [{"name": name, "type": datatype, "link": None} for name, datatype in (inputs or [])],
            "outputs": [{"name": name, "type": datatype, "links": []} for name, datatype in (outputs or [])],
            "properties": {"Node name for S&R": kind}, "widgets_values": list(widgets.values()),
            "widgets_values_named": dict(widgets), "color": "#e3ecf8", "bgcolor": "#f4f7fc",
        }
        self.nodes.append(node)
        self.api[str(identifier)] = {"class_type": kind, "inputs": dict(widgets), "_meta": {"title": title}}
        return node

    def connect(self, source, output, target, name):
        src = next(node for node in self.nodes if node["id"] == source)
        dst = next(node for node in self.nodes if node["id"] == target)
        slot = next(i for i, item in enumerate(dst["inputs"]) if item["name"] == name)
        link_id = len(self.links) + 1
        self.links.append([link_id, source, output, target, slot, src["outputs"][output]["type"]])
        src["outputs"][output]["links"].append(link_id)
        dst["inputs"][slot]["link"] = link_id
        self.api[str(target)]["inputs"][name] = [str(source), output]

    def workflow(self, note_id=6, note=NOTE):
        self.nodes.append({
            "id": note_id, "type": "Note", "title": "使用说明", "pos": [-1220, -1040], "size": [980, 480],
            "flags": {}, "order": len(self.nodes), "mode": 0, "inputs": [], "outputs": [],
            "properties": {}, "widgets_values": [note], "color": "#fff0ca", "bgcolor": "#fff8e6",
        })
        return {
            "last_node_id": note_id, "last_link_id": len(self.links), "nodes": self.nodes,
            "links": self.links, "groups": [], "config": {},
            "extra": {"ds": {"scale": 0.72, "offset": [1420, 860]}}, "version": 0.4,
        }


def build():
    loader = {
        "fl2va_model": H3_MODEL, "ref2va_model": H3_MODEL, "task_mode": "Ref2VA（推荐）",
        "text_encoder": CLIP_MODEL, "video_vae": VIDEO_VAE, "audio_vae": AUDIO_VAE,
        "attention_mode": "ComfyUI 默认", "lora_1": TURBO_LORA, "lora_1_strength": 1.0,
        "lora_2": CHARACTER_LORA, "lora_2_strength": 1.0,
    }
    for index in range(3, 9):
        loader[f"lora_{index}"] = "none"
        loader[f"lora_{index}_strength"] = 1.0
    builder = Builder()
    builder.add(1, "CSRModelLoader", "MiniMax H3 Aicg 加载器 · CSR独立版", (-1220, -500),
                (500, 760), loader,
                outputs=[("model_bundle", "CSR_MODEL_BUNDLE"), ("model", "MODEL")])
    builder.add(2, "CSRMediaLibrary", "MiniMax H3 Aicg资源库 · CSR独立版", (-610, -500),
                (560, 980),
                {"media_state": "{}",
                 "segment_ranges": json.dumps([{"start": 0, "end": 10.0}], ensure_ascii=False),
                 "character_bindings": DEFAULT_BINDINGS,
                 "short_edge": 480, "context_frames": 22, "seam_blend_frames": 3,
                 "encoder": "libx264（CPU·稳定）", "test_seconds": 0.0},
                inputs=[("model_bundle", "CSR_MODEL_BUNDLE")],
                outputs=[("job_bundle", "CSR_JOB_BUNDLE")])
    builder.connect(1, 0, 2, "model_bundle")
    builder.add(3, "CSRSegmentReplace", "CSR ③ 逐段替换 · 自动保存 · 断点续跑 · 实时预览",
                (70, -500), (540, 900),
                {"description": "把画面中的目标人物替换为上传人物参考图（若上传背景图则同时替换环境）；保留原视频的镜头、身体动作、口型、人物站位与互动节奏，不增加原视频没有的动作。",
                 "replacement_tags": "自定义",
                 "steps": 8, "sampler_name": "er_sde", "scheduler": "beta", "seed": 123456,
                 "ref_image_size": "最大2048（身份优先）", "face_anchor": False,
                 "source_reference_scale": 1.0, "audio_reuse": True, "resume_completed": True,
                 "live_preview": True, "preview_every_steps": 2, "preview_resolution": 512},
                inputs=[("job_bundle", "CSR_JOB_BUNDLE")],
                outputs=[("rendered_segments", "CSR_RENDERED_SEGMENTS")])
    node3 = builder.nodes[2]
    seed_index = list(node3["widgets_values_named"]).index("seed") + 1
    node3["widgets_values"].insert(seed_index, "fixed")
    builder.connect(2, 0, 3, "job_bundle")
    builder.add(4, "CSRMerge", "CSR ④ 无缝合并 · 后置封装音轨", (730, -500), (470, 250),
                {"keep_original_audio": True, "verify_boundaries": True, "seam_exposure_lock": True},
                inputs=[("rendered_segments", "CSR_RENDERED_SEGMENTS")],
                outputs=[("video", "VIDEO")])
    builder.connect(3, 0, 4, "rendered_segments")
    prefix = "video/AICG3D-CSR_单线人物场景替换"
    builder.add(5, "SaveVideo", "保存最终成片", (1310, -500), (480, 450),
                {"filename_prefix": prefix, "format": "mp4", "format.codec": "auto", "codec": "auto"},
                inputs=[("video", "VIDEO")], outputs=[("video", "VIDEO")])
    builder.connect(4, 0, 5, "video")
    builder.api["5"]["inputs"] = {
        "filename_prefix": prefix,
        "format": "mp4",
        "format.codec": "auto",
        "codec": "auto",
        "video": ["4", 0],
    }
    return builder.workflow(), builder.api


def build_split():
    loader = {
        "fl2va_model": H3_MODEL, "ref2va_model": H3_MODEL, "task_mode": "Ref2VA（推荐）",
        "text_encoder": CLIP_MODEL, "video_vae": VIDEO_VAE, "audio_vae": AUDIO_VAE,
        "attention_mode": "ComfyUI 默认", "lora_1": TURBO_LORA, "lora_1_strength": 1.0,
        "lora_2": CHARACTER_LORA, "lora_2_strength": 1.0,
    }
    for index in range(3, 9):
        loader[f"lora_{index}"] = "none"
        loader[f"lora_{index}_strength"] = 1.0
    builder = Builder()
    builder.add(1, "CSRModelLoader", "MiniMax H3 Aicg 加载器 · CSR独立版", (-1540, -520),
                (500, 760), loader,
                outputs=[("model_bundle", "CSR_MODEL_BUNDLE"), ("model", "MODEL")])
    builder.add(2, "CSRVideoCrop", "MiniMax H3 Aicg 视频裁剪 · CSR独立版", (-940, -520),
                (540, 660),
                {"video_state": "{}",
                 "segment_ranges": json.dumps([{"start": 0, "end": 10.0}], ensure_ascii=False),
                 "short_edge": 480,
                 "resolution_preset": "540P", "custom_width": 0, "custom_height": 0,
                 "context_frames": 22, "seam_blend_frames": 3,
                 "encoder": "libx264（CPU·稳定）", "test_seconds": 0.0, "aspect_ratio": "16:9"},
                inputs=[("model_bundle", "CSR_MODEL_BUNDLE"), ("model_patch", "MODEL")],
                outputs=[("video_bundle", "CSR_VIDEO_BUNDLE")])
    builder.connect(1, 0, 2, "model_bundle")
    builder.add(3, "CSRMediaAssets", "MiniMax H3 Aicg资源库 · CSR独立版", (-300, -520),
                (540, 500),
                {"asset_state": "{}",
                 "character_bindings": DEFAULT_BINDINGS},
                inputs=[("video_bundle", "CSR_VIDEO_BUNDLE")],
                outputs=[("job_bundle", "CSR_JOB_BUNDLE")])
    builder.connect(2, 0, 3, "video_bundle")
    builder.add(4, "CSRSegmentReplace", "CSR ③ 逐段替换 · 自动保存 · 断点续跑 · 实时预览",
                (330, -520), (540, 900),
                {"description": "把画面中的目标人物替换为上传人物参考图（若上传背景图则同时替换环境）；保留原视频的镜头、身体动作、口型、人物站位与互动节奏，不增加原视频没有的动作。",
                 "replacement_tags": "自定义",
                 "steps": 8, "sampler_name": "er_sde", "scheduler": "beta", "seed": 123456,
                 "ref_image_size": "最大2048（身份优先）", "face_anchor": False,
                 "source_reference_scale": 1.0, "audio_reuse": True, "resume_completed": True,
                 "live_preview": True, "preview_every_steps": 2, "preview_resolution": 512},
                inputs=[("job_bundle", "CSR_JOB_BUNDLE")],
                outputs=[("rendered_segments", "CSR_RENDERED_SEGMENTS")])
    node4 = builder.nodes[3]
    seed_index = list(node4["widgets_values_named"]).index("seed") + 1
    node4["widgets_values"].insert(seed_index, "fixed")
    builder.connect(3, 0, 4, "job_bundle")
    builder.add(5, "CSRSecondPass", "CSR ③B 二采放大 · 可选 · 断点续跑", (930, -520), (540, 180),
                {"enable_second_pass": False,
                 "second_pass_model": "沿用一采模型", "second_pass_lora": "none", "second_pass_lora_strength": 1.0,
                 "latent_upscale_model": "minimax_h3_latent_upscaler_3d_fp16_V2.safetensors",
                 "upscale_scale": 1.5, "upscale_device": "cuda", "upscale_precision": "fp16",
                 "upscale_chunking": True, "steps": 4, "sampler_name": "er_sde", "scheduler": "beta",
                 "denoise": 0.3, "seed": 888888, "resume_completed": True,
                 "live_preview": True, "preview_every_steps": 1, "preview_resolution": 512},
                inputs=[("rendered_segments", "CSR_RENDERED_SEGMENTS")],
                outputs=[("rendered_segments", "CSR_RENDERED_SEGMENTS")])
    node5 = builder.nodes[4]
    seed_index = list(node5["widgets_values_named"]).index("seed") + 1
    node5["widgets_values"].insert(seed_index, "fixed")
    builder.connect(4, 0, 5, "rendered_segments")
    builder.add(6, "CSRMerge", "CSR ④ 无缝合并 · 后置封装音轨", (1560, -520), (470, 250),
                {"keep_original_audio": True, "verify_boundaries": True, "seam_exposure_lock": True},
                inputs=[("rendered_segments", "CSR_RENDERED_SEGMENTS")],
                outputs=[("video", "VIDEO")])
    builder.connect(5, 0, 6, "rendered_segments")
    prefix = "video/AICG3D-CSR_视频裁剪_资源库_单线"
    builder.add(7, "SaveVideo", "保存最终成片", (2100, -520), (480, 450),
                {"filename_prefix": prefix, "format": "mp4", "format.codec": "auto", "codec": "auto"},
                inputs=[("video", "VIDEO")], outputs=[("video", "VIDEO")])
    builder.connect(6, 0, 7, "video")
    builder.api["7"]["inputs"] = {
        "filename_prefix": prefix,
        "format": "mp4",
        "format.codec": "auto",
        "codec": "auto",
        "video": ["6", 0],
    }
    return builder.workflow(8, SPLIT_NOTE), builder.api
def main():
    WORKFLOWS.mkdir(parents=True, exist_ok=True)
    workflow, api = build()
    workflow_path = WORKFLOWS / "AICG3D-CSR_单线人物场景替换_独立模型加载器_资源库.json"
    api_path = WORKFLOWS / "AICG3D-CSR_单线人物场景替换_独立模型加载器_资源库_API.json"
    workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    api_path.write_text(json.dumps(api, ensure_ascii=False, indent=2), encoding="utf-8")
    print(workflow_path)
    print(api_path)

    split_workflow, split_api = build_split()
    split_workflow_path = WORKFLOWS / "AICG3D-CSR_视频裁剪_资源库_单线.json"
    split_api_path = WORKFLOWS / "AICG3D-CSR_视频裁剪_资源库_单线_API.json"
    split_workflow_path.write_text(json.dumps(split_workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    split_api_path.write_text(json.dumps(split_api, ensure_ascii=False, indent=2), encoding="utf-8")
    print(split_workflow_path)
    print(split_api_path)


if __name__ == "__main__":
    main()
