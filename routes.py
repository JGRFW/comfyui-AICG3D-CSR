"""HTTP helpers for the CSR video upload/segmentation editor."""
from __future__ import annotations

import json

import folder_paths
from aiohttp import web
from server import PromptServer

from .media import VideoError, probe


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
