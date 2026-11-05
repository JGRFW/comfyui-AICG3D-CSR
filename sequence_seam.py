# Adapted from ComfyUI-AICG3D, Copyright (c) nkxx188, MIT License.
"""Cross-segment exposure lock, opening grade and direct seamless export."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from .media import FPS, VideoError, boundary_frame_deltas, ffmpeg_path, probe, probe_audio, read_frames

EXPOSURE_WINDOW = 9
SEGMENT_LUMA_MAX = 0.04
SEGMENT_LUMA_EPSILON = 0.002
GRADE_FRAMES = 12
GRADE_WEIGHT = 0.70
GRADE_BLUR = 64
ADD_LUMA_FRAMES = 12
ADD_LUMA_MAX = 0.10
SEAM_LUMA_EPSILON = 0.008
BRIDGE_RATIO = 1.75
BRIDGE_MIN_STEP = 0.025
BRIDGE_MAX_STEP = 0.090
CUT_LOWFREQ = 0.045
CUT_STRUCTURE = 0.022
BRIDGE_MIN_WEIGHT = 0.10
BRIDGE_MAX_WEIGHT = 0.45


def _frame_luma(frame: torch.Tensor) -> float:
    return float((frame.float() * frame.new_tensor([0.299, 0.587, 0.114])).sum(-1).mean())


def _robust_luma(frames: torch.Tensor) -> float:
    if frames.ndim != 4 or frames.numel() == 0:
        return 0.0
    step = max(1, int(frames.shape[0]) // 24)
    values = (frames[::step].float() * frames.new_tensor([0.299, 0.587, 0.114])).sum(-1).mean((1, 2))
    return float(values.median())


def _fit(frame: torch.Tensor, width: int, height: int) -> torch.Tensor:
    if frame.ndim == 4:
        frame = frame[0]
    if tuple(frame.shape[:2]) == (height, width):
        return frame
    value = frame.permute(2, 0, 1).unsqueeze(0).float()
    return F.interpolate(value, size=(height, width), mode="bilinear", align_corners=False)[0].permute(1, 2, 0).to(frame.dtype)


def _blur(frames: torch.Tensor, kernel: int = GRADE_BLUR) -> torch.Tensor:
    source = frames.detach().float()
    if source.ndim == 3:
        source = source.unsqueeze(0)
    kernel = max(3, int(kernel) | 1)
    value = source.permute(0, 3, 1, 2)
    value = F.pad(value, (kernel // 2, kernel // 2, kernel // 2, kernel // 2), mode="replicate")
    return F.avg_pool2d(value, kernel, stride=1).permute(0, 2, 3, 1)


def _mae(left: torch.Tensor, right: torch.Tensor) -> float:
    if left.ndim == 4:
        left = left[0]
    if right.ndim == 4:
        right = right[0]
    if tuple(left.shape) != tuple(right.shape):
        right = _fit(right, int(left.shape[1]), int(left.shape[0]))
    return float((left.float() - right.float()).abs().mean())


def _snapshot(frames: torch.Tensor, tail: torch.Tensor) -> dict[str, float]:
    guide = _fit(tail[-1], int(frames.shape[2]), int(frames.shape[1]))
    body = frames[0]
    y0, y1, y2, start = _frame_luma(body), _frame_luma(frames[min(1, len(frames) - 1)]), _frame_luma(frames[min(2, len(frames) - 1)]), _frame_luma(guide)
    left, right = _blur(guide)[0], _blur(body)[0]
    structure_left = left - left.mean((0, 1), keepdim=True)
    structure_right = right - right.mean((0, 1), keepdim=True)
    return {
        "seam_gap": abs(y0 - start),
        "opening_spike": abs(y1 - y0) + abs(y2 - y1),
        "lowfreq_diff": _mae(left, right),
        "structure_diff": _mae(structure_left, structure_right),
    }


def _match_segment_luma(frames: torch.Tensor, target: float | None) -> tuple[torch.Tensor, float]:
    if target is None:
        return frames, 0.0
    offset = max(-SEGMENT_LUMA_MAX, min(SEGMENT_LUMA_MAX, target - _robust_luma(frames)))
    if abs(offset) >= SEGMENT_LUMA_EPSILON:
        frames.add_(offset).clamp_(0, 1)
    return frames, float(offset)


def _match_opening_grade(frames: torch.Tensor, tail: torch.Tensor) -> torch.Tensor:
    count = min(GRADE_FRAMES, len(frames))
    guide = _fit(tail[-1], int(frames.shape[2]), int(frames.shape[1]))
    source = frames[:count].float()
    source_blur = _blur(source)
    guide_blur = _blur(guide)[0]
    weights = frames.new_tensor([GRADE_WEIGHT * (1.0 - index / count) for index in range(count)]).view(-1, 1, 1, 1)
    corrected = (source + weights * (guide_blur.unsqueeze(0) - source_blur)).clamp_(0, 1)
    result = frames.clone()
    result[:count] = corrected.to(frames.dtype)
    return result


def _additive_opening(frames: torch.Tensor, tail: torch.Tensor) -> tuple[torch.Tensor, float, float]:
    count = min(ADD_LUMA_FRAMES, max(0, len(frames) - 1))
    if count < 2:
        return frames, 0.0, 0.0
    guide = _fit(tail[-1], int(frames.shape[2]), int(frames.shape[1]))
    start = _frame_luma(guide)
    y0, y1, y2 = _frame_luma(frames[0]), _frame_luma(frames[1]), _frame_luma(frames[2])
    end = _frame_luma(frames[count])
    before = abs(y0 - start) + abs(y1 - y0) + abs(y2 - y1)
    result = frames
    for index in range(count):
        target = start * (1.0 - index / count) + end * (index / count)
        delta = max(-ADD_LUMA_MAX, min(ADD_LUMA_MAX, target - _frame_luma(result[index])))
        if abs(delta) >= 1e-5:
            result[index] = (result[index].float() + delta).clamp_(0, 1).to(frames.dtype)
    after = _snapshot(result, tail)["opening_spike"]
    return result, before, after


def _motion_bridge(frames: torch.Tensor, tail: torch.Tensor, lowfreq: float) -> tuple[torch.Tensor, float]:
    if len(frames) < 2 or len(tail) < 2 or lowfreq > CUT_LOWFREQ:
        return frames, 0.0
    previous = _fit(tail[-2], int(frames.shape[2]), int(frames.shape[1]))
    last = _fit(tail[-1], int(frames.shape[2]), int(frames.shape[1]))
    body = _fit(frames[0], int(frames.shape[2]), int(frames.shape[1]))
    following = _fit(frames[1], int(frames.shape[2]), int(frames.shape[1]))
    regular = max(_mae(previous, last), _mae(body, following), 1e-6)
    seam = _mae(last, body)
    if seam < BRIDGE_MIN_STEP or seam > BRIDGE_MAX_STEP or seam / regular < BRIDGE_RATIO:
        return frames, 0.0
    severity = max(0.0, min(1.0, max(
        (seam - BRIDGE_MIN_STEP) / max(1e-6, BRIDGE_MAX_STEP - BRIDGE_MIN_STEP),
        (seam / regular - BRIDGE_RATIO) / max(1e-6, 5.0 - BRIDGE_RATIO),
    )))
    weight = BRIDGE_MIN_WEIGHT + (BRIDGE_MAX_WEIGHT - BRIDGE_MIN_WEIGHT) * severity
    predicted = (last.float() * 2.0 - previous.float()).clamp_(0, 1)
    bridge = predicted * 0.65 + last.float() * 0.35
    frames[0] = (body.float() * (1.0 - weight) + bridge * weight).clamp_(0, 1).to(frames.dtype)
    return frames, float(weight)


class SequenceSeamMatcher:
    def __init__(self, enabled: bool = True):
        self.enabled = bool(enabled)
        self.previous_tail: torch.Tensor | None = None
        self.previous_luma: float | None = None
        self.records: list[dict[str, Any]] = []

    def apply(self, frames: torch.Tensor, index: int) -> torch.Tensor:
        repaired = frames
        if self.previous_tail is None:
            self.previous_tail = repaired[-min(3, len(repaired)):].detach().cpu().contiguous()
            self.previous_luma = _robust_luma(repaired)
            return repaired
        before = _snapshot(repaired, self.previous_tail)
        hard_cut = before["structure_diff"] > CUT_STRUCTURE and before["lowfreq_diff"] > 0.012
        bridge = 0.0
        offset = 0.0
        if self.enabled and not hard_cut:
            repaired, bridge = _motion_bridge(repaired, self.previous_tail, before["lowfreq_diff"])
            repaired = _match_opening_grade(repaired, self.previous_tail)
            repaired, offset = _match_segment_luma(repaired, self.previous_luma)
            repaired, opening_before, opening_after = _additive_opening(repaired, self.previous_tail)
        else:
            opening_before, opening_after = before["opening_spike"], before["opening_spike"]
        after = _snapshot(repaired, self.previous_tail)
        self.records.append(
            {
                "from_segment": index - 1,
                "to_segment": index,
                "enabled": self.enabled,
                "hard_cut": hard_cut,
                "seam_gap_before": round(before["seam_gap"], 6),
                "seam_gap_after": round(after["seam_gap"], 6),
                "opening_spike_before": round(opening_before, 6),
                "opening_spike_after": round(opening_after, 6),
                "lowfreq_diff": round(before["lowfreq_diff"], 6),
                "structure_diff": round(before["structure_diff"], 6),
                "global_offset": round(offset, 6),
                "bridge_weight": round(bridge, 6),
            }
        )
        self.previous_tail = repaired[-min(3, len(repaired)):].detach().cpu().contiguous()
        self.previous_luma = _robust_luma(repaired)
        return repaired


def export_with_seam_repair(
    paths: list[str | os.PathLike],
    source_audio: str | os.PathLike | None,
    output: str | os.PathLike,
    total_frames: int,
    boundaries: list[int],
    *,
    segment_frames: list[int],
    width: int,
    height: int,
    output_width: int,
    output_height: int,
    keep_audio: bool,
    audio_start_seconds: float = 0.0,
) -> dict[str, Any]:
    if len(paths) != len(segment_frames):
        raise VideoError("二采/一采片段数量与帧数记录不一致。")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial = output_path.with_name(output_path.stem + ".partial.mp4")
    audio_info = probe_audio(source_audio) if source_audio is not None and Path(source_audio).is_file() else {}
    mux_audio = bool(keep_audio and audio_info.get("has_audio"))
    command = [
        ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(FPS), "-i", "-",
    ]
    if mux_audio:
        command += ["-i", str(source_audio), "-map", "0:v:0", "-map", "1:a:0"]
        audio_filter = "asetpts=PTS-STARTPTS"
        if audio_info["audio_offset"] < 0:
            audio_filter += f",atrim=start={-audio_info['audio_offset']:.9f},asetpts=PTS-STARTPTS"
        elif audio_info["audio_offset"] > 0:
            audio_filter += f",adelay={round(audio_info['audio_offset'] * 1000)}:all=1"
        if audio_start_seconds > 0:
            audio_filter += f",atrim=start={float(audio_start_seconds):.9f},asetpts=PTS-STARTPTS"
        command += ["-af", audio_filter + ",apad", "-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-map", "0:v:0", "-an"]
    command += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "16",
        "-vf", f"scale={int(output_width)}:{int(output_height)}:flags=lanczos",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-fps_mode", "cfr",
        "-t", f"{int(total_frames) / FPS:.9f}", "-movflags", "+faststart", str(partial),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    matcher = SequenceSeamMatcher(True)
    try:
        assert process.stdin is not None
        for index, (path, frames) in enumerate(zip(paths, segment_frames)):
            raw, actual = read_frames(path, 0, int(frames), width, height)
            if actual != int(frames):
                raise VideoError(f"接缝修复读取第 {index + 1} 段帧数不正确：预期 {frames}，实际 {actual}。")
            tensor = torch.frombuffer(bytearray(raw), dtype=torch.uint8).reshape(actual, height, width, 3).float().div_(255.0)
            corrected = matcher.apply(tensor, index)
            process.stdin.write(
                corrected.mul(255).round().to(torch.uint8).contiguous().numpy().tobytes()
            )
        process.stdin.close()
        assert process.stderr is not None
        error = process.stderr.read()
        code = process.wait()
    except BaseException:
        process.terminate()
        process.wait()
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        raise
    finally:
        if process.stderr:
            process.stderr.close()
    if code:
        raise VideoError("接缝修复合并失败：" + error.decode("utf-8", errors="replace")[-4000:])
    info = probe(partial, count_frames=True)
    if info["frames"] != total_frames:
        raise VideoError(f"最终接缝修复帧数不匹配：预期 {total_frames}，实际 {info['frames']}。")
    os.replace(partial, output_path)
    report = {
        "output": str(output_path.resolve()),
        "total_frames": int(total_frames),
        "duration_seconds": int(total_frames) / FPS,
        "output_width": int(output_width),
        "output_height": int(output_height),
        "boundary_frames": list(boundaries),
        "audio_source": str(Path(source_audio).resolve()) if mux_audio else None,
        "audio_start_seconds": round(float(audio_start_seconds), 9),
        "audio_muxed_after_video": mux_audio,
        "seam_exposure_lock": True,
        "seam_records": matcher.records,
    }
    report["boundary_deltas"] = boundary_frame_deltas(output_path, boundaries, output_width, output_height)
    return report
