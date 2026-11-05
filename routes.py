"""HTTP helpers for the CSR video upload/segmentation editor."""
from __future__ import annotations

import json
from pathlib import Path

import folder_paths
from aiohttp import web
from server import PromptServer

from .media import VideoError, probe
from . import prompt_optimizer

REPLACEMENT_SKILLS_PATH = Path(__file__).resolve().with_name("skills") / "replacement_skills.json"


def _optimizer_config_payload(payload: dict) -> dict:
    current = prompt_optimizer._read_config()
    incoming = payload if isinstance(payload, dict) else {}
    merged = dict(current)
    merged.update(incoming)
    if incoming.get("clear_api_key"):
        merged["api_key"] = ""
    elif not str(incoming.get("api_key") or "").strip():
        merged["api_key"] = current.get("api_key", "")
    return prompt_optimizer._normalize_config(merged)


@PromptServer.instance.routes.get("/aicg3d_csr/replacement_skills")
async def csr_replacement_skills(_request):
    try:
        data = json.loads(REPLACEMENT_SKILLS_PATH.read_text(encoding="utf-8"))
        skills = data.get("skills") if isinstance(data, dict) else None
        if not isinstance(skills, list):
            raise ValueError("替换技能文件格式无效。")
        return web.json_response({"version": int(data.get("version") or 1), "skills": skills})
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return web.json_response({"error": str(exc)}, status=500)


@PromptServer.instance.routes.get("/aicg3d_csr/prompt_optimizer/config")
async def csr_prompt_optimizer_config(_request):
    return web.json_response(prompt_optimizer._public_config(prompt_optimizer._read_config()))


@PromptServer.instance.routes.post("/aicg3d_csr/prompt_optimizer/config")
async def csr_prompt_optimizer_save(request):
    try:
        payload = await request.json()
        config = _optimizer_config_payload(payload)
        prompt_optimizer._write_config(config)
        return web.json_response(prompt_optimizer._public_config(config))
    except (OSError, TypeError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


@PromptServer.instance.routes.post("/aicg3d_csr/prompt_optimizer/models")
async def csr_prompt_optimizer_models(request):
    try:
        payload = await request.json()
        config = _optimizer_config_payload(payload)
        if config["mode"] == "local":
            return web.json_response({"models": prompt_optimizer.scan_local_models()})
        models = await prompt_optimizer._api_models(config)
        return web.json_response({"models": models})
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


@PromptServer.instance.routes.post("/aicg3d_csr/prompt_optimizer/optimize")
async def csr_prompt_optimizer_optimize(request):
    try:
        payload = await request.json()
        result = await prompt_optimizer.optimize_prompt(payload)
        return web.json_response({"prompt": result})
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


@PromptServer.instance.routes.get("/aicg3d_csr/video_info")
async def csr_video_info(request):
    value = str(request.query.get("file") or "").strip()
    if not value:
        return web.json_response({"error": "缺少 file 参数"}, status=400)
    try:
        path = folder_paths.get_annotated_filepath(value)
        info = probe(path, count_frames=True)
        return web.json_response(info)
    except (VideoError, OSError, ValueError, json.JSONDecodeError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
