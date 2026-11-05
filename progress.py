"""Live status and visual preview transport for CSR segment replacement."""
from __future__ import annotations

import base64
import io
import logging
import time
from typing import Any

LOG = logging.getLogger(__name__)
EVENT = "aicg3d_csr_progress"


def _execution_context():
    try:
        from comfy_execution.utils import get_executing_context

        context = get_executing_context()
        return (
            str(getattr(context, "node_id", "") or ""),
            str(getattr(context, "prompt_id", "") or ""),
        )
    except Exception:  # noqa: BLE001
        return "", ""


class CSRProgressMonitor:
    def __init__(self, node_id: str | None = None):
        context_node, context_prompt = _execution_context()
        self.node_id = str(node_id or context_node)
        self.prompt_id = context_prompt
        self.started_at = time.perf_counter()
        self._previewer = None
        self._preview_failed = False
        self._last_preview_at = 0.0
        self._last_step = -1

    def _elapsed(self) -> float:
        return max(0.0, time.perf_counter() - self.started_at)

    def _server(self):
        try:
            from server import PromptServer

            return getattr(PromptServer, "instance", None)
        except Exception:  # noqa: BLE001
            return None

    def _send(self, payload: dict[str, Any]) -> None:
        server = self._server()
        if server is None or not self.node_id:
            return
        payload = {
            "node_id": self.node_id,
            "prompt_id": self.prompt_id,
            "elapsed": round(self._elapsed(), 2),
            **payload,
        }
        try:
            server.send_sync(EVENT, payload, getattr(server, "client_id", None))
        except Exception:  # noqa: BLE001
            pass

    def configure_preview(self, model) -> None:
        if self._previewer is not None or self._preview_failed:
            return
        try:
            import latent_preview

            latent_format = model.model.latent_format
            self._previewer = latent_preview.get_previewer(model.load_device, latent_format)
        except Exception as exc:  # noqa: BLE001
            self._preview_failed = True
            LOG.warning("AICG3D-CSR live preview unavailable: %s", exc)

    def _preview_jpeg(self, x0, max_side: int) -> str | None:
        if self._previewer is None or x0 is None:
            return None
        try:
            latent = x0
            if getattr(latent, "is_nested", False):
                tensors = getattr(latent, "tensors", None) or ()
                if not tensors:
                    return None
                latent = tensors[0]
            if getattr(latent, "ndim", 0) == 5:
                latent = latent[:1]
            decoded = self._previewer.decode_latent_to_preview_image("JPEG", latent)
            image = decoded[1] if isinstance(decoded, tuple) else decoded
            if image is None:
                return None
            image = image.convert("RGB")
            longest = max(image.size)
            if longest > max_side:
                from PIL import Image

                scale = max_side / float(longest)
                image = image.resize(
                    (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                    resample=getattr(Image, "Resampling", Image).LANCZOS,
                )
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=92)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:  # noqa: BLE001
            return None

    def emit(
        self,
        *,
        phase: str,
        overall: float,
        segment_index: int,
        total_segments: int,
        segment_start: int,
        segment_end: int,
        total_frames: int,
        step: int = 0,
        steps: int = 0,
        eta: float | None = None,
        done: bool = False,
        ok: bool = True,
        warning: str | None = None,
        segment_file: str | None = None,
        segment_subfolder: str | None = None,
        x0=None,
        live_preview: bool = True,
        preview_every_steps: int = 2,
        preview_resolution: int = 512,
    ) -> None:
        preview_b64 = None
        step_number = int(step)
        if live_preview and x0 is not None:
            should_preview = (
                step_number <= 1
                or step_number >= int(steps)
                or (step_number - self._last_step) >= max(1, int(preview_every_steps))
                or (time.perf_counter() - self._last_preview_at) >= 4.0
            )
            if should_preview:
                self._last_preview_at = time.perf_counter()
                self._last_step = step_number
                preview_b64 = self._preview_jpeg(x0, max(128, int(preview_resolution)))
        self._send(
            {
                "phase": phase,
                "overall": round(max(0.0, min(1.0, float(overall))), 5),
                "segment_index": int(segment_index),
                "segment_number": int(segment_index) + 1,
                "total_segments": int(total_segments),
                "segment_start": int(segment_start),
                "segment_end": int(segment_end),
                "total_frames": int(total_frames),
                "step": step_number,
                "steps": int(steps),
                "eta": None if eta is None else round(max(0.0, float(eta)), 1),
                "done": bool(done),
                "ok": bool(ok),
                "warning": warning,
                "segment_file": segment_file,
                "segment_subfolder": segment_subfolder,
                "preview_jpeg": preview_b64,
            }
        )

    def fail(self, error: Exception, *, segment_index: int = 0, total_segments: int = 1) -> None:
        self._send(
            {
                "phase": "error",
                "overall": 0.0,
                "segment_index": int(segment_index),
                "segment_number": int(segment_index) + 1,
                "total_segments": int(total_segments),
                "step": 0,
                "steps": 0,
                "done": True,
                "ok": False,
                "error": str(error),
            }
        )
