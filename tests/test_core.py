"""Core planning tests that do not require a GPU or a running ComfyUI server."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media import FPS, align_model_frames, plan_segments, resolution_canvas


class PlanSegmentsTests(unittest.TestCase):
    def test_free_ranges_stay_exact_and_contiguous(self):
        total = 6 * FPS
        segments = plan_segments(
            total,
            '[{"start":0,"end":3},{"start":3,"end":4.5},{"start":4.5,"end":6}]',
            context_frames=22,
        )
        self.assertEqual([(item.start, item.end) for item in segments], [(0, 72), (72, 108), (108, 144)])
        self.assertEqual([item.output_frames for item in segments], [72, 36, 36])
        self.assertEqual(segments[0].prefix, 0)
        self.assertEqual(segments[1].prefix, 22)
        self.assertEqual(segments[1].input_start, 50)
        for item in segments:
            self.assertGreaterEqual(item.model_frames, item.prefix + item.output_frames)
            self.assertEqual((item.model_frames - 5) % 17, 0)

    def test_plain_text_ranges_are_supported(self):
        segments = plan_segments(6 * FPS, "0-3\n3-6")
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[-1].end, 144)

    def test_gap_is_rejected(self):
        with self.assertRaisesRegex(Exception, "缺口"):
            plan_segments(6 * FPS, "0-2\n3-6")

    def test_short_last_range_snaps_to_exact_end(self):
        segments = plan_segments(round(6.01 * FPS), "0-3\n3-6")
        self.assertEqual(segments[-1].end, round(6.01 * FPS))

    def test_cropped_window_can_start_and_end_inside_source(self):
        segments = plan_segments(
            20 * FPS,
            "[{\"start\":5,\"end\":15}]",
            context_frames=22,
        )
        self.assertEqual(len(segments), 1)
        self.assertEqual((segments[0].start, segments[0].end), (5 * FPS, 15 * FPS))
        self.assertEqual(segments[0].prefix, 22)
        self.assertEqual(segments[0].input_start, 5 * FPS - 22)
        self.assertEqual(segments[0].output_frames, 10 * FPS)

    def test_h3_frame_alignment(self):
        self.assertEqual([align_model_frames(value) for value in (72, 73, 90, 108)], [73, 73, 90, 124])

    def test_standard_resolution_presets_keep_exact_delivery_size(self):
        model_width, model_height, output_width, output_height = resolution_canvas(
            1920, 1080, 480, "1080P"
        )
        self.assertEqual((output_width, output_height), (1920, 1080))
        self.assertEqual((model_width, model_height), (1920, 1088))

    def test_custom_resolution_preserves_exact_requested_size(self):
        model_width, model_height, output_width, output_height = resolution_canvas(
            1920, 1080, 480, "自定义", 1000, 1000
        )
        self.assertEqual((output_width, output_height), (1000, 1000))
        self.assertEqual((model_width, model_height), (1024, 1024))

    def test_resolution_and_aspect_ratio_produce_fixed_delivery_sizes(self):
        landscape = resolution_canvas(1920, 1080, 480, "540P", aspect_ratio="16:9")
        portrait = resolution_canvas(1920, 1080, 480, "540P", aspect_ratio="9:16")
        hd = resolution_canvas(1920, 1080, 480, "480P", aspect_ratio="16:9")
        self.assertEqual(landscape, (960, 544, 960, 540))
        self.assertEqual(portrait, (544, 960, 540, 960))
        self.assertEqual(hd, (864, 480, 854, 480))


if __name__ == "__main__":
    unittest.main()
