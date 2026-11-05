"""End-to-end audio separation and final mux tests."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import media


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe are required")
class AudioPipelineTests(unittest.TestCase):
    def test_audio_is_extracted_and_only_muxed_at_the_end(self):
        with tempfile.TemporaryDirectory(prefix="csr_audio_test_") as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            media.run(
                [
                    media.ffmpeg_path(),
                    "-hide_banner",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=320x192:rate=24",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000",
                    "-t",
                    "1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    str(source),
                ]
            )
            source_info = media.probe(source, count_frames=True)
            self.assertTrue(source_info["has_audio"])
            self.assertEqual(source_info["frames"], 24)

            normalized = root / "normalized.mp4"
            video_info = media.normalize_video(source, normalized, 320, 192, duration_seconds=1)
            self.assertFalse(video_info["has_audio"])
            self.assertEqual(video_info["frames"], 24)

            standalone = root / "source_audio.wav"
            audio_info = media.extract_audio(source, standalone, duration_seconds=1)
            self.assertTrue(audio_info["has_audio"])
            self.assertEqual(audio_info["codec"], "pcm_s16le")
            self.assertEqual(audio_info["sample_rate"], 48000)

            parts = []
            for index, (start, count) in enumerate(((0, 12), (12, 12))):
                raw, actual = media.read_frames(normalized, start, count, 320, 192)
                self.assertEqual(actual, count)
                part = root / f"part_{index}.mp4"
                frame_bytes = 320 * 192 * 3
                media.encode_frames(
                    part,
                    (raw[offset : offset + frame_bytes] for offset in range(0, len(raw), frame_bytes)),
                    320,
                    192,
                )
                self.assertFalse(media.probe(part, count_frames=True)["has_audio"])
                parts.append(part)

            final = root / "final.mp4"
            report = media.merge_segments(
                parts,
                standalone,
                final,
                24,
                [12],
                width=160,
                height=96,
                keep_audio=True,
            )
            final_info = media.probe(final, count_frames=True)
            self.assertEqual(final_info["frames"], 24)
            self.assertEqual((final_info["width"], final_info["height"]), (160, 96))
            self.assertTrue(final_info["has_audio"])
            self.assertTrue(report["audio_muxed_after_video"])


if __name__ == "__main__":
    unittest.main()
