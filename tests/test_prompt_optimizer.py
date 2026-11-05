"""Prompt optimizer guardrails that do not require a live model server."""
from pathlib import Path
import asyncio
import importlib
import sys
import tempfile
import types
import unittest
from unittest import mock

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
sys.modules.setdefault("folder_paths", types.SimpleNamespace(
    get_user_directory=lambda: str(ROOT / ".test-user"),
    get_output_directory=lambda: str(ROOT / ".test-output"),
    get_folder_paths=lambda _category: [],
))

optimizer = importlib.import_module("prompt_optimizer")


class PromptOptimizerTests(unittest.TestCase):
    def test_api_base_defaults_to_v1(self):
        self.assertEqual(
            optimizer._normalize_api_base("http://127.0.0.1:11434"),
            "http://127.0.0.1:11434/v1",
        )

    def test_remote_api_is_blocked_without_explicit_opt_in(self):
        self.assertEqual(
            optimizer._validate_local_api_base("http://127.0.0.1:1234/v1"),
            "http://127.0.0.1:1234/v1",
        )
        with self.assertRaisesRegex(ValueError, "局域网"):
            optimizer._validate_local_api_base("http://8.8.8.8:1234/v1")

    def test_background_tags_resolve_to_strict_scheme(self):
        self.assertEqual(optimizer.resolve_scheme("背景/场景替换"), "background_replace")
        self.assertEqual(optimizer.resolve_scheme("单人替换"), "single_person_replace")
        self.assertEqual(optimizer.resolve_scheme("多人替换"), "multi_person_replace")
        self.assertEqual(optimizer.resolve_scheme("商品替换"), "product_replace")
        self.assertEqual(
            optimizer.resolve_scheme("背景/场景替换", "background_repair"),
            "background_repair",
        )

    def test_background_messages_contain_replacement_invariants(self):
        messages = optimizer._messages(
            "替换背景",
            "背景/场景替换",
            "background_replace",
            "中文",
            "strong",
        )
        text = "\n".join(item["content"] for item in messages)
        self.assertIn("complete environment", text)
        self.assertIn("Do not blend the old and new scene", text)
        self.assertIn("Return only the final prompt", text)

    def test_guardrail_is_added_and_model_noise_is_cleaned(self):
        cleaned = optimizer._clean_output("```text\nFinal prompt: replace the room\n```")
        self.assertNotIn("```", cleaned)
        guarded = optimizer._with_guardrail(cleaned, "background_replace", "中文")
        self.assertIn("强制背景替换", guarded)
        self.assertIn("replace the room", guarded)

    def test_vision_is_disabled_by_default_and_does_not_touch_media(self):
        config = optimizer._normalize_config({})
        self.assertFalse(config["vision_enabled"])
        self.assertEqual(config["vision_model"], "")
        self.assertEqual(config["local_mmproj"], "")
        payload = {
            "description": "替换背景",
            "replacement_tag": "背景/场景替换",
            "config": {"mode": "api", "vision_enabled": False},
            "media": {"video": "C:/private/do-not-read.mp4"},
        }
        with (
            mock.patch.object(optimizer, "_read_config", return_value=dict(optimizer.DEFAULT_CONFIG)),
            mock.patch.object(optimizer, "_visual_media", side_effect=AssertionError("media must not be read")),
            mock.patch.object(optimizer, "_api_optimize", new=mock.AsyncMock(return_value="replace the room")),
        ):
            result = asyncio.run(optimizer.optimize_prompt(payload))
        self.assertIn("replace the room", result)

    def test_visual_media_rejects_paths_outside_comfy_roots(self):
        with self.assertRaisesRegex(ValueError, "input、output 或 temp"):
            optimizer._resolve_media_file(str(ROOT / "README.md"))

    def test_image_encoding_returns_embeddable_data_url(self):
        output_root = ROOT / ".test-output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as temporary:
            path = Path(temporary) / "sample.png"
            Image.new("RGB", (1024, 768), (34, 120, 190)).save(path)
            encoded = optimizer._image_data_url(path)
        self.assertTrue(encoded.startswith("data:image/jpeg;base64,"))
        self.assertGreater(len(encoded), 1000)

    def test_visual_media_is_bounded_and_prioritizes_replacements(self):
        output_root = ROOT / ".test-output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as temporary:
            folder = Path(temporary)
            video = folder / "source.mp4"
            video.write_bytes(b"video-placeholder")
            files = []
            for index in range(6):
                path = folder / f"image_{index}.png"
                path.write_bytes(b"image-placeholder")
                files.append(str(path))
            media = {
                "video": str(video),
                "video_start": 1.0,
                "video_end": 4.0,
                "video_duration": 10.0,
                "images": [
                    {"file": files[0], "kind": "person", "label": "person"},
                    {"file": files[1], "kind": "reference", "label": "reference"},
                    {"file": files[2], "kind": "background", "label": "background"},
                    {"file": files[3], "kind": "object", "label": "product A"},
                    {"file": files[4], "kind": "object", "label": "product B"},
                ],
            }
            with (
                mock.patch.object(optimizer, "_video_frame_data_url", return_value="[image omitted]video"),
                mock.patch.object(optimizer, "_image_data_url", return_value="[image omitted]image"),
            ):
                visuals = optimizer._visual_media(media)
        self.assertEqual(len(visuals), optimizer.VISUAL_IMAGE_LIMIT)
        self.assertEqual([item["kind"] for item in visuals[:3]], ["video"] * 3)
        self.assertEqual([item["kind"] for item in visuals[3:]], ["background", "object", "object"])

    def test_vision_without_selected_model_stays_text_only(self):
        payload = {
            "description": "替换背景",
            "replacement_tag": "背景/场景替换",
            "config": {"mode": "api", "vision_enabled": True, "vision_model": ""},
            "media": {"video": "C:/private/do-not-read.mp4"},
        }
        with (
            mock.patch.object(optimizer, "_read_config", return_value=dict(optimizer.DEFAULT_CONFIG)),
            mock.patch.object(optimizer, "_visual_media", side_effect=AssertionError("no visual model selected")),
            mock.patch.object(optimizer, "_api_optimize", new=mock.AsyncMock(return_value="replace the room")),
        ):
            result = asyncio.run(optimizer.optimize_prompt(payload))
        self.assertIn("replace the room", result)

    def test_local_visual_request_unloads_model_after_optimization(self):
        payload = {
            "description": "替换背景",
            "replacement_tag": "背景/场景替换",
            "config": {"mode": "local", "vision_enabled": True, "local_mmproj": "mmproj.gguf"},
        }
        visual = [{"kind": "background", "label": "background", "url": "[image omitted]test"}]
        with (
            mock.patch.object(optimizer, "_read_config", return_value=dict(optimizer.DEFAULT_CONFIG)),
            mock.patch.object(optimizer, "_visual_media", return_value=visual),
            mock.patch.object(optimizer, "_local_optimize_sync", return_value="replace the room"),
            mock.patch.object(optimizer, "close_local_model") as close,
        ):
            result = asyncio.run(optimizer.optimize_prompt(payload))
        self.assertIn("replace the room", result)
        self.assertTrue(close.called)

    def test_vision_messages_use_openai_multimodal_format(self):
        messages = optimizer._messages("替换背景", "背景/场景替换", "background_replace", "中文", "strong")
        visuals = [
            {"kind": "background", "label": f"reference {index}", "url": "[image omitted]test"}
            for index in range(8)
        ]
        result = optimizer._vision_messages(messages, visuals)
        content = result[-1]["content"]
        image_parts = [item for item in content if item.get("type") == "image_url"]
        self.assertEqual(len(image_parts), optimizer.VISUAL_IMAGE_LIMIT)
        self.assertEqual(image_parts[0]["image_url"]["detail"], "low")
        payload = optimizer._api_payload(
            optimizer._normalize_config({"model": "text-model", "vision_model": "vision-model"}),
            result,
            "balanced",
        )
        self.assertEqual(payload["model"], "vision-model")

    def test_qwen_gguf_vision_handlers_are_selected_by_filename(self):
        self.assertEqual(optimizer._vision_handler_name(Path("Qwen3VL-4B-Instruct-Q8_0.gguf")), "qwen3vl")
        self.assertEqual(optimizer._vision_handler_name(Path("Qwen3.5-9B-NSFW-Q8_0.gguf")), "qwen35")
        self.assertEqual(optimizer._vision_handler_name(Path("Qwen2.5-VL-7B.gguf")), "qwen25vl")
        self.assertEqual(optimizer._vision_handler_name(Path("gemma-4-12b-it-Q8_0.gguf")), "gemma4")

    def test_local_vision_uses_selected_mmproj_and_chat_handler(self):
        output_root = ROOT / ".test-output"
        output_root.mkdir(exist_ok=True)
        calls = {}

        class FakeHandler:
            def __init__(self, **kwargs):
                calls["handler"] = kwargs

        class FakeLlama:
            def __init__(self, **kwargs):
                calls["llama"] = kwargs

        with tempfile.TemporaryDirectory(dir=output_root) as temporary:
            folder = Path(temporary)
            model = folder / "Qwen3VL-4B-Instruct-Q8_0.gguf"
            mmproj = folder / "mmproj-Qwen3VL-4B-Instruct-F16.gguf"
            model.write_bytes(b"model")
            mmproj.write_bytes(b"mmproj")
            llama_module = types.ModuleType("llama_cpp")
            llama_module.Llama = FakeLlama
            chat_module = types.ModuleType("llama_cpp.llama_chat_format")
            chat_module.Qwen3VLChatHandler = FakeHandler
            llama_module.llama_chat_format = chat_module
            old_state = (optimizer._LOCAL_MODEL, optimizer._LOCAL_HANDLER, optimizer._LOCAL_MODEL_KEY)
            optimizer._LOCAL_MODEL = optimizer._LOCAL_HANDLER = optimizer._LOCAL_MODEL_KEY = None
            try:
                with (
                    mock.patch.object(optimizer, "_local_model_roots", return_value=[folder.resolve()]),
                    mock.patch.dict(sys.modules, {
                        "llama_cpp": llama_module,
                        "llama_cpp.llama_chat_format": chat_module,
                    }),
                ):
                    config = optimizer._normalize_config({
                        "local_model": str(model),
                        "local_mmproj": str(mmproj),
                        "local_gpu_layers": 0,
                    })
                    optimizer._get_local_model(config, vision=True)
            finally:
                optimizer._LOCAL_MODEL, optimizer._LOCAL_HANDLER, optimizer._LOCAL_MODEL_KEY = old_state
        self.assertEqual(calls["handler"]["clip_model_path"], str(mmproj.resolve()))
        self.assertIsInstance(calls["llama"]["chat_handler"], FakeHandler)


if __name__ == "__main__":
    unittest.main()
