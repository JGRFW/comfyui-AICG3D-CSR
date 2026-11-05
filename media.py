"""FFmpeg-backed video planning and seamless assembly for AICG3D-CSR."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

FPS = 24
RESOLUTION_PRESETS = ("360P", "480P", "540P", "720P", "1080P")
ASPECT_RATIO_VALUES = {
    "跟随源视频": None,
    "16:9": 16 / 9,
    "16:10": 16 / 10,
    "9:16": 9 / 16,
    "1:1": 1.0,
    "4:3": 4 / 3,
    "3:4": 3 / 4,
    "21:9": 21 / 9,
}


class VideoError(RuntimeError):
    pass


def ffmpeg_path() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise VideoError(
            "需要 FFmpeg。请把 ffmpeg/ffprobe 加入 PATH，或在 ComfyUI 环境安装 imageio-ffmpeg。"
        ) from exc


def ffprobe_path() -> str:
    candidates: list[Path] = []
    ffmpeg = Path(ffmpeg_path())
    if ffmpeg.name.lower().startswith("ffmpeg"):
        candidates.append(ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    found = shutil.which("ffprobe")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise VideoError("需要与 FFmpeg 配套的 ffprobe，请把二者加入 PATH。")


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    process = subprocess.run(
        [str(part) for part in command],
        capture_output=True,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if check and process.returncode:
        message = process.stderr.decode("utf-8", errors="replace")[-4000:]
        raise VideoError(f"FFmpeg 执行失败：{message}")
    return process


def probe(path: str | os.PathLike, *, count_frames: bool = False) -> dict:
    command = [ffprobe_path(), "-v", "error", "-show_streams", "-show_format", "-of", "json"]
    if count_frames:
        command.insert(1, "-count_frames")
    command.append(str(path))
    process = run(command)
    data = json.loads(process.stdout.decode("utf-8", errors="replace"))
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
    if video is None:
        raise VideoError("输入文件没有视频轨道。")
    audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)
    duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0.0)
    raw_frames = (
        video.get("nb_read_frames")
        or video.get("nb_frames")
        or (round(duration * FPS) if duration > 0 else 0)
    )
    video_start = float(video.get("start_time") or 0.0)
    audio_start = float(audio.get("start_time") or video_start) if audio else video_start
    return {
        "path": str(Path(path).resolve()),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "duration": duration,
        "frames": int(raw_frames),
        "fps": float(video.get("avg_frame_rate", "0/1").split("/")[0] or 0)
        / max(1.0, float((video.get("avg_frame_rate") or "1/1").split("/")[-1] or 1)),
        "audio_offset": audio_start - video_start,
        "has_audio": audio is not None,
        "codec": video.get("codec_name"),
    }


def probe_audio(path: str | os.PathLike) -> dict:
    command = [ffprobe_path(), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    process = run(command)
    data = json.loads(process.stdout.decode("utf-8", errors="replace"))
    audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if audio is None:
        return {
            "path": str(Path(path).resolve()),
            "has_audio": False,
            "duration": 0.0,
            "audio_offset": 0.0,
            "codec": None,
            "sample_rate": 0,
            "channels": 0,
        }
    duration = float(audio.get("duration") or data.get("format", {}).get("duration") or 0.0)
    return {
        "path": str(Path(path).resolve()),
        "has_audio": True,
        "duration": duration,
        "audio_offset": 0.0,
        "codec": audio.get("codec_name"),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
    }


def output_canvas(width: int, height: int, short_edge: int) -> tuple[int, int]:
    if width < 1 or height < 1:
        raise VideoError("视频尺寸无效。")
    scale = float(short_edge) / min(width, height)
    out_width = max(32, round(width * scale / 32) * 32)
    out_height = max(32, round(height * scale / 32) * 32)
    return out_width, out_height


def resolution_canvas(
    width: int,
    height: int,
    short_edge: int,
    preset: str = "默认（短边）",
    custom_width: int = 0,
    custom_height: int = 0,
    aspect_ratio: str = "跟随源视频",
) -> tuple[int, int, int, int]:
    """Return model canvas and exact delivery canvas.

    H3 patchifies in 32-pixel blocks, so generation dimensions must be aligned.
    Standard presets such as 1080p are restored exactly during final delivery.
    """
    if width < 1 or height < 1:
        raise VideoError("视频尺寸无效。")
    text = str(preset or "默认（短边）")
    aspect_text = str(aspect_ratio or "跟随源视频")
    aspect = ASPECT_RATIO_VALUES.get(aspect_text, None)
    if text in RESOLUTION_PRESETS or text == "默认（短边）":
        target_short = int(text[:-1]) if text in RESOLUTION_PRESETS else int(short_edge)
        if aspect is None:
            scale = float(target_short) / min(width, height)
            out_width, out_height = round(width * scale), round(height * scale)
        elif aspect >= 1.0:
            out_width, out_height = round(target_short * aspect), target_short
        else:
            out_width, out_height = target_short, round(target_short / aspect)
    elif text == "自定义" and (int(custom_width) > 0 or int(custom_height) > 0):
        requested_width, requested_height = int(custom_width), int(custom_height)
        if requested_width > 0 and requested_height > 0:
            out_width, out_height = requested_width, requested_height
        elif requested_width > 0:
            out_width = requested_width
            out_height = round(requested_width * height / width)
        else:
            out_height = requested_height
            out_width = round(requested_height * width / height)
    else:
        out_width, out_height = output_canvas(width, height, int(short_edge))
    out_width = max(2, math.floor(int(out_width) / 2 + 0.5) * 2)
    out_height = max(2, math.floor(int(out_height) / 2 + 0.5) * 2)
    model_width = max(32, math.ceil(out_width / 32) * 32)
    model_height = max(32, math.ceil(out_height / 32) * 32)
    return model_width, model_height, out_width, out_height


def align_model_frames(count: int) -> int:
    """H3 uses a 17k+5 frame grid. Return the smallest legal frame count >= count."""
    count = max(5, int(count))
    return count + (5 - count) % 17


def _parse_range_rows(value: str | list | tuple) -> list[tuple[float, float]]:
    if isinstance(value, (list, tuple)):
        rows = list(value)
    else:
        text = str(value or "").strip()
        if not text:
            raise VideoError("还没有设置分段。请在“上传视频与自由分段”节点里添加至少一段。")
        try:
            decoded = json.loads(text)
            rows = decoded if isinstance(decoded, list) else decoded.get("segments", [])
        except (json.JSONDecodeError, AttributeError):
            rows = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:-|~|,|，|;|；|\s)\s*(-?\d+(?:\.\d+)?)", line)
                if match:
                    rows.append((float(match.group(1)), float(match.group(2))))
            if not rows:
                numbers = [float(number) for number in re.findall(r"\d+(?:\.\d+)?", text)]
                rows = [(numbers[index], numbers[index + 1]) for index in range(0, len(numbers) - 1, 2)]

    parsed: list[tuple[float, float]] = []
    for row in rows:
        if isinstance(row, dict):
            start = row.get("start", row.get("start_sec", row.get("from")))
            end = row.get("end", row.get("end_sec", row.get("to")))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            start, end = row[0], row[1]
        else:
            raise VideoError(f"无法识别分段格式：{row!r}")
        try:
            start_seconds, end_seconds = float(start), float(end)
        except (TypeError, ValueError) as exc:
            raise VideoError(f"分段起止必须为秒数：{row!r}") from exc
        if not math.isfinite(start_seconds) or not math.isfinite(end_seconds):
            raise VideoError("分段起止必须是有限数字。")
        if end_seconds <= start_seconds:
            raise VideoError(f"分段结束时间必须大于开始时间：{start_seconds:g}-{end_seconds:g}")
        parsed.append((start_seconds, end_seconds))
    if not parsed:
        raise VideoError("没有可用的分段。")
    return parsed


@dataclass(frozen=True)
class Segment:
    index: int
    start: int
    end: int
    input_start: int
    prefix: int
    model_frames: int

    @property
    def output_frames(self) -> int:
        return self.end - self.start

    @property
    def start_seconds(self) -> float:
        return self.start / FPS

    @property
    def end_seconds(self) -> float:
        return self.end / FPS

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "start_seconds": round(self.start_seconds, 6),
            "end_seconds": round(self.end_seconds, 6),
            "output_frames": self.output_frames,
            "input_start": self.input_start,
            "prefix": self.prefix,
            "model_frames": self.model_frames,
        }


def plan_segments(
    total_frames: int,
    ranges: str | list | tuple,
    *,
    context_frames: int = 22,
    max_segments: int = 200,
) -> list[Segment]:
    if total_frames < 1:
        raise VideoError("视频没有有效帧。")
    rows = _parse_range_rows(ranges)
    if len(rows) > max_segments:
        raise VideoError(f"分段数 {len(rows)} 超过上限 {max_segments}。")
    context_frames = max(0, min(int(context_frames), 90))
    frame_rows: list[tuple[int, int]] = []
    for index, (start_seconds, end_seconds) in enumerate(rows):
        start = round(start_seconds * FPS)
        end = round(end_seconds * FPS)
        if index == len(rows) - 1:
            if abs(end_seconds - total_frames / FPS) <= 1.0 / FPS:
                end = total_frames
        frame_rows.append((start, end))

    for index, (start, end) in enumerate(frame_rows):
        if start < 0 or end > total_frames:
            raise VideoError(f"第 {index + 1} 段超出视频范围：{start / FPS:.3f}-{end / FPS:.3f} 秒。")
        if end <= start:
            raise VideoError(f"第 {index + 1} 段不足一帧。")
    for index in range(1, len(frame_rows)):
        if frame_rows[index][0] != frame_rows[index - 1][1]:
            previous_end = frame_rows[index - 1][1] / FPS
            current_start = frame_rows[index][0] / FPS
            kind = "缺口" if current_start > previous_end else "重叠"
            raise VideoError(
                f"第 {index} 段与第 {index + 1} 段存在{kind}：{previous_end:.3f}s != {current_start:.3f}s。"
                "输出区间必须首尾相接；跨段连续性由节点内部重叠上下文处理，不需要手填重复时间。"
            )

    segments: list[Segment] = []
    for index, (start, end) in enumerate(frame_rows):
        output_frames = end - start
        prefix = min(context_frames, output_frames, start if index == 0 else output_frames)
        input_start = start - prefix
        model_frames = align_model_frames(prefix + output_frames)
        segments.append(Segment(index, start, end, input_start, prefix, model_frames))
    return segments


def extract_audio(
    source: str | os.PathLike,
    target: str | os.PathLike,
    *,
    audio_offset: float = 0.0,
    duration_seconds: float = 0.0,
) -> dict:
    """Extract one standalone, timeline-aligned WAV track. No segment carries audio."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial.wav")
    filters = ["asetpts=PTS-STARTPTS"]
    if audio_offset < 0:
        filters.append(f"atrim=start={-audio_offset:.9f}")
        filters.append("asetpts=PTS-STARTPTS")
    elif audio_offset > 0:
        filters.append(f"adelay={round(audio_offset * 1000)}:all=1")
    filters.append("apad")
    command = [
        ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-i", str(source),
        *(["-t", f"{duration_seconds:.9f}"] if duration_seconds > 0 else []),
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-af", ",".join(filters),
        "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(partial),
    ]
    run(command)
    os.replace(partial, target)
    return probe_audio(target)


def normalize_video(
    source: str | os.PathLike,
    target: str | os.PathLike,
    width: int,
    height: int,
    *,
    start_seconds: float = 0.0,
    duration_seconds: float = 0.0,
) -> dict:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + ".partial.mp4")
    trim = ["-ss", f"{start_seconds:.9f}"] if start_seconds > 0 else []
    duration = ["-t", f"{duration_seconds:.9f}"] if duration_seconds > 0 else []
    command = [
        ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        *trim, "-i", str(source), *duration, "-an",
        "-vf", (
            f"setpts=PTS-STARTPTS,fps={FPS},"
            f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={width}:{height},setsar=1"
        ),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(partial),
    ]
    run(command)
    os.replace(partial, target)
    return probe(target, count_frames=True)


def read_frames(
    path: str | os.PathLike,
    start: int,
    count: int,
    width: int,
    height: int,
    *,
    gray: bool = False,
) -> tuple[bytes, int]:
    command = [
        ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-ss", f"{int(start) / FPS:.9f}", "-i", str(path), "-frames:v", str(int(count)), "-an",
        "-vf", f"scale={width}:{height}:flags=bilinear",
        "-f", "rawvideo", "-pix_fmt", "gray" if gray else "rgb24", "-",
    ]
    process = run(command)
    frame_bytes = width * height * (1 if gray else 3)
    if not process.stdout or len(process.stdout) % frame_bytes:
        raise VideoError("分段解码没有得到完整帧，请检查视频文件或 FFmpeg 版本。")
    return process.stdout, len(process.stdout) // frame_bytes


def encode_frames(
    path: str | os.PathLike,
    frames: Iterable[bytes],
    width: int,
    height: int,
    *,
    encoder: str = "libx264",
    crf: int = 16,
) -> None:
    if encoder not in ("libx264", "h264_nvenc"):
        raise VideoError(f"不支持的编码器：{encoder}")
    command = [
        ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(FPS),
        "-i", "-", "-an", "-c:v", encoder,
    ]
    if encoder == "libx264":
        command += ["-preset", "veryfast", "-crf", str(crf)]
    else:
        command += ["-preset", "p4", "-rc", "vbr", "-cq", str(crf)]
    command += ["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    try:
        assert process.stdin is not None
        for frame in frames:
            process.stdin.write(frame)
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
        raise VideoError("视频编码失败：" + error.decode("utf-8", errors="replace")[-3000:])


def _concat_quote(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "'\\''")


def boundary_frame_deltas(path: str | os.PathLike, boundaries: Iterable[int], width: int, height: int) -> list[dict]:
    result: list[dict] = []
    for boundary in boundaries:
        if boundary < 1:
            continue
        try:
            pair, count = read_frames(path, boundary - 1, 2, width, height)
            if count != 2:
                continue
            frame_bytes = width * height * 3
            before = pair[:frame_bytes]
            after = pair[frame_bytes:]
            delta = sum(abs(a - b) for a, b in zip(before, after)) / max(1, len(before))
            result.append({"frame": int(boundary), "mean_abs_delta_0_255": round(delta, 4)})
        except (VideoError, OSError):
            continue
    return result


def merge_segments(
    paths: list[str | os.PathLike],
    source_audio: str | os.PathLike,
    output: str | os.PathLike,
    total_frames: int,
    boundaries: Iterable[int] = (),
    *,
    width: int = 0,
    height: int = 0,
    keep_audio: bool = True,
    encoder: str = "libx264",
    audio_start_seconds: float = 0.0,
) -> dict:
    if not paths:
        raise VideoError("没有可合并的片段。")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    listing = output_path.parent / "concat.txt"
    lines = []
    for path in paths:
        item = Path(path)
        if not item.is_file():
            raise VideoError(f"缺少已完成片段：{item}")
        lines.append(f"file '{_concat_quote(item.resolve())}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")

    partial_final = output_path.with_name("final.partial.mp4")
    # Re-encoding the concat timeline once removes encoder-parameter and timestamp seams
    # that can survive a stream-copy concat even when every segment has the right length.
    base = [
        ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(listing),
    ]
    info = probe_audio(source_audio) if source_audio is not None and Path(source_audio).is_file() else {}
    if keep_audio and info.get("has_audio"):
        base += ["-i", str(source_audio), "-map", "0:v:0", "-map", "1:a:0"]
        filters = "asetpts=PTS-STARTPTS"
        if info["audio_offset"] < 0:
            filters += f",atrim=start={-info['audio_offset']:.9f},asetpts=PTS-STARTPTS"
        elif info["audio_offset"] > 0:
            filters += f",adelay={round(info['audio_offset'] * 1000)}:all=1"
        if audio_start_seconds > 0:
            filters += f",atrim=start={float(audio_start_seconds):.9f},asetpts=PTS-STARTPTS"
        base += ["-af", filters + ",apad", "-c:a", "aac", "-b:a", "192k"]
    else:
        base += ["-map", "0:v:0", "-an"]
    if encoder == "libx264":
        video_args = ["-c:v", "libx264", "-preset", "medium", "-crf", "16"]
    elif encoder == "h264_nvenc":
        video_args = ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "16"]
    else:
        raise VideoError(f"不支持的编码器：{encoder}")
    base += video_args + [
        *(["-vf", f"scale={int(width)}:{int(height)}:flags=lanczos"] if width > 0 and height > 0 else []),
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-fps_mode", "cfr",
        "-t", f"{total_frames / FPS:.9f}", "-movflags", "+faststart", str(partial_final),
    ]
    run(base)
    actual = probe(partial_final, count_frames=True)["frames"]
    if actual != total_frames:
        raise VideoError(f"最终合并帧数不匹配：预期 {total_frames} 帧，实际 {actual} 帧。")
    os.replace(partial_final, output_path)
    boundaries = list(boundaries)
    report = {
        "output": str(output_path.resolve()),
        "total_frames": total_frames,
        "duration_seconds": total_frames / FPS,
        "output_width": int(width) if width > 0 else None,
        "output_height": int(height) if height > 0 else None,
        "boundary_frames": boundaries,
        "audio_source": str(Path(source_audio).resolve()) if keep_audio and info.get("has_audio") else None,
        "audio_start_seconds": round(float(audio_start_seconds), 9),
        "audio_muxed_after_video": bool(keep_audio and info.get("has_audio")),
    }
    if width > 0 and height > 0:
        report["boundary_deltas"] = boundary_frame_deltas(output_path, boundaries, width, height)
    return report


def write_json(path: str | os.PathLike, value: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".partial")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)
