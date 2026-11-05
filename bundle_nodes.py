"""Standalone model and media bundle nodes for AICG3D-CSR."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import folder_paths
import nodes as comfy_nodes

from .nodes import DEFAULT_BINDINGS, ENCODER_CHOICES, CSRReferences, CSRVideoSegments, resolve_media_path

LOG = logging.getLogger(__name__)
BUNDLE_VERSION = "1.0.0"
TASK_CHOICES = ["Ref2VA（推荐）", "FL2VA"]
ATTENTION_CHOICES = ["ComfyUI 默认"]
LORA_SLOTS = 8
RESOLUTION_CHOICES = ["默认（短边）", "360P", "480P", "540P", "720P", "1080P", "自定义"]
ASPECT_RATIO_CHOICES = ["跟随源视频", "16:9", "16:10", "9:16", "1:1", "4:3", "3:4", "21:9"]
NONE_MODEL = "none"


def _files(category: str) -> list[str]:
    return list(folder_paths.get_filename_list(category))


def _pick(files: list[str], needles: tuple[str, ...], fallback: str = "") -> str:
    lowered = [(item, item.lower()) for item in files]
    for needle in needles:
        for item, low in lowered:
            if needle.lower() in low:
                return item
    return fallback or (files[0] if files else NONE_MODEL)


def _model_default() -> str:
    files = _files("diffusion_models")
    return _pick(files, ("dasiwa minimaxh3", "dasiwa minimax h3", "minimax_h3_ref2va", "minimax"), NONE_MODEL)


def _clip_default() -> str:
    return _pick(_files("text_encoders"), ("qwen3vl_32b_minimax_h3", "minimax_h3"), "")


def _video_vae_default() -> str:
    return _pick(_files("vae"), ("minimax_h3_video_vae_int8", "minimax_h3_video_vae"), "")


def _audio_vae_default() -> str:
    return _pick(_files("vae"), ("minimax_h3_audio_vae", "minimax_h3_audio"), "")


def _turbo_lora_default() -> str:
    return _pick(_files("loras"), ("minimax_h3_turbo_v4_step600_ema_dasiwaref2vahybrid", "minimax_h3_turbo"), NONE_MODEL)


def _swap_lora_default() -> str:
    return _pick(_files("loras"), ("h3_character_swap_pro4500_1000", "character_swap"), NONE_MODEL)


def _file_stamp(path: str | None) -> list | None:
    if not path or not Path(path).is_file():
        return None
    stat = Path(path).stat()
    return [str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns]


def _model_stamp(category: str, name: str) -> list | None:
    if not name or name.lower() in {"none", "无"}:
        return None
    path = folder_paths.get_full_path(category, name)
    return _file_stamp(path)


def _media_path(value: str) -> str:
    return resolve_media_path(value)


def _normalize_media_state(value: str) -> dict[str, Any]:
    try:
        state = json.loads(value or "{}")
    except (TypeError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}

    def entry(name: str) -> dict[str, Any]:
        value = state.get(name)
        if isinstance(value, str):
            value = {"file": value}
        if not isinstance(value, dict):
            return {"file": "", "kind": "person"} if name.startswith("character_") else {"file": ""}
        result = {"file": str(value.get("file") or value.get("filename") or "").strip()}
        if name.startswith("character_"):
            kind = str(value.get("kind") or "person").lower()
            result["kind"] = "object" if kind in {"object", "item", "product", "prop"} else "person"
        return result

    return {
        "video": entry("video"),
        "character_1": entry("character_1"),
        "character_2": entry("character_2"),
        "character_3": entry("character_3"),
        "character_4": entry("character_4"),
        "character_5": entry("character_5"),
        "character_6": entry("character_6"),
        "character_7": entry("character_7"),
        "background": entry("background"),
        "reference": entry("reference"),
    }


def _normalize_video_state(value: str) -> dict[str, Any]:
    return {"video": _normalize_media_state(value)["video"]}


def _normalize_asset_state(value: str) -> dict[str, Any]:
    state = _normalize_media_state(value)
    state.pop("video")
    return state


def _load_image(file: str):
    if not file:
        return None
    _media_path(file)
    return comfy_nodes.LoadImage().load_image(file)[0]


class CSRModelLoader:
    @classmethod
    def INPUT_TYPES(cls):
        diffusion = _files("diffusion_models")
        clips = _files("text_encoders")
        vaes = _files("vae")
        loras = [NONE_MODEL, *_files("loras")]
        required = {
            "fl2va_model": (diffusion, {"default": _model_default()}),
            "ref2va_model": (diffusion, {"default": _model_default()}),
            "task_mode": (TASK_CHOICES, {"default": TASK_CHOICES[0]}),
            "text_encoder": (clips, {"default": _clip_default()}),
            "video_vae": (vaes, {"default": _video_vae_default()}),
            "audio_vae": (vaes, {"default": _audio_vae_default()}),
            "attention_mode": (ATTENTION_CHOICES, {"default": ATTENTION_CHOICES[0]}),
        }
        defaults = {
            1: _turbo_lora_default(),
            2: _swap_lora_default(),
        }
        for index in range(1, LORA_SLOTS + 1):
            required[f"lora_{index}"] = (loras, {"default": defaults.get(index, NONE_MODEL)})
            required[f"lora_{index}_strength"] = (
                "FLOAT",
                {"default": 1.0, "min": -30.0, "max": 30.0, "step": 0.05},
            )
        optional = {
            f"lora_{index}_enabled": ("BOOLEAN", {"default": True})
            for index in range(1, LORA_SLOTS + 1)
        }
        return {"required": required, "optional": optional}

    RETURN_TYPES = ("CSR_MODEL_BUNDLE",)
    RETURN_NAMES = ("model_bundle",)
    FUNCTION = "load"
    CATEGORY = "AICG3D-CSR/独立节点"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        keys = ["fl2va_model", "ref2va_model", "task_mode", "text_encoder", "video_vae", "audio_vae", "attention_mode"]
        for index in range(1, LORA_SLOTS + 1):
            keys.extend((f"lora_{index}", f"lora_{index}_strength", f"lora_{index}_enabled"))
        return json.dumps([kwargs.get(key) for key in keys], ensure_ascii=False, sort_keys=True)

    def load(self, **kwargs):
        task_mode = str(kwargs.get("task_mode") or TASK_CHOICES[0])
        model_name = str(kwargs.get("ref2va_model") if task_mode.startswith("Ref2VA") else kwargs.get("fl2va_model"))
        if not model_name or model_name.lower() in {"none", "无"}:
            raise ValueError("请选择一个 MiniMax H3 主模型。")
        clip_name = str(kwargs.get("text_encoder") or "")
        video_vae_name = str(kwargs.get("video_vae") or "")
        audio_vae_name = str(kwargs.get("audio_vae") or "")
        if not clip_name or not video_vae_name:
            raise ValueError("文本编码器和视频 VAE 不能为空。")

        model = comfy_nodes.UNETLoader().load_unet(model_name, "default")[0]
        applied_loras = []
        for index in range(1, LORA_SLOTS + 1):
            lora_name = str(kwargs.get(f"lora_{index}") or NONE_MODEL)
            strength = float(kwargs.get(f"lora_{index}_strength") or 0.0)
            enabled = bool(kwargs.get(f"lora_{index}_enabled", True))
            if not enabled or lora_name.lower() in {"none", "无"}:
                continue
            model = comfy_nodes.LoraLoaderModelOnly().load_lora_model_only(model, lora_name, strength)[0]
            applied_loras.append({"name": lora_name, "strength": strength})
        clip = comfy_nodes.CLIPLoader().load_clip(clip_name, "minimax", "default")[0]
        vae = comfy_nodes.VAELoader().load_vae(video_vae_name)[0]
        bundle = {
            "bundle_type": "CSR_MODEL_BUNDLE",
            "version": BUNDLE_VERSION,
            "task_mode": "ref2va" if task_mode.startswith("Ref2VA") else "fl2va",
            "model_name": model_name,
            "fl2va_model_name": str(kwargs.get("fl2va_model") or ""),
            "ref2va_model_name": str(kwargs.get("ref2va_model") or ""),
            "clip_name": clip_name,
            "video_vae_name": video_vae_name,
            "audio_vae_name": audio_vae_name,
            "attention_mode": str(kwargs.get("attention_mode") or ATTENTION_CHOICES[0]),
            "loras": applied_loras,
            "model": model,
            "clip": clip,
            "vae": vae,
            "audio_vae": None,
        }
        summary = (
            f"MiniMax H3 Aicg 加载器：{task_mode} | {model_name} | "
            f"{len(applied_loras)} 个 LoRA | CLIP={clip_name} | VAE={video_vae_name}"
        )
        LOG.info("AICG3D-CSR: %s", summary)
        return (bundle,)


class CSRVideoCrop:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_bundle": ("CSR_MODEL_BUNDLE",),
                "video_state": ("STRING", {"default": "{}", "multiline": False}),
                "segment_ranges": (
                    "STRING",
                    {"default": json.dumps([{"start": 0, "end": 10.0}], ensure_ascii=False), "multiline": True},
                ),
                "short_edge": ([384, 480, 640, 720, 960], {"default": 480}),
                "resolution_preset": (list(RESOLUTION_CHOICES), {"default": RESOLUTION_CHOICES[0]}),
                "custom_width": ("INT", {"default": 0, "min": 0, "max": 8192, "step": 2}),
                "custom_height": ("INT", {"default": 0, "min": 0, "max": 8192, "step": 2}),
                "context_frames": ("INT", {"default": 22, "min": 0, "max": 90}),
                "seam_blend_frames": ("INT", {"default": 3, "min": 0, "max": 12}),
                "encoder": (list(ENCODER_CHOICES.values()), {"default": ENCODER_CHOICES["libx264"]}),
                "test_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 36000.0, "step": 0.1}),
            },
            "optional": {
                "aspect_ratio": (list(ASPECT_RATIO_CHOICES), {"default": "16:9"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("CSR_VIDEO_BUNDLE",)
    RETURN_NAMES = ("video_bundle",)
    FUNCTION = "load"
    CATEGORY = "AICG3D-CSR/独立节点"

    @classmethod
    def IS_CHANGED(cls, video_state="", **kwargs):
        state = _normalize_video_state(video_state)
        file = state["video"]["file"]
        try:
            stamp = _file_stamp(_media_path(file)) if file else None
        except ValueError:
            stamp = None
        values = [video_state, stamp, kwargs.get("segment_ranges"), kwargs.get("short_edge"),
                  kwargs.get("resolution_preset"), kwargs.get("custom_width"), kwargs.get("custom_height"),
                  kwargs.get("aspect_ratio"),
                  kwargs.get("context_frames"), kwargs.get("seam_blend_frames"), kwargs.get("encoder"),
                  kwargs.get("test_seconds")]
        return json.dumps(values, ensure_ascii=False, default=str)

    @classmethod
    def VALIDATE_INPUTS(cls, video_state="", encoder=None, **_kwargs):
        if encoder is not None and encoder not in ENCODER_CHOICES.values():
            return "视频编码器取值无效。"
        aspect_ratio = _kwargs.get("aspect_ratio")
        if aspect_ratio is not None and str(aspect_ratio) not in ASPECT_RATIO_CHOICES:
            return "输出宽高比取值无效。"
        resolution_preset = _kwargs.get("resolution_preset")
        if resolution_preset is not None and str(resolution_preset) not in RESOLUTION_CHOICES:
            return "输出分辨率取值无效。"
        file = _normalize_video_state(video_state)["video"]["file"]
        if not file:
            return "请先上传源视频。"
        try:
            _media_path(file)
        except ValueError as exc:
            return str(exc)
        return True

    def load(
        self,
        model_bundle,
        video_state,
        segment_ranges,
        short_edge,
        resolution_preset,
        custom_width,
        custom_height,
        context_frames,
        seam_blend_frames,
        encoder,
        test_seconds=0.0,
        aspect_ratio="16:9",
        unique_id=None,
    ):
        state = _normalize_video_state(video_state)
        video_file = state["video"]["file"]
        if not video_file:
            raise ValueError("请先在视频裁剪节点中上传源视频。")
        planner = CSRVideoSegments()
        plan, plan_summary = planner.prepare(
            video_file,
            segment_ranges,
            int(short_edge),
            int(context_frames),
            int(seam_blend_frames),
            encoder,
            float(test_seconds or 0.0),
            resolution_preset=str(resolution_preset),
            custom_width=int(custom_width),
            custom_height=int(custom_height),
            aspect_ratio=str(aspect_ratio or "16:9"),
        )
        bundle = {
            **model_bundle,
            "bundle_type": "CSR_VIDEO_BUNDLE",
            "video_state": state,
            "plan": plan,
            "plan_summary": plan_summary,
        }
        LOG.info("AICG3D-CSR video crop: %s", plan_summary.splitlines()[0])
        return (bundle,)


class CSRMediaAssets:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_bundle": ("CSR_VIDEO_BUNDLE",),
                "asset_state": ("STRING", {"default": "{}", "multiline": False}),
                "character_bindings": (
                    "STRING",
                    {
                        "default": DEFAULT_BINDINGS,
                        "multiline": True,
                    },
                ),
            },
        }

    RETURN_TYPES = ("CSR_JOB_BUNDLE",)
    RETURN_NAMES = ("job_bundle",)
    FUNCTION = "load"
    CATEGORY = "AICG3D-CSR/独立节点"

    @classmethod
    def IS_CHANGED(cls, asset_state="", character_bindings="", **_kwargs):
        state = _normalize_asset_state(asset_state)
        stamps = []
        for entry in state.values():
            try:
                stamps.append(_file_stamp(_media_path(entry["file"])) if entry["file"] else None)
            except ValueError:
                stamps.append(None)
        return json.dumps([asset_state, stamps, character_bindings], ensure_ascii=False, default=str)

    @classmethod
    def VALIDATE_INPUTS(cls, asset_state="", **_kwargs):
        try:
            state = _normalize_asset_state(asset_state)
            for entry in state.values():
                if entry["file"]:
                    _media_path(entry["file"])
            if not any(entry["file"] for entry in state.values()):
                return "请至少上传一张人物替换图、背景图或参考图。"
        except ValueError as exc:
            return str(exc)
        return True

    def load(self, video_bundle, asset_state, character_bindings):
        state = _normalize_asset_state(asset_state)
        character_keys = [f"character_{index}" for index in range(1, 8)]
        images = {
            **{key: _load_image(state[key]["file"]) for key in character_keys},
            "background": _load_image(state["background"]["file"]),
            "reference": _load_image(state["reference"]["file"]),
        }
        has_characters = any(images[key] is not None for key in character_keys)
        if not any(images[key] is not None for key in (*character_keys, "background", "reference")):
            raise ValueError("请至少上传一张人物替换图、背景图或参考图。")
        requested = "characters_and_scene" if has_characters and images["background"] is not None else "characters" if has_characters else "scene"
        subject_kinds = {key: state[key].get("kind", "person") for key in character_keys}
        references = CSRReferences().build(
            requested,
            character_bindings,
            False,
            subject_kinds=subject_kinds,
            **{key: images[key] for key in character_keys},
            scene=images["background"],
            master_frame=images["reference"],
        )[0]
        if len(references["images"]) > 9:
            raise ValueError(
                f"当前任务包含 {len(references['images'])} 张参考图，超过 H3 单次 9 张图片参考上限。"
                "请减少替换参考、背景或首帧，或拆分成多个顺序替换任务。"
            )
        bundle = {
            **video_bundle,
            "bundle_type": "CSR_JOB_BUNDLE",
            "references": references,
            "media_state": state,
            "media_stamps": {key: _file_stamp(_media_path(value["file"])) if value["file"] else None
                             for key, value in state.items()},
        }
        summary = (
            f"资源库：替换参考 {sum(images[key] is not None for key in character_keys)} 张；"
            f"背景 {int(images['background'] is not None)} 张；参考图 "
            f"{int(images['reference'] is not None)} 张"
        )
        LOG.info("AICG3D-CSR: %s", summary)
        return (bundle,)


class CSRMediaLibrary:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_bundle": ("CSR_MODEL_BUNDLE",),
                "media_state": ("STRING", {"default": "{}", "multiline": False}),
                "segment_ranges": (
                    "STRING",
                    {"default": json.dumps([{"start": 0, "end": 10.0}], ensure_ascii=False), "multiline": True},
                ),
                "character_bindings": (
                    "STRING",
                    {
                        "default": DEFAULT_BINDINGS,
                        "multiline": True,
                    },
                ),
                "short_edge": ([384, 480, 640, 720, 960], {"default": 480}),
                "context_frames": ("INT", {"default": 22, "min": 0, "max": 90}),
                "seam_blend_frames": ("INT", {"default": 3, "min": 0, "max": 12}),
                "encoder": (list(ENCODER_CHOICES.values()), {"default": ENCODER_CHOICES["libx264"]}),
                "test_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 36000.0, "step": 0.1}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("CSR_JOB_BUNDLE",)
    RETURN_NAMES = ("job_bundle",)
    FUNCTION = "load"
    CATEGORY = "AICG3D-CSR/独立节点"

    @classmethod
    def IS_CHANGED(cls, media_state="", **kwargs):
        state = _normalize_media_state(media_state)
        stamps = [_file_stamp(_media_path(entry["file"]) if entry["file"] else None) for entry in state.values()]
        values = [media_state, stamps, kwargs.get("segment_ranges"), kwargs.get("short_edge"),
                  kwargs.get("context_frames"), kwargs.get("seam_blend_frames"), kwargs.get("encoder"),
                  kwargs.get("test_seconds")]
        return json.dumps(values, ensure_ascii=False, default=str)

    @classmethod
    def VALIDATE_INPUTS(cls, media_state="", segment_ranges="", encoder=None, **_kwargs):
        if encoder is not None and encoder not in ENCODER_CHOICES.values():
            return "视频编码器取值无效。"
        try:
            state = _normalize_media_state(media_state)
            for item in state.values():
                if item["file"]:
                    _media_path(item["file"])
        except ValueError as exc:
            return str(exc)
        return True

    def load(
        self,
        model_bundle,
        media_state,
        segment_ranges,
        character_bindings,
        short_edge,
        context_frames,
        seam_blend_frames,
        encoder,
        test_seconds=0.0,
        unique_id=None,
    ):
        state = _normalize_media_state(media_state)
        video_file = state["video"]["file"]
        if not video_file:
            raise ValueError("请先在资源库中上传源视频。")
        character_keys = [f"character_{index}" for index in range(1, 8)]
        images = {
            **{key: _load_image(state[key]["file"]) for key in character_keys},
            "background": _load_image(state["background"]["file"]),
            "reference": _load_image(state["reference"]["file"]),
        }
        has_characters = any(images[key] is not None for key in character_keys)
        if not any(images[key] is not None for key in (*character_keys, "background", "reference")):
            raise ValueError("请至少上传一张人物替换图、背景图或参考图。")
        planner = CSRVideoSegments()
        plan, plan_summary = planner.prepare(
            video_file,
            segment_ranges,
            int(short_edge),
            int(context_frames),
            int(seam_blend_frames),
            encoder,
            float(test_seconds or 0.0),
        )
        requested = "characters_and_scene" if has_characters and images["background"] is not None else "characters" if has_characters else "scene"
        subject_kinds = {key: state[key].get("kind", "person") for key in character_keys}
        references = CSRReferences().build(
            requested,
            character_bindings,
            False,
            subject_kinds=subject_kinds,
            **{key: images[key] for key in character_keys},
            scene=images["background"],
            master_frame=images["reference"],
        )[0]
        bundle = {
            **model_bundle,
            "bundle_type": "CSR_JOB_BUNDLE",
            "references": references,
            "plan": plan,
            "media_state": state,
            "media_stamps": {key: _file_stamp(_media_path(value["file"])) if value["file"] else None
                             for key, value in state.items()},
            "plan_summary": plan_summary,
        }
        summary = (
            f"资源库：视频 {Path(video_file).name}；人物图 "
            f"{sum(images[key] is not None for key in character_keys)} 张；"
            f"背景 {int(images['background'] is not None)} 张；参考图 "
            f"{int(images['reference'] is not None)} 张；{plan_summary.splitlines()[0]}"
        )
        LOG.info("AICG3D-CSR: %s", summary)
        return (bundle,)


NODE_CLASS_MAPPINGS = {
    "CSRModelLoader": CSRModelLoader,
    "CSRMediaLibrary": CSRMediaLibrary,
    "CSRVideoCrop": CSRVideoCrop,
    "CSRMediaAssets": CSRMediaAssets,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "CSRModelLoader": "MiniMax H3 Aicg 加载器 · CSR独立版",
    "CSRMediaLibrary": "MiniMax H3 Aicg资源库（旧版合并） · CSR独立版",
    "CSRVideoCrop": "MiniMax H3 Aicg 视频裁剪 · CSR独立版",
    "CSRMediaAssets": "MiniMax H3 Aicg资源库 · CSR独立版",
}
