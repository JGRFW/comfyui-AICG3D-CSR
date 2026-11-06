"""AICG3D-CSR: free-range video segments with H3 replacement and seamless merge."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any

import comfy.model_management
import comfy.nested_tensor
import comfy.sample
import comfy.samplers
import comfy.utils
import folder_paths
import node_helpers
import numpy as np
import torch
import torch.nn.functional as F
from comfy_api.latest import InputImpl
from comfy_extras.nodes_custom_sampler import Guider_Basic
from comfy_extras.nodes_minimax_h3 import MiniMaxH3AddGuide, _empty_av_latent
from filelock import FileLock

from .media import (
    FPS,
    VideoError,
    encode_frames,
    extract_audio,
    merge_segments,
    normalize_video,
    plan_segments,
    probe,
    probe_audio,
    read_frames,
    resolution_canvas,
    write_json,
)
from .progress import CSRProgressMonitor
from .sequence_seam import export_with_seam_repair

CATEGORY = "AICG3D-CSR/人物场景替换"
LOG = logging.getLogger(__name__)
VERSION = "2.3.0"

TARGET_CHOICES = {
    "auto": "自动判断（推荐）",
    "characters_and_scene": "参考主体 + 场景",
    "characters": "仅参考主体（人物/物品）",
    "scene": "仅场景",
}
REF_SIZE_CHOICES = {
    "max": "最大2048（身份优先）",
    "match": "匹配成片（更快）",
}
REPLACEMENT_TAG_CHOICES = [
    "自定义",
    "单人替换",
    "多人替换",
    "商品替换",
    "人物替换",
    "背景/场景替换",
    "物品/产品替换",
    "人物 + 背景",
    "人物 + 物品",
    "人物 + 背景 + 物品",
]
ENCODER_CHOICES = {
    "libx264": "libx264（CPU·稳定）",
    "h264_nvenc": "h264_nvenc（NVIDIA加速）",
}
DEFAULT_BINDING_LINES = (
    "the leftmost designated source subject, corresponding to replacement reference 1; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 2; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 3; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 4; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 5; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 6; track this exact target in every frame",
    "the next distinct source subject to the right, corresponding to replacement reference 7; track this exact target in every frame",
)
DEFAULT_BINDINGS = "\n".join(DEFAULT_BINDING_LINES)
DEFAULT_RANGES = json.dumps(
    [{"start": 0.0, "end": 10.0}],
    ensure_ascii=False,
)


def choice_options(table: dict[str, str]) -> list[str]:
    return list(table.values())


def choice_key(value: Any, table: dict[str, str], default: str) -> str:
    text = str(value)
    if text in table:
        return text
    for key, label in table.items():
        if text == label:
            return key
    return default


def choice_valid(value: Any, table: dict[str, str]) -> bool:
    text = str(value)
    return text in table or text in set(table.values())


def disk_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        root = Path(folder_paths.get_output_directory()) / "AICG3D-CSR"
        root.mkdir(parents=True, exist_ok=True)
        with FileLock(str(root / ".operation.lock"), timeout=0):
            return function(*args, **kwargs)

    return wrapped


def local_file(value: str, *, optional: bool = False) -> str | None:
    text = str(value or "").strip().strip('"')
    if not text and optional:
        return None
    if not text:
        raise ValueError("请先上传并选择视频。")
    return resolve_media_path(text)


def resolve_media_path(value: str) -> str:
    """Resolve an uploaded media path without allowing arbitrary local reads."""
    text = str(value or "").strip().strip('"')
    if not text:
        raise ValueError("媒体路径为空。")
    candidate = Path(text)
    if candidate.is_absolute():
        path = candidate.resolve()
        roots = [
            Path(folder_paths.get_input_directory()).resolve(),
            Path(folder_paths.get_output_directory()).resolve(),
            Path(folder_paths.get_temp_directory()).resolve(),
        ]
        if not any(path.is_relative_to(root) for root in roots):
            raise ValueError("媒体文件必须位于 ComfyUI 的 input、output 或 temp 目录中。")
    else:
        path = Path(folder_paths.get_annotated_filepath(text)).resolve()
    if not path.is_file():
        raise ValueError(f"找不到已上传的媒体文件：{text}")
    return str(path)


def file_stamp(path: str | None) -> list | None:
    if not path:
        return None
    stat = Path(path).stat()
    return [str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns]


def output_file_ref(path: str | os.PathLike) -> tuple[str, str]:
    target = Path(path)
    try:
        relative = target.resolve().relative_to(Path(folder_paths.get_output_directory()).resolve())
        return relative.name, relative.parent.as_posix() if str(relative.parent) != "." else ""
    except (ValueError, OSError):
        return target.name, ""


def graph_file_stamps(prompt: dict | None) -> list:
    if not prompt:
        return []
    categories = {
        "unet_name": "diffusion_models",
        "clip_name": "text_encoders",
        "vae_name": "vae",
        "lora_name": "loras",
    }
    stamps = []
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        for key, value in node.get("inputs", {}).items():
            if not isinstance(value, str) or not value:
                continue
            category = categories.get(key)
            if node.get("class_type") == "ModelPatchLoader" and key == "name":
                category = "model_patches"
            path = folder_paths.get_full_path(category, value) if category else None
            if path and Path(path).is_file():
                stamps.append(file_stamp(path))
    return stamps


def graph_patch_signature(prompt: dict | None) -> str:
    """Fingerprint scalar settings from third-party model-patch nodes."""
    if not prompt:
        return ""
    ignored_classes = {"SaveVideo", "PreviewImage", "LoadImage", "Note", "Reroute"}
    entries = []
    for node_id, node in sorted(prompt.items(), key=lambda item: str(item[0])):
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        if not class_type or class_type.startswith("CSR") or class_type in ignored_classes:
            continue
        inputs = {}
        for key, value in (node.get("inputs") or {}).items():
            if key in {"model", "clip", "vae", "video", "images", "audio"}:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                inputs[key] = value
        if inputs:
            entries.append([str(node_id), class_type, inputs])
    if not entries:
        return ""
    encoded = json.dumps(entries, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def tensor_stamp(image: torch.Tensor) -> str:
    array = image[:1].detach().to("cpu").contiguous().numpy()
    return hashlib.sha256(array.tobytes()).hexdigest()


def fit_image(image: torch.Tensor, width: int, height: int) -> torch.Tensor:
    return comfy.utils.common_upscale(
        image[:1, ..., :3].movedim(-1, 1), width, height, "lanczos", "disabled"
    ).movedim(1, -1)


def frames_tensor(path: str, start: int, count: int, width: int, height: int, *, gray: bool = False) -> torch.Tensor:
    raw, actual = read_frames(path, start, count, width, height, gray=gray)
    shape = (actual, height, width) if gray else (actual, height, width, 3)
    array = np.frombuffer(raw, dtype=np.uint8).reshape(shape).copy()
    result = torch.from_numpy(array).float().div_(255.0)
    if actual < count:
        result = torch.cat([result, result[-1:].expand(count - actual, *result.shape[1:])], dim=0)
    return result


def encoded_reference(vae, image: torch.Tensor, width: int, height: int, mode: str):
    image_height, image_width = image.shape[1:3]
    if mode == "max":
        scale = min(1.0, 2048.0 / min(image_width, image_height))
    else:
        scale = min(1.0, math.sqrt(width * height / (image_width * image_height)))
    ref_width = max(32, round(image_width * scale / 32) * 32)
    ref_height = max(32, round(image_height * scale / 32) * 32)
    resized = fit_image(image, ref_width, ref_height)
    latent = vae.encode(resized).to(comfy.model_management.intermediate_device())
    item = {"type": "image", "data": resized}
    block = {
        "kind": "image",
        "latent_h": ref_height // 16,
        "latent_w": ref_width // 16,
        "latent": latent,
    }
    return item, block


def empty_video_latent(width: int, height: int, frame_count: int) -> dict:
    """Keep only one structural audio token; real audio is never sampled in CSR segments."""
    latent, _ = _empty_av_latent(width, height, frame_count)
    video, audio = latent["samples"].unbind()
    placeholder = audio[:, :, :, :1].clone()
    return {"samples": comfy.nested_tensor.NestedTensor((video, placeholder))}


def parse_bindings(text: str, slots: list[int]) -> list[str]:
    lines = (text or "").splitlines()
    return [
        lines[index - 1].strip()
        if index - 1 < len(lines) and lines[index - 1].strip()
        else DEFAULT_BINDING_LINES[min(index, len(DEFAULT_BINDING_LINES)) - 1]
        for index in slots
    ]


REASONING_LINE = re.compile(
    r"^\s*(?:the user wants|the user asks|i need to|i must|i should|let me|wait\b|now write|draft\b|analysis\s*:|reasoning\s*:)",
    re.IGNORECASE,
)
LEGACY_DEFAULT_BINDING = re.compile(
    r"^(?:the target person or object corresponding to replacement reference|the .*designated source subject, corresponding to replacement reference)",
    re.IGNORECASE,
)


def clean_replacement_description(value: str) -> str:
    """Remove optimizer reasoning so it can never be embedded into H3 conditioning."""
    text = str(value or "").strip()
    had_reasoning = False
    for tag in ("think", "analysis", "reasoning"):
        closing = list(re.finditer(rf"</{tag}\s*>", text, flags=re.IGNORECASE))
        if closing:
            had_reasoning = True
            text = text[closing[-1].end() :]
        elif re.search(rf"<{tag}\b", text, flags=re.IGNORECASE):
            had_reasoning = True
            text = re.sub(
                rf"<{tag}\b[^>]*>.*$",
                "",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
    text = re.sub(r"<\|(?:channel|analysis|reasoning)\|>", "", text, flags=re.IGNORECASE)
    kept = []
    for line in text.splitlines():
        if REASONING_LINE.search(line):
            had_reasoning = True
            continue
        kept.append(line)
    text = "\n".join(kept).strip()
    if had_reasoning and text and text[-1] not in ".!?。！？":
        complete = list(re.finditer(r"[.!?。！？](?=\s|$)", text))
        text = text[: complete[-1].end()].strip() if complete else ""
    return text


def effective_binding(binding: str, index: int, total: int, kind: str) -> str:
    text = str(binding or "").strip()
    if text and not LEGACY_DEFAULT_BINDING.search(text):
        return text
    if total <= 1:
        position = "the only designated source"
    elif index == 1:
        position = "the leftmost designated source"
    elif index == total:
        position = "the rightmost designated source"
    else:
        position = "the next distinct designated source"
    noun = "person" if kind == "person" else "object or product"
    return (
        f"{position} {noun} in <Video 1>, mapped only to replacement reference {index}; "
        "track this exact target in every frame and do not reuse it for another target"
    )


def inferred_replacement_tag(subjects: list, objects: list, scene_subject: str | None, fallback: str) -> str:
    if subjects and objects and scene_subject:
        return "人物 + 背景 + 物品"
    if subjects and scene_subject:
        return "人物 + 背景"
    if objects and scene_subject:
        return "物品 + 背景"
    if subjects and objects:
        return "人物 + 物品"
    if scene_subject:
        return "背景/场景替换"
    if len(subjects) > 1:
        return "多人替换"
    if subjects:
        return "单人替换"
    if objects:
        return "商品替换"
    return fallback or "自定义"


POSITION_HINTS = (
    ("left", "on the left side of the frame"),
    ("左", "on the left side of the frame"),
    ("right", "on the right side of the frame"),
    ("右", "on the right side of the frame"),
    ("center", "at the centre of the frame"),
    ("centre", "at the centre of the frame"),
    ("中间", "at the centre of the frame"),
    ("foreground", "in the foreground"),
    ("前景", "in the foreground"),
    ("background", "in the background"),
    ("背景", "in the background"),
)


def position_phrase(binding: str) -> str:
    lowered = (binding or "").lower()
    for hint, phrase in POSITION_HINTS:
        if hint in lowered:
            return phrase
    return "in the frame"


def references_prompt(references: dict, description: str, replacement_tags: str = "自定义") -> str:
    pictures: dict[int, str] = {}
    subjects = []
    objects = []
    scene_subject = None
    master_picture = None
    for ordinal, item in enumerate(references["images"], 1):
        tag = f"<Picture {ordinal}>"
        pictures[ordinal] = tag
        if item["role"] == "character":
            subjects.append((item["subject"], tag, item["binding"]))
        elif item["role"] == "object":
            objects.append((item["subject"], tag, item["binding"]))
        elif item["role"] == "scene":
            scene_subject = tag
        else:
            master_picture = tag

    subjects = [
        (subject, tag, effective_binding(binding, index, len(subjects), "person"))
        for index, (subject, tag, binding) in enumerate(subjects, 1)
    ]
    objects = [
        (subject, tag, effective_binding(binding, index, len(objects), "object"))
        for index, (subject, tag, binding) in enumerate(objects, 1)
    ]
    selected_tag = str(replacement_tags or "自定义").strip()
    effective_tag = inferred_replacement_tag(subjects, objects, scene_subject, selected_tag)

    lines = ["subject_definitions:"]
    person_total = len(subjects)
    for person_index, (subject, tag, binding) in enumerate(subjects, 1):
        lines.append(
            f"<Subject {subject}> is replacement person {person_index} of exactly {person_total}: {binding}. "
            f"It is bound one-to-one to {tag} and to one distinct source person only. "
            f"Take facial identity, hairstyle, body proportions and clothing from {tag} only; "
            "ignore its background, pose and lighting. No other person may reuse this reference."
        )
    object_total = len(objects)
    for object_index, (subject, tag, binding) in enumerate(objects, 1):
        lines.append(
            f"<Subject {subject}> is replacement object {object_index} of exactly {object_total}, shown in {tag}: {binding}. "
            f"Take its complete silhouette, scale, colours, material, texture, structure and identifying details from {tag} only; "
            "ignore its background and replace the corresponding source object or prop without redesigning it."
        )
    if person_total > 1:
        lines.append(
            f"Person count lock: exactly {person_total} distinct source people must be replaced by exactly {person_total} distinct replacement identities. "
            "Do not merge two targets, omit the less prominent target, duplicate one identity, or replace only the main character."
        )
    if scene_subject:
        scene_index = next(
            index for index, item in enumerate(references["images"], 1) if item["role"] == "scene"
        )
        lines.append(
            f"<Picture {scene_index}> is the complete replacement environment, not a person. "
            "It is the mandatory and sole source for the environment, not a style, colour or relighting reference. "
            "Cover every background pixel outside retained foreground subjects with its complete spatial layout, architecture, furniture, surfaces, colours and lighting. "
            "Delete all walls, floors, ceilings, windows, furniture, decor, room layout, materials and lighting patterns from <Video 1>; do not recolour, blur, partially retouch or blend the old scene. "
            f"Do not bring any person from <Picture {scene_index}> into the result."
        )
        if subjects or objects:
            lines.append(
                "The subject replacements and this complete environment replacement are simultaneous mandatory edits. "
                "Do not replace only the people, do not replace only the scene, and do not treat either task as optional."
            )
    if master_picture:
        lines.append(
            f"{master_picture} is the approved first frame of this segment, showing the final identities, "
            "costumes and environment already in place."
        )
    lines.append("<Video 1> is the source clip that supplies motion, timing, framing and performance.")

    targets = []
    if subjects:
        targets.append(
            "the selected actors in <Video 1> are re-identified as "
            + " and ".join(f"<Subject {subject}>" for subject, _, _ in subjects)
        )
    if objects:
        targets.append(
            "the selected held or placed objects in <Video 1> are replaced by "
            + " and ".join(f"<Subject {subject}>" for subject, _, _ in objects)
        )
    if scene_subject:
        targets.append(
            f"the complete environment behind and around all people in <Video 1> is replaced by {scene_subject}"
        )
    task = "[video editing]"
    if effective_tag and effective_tag != "自定义":
        task = f"[video editing][{effective_tag}]"
    simultaneous = (
        "All listed replacements are simultaneous requirements. Satisfy every category in the same output; "
        "do not satisfy only one person, only one object, or only the background."
    )
    summary_target = "; ".join(targets)
    if summary_target:
        summary_target = summary_target[0].upper() + summary_target[1:]
    lines += [
        "",
        "summary:",
        f"{task} The target clip is an edit of <Video 1>. {summary_target}. "
        f"{simultaneous} Everything else in <Video 1> remains unchanged.",
        "",
        "retention_analysis:",
        "<Video 1>: fully_preserved - duration, framing, camera movement, subject placement, "
        "action timing, mouth motion and source soundtrack are retained.",
    ]
    for subject, tag, binding in subjects:
        lines.append(
            f"<Subject {subject}>: attribute_transfer - identity, hairstyle, body proportions and clothing "
            f"from {tag} are transferred onto {binding}; motion still comes from <Video 1>."
        )
    for subject, tag, binding in objects:
        lines.append(
            f"<Subject {subject}>: attribute_transfer - silhouette, proportions, colour, material and construction "
            f"from {tag} replace the source object at {binding}; hand contact and motion still come from <Video 1>."
        )
    if scene_subject:
        lines.append(
            f"{scene_subject}: attribute_transfer - its entire architecture, room layout, furniture, surfaces, "
            "colours and lighting replace every background region while camera motion follows <Video 1>. "
            "This replacement is compulsory: the original walls, floor, ceiling, furniture, décor and room structure are removed, not merely recoloured. "
            "Every specified foreground replacement stays fixed to its own reference, and all occlusion, contact shadows, motion, framing and timing remain coherent."
        )
    if master_picture:
        lines.append(
            f"{master_picture}: fully_preserved - identities, clothing and environment remain consistent."
        )

    openings = [
        f"<Subject {subject}> appears {position_phrase(binding)}"
        for subject, _, binding in subjects
    ]
    openings.extend(
        f"<Subject {subject}> replaces the corresponding object {position_phrase(binding)}"
        for subject, _, binding in objects
    )
    if scene_subject:
        openings.append(
            f"{scene_subject} completely replaces the entire environment behind and around them, "
            "without preserving the original walls, furniture, floor, ceiling, décor or room layout"
        )
    shot = "[Shot 1] "
    if openings:
        shot += ", ".join(openings) + ". "
    if subjects:
        shot += (
            "Every replaced actor keeps the facial identity, hairstyle, body proportions and clothing "
            "from its own reference image while body motion, mouth motion and interaction timing follow "
            "<Video 1>. Do not create a different same-style person. "
        )
    if objects:
        shot += (
            "Every replacement object keeps the silhouette, scale, colour, material and structural details from "
            "its own reference image and remains naturally held or placed at the original location. "
        )
    if person_total > 1:
        shot += (
            f"Person count is locked at exactly {person_total}. Preserve the source person count and replace every designated target, "
            "using a separate one-to-one reference for each. Do not replace only the most prominent person, do not merge identities, "
            "do not reuse one reference for two people, and do not leave any designated child or adult unreplaced. "
        )
    if scene_subject and (subjects or objects):
        shot += (
            "Subject replacement and complete environment replacement are simultaneous mandatory edits. "
            "Do not return only replaced people with the old background, and do not return only the new background with unreplaced people. "
        )
    shot += description.strip() or (
        "Reproduce <Video 1> frame for frame in composition, subject placement, camera movement and body "
        "motion, applying only the requested identity and environment replacements."
    )
    lines += [
        "",
        "detailed_description:",
        shot,
        "",
        "overall_soundscape:",
        "No target audio is required. The source soundtrack is preserved as a separate file and muxed after all visual segments finish.",
        "",
        "non_diegetic_music:",
        "N/A",
    ]
    return "\n".join(lines)


def swap_lora_strengths(prompt: dict | None) -> list[tuple[str, float]]:
    found = []
    for node in (prompt or {}).values():
        if not isinstance(node, dict) or node.get("class_type") != "LoraLoaderModelOnly":
            continue
        inputs = node.get("inputs", {})
        name = str(inputs.get("lora_name", ""))
        if "character_swap" in name.lower() or "换人" in name:
            found.append((name, float(inputs.get("strength_model", 1.0))))
    return found


FACE_MODEL_HINTS = (
    ("ultralytics", "bbox", "face_yolov8m.pt"),
    ("ultralytics", "face_yolov8m.pt"),
    ("ultralytics", "bbox", "face_yolov8n.pt"),
)


@lru_cache(maxsize=1)
def face_detector():
    try:
        from ultralytics import YOLO
    except Exception as exc:  # noqa: BLE001
        LOG.warning("AICG3D-CSR: 未安装 ultralytics，锁脸自动跳过：%s", exc)
        return None
    for parts in FACE_MODEL_HINTS:
        path = os.path.join(folder_paths.models_dir, *parts)
        if os.path.isfile(path):
            try:
                return YOLO(path)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("AICG3D-CSR: 人脸检测模型加载失败：%s", exc)
                return None
    LOG.warning("AICG3D-CSR: 未找到 face_yolov8m.pt，锁脸自动跳过。")
    return None


def face_boxes(image: torch.Tensor) -> list[tuple[float, float, float, float]]:
    model = face_detector()
    if model is None or not isinstance(image, torch.Tensor):
        return []
    frame = image[0] if image.ndim == 4 else image
    try:
        array = (frame.detach().cpu().float().clamp(0, 1).numpy() * 255).astype("uint8")
        results = model(array, verbose=False)
    except Exception:  # noqa: BLE001
        return []
    boxes = []
    for result in results or []:
        raw = getattr(result, "boxes", None)
        if raw is None:
            continue
        for box in raw:
            try:
                x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
                confidence = float(box.conf[0]) if box.conf is not None else 1.0
            except Exception:  # noqa: BLE001
                continue
            if confidence >= 0.35 and x2 - x1 >= 8 and y2 - y1 >= 8:
                boxes.append((x1, y1, x2, y2))
    boxes.sort(key=lambda item: (item[2] - item[0]) * (item[3] - item[1]), reverse=True)
    return boxes


def face_region(box: tuple[float, float, float, float], width: int, height: int):
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    half = max(x2 - x1, y2 - y1) * 0.75
    left = int(max(0, cx - half))
    right = int(min(width, cx + half))
    top = int(max(0, cy - half * 1.15))
    bottom = int(min(height, cy + half * 1.05))
    if right - left < 16 or bottom - top < 16:
        return None
    return left, top, right, bottom


def face_crop(image: torch.Tensor) -> torch.Tensor | None:
    boxes = face_boxes(image)
    if not boxes:
        return None
    frame = image[0] if image.ndim == 4 else image
    region = face_region(boxes[0], int(frame.shape[1]), int(frame.shape[0]))
    if region is None:
        return None
    left, top, right, bottom = region
    return frame[top:bottom, left:right, :].detach().cpu().float().clamp(0, 1).contiguous()


def anchor_faces(base_frame: torch.Tensor, patches: list[torch.Tensor | None], width: int, height: int):
    usable = [patch for patch in patches if patch is not None]
    if not usable:
        return fit_image(base_frame[None], width, height), 0
    boxes = sorted(face_boxes(base_frame), key=lambda box: (box[0] + box[2]) / 2.0)
    if not boxes:
        return fit_image(base_frame[None], width, height), 0
    frame = base_frame.detach().cpu().float().clamp(0, 1)
    input_height, input_width = int(frame.shape[0]), int(frame.shape[1])
    pasted = 0
    for patch, box in zip(patches, boxes):
        if patch is None:
            continue
        region = face_region(box, input_width, input_height)
        if region is None:
            continue
        left, top, right, bottom = region
        canvas = frame.clone()
        resized = F.interpolate(
            patch.permute(2, 0, 1).unsqueeze(0),
            size=(bottom - top, right - left),
            mode="bilinear",
            align_corners=False,
        )[0].permute(1, 2, 0)
        ys = torch.linspace(-1.0, 1.0, bottom - top)
        xs = torch.linspace(-1.0, 1.0, right - left)
        mask = (1.0 - torch.sqrt(ys[:, None] ** 2 + xs[None, :] ** 2)).clamp(0.0, 1.0)
        mask = (mask / 0.45).clamp(0.0, 1.0).unsqueeze(-1)
        area = canvas[top:bottom, left:right, :]
        canvas[top:bottom, left:right, :] = area * (1.0 - mask) + resized * mask
        frame = canvas
        pasted += 1
    return fit_image(frame[None], width, height), pasted


class CSRVideoSegments:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = []
        for root, _, names in os.walk(input_dir):
            for name in names:
                if Path(name).suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}:
                    relative = os.path.relpath(os.path.join(root, name), input_dir)
                    files.append(relative.replace("\\", "/"))
        return {
            "required": {
                "video_file": (sorted(files) or [""], {"tooltip": "点击节点内的上传区域，或从已上传视频中选择。"}),
                "segment_ranges": ("STRING", {"default": DEFAULT_RANGES, "multiline": True, "tooltip": "由节点 UI 自动维护。"}),
                "short_edge": ([384, 480, 640, 720, 960], {"default": 480, "tooltip": "输出短边。预览用 480，正式可用 640/720。"}),
                "context_frames": ("INT", {"default": 22, "min": 0, "max": 90, "step": 1, "tooltip": "每段从上一段取多少帧作为动作上下文；这些帧不会重复输出。"}),
                "seam_blend_frames": ("INT", {"default": 3, "min": 0, "max": 12, "step": 1, "tooltip": "跨段接缝处对前几帧做短过渡；0 表示完全由上下文与统一重编码保证连续。"}),
                "encoder": (choice_options(ENCODER_CHOICES), {"default": ENCODER_CHOICES["libx264"]}),
            },
            "optional": {
                "test_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 36000.0, "step": 0.1, "tooltip": "0=处理完整视频；调试时可只截取前几秒。"}),
            },
        }

    RETURN_TYPES = ("CSR_VIDEO_PLAN", "STRING")
    RETURN_NAMES = ("plan", "plan_summary")
    FUNCTION = "prepare"
    CATEGORY = CATEGORY

    @classmethod
    def VALIDATE_INPUTS(cls, video_file=None, encoder=None):
        if video_file is not None and str(video_file) and not folder_paths.exists_annotated_filepath(str(video_file)):
            return f"找不到上传视频：{video_file}"
        if encoder is not None and not choice_valid(encoder, ENCODER_CHOICES):
            return "视频编码器取值无效。"
        return True

    @classmethod
    def IS_CHANGED(cls, video_file="", segment_ranges="", short_edge=480, context_frames=22, seam_blend_frames=3, encoder="", test_seconds=0.0, resolution_preset="默认（短边）", custom_width=0, custom_height=0, aspect_ratio="跟随源视频"):
        path = local_file(video_file, optional=True)
        return json.dumps(
            [file_stamp(path), segment_ranges, short_edge, context_frames, seam_blend_frames, encoder, test_seconds,
             resolution_preset, custom_width, custom_height, aspect_ratio],
            ensure_ascii=False,
        )

    @disk_operation
    def prepare(
        self,
        video_file,
        segment_ranges,
        short_edge,
        context_frames,
        seam_blend_frames,
        encoder,
        test_seconds=0.0,
        resolution_preset="默认（短边）",
        custom_width=0,
        custom_height=0,
        aspect_ratio="跟随源视频",
    ):
        source = local_file(video_file)
        info = probe(source, count_frames=True)
        usable_seconds = info["duration"]
        if test_seconds and test_seconds > 0:
            usable_seconds = min(usable_seconds, float(test_seconds))
        width, height, output_width, output_height = resolution_canvas(
            info["width"],
            info["height"],
            int(short_edge),
            resolution_preset,
            int(custom_width),
            int(custom_height),
            aspect_ratio,
        )
        token = hashlib.sha256(
            json.dumps([file_stamp(source), width, height, output_width, output_height, usable_seconds], ensure_ascii=False).encode()
        ).hexdigest()[:24]
        source_dir = Path(folder_paths.get_output_directory()) / "AICG3D-CSR" / ("source_" + token)
        source_dir.mkdir(parents=True, exist_ok=True)
        audio_path = source_dir / "source_audio.wav"
        audio_info = None
        if info["has_audio"]:
            if audio_path.is_file():
                audio_info = probe_audio(audio_path)
            else:
                audio_info = extract_audio(
                    source,
                    audio_path,
                    audio_offset=float(info["audio_offset"]),
                    duration_seconds=usable_seconds,
                )
        normalized = source_dir / "normalized.mp4"
        if normalized.is_file():
            normalized_info = probe(normalized, count_frames=True)
        else:
            normalized_info = normalize_video(
                source,
                normalized,
                width,
                height,
                duration_seconds=usable_seconds if test_seconds else 0,
            )
        source_frames = int(normalized_info["frames"])
        if source_frames < 1:
            normalized_info = probe(normalized, count_frames=True)
            source_frames = int(normalized_info["frames"])
        if source_frames < 1:
            raise VideoError("规范化后没有得到有效帧。")
        segments = plan_segments(
            source_frames,
            segment_ranges,
            context_frames=int(context_frames),
        )
        output_frames = sum(segment.output_frames for segment in segments)
        target_start_frame = segments[0].start
        target_end_frame = segments[-1].end
        encoder = choice_key(encoder, ENCODER_CHOICES, "libx264")
        plan = {
            "version": VERSION,
            "source": source,
            "source_stamp": file_stamp(source),
            "audio_path": str(audio_path) if audio_info is not None else None,
            "audio_stamp": file_stamp(str(audio_path)) if audio_info is not None else None,
            "audio_info": audio_info,
            "audio_separated": True,
            "segment_audio": False,
            "h3_audio_placeholder_frames": 1,
            "normalized": str(normalized),
            "normalized_stamp": file_stamp(str(normalized)),
            "width": width,
            "height": height,
            "output_width": output_width,
            "output_height": output_height,
            "resolution_preset": resolution_preset,
            "aspect_ratio": str(aspect_ratio or "跟随源视频"),
            "fps": FPS,
            "source_total_frames": source_frames,
            "source_duration_seconds": source_frames / FPS,
            "target_start_frame": target_start_frame,
            "target_end_frame": target_end_frame,
            "target_start_seconds": target_start_frame / FPS,
            "target_end_seconds": target_end_frame / FPS,
            "total_frames": output_frames,
            "duration_seconds": output_frames / FPS,
            "context_frames": int(context_frames),
            "seam_blend_frames": int(seam_blend_frames),
            "encoder": encoder,
            "segments": [segment.as_dict() for segment in segments],
        }
        plan["plan_digest"] = hashlib.sha256(
            json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:24]
        write_json(source_dir / "plan.json", plan)
        lines = [
            f"AICG3D-CSR 分段计划：模型画布 {width}x{height} / 输出 {output_width}x{output_height} / {FPS}fps / "
            f"目标 {target_start_frame / FPS:.3f}-{target_end_frame / FPS:.3f}s / {output_frames}帧 / {output_frames / FPS:.3f}秒",
            f"共 {len(segments)} 段；上下文 {context_frames} 帧；接缝过渡 {seam_blend_frames} 帧；编码器 {encoder}",
            (
                f"音频已剥离：{audio_path}；分段视频不携带音频。"
                if audio_info is not None
                else "源视频没有音轨；分段与最终合并均不生成音频。"
            ),
        ]
        for segment in segments:
            lines.append(
                f"第 {segment.index + 1} 段：{segment.start / FPS:.3f}-{segment.end / FPS:.3f}s，"
                f"输出 {segment.output_frames} 帧，模型输入 {segment.model_frames} 帧"
            )
        LOG.info("AICG3D-CSR: %s", lines[0])
        return plan, "\n".join(lines)


class CSRReferences:
    CHARACTER_SLOTS = 7
    TARGETS = {"auto", "characters_and_scene", "characters", "scene"}

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            f"character_{index}": ("IMAGE", {"tooltip": f"替换参考 {index}；可为人物、产品、背包或其他物品，不需要时断开。"})
            for index in range(1, cls.CHARACTER_SLOTS + 1)
        }
        optional["scene"] = ("IMAGE", {"tooltip": "目标场景图；断开则保留原视频环境。"})
        optional["master_frame"] = ("IMAGE", {"tooltip": "可选目标首帧；连接后会作为第一段起始关键帧。"})
        return {
            "required": {
                "target": (choice_options(TARGET_CHOICES), {"default": TARGET_CHOICES["auto"]}),
                "character_bindings": (
                    "STRING",
                    {
                        "default": DEFAULT_BINDINGS,
                        "multiline": True,
                        "tooltip": "每行对应一个替换参考槽位，可用于人物或物品的空间绑定描述。",
                    },
                ),
                "require_master_frame": ("BOOLEAN", {"default": False}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("CSR_REFERENCES",)
    RETURN_NAMES = ("references",)
    FUNCTION = "build"
    CATEGORY = CATEGORY

    @classmethod
    def VALIDATE_INPUTS(cls, target=None):
        return True if choice_valid(target, TARGET_CHOICES) else "替换目标取值无效。"

    def build(
        self,
        target,
        character_bindings=DEFAULT_BINDINGS,
        require_master_frame=False,
        subject_kinds=None,
        **slots,
    ):
        target = choice_key(target, TARGET_CHOICES, "auto")
        subject_kinds = subject_kinds or {}
        subjects = []
        for index in range(1, self.CHARACTER_SLOTS + 1):
            image = slots.get(f"character_{index}")
            if image is None:
                continue
            if not torch.is_tensor(image) or image.ndim != 4:
                raise ValueError(f"替换参考 {index} 不是有效图像张量。")
            raw_kind = str(subject_kinds.get(f"character_{index}", "person")).lower()
            kind = "object" if raw_kind in {"object", "item", "product", "prop"} else "person"
            subjects.append(
                {
                    "role": "character" if kind == "person" else "object",
                    "kind": kind,
                    "slot": index,
                    "subject": len(subjects) + 1,
                    "image": image[:1].clone(),
                }
            )
        characters = [item for item in subjects if item["role"] == "character"]
        objects = [item for item in subjects if item["role"] == "object"]
        scene = slots.get("scene")
        master = slots.get("master_frame")
        if scene is not None and (not torch.is_tensor(scene) or scene.ndim != 4):
            raise ValueError("场景参考图不是有效图像张量。")
        if master is not None and (not torch.is_tensor(master) or master.ndim != 4):
            raise ValueError("目标首帧不是有效图像张量。")
        for item, binding in zip(subjects, parse_bindings(character_bindings, [item["slot"] for item in subjects])):
            item["binding"] = binding
        has_subjects, has_scene, has_master = bool(subjects), scene is not None, master is not None
        if target == "auto":
            resolved = (
                "characters_and_scene"
                if has_subjects and has_scene
                else "characters"
                if has_subjects
                else "scene"
                if has_scene
                else "master_only"
                if has_master
                else "empty"
            )
        elif target == "characters_and_scene":
            resolved = (
                "characters_and_scene"
                if has_subjects and has_scene
                else "characters"
                if has_subjects
                else "scene"
                if has_scene
                else "master_only"
                if has_master
                else "empty"
            )
        elif target == "characters":
            resolved = "characters" if has_subjects else "scene" if has_scene else "master_only" if has_master else "empty"
        else:
            resolved = "scene" if has_scene else "characters" if has_subjects else "master_only" if has_master else "empty"
        if resolved == "empty":
            raise ValueError("请至少连接一张人物图、场景图或目标首帧。")
        if require_master_frame and master is None:
            raise ValueError("已勾选必须提供目标首帧，但没有连接目标首帧。")
        ignore_master_for_scene = bool(
            master is not None
            and scene is not None
            and resolved in ("scene", "characters_and_scene")
        )
        images = list(subjects) if resolved in ("characters", "characters_and_scene") else []
        if resolved in ("scene", "characters_and_scene") and scene is not None:
            images.append({"role": "scene", "image": scene[:1].clone()})
        if master is not None and not ignore_master_for_scene:
            images.append({"role": "master", "image": master[:1].clone()})
        return (
            {
                "target": resolved,
                "requested_target": target,
                "images": images,
                "master": master[:1].clone() if master is not None and not ignore_master_for_scene else None,
                "ignored_master_for_scene": ignore_master_for_scene,
                "counts": {
                    "characters": len(characters),
                    "objects": len(objects),
                    "scene": int(scene is not None),
                    "master": int(master is not None),
                },
            },
        )


class CSRSegmentReplace:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "job_bundle": ("CSR_JOB_BUNDLE",),
                "description": (
                    "STRING",
                    {
                        "default": (
                            "把画面中的目标人物替换为人物1；保留原视频的镜头、身体动作、口型、"
                            "人物站位与互动节奏，不增加原视频没有的动作。"
                        ),
                        "multiline": True,
                    },
                ),
                "replacement_tags": (REPLACEMENT_TAG_CHOICES, {"default": "自定义"}),
                "steps": ("INT", {"default": 8, "min": 1, "max": 100}),
                "sampler_name": (comfy.samplers.SAMPLER_NAMES, {"default": "er_sde"}),
                "scheduler": (comfy.samplers.SCHEDULER_NAMES, {"default": "beta"}),
                "seed": ("INT", {"default": 123456, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "ref_image_size": (choice_options(REF_SIZE_CHOICES), {"default": REF_SIZE_CHOICES["max"]}),
                "face_anchor": ("BOOLEAN", {"default": False, "tooltip": "单人换脸失败时可开启；多人不建议。"}),
                "source_reference_scale": ("FLOAT", {"default": 1.0, "min": 0.05, "max": 1.0, "step": 0.05}),
                "audio_reuse": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "兼容项。真实音轨已在 MiniMax H3 Aicg资源库中剥离，并在 CSR ④ 全部分段合并后追加，不参与任何分段采样。",
                    },
                ),
                "resume_completed": ("BOOLEAN", {"default": True}),
                "live_preview": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "在节点底部实时显示当前段画面。预览解码有额外开销，可关闭但进度面板仍保留。",
                    },
                ),
                "preview_every_steps": (
                    "INT",
                    {"default": 2, "min": 1, "max": 100, "step": 1},
                ),
                "preview_resolution": (
                    [256, 384, 512, 768],
                    {"default": 512, "tooltip": "实时 JPEG 预览的最大边长。数值越高越清晰，解码开销也越大。"},
                ),
            },
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("CSR_RENDERED_SEGMENTS",)
    RETURN_NAMES = ("rendered_segments",)
    FUNCTION = "render"
    CATEGORY = CATEGORY

    @classmethod
    def VALIDATE_INPUTS(cls, ref_image_size=None, replacement_tags=None):
        if replacement_tags is not None and str(replacement_tags) not in REPLACEMENT_TAG_CHOICES:
            return "替换标签取值无效。"
        return True if choice_valid(ref_image_size, REF_SIZE_CHOICES) else "参考图尺寸取值无效。"

    @disk_operation
    def render(
        self,
        job_bundle,
        description,
        replacement_tags,
        steps,
        sampler_name,
        scheduler,
        seed,
        ref_image_size,
        face_anchor,
        source_reference_scale,
        audio_reuse,
        resume_completed,
        live_preview,
        preview_every_steps,
        preview_resolution,
        model_patch=None,
        prompt=None,
        unique_id=None,
    ):
        model = job_bundle["model"]
        clip = job_bundle["clip"]
        vae = job_bundle["vae"]
        plan = job_bundle["plan"]
        references = job_bundle["references"]
        model_patch = job_bundle.get("model_patch")
        raw_description = str(description or "")
        description = clean_replacement_description(raw_description)
        if description != raw_description.strip():
            LOG.warning("AICG3D-CSR: removed prompt-optimizer reasoning or truncated text before H3 conditioning.")
        if file_stamp(plan["source"]) != plan["source_stamp"]:
            raise ValueError("源视频已变化，请重新执行 MiniMax H3 Aicg资源库。")
        if file_stamp(plan["normalized"]) != plan["normalized_stamp"]:
            raise ValueError("规范化缓存已变化，请重新执行 MiniMax H3 Aicg资源库。")
        if plan.get("audio_path") and file_stamp(plan["audio_path"]) != plan.get("audio_stamp"):
            raise ValueError("独立音轨缓存已变化，请重新执行 MiniMax H3 Aicg资源库。")
        ref_image_size = choice_key(ref_image_size, REF_SIZE_CHOICES, "max")
        width, height = int(plan["width"]), int(plan["height"])
        characters = [item for item in references["images"] if item["role"] == "character"]
        warnings = []
        if job_bundle.get("external_model_patch"):
            LOG.info(
                "AICG3D-CSR: using external MODEL patch %s for sampling.",
                job_bundle.get("external_model_patch_type") or "unknown",
            )
        if references.get("ignored_master_for_scene"):
            warnings.append(
                "检测到背景替换与参考/首帧同时上传；为避免旧首帧锁住原背景，已自动忽略该首帧的环境引导。"
            )
        if len(characters) > 1:
            warnings.append(
                "本次连接了多个人物参考图。公开 H3 Character Swap LoRA 的稳定路线通常是一遍只换一个人；"
                "多人建议拆成多个 CSR ③ 节点顺序执行。"
            )
        for name, strength in swap_lora_strengths(prompt):
            if len(characters) > 1 and strength > 0.3:
                warnings.append(
                    f"检测到换人 LoRA「{os.path.basename(name)}」强度 {strength:g}，多人同时替换容易只换到一个人。"
                )
        face_patches = []
        if face_anchor:
            face_patches = [face_crop(item["image"]) for item in characters]
            if len(characters) > 1:
                warnings.append("多人任务开启了锁脸；人脸可能被重复绑定，建议关闭。")
        settings = {
            "description": description,
            "replacement_tags": replacement_tags,
            "steps": int(steps),
            "sampler": sampler_name,
            "scheduler": scheduler,
            "seed": int(seed),
            "ref_image_size": ref_image_size,
            "face_anchor": bool(face_anchor),
            "source_reference_scale": float(source_reference_scale),
            "audio_mode": "separate_track_post_mux",
            "has_model_patch": model_patch is not None,
            "has_external_model_patch": bool(job_bundle.get("external_model_patch")),
            "external_model_patch_type": str(job_bundle.get("external_model_patch_type") or ""),
        }
        reference_stamps = [
            {key: value for key, value in item.items() if key != "image"} | {"sha256": tensor_stamp(item["image"])}
            for item in references["images"]
        ]
        digest = hashlib.sha256(
            json.dumps(
                [
                    plan,
                    settings,
                    reference_stamps,
                    graph_file_stamps(prompt),
                    graph_patch_signature(prompt),
                    VERSION,
                    "CSR-segment-replace",
                ],
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ).encode()
        ).hexdigest()[:24]
        job = Path(folder_paths.get_output_directory()) / "AICG3D-CSR" / ("job_" + digest)
        segments_dir = job / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)
        base_prompt = references_prompt(references, description, replacement_tags)
        LOG.info("AICG3D-CSR prompt sections: %s", [line for line in base_prompt.splitlines() if line.endswith(":")])

        monitor = CSRProgressMonitor(unique_id)
        monitor.configure_preview(model)
        total_segments = len(plan["segments"])
        processed_frames = 0
        last_segment_file = None
        last_segment_subfolder = None
        last_steps = 0
        first = plan["segments"][0] if plan["segments"] else {"start": 0, "end": 0}
        monitor.emit(
            phase="start",
            overall=0.0,
            segment_index=0,
            total_segments=total_segments,
            segment_start=int(first["start"]),
            segment_end=int(first["end"]),
            total_frames=int(plan["total_frames"]),
            live_preview=False,
        )

        cached_images = None
        previous_tail = None
        paths, reports = [], []
        start_time = time.perf_counter()
        boundaries = []
        output_offset = 0
        for segment in plan["segments"][:-1]:
            output_offset += int(segment["output_frames"])
            boundaries.append(output_offset)
        for segment in plan["segments"]:
            comfy.model_management.throw_exception_if_processing_interrupted()
            index = int(segment["index"])
            prefix, model_frames = int(segment["prefix"]), int(segment["model_frames"])
            keep = int(segment["output_frames"])
            target = segments_dir / f"segment_{index:05d}.mp4"
            marker = target.with_suffix(".json")
            if resume_completed and target.is_file() and marker.is_file():
                try:
                    record = json.loads(marker.read_text(encoding="utf-8"))
                    valid = (
                        record.get("digest") == digest
                        and record.get("frames") == keep
                        and record.get("sha256") == hashlib.sha256(target.read_bytes()).hexdigest()
                        and probe(target, count_frames=True)["frames"] == keep
                    )
                except (OSError, ValueError, json.JSONDecodeError, VideoError):
                    valid = False
                if valid:
                    paths.append(str(target))
                    tail_count = min(
                        max(int(plan.get("context_frames", 0)), int(plan.get("seam_blend_frames", 0))),
                        keep,
                    )
                    previous_tail = (
                        frames_tensor(str(target), keep - tail_count, tail_count, width, height)
                        if tail_count
                        else None
                    )
                    reports.append(
                        {
                            "segment": index,
                            "resumed": True,
                            "frames": keep,
                            "start_frame": segment["start"],
                            "end_frame": segment["end"],
                        }
                    )
                    processed_frames += keep
                    segment_file, segment_subfolder = output_file_ref(target)
                    last_segment_file, last_segment_subfolder = segment_file, segment_subfolder
                    overall = processed_frames / max(1, int(plan["total_frames"]))
                    monitor.emit(
                        phase="resumed",
                        overall=overall,
                        segment_index=index,
                        total_segments=total_segments,
                        segment_start=int(segment["start"]),
                        segment_end=int(segment["end"]),
                        total_frames=int(plan["total_frames"]),
                        segment_file=segment_file,
                        segment_subfolder=segment_subfolder,
                        live_preview=False,
                    )
                    continue

            segment_started = time.perf_counter()
            monitor.emit(
                phase="preparing",
                overall=processed_frames / max(1, int(plan["total_frames"])),
                segment_index=index,
                total_segments=total_segments,
                segment_start=int(segment["start"]),
                segment_end=int(segment["end"]),
                total_frames=int(plan["total_frames"]),
                live_preview=False,
            )
            LOG.info(
                "AICG3D-CSR render %d/%d source[%d:%d] prefix=%d",
                index + 1,
                len(plan["segments"]),
                segment["start"],
                segment["end"],
                prefix,
            )
            if cached_images is None:
                cached_images = [
                    encoded_reference(vae, item["image"], width, height, ref_image_size)
                    for item in references["images"]
                ]
            source = frames_tensor(plan["normalized"], int(segment["input_start"]), model_frames, width, height)
            real_count = prefix + keep
            if real_count < model_frames:
                source[real_count:] = source[real_count - 1 : real_count]

            ref_width = max(32, round(width * float(source_reference_scale) / 32) * 32)
            ref_height = max(32, round(height * float(source_reference_scale) / 32) * 32)
            source_ref = comfy.utils.common_upscale(
                source.movedim(-1, 1), ref_width, ref_height, "bilinear", "disabled"
            ).movedim(1, -1)
            source_latent = vae.encode(source_ref).to(comfy.model_management.intermediate_device())
            items = [item[0] for item in cached_images]
            items.append(
                {
                    "type": "video",
                    "data": source_ref[::12],
                    "timestamps": [frame / 2 for frame in range(len(source_ref[::12]))],
                }
            )
            blocks = [item[1] for item in cached_images]
            blocks.append(
                {
                    "kind": "video",
                    "latent_t": source_latent.shape[2],
                    "latent_h": ref_height // 16,
                    "latent_w": ref_width // 16,
                    "ref_audio_t": 0,
                    "latent": source_latent,
                    "audio_latent": None,
                }
            )
            tokens = clip.tokenize(base_prompt, minimax_ref_items=items)
            positive = clip.encode_from_tokens_scheduled(tokens)
            positive = node_helpers.conditioning_set_values(positive, {"minimax_refs": blocks})
            latent = empty_video_latent(width, height, model_frames)

            guide = None
            if prefix and previous_tail is not None:
                if previous_tail.shape[0] < prefix:
                    raise RuntimeError("上一段尾帧不足，不能继承当前段的上下文。")
                guide = previous_tail[-prefix:]
            elif index == 0 and references.get("master") is not None:
                guide = references["master"]
            anchored = 0
            if face_patches:
                base = (guide[0] if guide is not None else source[prefix]).detach().cpu().float()
                anchored_frame, anchored = anchor_faces(base, face_patches, width, height)
                if anchored:
                    guide = anchored_frame if guide is None else torch.cat([anchored_frame, guide[1:]], dim=0)
            if guide is not None:
                positive = MiniMaxH3AddGuide.execute(positive, latent, 0, vae=vae, image=guide).result[0]

            segment_model = model
            if model_patch is not None:
                from comfy_extras.nodes_minimax_h3 import MiniMaxH3FunControlNetApply

                control = source[prefix : prefix + keep]
                segment_model = MiniMaxH3FunControlNetApply.execute(
                    model,
                    model_patch,
                    vae,
                    0.8,
                    0.0,
                    1.0,
                    control_video=control,
                ).result[0]
            guider = Guider_Basic(segment_model)
            guider.set_conds(positive)
            sigmas = comfy.samplers.calculate_sigmas(
                segment_model.get_model_object("model_sampling"), scheduler, int(steps)
            ).cpu()
            noise = comfy.sample.prepare_noise(latent["samples"], int(seed))
            progress = comfy.utils.ProgressBar(int(steps))

            def callback(step, x0, _x, total):
                progress.update_absolute(step + 1, total)
                step_ratio = min(1.0, (step + 1) / max(1, int(total)))
                overall = (processed_frames + keep * step_ratio) / max(1, int(plan["total_frames"]))
                elapsed = monitor._elapsed()
                eta = elapsed * (1.0 - overall) / overall if overall > 0.02 else None
                monitor.emit(
                    phase="sampling",
                    overall=overall,
                    segment_index=index,
                    total_segments=total_segments,
                    segment_start=int(segment["start"]),
                    segment_end=int(segment["end"]),
                    total_frames=int(plan["total_frames"]),
                    step=step + 1,
                    steps=int(total),
                    eta=eta,
                    x0=x0,
                    live_preview=bool(live_preview),
                    preview_every_steps=int(preview_every_steps),
                    preview_resolution=int(preview_resolution),
                )

            samples = guider.sample(
                noise,
                latent["samples"],
                comfy.samplers.sampler_object(sampler_name),
                sigmas,
                callback=callback,
                disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
                seed=int(seed),
            )
            if not samples.is_nested or len(samples.tensors) != 2:
                raise RuntimeError("当前模型不是 MiniMax H3 AV 模型，请使用匹配的 H3 模型、文本编码器和 VAE。")
            monitor.emit(
                phase="decoding",
                overall=(processed_frames + keep * 0.98) / max(1, int(plan["total_frames"])),
                segment_index=index,
                total_segments=total_segments,
                segment_start=int(segment["start"]),
                segment_end=int(segment["end"]),
                total_frames=int(plan["total_frames"]),
                step=int(steps),
                steps=int(steps),
                live_preview=False,
            )
            samples = samples.to(torch.device("cpu"))
            decoded = vae.decode(samples.tensors[0])
            if decoded.ndim == 5:
                decoded = decoded.reshape(-1, *decoded.shape[-3:])
            if decoded.shape[0] < prefix + keep:
                raise RuntimeError("VAE 解码帧数不足，拒绝用拉伸时长掩盖错误。")
            decoded = decoded[prefix : prefix + keep, ..., :3].detach().cpu().clone().clamp_(0, 1)
            reference_frames = source[prefix : prefix + keep].cpu()

            blend_count = int(plan.get("seam_blend_frames", 0)) if index > 0 and previous_tail is not None else 0
            blend_count = min(blend_count, keep, previous_tail.shape[0] if previous_tail is not None else 0)
            if blend_count > 0:
                previous = previous_tail[-blend_count:].to(decoded.device)
                blended = []
                for frame_index in range(blend_count):
                    alpha = 1.0 - frame_index / blend_count
                    blended.append(
                        (previous[frame_index] * alpha + decoded[frame_index] * (1.0 - alpha)).clamp_(0, 1)
                    )
                blended[0] = previous[-1].clone()
                decoded = torch.cat([torch.stack(blended, dim=0), decoded[blend_count:]], dim=0)
            boundary_lock_delta = (
                float((decoded[0] - previous_tail[-1]).abs().mean())
                if index > 0 and previous_tail is not None
                else None
            )

            delta = (decoded - reference_frames).abs()
            deviation = float(delta.mean())
            half = width // 2
            left_deviation = float(delta[:, :, :half].mean())
            right_deviation = float(delta[:, :, half:].mean())
            if deviation < 0.06:
                warnings.append(
                    f"第 {index + 1} 段与源片平均差异仅 {deviation:.4f}，可能没有真正替换人物或场景。"
                )
            temporary = target.with_name(target.stem + ".partial.mp4")
            encode_frames(
                temporary,
                (
                    frame.mul(255).round().to(torch.uint8).contiguous().numpy().tobytes()
                    for frame in decoded
                ),
                width,
                height,
                encoder=plan["encoder"],
            )
            if probe(temporary, count_frames=True)["frames"] != keep:
                raise RuntimeError("片段编码后的帧数不正确。")
            os.replace(temporary, target)
            processed_frames += keep
            segment_file, segment_subfolder = output_file_ref(target)
            last_segment_file, last_segment_subfolder = segment_file, segment_subfolder
            last_steps = int(steps)
            monitor.emit(
                phase="segment_saved",
                overall=processed_frames / max(1, int(plan["total_frames"])),
                segment_index=index,
                total_segments=total_segments,
                segment_start=int(segment["start"]),
                segment_end=int(segment["end"]),
                total_frames=int(plan["total_frames"]),
                step=int(steps),
                steps=int(steps),
                segment_file=segment_file,
                segment_subfolder=segment_subfolder,
                live_preview=False,
            )
            tail_count = min(
                max(int(plan.get("context_frames", 0)), int(plan.get("seam_blend_frames", 0))),
                keep,
            )
            previous_tail = (
                frames_tensor(str(target), keep - tail_count, tail_count, width, height)
                if tail_count
                else None
            )
            write_json(
                marker,
                {
                    "digest": digest,
                    "frames": keep,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                },
            )
            paths.append(str(target))
            reports.append(
                {
                    "segment": index,
                    "resumed": False,
                    "frames": keep,
                    "start_frame": segment["start"],
                    "end_frame": segment["end"],
                    "faces_anchored": anchored,
                    "seam_blend_frames": blend_count,
                    "boundary_lock_delta": round(boundary_lock_delta, 8)
                    if boundary_lock_delta is not None
                    else None,
                    "deviation_from_source": round(deviation, 5),
                    "left_half_deviation": round(left_deviation, 5),
                    "right_half_deviation": round(right_deviation, 5),
                    "elapsed_seconds": round(time.perf_counter() - segment_started, 3),
                }
            )
            write_json(
                job / "progress.json",
                {"completed": len(paths), "total": len(plan["segments"]), "segments": reports},
            )
            del decoded, source, source_ref, samples
            try:
                torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001
                pass

        deviations = [item["deviation_from_source"] for item in reports if "deviation_from_source" in item]
        last = plan["segments"][-1] if plan["segments"] else {"index": 0, "start": 0, "end": 0}
        monitor.emit(
            phase="complete",
            overall=1.0,
            segment_index=int(last.get("index", total_segments - 1)),
            total_segments=total_segments,
            segment_start=int(last["start"]),
            segment_end=int(last["end"]),
            total_frames=int(plan["total_frames"]),
            step=last_steps,
            steps=last_steps,
            segment_file=last_segment_file,
            segment_subfolder=last_segment_subfolder,
            done=True,
            ok=True,
            live_preview=False,
        )
        result = {
            "version": VERSION,
            "job": str(job),
            "paths": paths,
            "source": plan["source"],
            "audio_path": plan.get("audio_path"),
            "audio_start_seconds": float(plan.get("target_start_seconds", 0.0)),
            "audio_separated": True,
            "segment_audio": False,
            "h3_audio_placeholder_frames": int(plan.get("h3_audio_placeholder_frames", 0)),
            "width": width,
            "height": height,
            "output_width": int(plan.get("output_width", width)),
            "output_height": int(plan.get("output_height", height)),
            "total_frames": int(plan["total_frames"]),
            "segments": reports,
            "boundaries": boundaries,
            "warnings": warnings,
            "mean_deviation_from_source": round(sum(deviations) / len(deviations), 5) if deviations else None,
            "elapsed_seconds": round(time.perf_counter() - start_time, 3),
            "quality_verified": False,
        }
        write_json(job / "run_report.json", result)
        lines = [
            f"逐段替换完成：{len(paths)}/{len(plan['segments'])} 段，共 {plan['total_frames']} 帧。",
            f"每段生成后已立即保存：{segments_dir}",
            f"报告：{job / 'run_report.json'}",
        ]
        if result["mean_deviation_from_source"] is not None:
            lines.append(f"与源片平均画面差异：{result['mean_deviation_from_source']}")
        lines += ["警告：" + warning for warning in warnings]
        LOG.info("AICG3D-CSR segment report:\n%s", "\n".join(lines))
        output_result = dict(result)
        output_result["_second_pass_context"] = {
            "job_bundle": job_bundle,
            "base_prompt": base_prompt,
            "ref_image_size": ref_image_size,
        }
        return (output_result,)


class CSRMerge:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "rendered_segments": ("CSR_RENDERED_SEGMENTS",),
                "keep_original_audio": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "全部分段合并完成后，再把 MiniMax H3 Aicg资源库提取的独立音轨封装进最终 MP4。",
                    },
                ),
                "verify_boundaries": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "seam_exposure_lock": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "label_on": "跨段曝光锁定",
                        "label_off": "普通合并",
                        "tooltip": "匹配相邻片段的曝光基线和段首低频光影，压掉 H3 分段采样产生的轻微闪亮；检测到硬切镜头时自动保护。",
                    },
                ),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "merge"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    @disk_operation
    def merge(self, rendered_segments, keep_original_audio, verify_boundaries, seam_exposure_lock=True):
        result = rendered_segments
        output = Path(result["job"]) / "final_seamless.mp4"
        audio_path = result.get("audio_path")
        mux_audio = bool(keep_original_audio and audio_path)
        boundaries = result.get("boundaries", []) if verify_boundaries else []
        if seam_exposure_lock:
            report = export_with_seam_repair(
                result["paths"],
                audio_path,
                output,
                int(result["total_frames"]),
                boundaries,
                segment_frames=[int(item["frames"]) for item in result["segments"]],
                width=int(result["width"]),
                height=int(result["height"]),
                output_width=int(result.get("output_width", result["width"])),
                output_height=int(result.get("output_height", result["height"])),
                keep_audio=mux_audio,
                audio_start_seconds=float(result.get("audio_start_seconds", 0.0)),
            )
            report["merge_mode"] = "exposure_lock_and_seam_repair"
        else:
            report = merge_segments(
                result["paths"],
                audio_path,
                output,
                int(result["total_frames"]),
                boundaries,
                width=int(result.get("output_width", result["width"])),
                height=int(result.get("output_height", result["height"])),
                keep_audio=mux_audio,
                encoder="libx264",
                audio_start_seconds=float(result.get("audio_start_seconds", 0.0)),
            )
            report["merge_mode"] = "plain_reencode"
        write_json(Path(result["job"]) / "merge_report.json", report)
        lines = [
            f"无缝合并完成：{report['total_frames']} 帧 / {report['duration_seconds']:.3f} 秒。",
            f"输出：{output}",
            "所有片段已统一重编码为同一 CFR 时间线，片段边界不会因编码参数或时间戳不同产生接缝。",
            f"独立音轨{'已后置封装：' + audio_path if mux_audio else '未封装（源视频无音轨或已关闭）'}。",
        ]
        if seam_exposure_lock:
            records = report.get("seam_records", [])
            repaired = sum(1 for item in records if item.get("enabled") and not item.get("hard_cut"))
            hard_cuts = sum(1 for item in records if item.get("hard_cut"))
            lines.append(f"跨段曝光锁定已应用：{repaired} 个接缝已平滑，{hard_cuts} 个硬切镜头已保护。")
        else:
            lines.append("跨段曝光锁定已关闭：本次只做普通统一重编码。")
        deltas = report.get("boundary_deltas", [])
        if deltas:
            lines.append("边界相邻帧差异：" + "；".join(
                f"{item['frame']}帧={item['mean_abs_delta_0_255']}" for item in deltas
            ))
        if result.get("warnings"):
            lines += ["生成警告：" + warning for warning in result["warnings"]]
        text = "\n".join(lines)
        LOG.info("AICG3D-CSR: %s", lines[0])
        LOG.info("AICG3D-CSR merge report:\n%s", text)
        return (InputImpl.VideoFromFile(str(output)),)


NODE_CLASS_MAPPINGS = {
    "CSRSegmentReplace": CSRSegmentReplace,
    "CSRMerge": CSRMerge,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CSRSegmentReplace": "CSR ③ 逐段替换 · 自动保存 · 断点续跑 · 实时预览",
    "CSRMerge": "CSR ④ 无缝合并 · 后置封装音轨",
}
