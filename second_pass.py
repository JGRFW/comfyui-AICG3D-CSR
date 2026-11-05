"""Optional per-segment second-pass latent upscale and resample."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from pathlib import Path

import comfy.model_management
import comfy.nested_tensor
import comfy.sample
import comfy.samplers
import comfy.utils
import folder_paths
import node_helpers
import nodes as comfy_nodes
import torch
from comfy_extras.nodes_custom_sampler import Guider_Basic
from comfy_extras.nodes_minimax_h3 import MiniMaxH3AddGuide

from .latent_upscale import MiniMaxH3EasyLatentUpscaler3D, scan_models as scan_latent_upscalers
from .media import VideoError, encode_frames, probe
from .nodes import (
    CATEGORY,
    REF_SIZE_CHOICES,
    VERSION,
    choice_key,
    disk_operation,
    encoded_reference,
    empty_video_latent,
    file_stamp,
    frames_tensor,
    graph_file_stamps,
    output_file_ref,
)
from .progress import CSRProgressMonitor

LOG = logging.getLogger(__name__)
SAME_MODEL = "沿用一采模型"
NONE_LORA = "none"


def _latent_upscaler_choices() -> list[str]:
    try:
        return list(scan_latent_upscalers())
    except Exception:
        return ["(请把 Latent 放大器放到 models/latent_upscale_models)"]


def _model_stamp(category: str, name: str) -> list | None:
    text = str(name or "").strip()
    if not text or text in {SAME_MODEL, NONE_LORA} or text.startswith("("):
        return None
    try:
        return file_stamp(folder_paths.get_full_path(category, text))
    except (OSError, ValueError):
        return None


def _model_path(category: str, name: str) -> str:
    path = folder_paths.get_full_path(category, name)
    if not path or not Path(path).is_file():
        raise ValueError(f"找不到模型：{name}")
    return path


def _target_dimensions(rendered: dict, scale: float) -> tuple[int, int, int, int]:
    output_width = max(2, round(int(rendered.get("output_width", rendered["width"])) * float(scale) / 2) * 2)
    output_height = max(2, round(int(rendered.get("output_height", rendered["height"])) * float(scale) / 2) * 2)
    model_width = max(32, math.ceil(output_width / 32) * 32)
    model_height = max(32, math.ceil(output_height / 32) * 32)
    return model_width, model_height, output_width, output_height


def _second_model(first_model, model_name: str, lora_name: str, lora_strength: float):
    if str(model_name or SAME_MODEL) == SAME_MODEL:
        model = first_model
    else:
        _model_path("diffusion_models", model_name)
        model = comfy_nodes.UNETLoader().load_unet(str(model_name), "default")[0]
    if lora_name and str(lora_name) != NONE_LORA:
        _model_path("loras", lora_name)
        model = comfy_nodes.LoraLoaderModelOnly().load_lora_model_only(
            model,
            str(lora_name),
            float(lora_strength),
        )[0]
    return model


def _second_sigmas(model, sampler_name: str, scheduler: str, steps: int, denoise: float) -> torch.Tensor:
    steps = max(1, int(steps))
    denoise = float(denoise)
    if denoise <= 0.0:
        return torch.tensor([], dtype=torch.float32)
    if denoise < 0.9999:
        planned_steps = max(steps, int(steps / denoise))
        sigmas = comfy.samplers.calculate_sigmas(
            model.get_model_object("model_sampling"),
            scheduler,
            planned_steps,
        )
        sigmas = sigmas[-(steps + 1):]
    else:
        sigmas = comfy.samplers.calculate_sigmas(
            model.get_model_object("model_sampling"),
            scheduler,
            steps,
        )
    return sigmas.cpu()


def _prepare_first_pass_frames(path: str, source: torch.Tensor, prefix: int, keep: int, model_frames: int, width: int, height: int):
    body = frames_tensor(path, 0, keep, width, height)
    pieces = []
    if prefix:
        pieces.append(source[:prefix])
    pieces.append(body)
    frames = torch.cat(pieces, dim=0)
    if frames.shape[0] < model_frames:
        frames = torch.cat([frames, frames[-1:].expand(model_frames - frames.shape[0], *frames.shape[1:])], dim=0)
    return frames[:model_frames]


def _conditioning_for_target(clip, vae, prompt: str, references: dict, source: torch.Tensor, width: int, height: int, ref_image_size: str):
    cached = [
        encoded_reference(vae, item["image"], width, height, ref_image_size)
        for item in references["images"]
    ]
    reference = comfy.utils.common_upscale(
        source.movedim(-1, 1),
        width,
        height,
        "lanczos",
        "disabled",
    ).movedim(1, -1)
    source_latent = vae.encode(reference).to(comfy.model_management.intermediate_device())
    items = [item[0] for item in cached]
    items.append(
        {
            "type": "video",
            "data": reference[::12],
            "timestamps": [frame / 2 for frame in range(len(reference[::12]))],
        }
    )
    blocks = [item[1] for item in cached]
    blocks.append(
        {
            "kind": "video",
            "latent_t": source_latent.shape[2],
            "latent_h": height // 16,
            "latent_w": width // 16,
            "ref_audio_t": 0,
            "latent": source_latent,
            "audio_latent": None,
        }
    )
    tokens = clip.tokenize(prompt, minimax_ref_items=items)
    positive = clip.encode_from_tokens_scheduled(tokens)
    return node_helpers.conditioning_set_values(positive, {"minimax_refs": blocks})


def _upscale_video_latent(latent: torch.Tensor, model_name: str, width: int, height: int, device: str, precision: str, chunking: bool) -> torch.Tensor:
    result = MiniMaxH3EasyLatentUpscaler3D.execute(
        {"samples": latent},
        str(model_name),
        {"mode": "target dimensions", "width": int(width), "height": int(height)},
        32,
        bool(chunking),
        str(device),
        str(precision),
    )[0]
    upscaled = result.get("samples") if isinstance(result, dict) else None
    if not isinstance(upscaled, torch.Tensor) or upscaled.ndim != 5:
        raise RuntimeError("二采 Latent 放大器没有返回有效的视频 Latent。")
    return upscaled


class CSRSecondPass:
    @classmethod
    def INPUT_TYPES(cls):
        models = [SAME_MODEL, *folder_paths.get_filename_list("diffusion_models")]
        loras = [NONE_LORA, *folder_paths.get_filename_list("loras")]
        return {
            "required": {
                "rendered_segments": ("CSR_RENDERED_SEGMENTS",),
                "enable_second_pass": ("BOOLEAN", {"default": False, "label_on": "二采开启", "label_off": "二采关闭"}),
                "second_pass_model": (models, {"default": SAME_MODEL}),
                "second_pass_lora": (loras, {"default": NONE_LORA}),
                "second_pass_lora_strength": ("FLOAT", {"default": 1.0, "min": -30.0, "max": 30.0, "step": 0.05}),
                "latent_upscale_model": (_latent_upscaler_choices(), {"default": _latent_upscaler_choices()[0]}),
                "upscale_scale": ("FLOAT", {"default": 1.5, "min": 1.0, "max": 4.0, "step": 0.05}),
                "upscale_device": (["cuda", "cpu"], {"default": "cuda"}),
                "upscale_precision": (["fp16", "bf16", "fp32"], {"default": "fp16"}),
                "upscale_chunking": ("BOOLEAN", {"default": True}),
                "steps": ("INT", {"default": 4, "min": 1, "max": 100}),
                "sampler_name": (comfy.samplers.SAMPLER_NAMES, {"default": "er_sde"}),
                "scheduler": (comfy.samplers.SCHEDULER_NAMES, {"default": "beta"}),
                "denoise": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.01}),
                "seed": ("INT", {"default": 888888, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "resume_completed": ("BOOLEAN", {"default": True}),
                "live_preview": ("BOOLEAN", {"default": True}),
                "preview_every_steps": ("INT", {"default": 1, "min": 1, "max": 100}),
                "preview_resolution": ([256, 384, 512, 768], {"default": 512}),
            },
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("CSR_RENDERED_SEGMENTS",)
    RETURN_NAMES = ("rendered_segments",)
    FUNCTION = "render"
    CATEGORY = CATEGORY

    @classmethod
    def VALIDATE_INPUTS(cls, enable_second_pass=False, latent_upscale_model=None, **_kwargs):
        if not enable_second_pass:
            return True
        if not latent_upscale_model or str(latent_upscale_model).startswith("("):
            return "开启二采后，请选择 Latent 放大模型。"
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        keys = (
            "enable_second_pass", "second_pass_model", "second_pass_lora",
            "second_pass_lora_strength", "latent_upscale_model", "upscale_scale",
            "upscale_device", "upscale_precision", "upscale_chunking", "steps",
            "sampler_name", "scheduler", "denoise", "seed", "resume_completed",
        )
        return json.dumps([kwargs.get(key) for key in keys], ensure_ascii=False, default=str)

    @disk_operation
    def render(
        self,
        rendered_segments,
        enable_second_pass,
        second_pass_model,
        second_pass_lora,
        second_pass_lora_strength,
        latent_upscale_model,
        upscale_scale,
        upscale_device,
        upscale_precision,
        upscale_chunking,
        steps,
        sampler_name,
        scheduler,
        denoise,
        seed,
        resume_completed,
        live_preview,
        preview_every_steps,
        preview_resolution,
        prompt=None,
        unique_id=None,
    ):
        if not enable_second_pass:
            result = dict(rendered_segments)
            result["second_pass_enabled"] = False
            return (result,)

        context = rendered_segments.get("_second_pass_context")
        if not isinstance(context, dict):
            raise ValueError("二采数据不完整，请重新执行 CSR ③。")
        bundle = context["job_bundle"]
        plan = bundle["plan"]
        references = bundle["references"]
        first_model = bundle["model"]
        clip = bundle["clip"]
        vae = bundle["vae"]
        base_prompt = context["base_prompt"]
        ref_image_size = choice_key(context["ref_image_size"], REF_SIZE_CHOICES, "max")
        model_width, model_height, output_width, output_height = _target_dimensions(
            rendered_segments, float(upscale_scale)
        )
        if str(latent_upscale_model).startswith("("):
            raise ValueError("请先在 models/latent_upscale_models 放入并选择 Latent 放大模型。")

        settings = {
            "second_pass_model": second_pass_model,
            "second_pass_lora": second_pass_lora,
            "second_pass_lora_strength": float(second_pass_lora_strength),
            "latent_upscale_model": latent_upscale_model,
            "upscale_scale": float(upscale_scale),
            "upscale_device": upscale_device,
            "upscale_precision": upscale_precision,
            "upscale_chunking": bool(upscale_chunking),
            "steps": int(steps),
            "sampler": sampler_name,
            "scheduler": scheduler,
            "denoise": float(denoise),
            "seed": int(seed),
            "target_model": [model_width, model_height],
            "target_output": [output_width, output_height],
        }
        first_hashes = [
            hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in rendered_segments["paths"]
        ]
        stamps = [
            _model_stamp("diffusion_models", second_pass_model),
            _model_stamp("loras", second_pass_lora),
            _model_stamp("latent_upscale_models", latent_upscale_model),
            graph_file_stamps(prompt),
        ]
        digest = hashlib.sha256(
            json.dumps(
                [VERSION, "CSR-second-pass", first_hashes, settings, stamps],
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ).encode()
        ).hexdigest()[:24]
        job = Path(rendered_segments["job"])
        segments_dir = job / "second_pass" / ("job_" + digest) / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        model = _second_model(
            first_model,
            str(second_pass_model),
            str(second_pass_lora),
            float(second_pass_lora_strength),
        )
        monitor = CSRProgressMonitor(unique_id)
        monitor.configure_preview(model)
        total_segments = len(plan["segments"])
        processed_frames = 0
        last_file = None
        last_subfolder = None
        previous_tail = None
        paths, reports, warnings = [], [], []
        start_time = time.perf_counter()

        for segment in plan["segments"]:
            comfy.model_management.throw_exception_if_processing_interrupted()
            index = int(segment["index"])
            prefix = int(segment["prefix"])
            model_frames = int(segment["model_frames"])
            keep = int(segment["output_frames"])
            first_path = rendered_segments["paths"][index]
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
                    tail_count = min(max(int(plan.get("context_frames", 0)), int(plan.get("seam_blend_frames", 0))), keep)
                    previous_tail = frames_tensor(str(target), keep - tail_count, tail_count, model_width, model_height) if tail_count else None
                    reports.append({"segment": index, "resumed_second_pass": True, "frames": keep})
                    processed_frames += keep
                    file, subfolder = output_file_ref(target)
                    last_file, last_subfolder = file, subfolder
                    monitor.emit(
                        phase="resumed",
                        overall=processed_frames / max(1, int(plan["total_frames"])),
                        segment_index=index,
                        total_segments=total_segments,
                        segment_start=int(segment["start"]),
                        segment_end=int(segment["end"]),
                        total_frames=int(plan["total_frames"]),
                        segment_file=file,
                        segment_subfolder=subfolder,
                        live_preview=False,
                    )
                    continue

            segment_started = time.perf_counter()
            source = frames_tensor(plan["normalized"], int(segment["input_start"]), model_frames, int(plan["width"]), int(plan["height"]))
            first_frames = _prepare_first_pass_frames(
                first_path,
                source,
                prefix,
                keep,
                model_frames,
                int(plan["width"]),
                int(plan["height"]),
            )
            base_video = vae.encode(first_frames).to(comfy.model_management.intermediate_device())
            monitor.emit(
                phase="upscaling",
                overall=processed_frames / max(1, int(plan["total_frames"])),
                segment_index=index,
                total_segments=total_segments,
                segment_start=int(segment["start"]),
                segment_end=int(segment["end"]),
                total_frames=int(plan["total_frames"]),
                step=0,
                steps=int(steps),
                live_preview=False,
            )
            if str(upscale_device).lower() in {"cuda", "rocm"}:
                try:
                    comfy.model_management.unload_model_and_clones(model, unload_additional_models=False)
                    comfy.model_management.soft_empty_cache()
                except Exception:
                    pass
            upscaled_video = _upscale_video_latent(
                base_video,
                str(latent_upscale_model),
                model_width,
                model_height,
                str(upscale_device),
                str(upscale_precision),
                bool(upscale_chunking),
            )
            second_latent = empty_video_latent(model_width, model_height, model_frames)
            placeholder_audio = second_latent["samples"].tensors[1]
            if upscaled_video.shape[0] != placeholder_audio.shape[0] or upscaled_video.shape[1] != 24:
                raise RuntimeError("二采 Latent 的 batch 或视频通道数与 H3 模型不兼容。")
            second_latent["samples"] = comfy.nested_tensor.NestedTensor(
                (
                    upscaled_video.to(comfy.model_management.intermediate_device()),
                    placeholder_audio.to(upscaled_video.device),
                )
            )
            positive = _conditioning_for_target(
                clip,
                vae,
                base_prompt,
                references,
                source,
                model_width,
                model_height,
                ref_image_size,
            )
            guide = None
            if prefix and previous_tail is not None:
                if previous_tail.shape[0] < prefix:
                    raise RuntimeError("二采上一段尾帧不足，不能继承当前段上下文。")
                guide = previous_tail[-prefix:]
            elif index == 0 and references.get("master") is not None:
                guide = comfy.utils.common_upscale(
                    references["master"].movedim(-1, 1),
                    model_width,
                    model_height,
                    "lanczos",
                    "center",
                ).movedim(1, -1)
            if guide is not None:
                positive = MiniMaxH3AddGuide.execute(
                    positive,
                    second_latent,
                    0,
                    vae=vae,
                    image=guide,
                ).result[0]

            guider = Guider_Basic(model)
            guider.set_conds(positive)
            sigmas = _second_sigmas(model, sampler_name, scheduler, int(steps), float(denoise)).cpu()
            if sigmas.numel() < 2:
                second_samples = second_latent["samples"]
            else:
                noise = comfy.sample.prepare_noise(second_latent["samples"], int(seed))
                progress_bar = comfy.utils.ProgressBar(max(1, int(sigmas.numel()) - 1))

                def callback(step, x0, _x, total):
                    progress_bar.update_absolute(step + 1, total)
                    ratio = min(1.0, (step + 1) / max(1, int(total)))
                    overall = (processed_frames + keep * ratio) / max(1, int(plan["total_frames"]))
                    elapsed = monitor._elapsed()
                    eta = elapsed * (1.0 - overall) / overall if overall > 0.02 else None
                    monitor.emit(
                        phase="second_sampling",
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

                second_samples = guider.sample(
                    noise,
                    second_latent["samples"],
                    comfy.samplers.sampler_object(str(sampler_name)),
                    sigmas,
                    callback=callback,
                    disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED,
                    seed=int(seed),
                )
            if not second_samples.is_nested or len(second_samples.tensors) != 2:
                raise RuntimeError("二采模型不是 MiniMax H3 AV 模型，无法生成兼容的 latent。")
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
            second_samples = second_samples.to(torch.device("cpu"))
            decoded = vae.decode(second_samples.tensors[0])
            if decoded.ndim == 5:
                decoded = decoded.reshape(-1, *decoded.shape[-3:])
            if decoded.shape[0] < prefix + keep:
                raise RuntimeError("二采 VAE 解码帧数不足。")
            decoded = decoded[prefix:prefix + keep, ..., :3].detach().cpu().clone().clamp_(0, 1)
            blend_count = int(plan.get("seam_blend_frames", 0)) if index > 0 and previous_tail is not None else 0
            blend_count = min(blend_count, keep, previous_tail.shape[0] if previous_tail is not None else 0)
            if blend_count > 0:
                previous = previous_tail[-blend_count:].to(decoded.device)
                blended = []
                for frame_index in range(blend_count):
                    alpha = 1.0 - frame_index / blend_count
                    blended.append((previous[frame_index] * alpha + decoded[frame_index] * (1.0 - alpha)).clamp_(0, 1))
                blended[0] = previous[-1].clone()
                decoded = torch.cat([torch.stack(blended, dim=0), decoded[blend_count:]], dim=0)

            temporary = target.with_name(target.stem + ".partial.mp4")
            encode_frames(
                temporary,
                (frame.mul(255).round().to(torch.uint8).contiguous().numpy().tobytes() for frame in decoded),
                model_width,
                model_height,
                encoder=plan["encoder"],
            )
            if probe(temporary, count_frames=True)["frames"] != keep:
                raise RuntimeError("二采片段编码后的帧数不正确。")
            temporary.replace(target)
            tail_count = min(max(int(plan.get("context_frames", 0)), int(plan.get("seam_blend_frames", 0))), keep)
            previous_tail = frames_tensor(str(target), keep - tail_count, tail_count, model_width, model_height) if tail_count else None
            paths.append(str(target))
            processed_frames += keep
            file, subfolder = output_file_ref(target)
            last_file, last_subfolder = file, subfolder
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
                segment_file=file,
                segment_subfolder=subfolder,
                live_preview=False,
            )
            marker.write_text(
                json.dumps(
                    {
                        "digest": digest,
                        "frames": keep,
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            reports.append(
                {
                    "segment": index,
                    "resumed_second_pass": False,
                    "frames": keep,
                    "elapsed_seconds": round(time.perf_counter() - segment_started, 3),
                }
            )
            del decoded, second_samples, second_latent, upscaled_video, base_video
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass

        last = plan["segments"][-1] if plan["segments"] else {"index": 0, "start": 0, "end": 0}
        monitor.emit(
            phase="complete",
            overall=1.0,
            segment_index=int(last.get("index", total_segments - 1)),
            total_segments=total_segments,
            segment_start=int(last["start"]),
            segment_end=int(last["end"]),
            total_frames=int(plan["total_frames"]),
            step=int(steps),
            steps=int(steps),
            segment_file=last_file,
            segment_subfolder=last_subfolder,
            done=True,
            ok=True,
            live_preview=False,
        )
        result = dict(rendered_segments)
        result.update(
            {
                "paths": paths,
                "width": model_width,
                "height": model_height,
                "output_width": output_width,
                "output_height": output_height,
                "segments": reports,
                "warnings": [*rendered_segments.get("warnings", []), *warnings],
                "second_pass_enabled": True,
                "second_pass": {
                    "digest": digest,
                    "settings": settings,
                    "segments_dir": str(segments_dir),
                    "elapsed_seconds": round(time.perf_counter() - start_time, 3),
                },
                "elapsed_seconds": round(float(rendered_segments.get("elapsed_seconds", 0.0)) + time.perf_counter() - start_time, 3),
            }
        )
        (job / "second_pass_report.json").write_text(
            json.dumps(result["second_pass"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return (result,)


NODE_CLASS_MAPPINGS = {"CSRSecondPass": CSRSecondPass}
NODE_DISPLAY_NAME_MAPPINGS = {"CSRSecondPass": "CSR ③B 二采放大 · 可选 · 断点续跑"}
