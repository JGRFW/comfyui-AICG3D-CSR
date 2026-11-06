"""Local prompt optimization for CSR replacement descriptions.

The optimizer is intentionally CSR-only. It does not import nodes or routes from
the original comfyui-AICG3D plugin.
"""
from __future__ import annotations

import asyncio
import base64
import gc
import io
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import threading
import urllib.parse

from PIL import Image

import aiohttp
import folder_paths
from filelock import FileLock

LOG = logging.getLogger("comfyui-AICG3D-CSR.prompt_optimizer")

IMAGE_MAX_SIDE = 512
IMAGE_JPEG_QUALITY = 82
VISUAL_IMAGE_LIMIT = 6
VIDEO_FRAME_LIMIT = 3
VISUAL_IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
VIDEO_SUFFIXES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
MAX_OUTPUT_TOKENS = {"concise": 500, "balanced": 900, "strong": 1400}
REASONING_MARKERS = re.compile(
    r"(?:</?think\b|<\|(?:channel|analysis|reasoning)\|>|^\s*(?:the user wants|i need to|i must|let me|wait\b|now write|draft)\b)",
    re.IGNORECASE | re.MULTILINE,
)

DEFAULT_CONFIG = {
    "mode": "api",
    "api_base": "http://127.0.0.1:11434/v1",
    "api_key": "",
    "model": "qwen2.5:7b",
    "vision_enabled": False,
    "vision_model": "",
    "local_model": "",
    "local_mmproj": "",
    "local_context": 8192,
    "local_gpu_layers": -1,
    "language": "English",
    "strength": "balanced",
    "scheme": "auto",
    "temperature": 0.35,
    "timeout": 180,
}
MODES = {"api": "OpenAI 兼容 API", "local": "本地 GGUF"}
LANGUAGES = {"English": "英文（H3 推荐）", "中文": "中文"}
STRENGTHS = {"concise": "简洁", "balanced": "标准", "strong": "强化"}
SCHEMES = {
    "auto": "跟随替换标签",
    "single_person_replace": "单人替换 Skill",
    "multi_person_replace": "多人替换 Skill",
    "product_replace": "商品替换 Skill",
    "background_replace": "背景彻底替换",
    "scene_rebuild": "场景结构重建",
    "person_replace": "人物身份替换",
    "object_replace": "物品/产品替换",
    "person_scene": "人物 + 场景",
    "person_object": "人物 + 物品",
    "composite": "综合替换",
    "background_repair": "修复：背景没有被替换",
    "foreground_preserve": "修复：前景人物被误改",
}
TAG_SCHEMES = {
    "单人替换": "single_person_replace",
    "多人替换": "multi_person_replace",
    "商品替换": "product_replace",
    "背景/场景替换": "background_replace",
    "人物替换": "person_replace",
    "物品/产品替换": "object_replace",
    "人物 + 背景": "person_scene",
    "人物 + 物品": "person_object",
    "人物 + 背景 + 物品": "composite",
    "自定义": "auto",
}

SYSTEM_PROMPT = """You are a senior prompt editor for MiniMax H3 video editing.
Rewrite the user's replacement instruction into one precise, production-ready prompt.
Preserve the user's intended edit. Never add story events, dialogue, camera cuts, characters, objects, logos, text, or actions that the user did not request.
Treat replacement references as property sources, not pose/background/style references unless explicitly requested.
For background replacement, removal of the original scene structure is mandatory: do not merely recolor, blur, relight, or partially retouch the old environment.
Keep unspecified foreground subjects, identities, wardrobe, motion, framing, timing, and camera behavior unchanged.
Return only the final prompt text. Do not reveal chain-of-thought, reasoning, analysis, planning, or self-correction.
Never emit <think>, </think>, <analysis>, markdown fences, headings, bullet lists, explanations, or alternative versions.
If multiple people and a background are requested, all of them are simultaneous mandatory edits. Never reduce the task to only one person or only the background.
"""

SCHEME_RULES = {
    "auto": "Infer the replacement target from the tag and user text; preserve everything else.",
    "single_person_replace": (
        "Replace exactly one designated person. Use only the matching person reference for identity, face, hair, body proportions and wardrobe. "
        "Preserve every other person, the background, camera, pose, mouth timing and interaction timing."
    ),
    "multi_person_replace": (
        "Replace multiple designated people one-to-one with their corresponding references. Never merge identities, swap identities, duplicate a person, omit a target or add a new person. "
        "Preserve the original person count, placement, layering, occlusion, interactions, camera and timing."
    ),
    "product_replace": (
        "Replace only the designated product or object. Preserve its exact silhouette, proportions, structure, packaging, material, colors, logo and label text from the reference. "
        "Keep grip, occlusion, perspective, contact shadows and environmental light consistent; do not redesign the product or invent text."
    ),
    "background_replace": (
        "Replace the complete environment everywhere except retained foreground subjects and specified products. "
        "The background reference is the sole source for room layout, architecture, furniture, surfaces, materials, colors and lighting. "
        "Erase the original walls, floor, ceiling, windows, decor, furniture and spatial structure. Do not blend the old and new scene."
    ),
    "scene_rebuild": (
        "Rebuild the entire visible environment from the scene reference, including depth, perspective, architecture, furniture, material, lighting and ambient color. "
        "The result must read as a different location, not a recolor or cosmetic retouch of the original background."
    ),
    "person_replace": (
        "Replace only the designated person. Identity, face, hair, body proportions and wardrobe come from the person reference. "
        "Preserve the original background, camera, pose, motion, mouth timing and interaction choreography."
    ),
    "object_replace": (
        "Replace only the designated object or product. Shape, color, material, structure, logo and details come from the product reference. "
        "Preserve hand pose, occlusion, contact shadows and all unrelated content."
    ),
    "person_scene": (
        "Replace both designated people and the complete environment. The new person and new scene must agree in perspective, scale, lighting and contact shadows. "
        "Do not import unrelated people, text, logos or watermarks from either reference."
    ),
    "person_object": (
        "Replace both the designated person and product. Preserve the original environment and enforce natural grip, occlusion and contact shadows for the product."
    ),
    "composite": (
        "Replace all explicitly specified people, products and the complete environment. Keep the source video's camera, timing and choreography. "
        "Maintain coherent perspective, scale, color, lighting and contact shadows among all replacements."
    ),
    "background_repair": (
        "This is a strict retry after background replacement failed. The background reference must replace every visible environment region. "
        "No wall, floor, ceiling, furniture, window, room layout, material or lighting pattern from the source video may remain. "
        "Do not output a recolored or lightly modified version of the original scene."
    ),
    "foreground_preserve": (
        "This is a strict retry after foreground subjects changed unintentionally. Preserve every original non-target person and object exactly. "
        "Apply the requested replacement only to the named target."
    ),
}

GUARDRAILS = {
    "single_person_replace": "仅替换明确指定的一个人物；其他人物、背景、物品、镜头和动作保持不变，禁止旧身份残留。",
    "multi_person_replace": "多人参考必须一一绑定；禁止身份融合、换脸串位、漏换、重复人物或新增人物，保持原人数、站位、遮挡和互动关系。",
    "product_replace": "仅替换指定商品；严格保持轮廓、结构、材质、颜色、LOGO和标签，禁止重新设计、改写文字、漂浮、穿模和物体复制。",
    "background_replace": (
        "强制背景替换：把背景参考视为完整环境来源，不是风格或调色参考。除明确保留的前景主体外，覆盖全部背景区域；"
        "清除原视频的墙体、地面、天花、门窗、家具、陈设、房间布局、材质与光照；不得只调色、模糊、局部修补或混合旧场景。"
        "保持人物身份、服装、动作、口型、站位、镜头和时长不变。"
    ),
    "scene_rebuild": (
        "强制场景重建：新场景必须具有参考图中的完整空间结构和透视，旧场景结构不得残留。前景主体边缘、遮挡、接触阴影和光照需自然一致。"
    ),
    "person_replace": "仅替换明确指定的人物；未指定人物、背景、物品、镜头和动作保持不变。",
    "object_replace": "仅替换明确指定的物品或产品；手部姿势、遮挡、接触阴影、人物和背景保持不变。",
    "person_scene": "同时替换指定人物与完整环境；禁止残留旧场景结构，禁止把参考人物、文字或水印带入成片。",
    "person_object": "同时替换指定人物与物品；背景保持不变，产品握持、遮挡和接触阴影自然。",
    "composite": "仅替换明确列出的人物、物品和环境；其他内容保持不变，并保证所有替换元素透视、比例、光照和接触阴影一致。",
    "background_repair": "这是背景替换失败后的强制重试：旧场景必须被完全删除，不能仅改变颜色或光照。",
    "foreground_preserve": "这是前景误变后的强制重试：所有未指定替换的人物和物品必须保持原样。",
}

_ACTIVE_TASKS: dict[str, asyncio.Task] = {}
_LOCAL_MODEL = None
_LOCAL_HANDLER = None
_LOCAL_MODEL_KEY: tuple | None = None
_LOCAL_LOCK = threading.RLock()


def _config_path() -> Path:
    getter = getattr(folder_paths, "get_user_directory", None)
    if callable(getter):
        root = Path(getter()) / "default"
    else:
        root = Path(folder_paths.get_output_directory()).parent / "user" / "default"
    return (root / "aicg3d_csr" / "prompt_optimizer.json").resolve()


def _read_config() -> dict:
    path = _config_path()
    config = dict(DEFAULT_CONFIG)
    if path.is_file():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                config.update(stored)
        except (OSError, ValueError) as exc:
            LOG.warning("Unable to read prompt optimizer config: %s", exc)
    return _normalize_config(config)


def _write_config(value: dict) -> dict:
    config = _normalize_config(value)
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with FileLock(str(path) + ".lock"):
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    return config


def _normalize_config(value: dict) -> dict:
    config = dict(DEFAULT_CONFIG)
    if isinstance(value, dict):
        config.update(value)
    mode = str(config.get("mode") or "api")
    config["mode"] = mode if mode in MODES else "api"
    config["api_base"] = _normalize_api_base(str(config.get("api_base") or DEFAULT_CONFIG["api_base"]))
    config["api_key"] = str(config.get("api_key") or "").strip()
    config["model"] = str(config.get("model") or DEFAULT_CONFIG["model"]).strip()
    config["vision_enabled"] = bool(config.get("vision_enabled", False))
    config["vision_model"] = str(config.get("vision_model") or "").strip()
    config["local_model"] = str(config.get("local_model") or "").strip()
    config["local_mmproj"] = str(config.get("local_mmproj") or "").strip()
    config["local_context"] = max(2048, min(131072, int(config.get("local_context") or 8192)))
    config["local_gpu_layers"] = max(-1, min(999, int(config.get("local_gpu_layers") or -1)))
    language = str(config.get("language") or "English")
    config["language"] = language if language in LANGUAGES else "English"
    strength = str(config.get("strength") or "balanced")
    config["strength"] = strength if strength in STRENGTHS else "balanced"
    scheme = str(config.get("scheme") or "auto")
    config["scheme"] = scheme if scheme in SCHEMES else "auto"
    config["temperature"] = max(0.0, min(1.5, float(config.get("temperature") or 0.35)))
    config["timeout"] = max(10, min(600, int(config.get("timeout") or 180)))
    return config


def _public_config(config: dict) -> dict:
    result = {key: value for key, value in config.items() if key != "api_key"}
    result["api_key_set"] = bool(config.get("api_key"))
    result["modes"] = MODES
    result["schemes"] = SCHEMES
    result["languages"] = LANGUAGES
    result["strengths"] = STRENGTHS
    result["local_models"] = scan_local_models()
    result["mmproj_files"] = scan_mmproj_models()
    try:
        import importlib.util

        result["llama_cpp_available"] = importlib.util.find_spec("llama_cpp") is not None
    except (ImportError, ValueError):
        result["llama_cpp_available"] = False
    return result


def _normalize_api_base(value: str) -> str:
    text = value.strip().rstrip("/")
    if not text:
        return DEFAULT_CONFIG["api_base"]
    if "://" not in text:
        text = "http://" + text
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("提示词优化 API 地址无效。")
    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _is_local_host(host: str) -> bool:
    name = str(host or "").strip().lower()
    if name in {"localhost", "host.docker.internal"} or name.endswith(".local"):
        return True
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(name, None)}
    except (OSError, ValueError):
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if not (ip.is_loopback or ip.is_private):
            return False
    return bool(addresses)


def _validate_local_api_base(value: str) -> str:
    base = _normalize_api_base(value)
    host = urllib.parse.urlsplit(base).hostname or ""
    if not _is_local_host(host) and os.environ.get("AICG3D_CSR_ALLOW_REMOTE_PROMPT_API") != "1":
        raise ValueError("仅允许连接本机或局域网提示词 API；远程 API 需显式设置 AICG3D_CSR_ALLOW_REMOTE_PROMPT_API=1。")
    return base


def _comfy_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _local_model_roots() -> list[Path]:
    root = _comfy_root()
    candidates = [
        root / "models" / "llm",
        root / "models" / "LLM",
        root / "models" / "prompt_optimizers",
        root / "models" / "language_models",
    ]
    getter = getattr(folder_paths, "get_folder_paths", None)
    if callable(getter):
        for category in ("llm", "LLM", "prompt_optimizers"):
            try:
                candidates.extend(Path(item) for item in getter(category))
            except Exception:
                continue
    unique = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def scan_local_models() -> list[dict]:
    return _scan_gguf_models(projectors=False)


def scan_mmproj_models() -> list[dict]:
    return _scan_gguf_models(projectors=True)


def _is_mmproj_name(name: str) -> bool:
    lowered = str(name or "").lower()
    return any(marker in lowered for marker in ("mmproj", "mm-projector", "projector"))


def _scan_gguf_models(*, projectors: bool) -> list[dict]:
    result = []
    for root in _local_model_roots():
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.gguf"), key=lambda item: str(item).lower()):
            if _is_mmproj_name(path.name) != bool(projectors):
                continue
            try:
                relative = path.resolve().relative_to(_comfy_root()).as_posix()
            except ValueError:
                relative = str(path.resolve())
            result.append({
                "name": path.name,
                "path": relative,
                "size": path.stat().st_size,
            })
    return result


def _resolve_local_mmproj(value: str) -> Path:
    selected = str(value or "").strip()
    if not selected:
        raise ValueError("请选择与视觉 GGUF 模型匹配的 mmproj 视觉投影文件。")
    candidate = Path(selected)
    if not candidate.is_absolute():
        candidate = _comfy_root() / candidate
    resolved = candidate.resolve()
    allowed = any(resolved.is_relative_to(root) for root in _local_model_roots())
    if not allowed or not resolved.is_file() or not _is_mmproj_name(resolved.name):
        raise ValueError("mmproj 视觉投影必须位于允许的 GGUF 模型目录中。")
    return resolved


def _resolve_local_model(value: str) -> Path:
    selected = str(value or "").strip()
    if not selected:
        raise ValueError("请选择一个本地 GGUF 模型。")
    candidate = Path(selected)
    if not candidate.is_absolute():
        candidate = _comfy_root() / candidate
    resolved = candidate.resolve()
    allowed = any(resolved.is_relative_to(root) for root in _local_model_roots())
    if not allowed or not resolved.is_file() or resolved.suffix.lower() != ".gguf":
        raise ValueError("本地模型必须位于 models/llm、models/LLM 或 models/prompt_optimizers。")
    return resolved


def _media_roots() -> list[Path]:
    roots = []
    for getter_name in ("get_input_directory", "get_output_directory", "get_temp_directory"):
        getter = getattr(folder_paths, getter_name, None)
        if not callable(getter):
            continue
        try:
            resolved = Path(getter()).resolve()
        except (OSError, TypeError, ValueError):
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _resolve_media_file(value: str) -> Path:
    text = str(value or "").strip().strip('"')
    if not text or "\x00" in text:
        raise ValueError("视觉素材路径为空或无效。")
    roots = _media_roots()
    candidate = Path(text)
    resolved = candidate.resolve() if candidate.is_absolute() else None
    if resolved is None:
        annotated_getter = getattr(folder_paths, "get_annotated_filepath", None)
        if callable(annotated_getter):
            try:
                resolved = Path(annotated_getter(text)).resolve()
            except (OSError, TypeError, ValueError):
                resolved = None
        if resolved is None or not any(resolved.is_relative_to(root) for root in roots):
            for root in roots:
                candidate = (root / text).resolve()
                if candidate.is_file():
                    resolved = candidate
                    break
    if resolved is None or not any(resolved.is_relative_to(root) for root in roots):
        raise ValueError("视觉素材必须位于 ComfyUI 的 input、output 或 temp 目录中。")
    if not resolved.is_file():
        raise ValueError(f"找不到视觉素材：{text}")
    return resolved


def _ffmpeg_executable() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError) as exc:
        raise RuntimeError("视觉分析需要 FFmpeg；请加入 PATH 或安装 imageio-ffmpeg。") from exc


def _image_bytes_data_url(data: bytes) -> str:
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.seek(0)
            image = source.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValueError("视觉参考不是可读取的图片。") from exc
    image.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return "data:image/jpeg;base64," + encoded


def _image_data_url(path: str | Path) -> str:
    target = Path(path)
    if target.suffix.lower() not in VISUAL_IMAGE_SUFFIXES:
        raise ValueError(f"不支持的视觉参考图片格式：{target.suffix or '(无扩展名)'}")
    try:
        return _image_bytes_data_url(target.read_bytes())
    except OSError as exc:
        raise ValueError(f"无法读取视觉参考：{target.name}") from exc


def _video_frame_data_url(path: str | Path, timestamp: float) -> str:
    target = Path(path)
    if target.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError(f"不支持的视频格式：{target.suffix or '(无扩展名)'}")
    command = [
        _ffmpeg_executable(),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, float(timestamp)):.6f}",
        "-i",
        str(target),
        "-an",
        "-sn",
        "-dn",
        "-frames:v",
        "1",
        "-vf",
        f"scale={IMAGE_MAX_SIDE}:{IMAGE_MAX_SIDE}:force_original_aspect_ratio=decrease",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    process = subprocess.run(
        command,
        capture_output=True,
        timeout=45,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if process.returncode or not process.stdout:
        message = process.stderr.decode("utf-8", errors="replace")[-600:]
        raise RuntimeError(f"无法读取视频视觉帧：{message.strip() or 'FFmpeg 未返回画面'}")
    return _image_bytes_data_url(process.stdout)


def _visual_role(entry: dict, fallback: str = "") -> str:
    raw = str(entry.get("kind") or entry.get("role") or fallback).strip().lower()
    if raw in {"background", "scene", "environment", "背景", "场景"}:
        return "background"
    if raw in {"object", "product", "item", "prop", "物品", "产品"}:
        return "object"
    if raw in {"character", "person", "人物"}:
        return "person"
    return "reference"


def _visual_media(media: dict) -> list[dict]:
    """Build bounded, low-resolution visual evidence from validated local media."""
    if not isinstance(media, dict):
        return []
    result = []
    video = media.get("video")
    video_file = video.get("file") if isinstance(video, dict) else video
    if str(video_file or "").strip():
        video_path = _resolve_media_file(str(video_file))
        info = video if isinstance(video, dict) else {}
        try:
            start = max(0.0, float(media.get("video_start", info.get("start", 0.0))))
        except (TypeError, ValueError):
            start = 0.0
        try:
            end = float(media.get("video_end", info.get("end", start + 1.0)))
        except (TypeError, ValueError):
            end = start + 1.0
        if not end > start:
            end = start + 1.0
        try:
            duration = max(0.0, float(media.get("video_duration", info.get("duration", 0.0))))
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            start = min(start, max(0.0, duration - 0.04))
            end = min(end, duration)
        points = [start, (start + end) / 2.0, max(start, end - 1.0 / 24.0)]
        for index, timestamp in enumerate(dict.fromkeys(round(point, 4) for point in points)):
            if len(result) >= VIDEO_FRAME_LIMIT:
                break
            try:
                url = _video_frame_data_url(video_path, timestamp)
            except (OSError, RuntimeError, ValueError) as exc:
                LOG.warning("Unable to sample video frame at %.3fs: %s", timestamp, exc)
                continue
            result.append({
                "kind": "video",
                "label": f"Source video target frame {index + 1} at {timestamp:.3f}s",
                "url": url,
            })

    references = media.get("images")
    candidates = []
    for index, entry in enumerate(references[:24] if isinstance(references, list) else []):
        if isinstance(entry, str):
            entry = {"file": entry}
        if not isinstance(entry, dict) or not str(entry.get("file") or "").strip():
            continue
        role = _visual_role(entry)
        priority = {"background": 0, "object": 1, "person": 2, "reference": 3}.get(role, 3)
        candidates.append((priority, index, entry, role))
    candidates.sort(key=lambda item: (item[0], item[1]))
    for _priority, index, entry, role in candidates:
        if len(result) >= VISUAL_IMAGE_LIMIT:
            break
        path = _resolve_media_file(str(entry.get("file") or ""))
        label = str(entry.get("label") or "").strip()
        if not label:
            label = {
                "background": "Replacement background/scene reference",
                "object": "Replacement object/product reference",
                "person": "Replacement person reference",
                "reference": "Additional visual reference",
            }[role]
        result.append({
            "kind": role,
            "label": f"{label} ({index + 1})",
            "url": _image_data_url(path),
        })
    return result[:VISUAL_IMAGE_LIMIT]


def _vision_messages(messages: list[dict], visual_media: list[dict]) -> list[dict]:
    result = [dict(message) for message in messages]
    main = result[-1].get("content") if result else ""
    text = str(main or "")
    text += (
        "\n\nVisual evidence is supplied below only to identify the source targets and their replacement references. "
        "Use it to make the replacement binding more precise. Do not invent details that are not visible. "
        "Do not treat a replacement reference as a pose, camera, background or composition reference unless the user explicitly requested that."
    )
    content = [{"type": "text", "text": text}]
    for item in visual_media[:VISUAL_IMAGE_LIMIT]:
        content.append({"type": "text", "text": f"Reference: {item['label']}"})
        content.append({
            "type": "image_url",
            "image_url": {"url": item["url"], "detail": "low"},
        })
    if result:
        result[-1] = {"role": "user", "content": content}
    else:
        result = [{"role": "user", "content": content}]
    return result


def _vision_handler_name(model_path: Path) -> str:
    name = model_path.name.lower().replace("_", "-")
    if re.search(r"qwen[-.]?3[.\-]?(?:5|6|8)", name):
        return "qwen35"
    if re.search(r"qwen[-.]?2[.\-]?5[-.]?vl", name):
        return "qwen25vl"
    if re.search(r"qwen[-.]?3(?:[.\-]?[0-9]+)?[-.]?vl", name):
        return "qwen3vl"
    if re.search(r"gemma[-.]?4", name):
        return "gemma4"
    if re.search(r"gemma[-.]?3", name):
        return "gemma3"
    raise ValueError("本地视觉模式暂支持 Qwen2.5-VL、Qwen3-VL、Qwen3.5/Qwen3.8 与 Gemma3/Gemma4 GGUF；其他模型请使用支持多模态的 OpenAI 兼容 API。")


def resolve_scheme(tag: str, requested: str = "auto") -> str:
    scheme = str(requested or "auto")
    if scheme in SCHEME_RULES and scheme != "auto":
        return scheme
    return TAG_SCHEMES.get(str(tag or "").strip(), "auto")


def infer_task_from_context(context: dict, fallback_tag: str, requested_scheme: str) -> tuple[str, str]:
    requested = str(requested_scheme or "auto")
    tag = str(fallback_tag or "自定义").strip()
    if not isinstance(context, dict):
        return tag, resolve_scheme(tag, requested)
    people = 0
    objects = 0
    background = False
    for item in context.get("images") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or item.get("role") or "").strip().lower()
        label = str(item.get("label") or "").strip().lower()
        if kind in {"person", "character"} or "人物" in label:
            people += 1
        elif kind in {"object", "product", "item", "prop"} or any(word in label for word in ("物品", "产品", "商品")):
            objects += 1
        elif kind in {"background", "scene", "environment"} or any(word in label for word in ("背景", "场景")):
            background = True
    if people and background:
        tag = "人物 + 背景 + 物品" if objects else "人物 + 背景"
        scheme = "composite" if objects else "person_scene"
    elif objects and background:
        tag = "物品 + 背景"
        scheme = "composite"
    elif people and objects:
        tag = "人物 + 物品"
        scheme = "person_object"
    elif people > 1:
        tag = "多人替换"
        scheme = "multi_person_replace"
    elif people == 1:
        tag = "单人替换"
        scheme = "single_person_replace"
    elif objects:
        tag = "商品替换"
        scheme = "product_replace"
    elif background:
        tag = "背景/场景替换"
        scheme = "background_replace"
    else:
        return tag, resolve_scheme(tag, requested)
    if requested in {"background_repair", "foreground_preserve"}:
        scheme = requested
    return tag, scheme


def _strength_text(value: str) -> str:
    return {
        "concise": "Keep the final prompt concise and direct.",
        "balanced": "Use a balanced level of detail with explicit preserve and prohibit clauses.",
        "strong": "Use strong, explicit constraints and ordered replacement instructions; repeat critical background or foreground invariants when necessary.",
    }.get(str(value), "Use a balanced level of detail with explicit preserve and prohibit clauses.")


def _messages(description: str, tag: str, scheme: str, language: str, strength: str) -> list[dict]:
    resolved = resolve_scheme(tag, scheme)
    rule = SCHEME_RULES.get(resolved, SCHEME_RULES["auto"])
    language_text = "Simplified Chinese" if language == "中文" else "English"
    user = (
        f"Replacement tag: {tag or '自定义'}\n"
        f"Scheme: {SCHEMES.get(resolved, resolved)}\n"
        f"Scheme rules: {rule}\n"
        f"Output language: {language_text}\n"
        f"Detail level: {_strength_text(strength)}\n"
        f"User instruction:\n{description or '(empty)'}\n\n"
        "Rewrite the instruction for MiniMax H3 now. Return only the final prompt."
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _extract_content(data: dict) -> str:
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise RuntimeError("提示词模型没有返回 choices。")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content") or first.get("text") or ""
    if isinstance(content, list):
        content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
    return str(content).strip()


def _strip_reasoning_sections(value: str) -> str:
    text = str(value or "").strip()
    for tag in ("think", "analysis", "reasoning"):
        closing_matches = list(re.finditer(rf"</{tag}\s*>", text, flags=re.IGNORECASE))
        if closing_matches:
            text = text[closing_matches[-1].end() :]
        else:
            text = re.sub(
                rf"<{tag}\b[^>]*>.*?</{tag}\s*>",
                "",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
        text = re.sub(rf"</?{tag}\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<\|(?:channel|analysis|reasoning)\|>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _is_reasoning_noise(value: str) -> bool:
    return bool(REASONING_MARKERS.search(str(value or "")))


def _retry_messages(messages: list[dict], previous: str) -> list[dict]:
    retry = [dict(message) for message in messages]
    retry.extend(
        [
            {"role": "assistant", "content": str(previous or "")[:6000]},
            {
                "role": "user",
                "content": (
                    "Your previous response exposed reasoning or was incomplete. Do not explain, analyze, plan, or use think tags. "
                    "Return only the complete final MiniMax H3 replacement prompt. Do not repeat the analysis."
                ),
            },
        ]
    )
    return retry


def _clean_output(value: str) -> str:
    text = _strip_reasoning_sections(str(value or ""))
    text = re.sub(r"^```(?:text|markdown)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(
        r"^(?:optimized prompt|final prompt|提示词|优化结果)\s*[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _with_guardrail(text: str, scheme: str, language: str) -> str:
    rule = GUARDRAILS.get(scheme)
    if not rule:
        return text
    if language == "中文":
        return f"{rule}\n{text}".strip()
    return f"{rule}\n{text}".strip()


async def _api_models(config: dict) -> list[str]:
    base = _validate_local_api_base(config["api_base"])
    headers = _api_headers(config)
    timeout = aiohttp.ClientTimeout(total=min(30, int(config["timeout"])))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(base.rstrip("/") + "/models", headers=headers) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"模型列表请求失败 ({response.status}): {text[:600]}")
            data = json.loads(text)
    result = []
    for item in data.get("data", []) if isinstance(data, dict) else []:
        if isinstance(item, dict):
            name = str(item.get("id") or item.get("name") or "").strip()
            if name:
                result.append(name)
    return sorted(set(result), key=str.lower)


def _api_headers(config: dict) -> dict:
    headers = {"Content-Type": "application/json"}
    key = str(config.get("api_key") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers




def _api_payload(config: dict, messages: list[dict], strength: str) -> dict:
    max_tokens = MAX_OUTPUT_TOKENS.get(strength, MAX_OUTPUT_TOKENS["balanced"])
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": float(config["temperature"]),
        "max_tokens": max_tokens,
        "stream": False,
    }
    if any(isinstance(message.get("content"), list) for message in messages):
        payload["model"] = str(config.get("vision_model") or config["model"]).strip()
    return payload


async def _api_optimize(config: dict, messages: list[dict], strength: str) -> str:
    base = _validate_local_api_base(config["api_base"])
    payload = _api_payload(config, messages, strength)
    timeout = aiohttp.ClientTimeout(total=int(config["timeout"]))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(base.rstrip("/") + "/chat/completions", headers=_api_headers(config), json=payload) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"提示词 API 请求失败 ({response.status}): {text[:1000]}")
            data = json.loads(text)
    return _extract_content(data)


def _get_local_model(config: dict, *, vision: bool = False):
    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise RuntimeError("本地 GGUF 模式需要安装 llama-cpp-python。") from exc
    model_path = _resolve_local_model(config["local_model"])
    handler_name = "text"
    mmproj_path = None
    if vision:
        mmproj_path = _resolve_local_mmproj(config["local_mmproj"])
        handler_name = _vision_handler_name(model_path)
    key = (
        str(model_path),
        int(config["local_context"]),
        int(config["local_gpu_layers"]),
        handler_name,
        str(mmproj_path) if mmproj_path else "",
    )
    global _LOCAL_MODEL, _LOCAL_HANDLER, _LOCAL_MODEL_KEY
    with _LOCAL_LOCK:
        if _LOCAL_MODEL is not None and _LOCAL_MODEL_KEY != key:
            try:
                _LOCAL_MODEL.close()
            except (AttributeError, RuntimeError):
                pass
            _LOCAL_MODEL = None
            _LOCAL_HANDLER = None
            _LOCAL_MODEL_KEY = None
        if _LOCAL_MODEL is None:
            kwargs = {}
            if vision and mmproj_path is not None:
                from llama_cpp import llama_chat_format

                handler_classes = {
                    "qwen25vl": getattr(llama_chat_format, "Qwen25VLChatHandler", None),
                    "qwen3vl": getattr(llama_chat_format, "Qwen3VLChatHandler", None),
                    "qwen35": getattr(llama_chat_format, "Qwen35ChatHandler", None),
                    "gemma3": getattr(llama_chat_format, "Gemma3ChatHandler", None),
                    "gemma4": getattr(llama_chat_format, "Gemma4ChatHandler", None),
                }
                handler_class = handler_classes.get(handler_name)
                if handler_class is None:
                    raise RuntimeError(f"当前 llama-cpp-python 不支持 {handler_name} 视觉处理器，请升级 llama-cpp-python。")
                projector_arg = "mmproj_path" if handler_name in {"gemma3"} else "clip_model_path"
                handler_kwargs = {projector_arg: str(mmproj_path), "verbose": False}
                if handler_name in {"qwen35", "gemma4"}:
                    handler_kwargs["enable_thinking"] = False
                _LOCAL_HANDLER = handler_class(**handler_kwargs)
                kwargs["chat_handler"] = _LOCAL_HANDLER
            _LOCAL_MODEL = Llama(
                model_path=str(model_path),
                n_ctx=key[1],
                n_gpu_layers=key[2],
                logits_all=False,
                verbose=False,
                **kwargs,
            )
            _LOCAL_MODEL_KEY = key
        return _LOCAL_MODEL


def _local_optimize_sync(config: dict, messages: list[dict], strength: str, *, vision: bool = False) -> str:
    model = _get_local_model(config, vision=vision)
    max_tokens = MAX_OUTPUT_TOKENS.get(strength, MAX_OUTPUT_TOKENS["balanced"])
    with _LOCAL_LOCK:
        result = model.create_chat_completion(
            messages=messages,
            temperature=float(config["temperature"]),
            max_tokens=max_tokens,
        )
    return _extract_content(result)


async def optimize_prompt(payload: dict) -> str:
    incoming = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    current = _read_config()
    merged = dict(current)
    merged.update(incoming)
    if incoming.get("clear_api_key"):
        merged["api_key"] = ""
    elif not str(incoming.get("api_key") or "").strip():
        merged["api_key"] = current.get("api_key", "")
    config = _normalize_config(merged)
    description = str(payload.get("description") or "").strip()
    if not description:
        raise ValueError("请先填写替换描述。")
    tag = str(payload.get("replacement_tag") or "自定义")
    tag, scheme = infer_task_from_context(
        payload.get("task_context") if isinstance(payload.get("task_context"), dict) else {},
        tag,
        str(payload.get("scheme") or config["scheme"]),
    )
    messages = _messages(description, tag, scheme, config["language"], config["strength"])
    vision_ready = bool(config["vision_enabled"]) and (
        bool(config["local_mmproj"]) if config["mode"] == "local" else bool(config["vision_model"])
    )
    visual_media = _visual_media(payload.get("media") or {}) if vision_ready else []
    if visual_media:
        messages = _vision_messages(messages, visual_media)
    async def generate(call_messages: list[dict]) -> str:
        if config["mode"] == "local":
            return await asyncio.to_thread(
                _local_optimize_sync,
                config,
                call_messages,
                config["strength"],
                vision=bool(visual_media),
            )
        return await _api_optimize(config, call_messages, config["strength"])

    try:
        result = await generate(messages)
        cleaned = _clean_output(result)
        if not cleaned or _is_reasoning_noise(cleaned):
            LOG.warning("Prompt model returned reasoning or an incomplete answer; retrying once.")
            result = await generate(_retry_messages(messages, result))
            cleaned = _clean_output(result)
    finally:
        if config["mode"] == "local" and visual_media:
            await asyncio.to_thread(close_local_model)
    if not cleaned:
        raise RuntimeError("提示词模型返回了空内容。")
    if _is_reasoning_noise(cleaned):
        raise RuntimeError("提示词模型返回了分析过程而不是最终提示词，已阻止写入替换描述。请降低温度后重试。")
    return _with_guardrail(cleaned, scheme, config["language"])


def close_local_model() -> None:
    global _LOCAL_MODEL, _LOCAL_HANDLER, _LOCAL_MODEL_KEY
    with _LOCAL_LOCK:
        if _LOCAL_MODEL is not None:
            try:
                _LOCAL_MODEL.close()
            except (AttributeError, RuntimeError):
                pass
        _LOCAL_MODEL = None
        _LOCAL_HANDLER = None
        _LOCAL_MODEL_KEY = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
