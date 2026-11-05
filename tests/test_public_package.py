"""Open-source packaging and compatibility guardrails."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib
import unittest

from build_single_wire import build_split

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


class PublicPackageTests(unittest.TestCase):
    def test_runtime_dependencies_are_declared_consistently(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        dependencies = "\n".join(project["project"]["dependencies"])
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for package in ("Pillow", "filelock", "numpy"):
            self.assertIn(package, dependencies)
            self.assertIn(package, requirements)

    def test_public_workflow_has_replacement_tags_and_seven_bindings(self):
        workflow, _api = build_split()
        nodes = {node["type"]: node for node in workflow["nodes"] if node["type"] != "Note"}
        segment = nodes["CSRSegmentReplace"]["widgets_values_named"]
        self.assertEqual(segment["replacement_tags"], "自定义")
        bindings = nodes["CSRMediaAssets"]["widgets_values_named"]["character_bindings"]
        self.assertEqual(len(bindings.splitlines()), 7)
        self.assertNotIn("the actor number", bindings)
        self.assertEqual(nodes["CSRModelLoader"]["widgets_values_named"]["attention_mode"], "ComfyUI 默认")
        self.assertTrue(nodes["CSRMerge"]["widgets_values_named"]["seam_exposure_lock"])
        backend = (ROOT / "nodes.py").read_text(encoding="utf-8")
        self.assertIn("export_with_seam_repair", backend)
        self.assertIn("hard_cut", (ROOT / "sequence_seam.py").read_text(encoding="utf-8"))

    def test_frontend_extensions_and_routes_are_namespaced(self):
        extension_names = []
        route_paths = []
        for script in WEB.glob("*.js"):
            text = script.read_text(encoding="utf-8")
            extension_names.extend(re.findall(r'name:\s*"([^"]+)"', text))
            route_paths.extend(re.findall(r'fetchApi\(\s*[`"](/[^`"?]+)', text))
        self.assertTrue(extension_names)
        self.assertTrue(all(name.startswith("AICG3D.CSR.") for name in extension_names))
        for path in route_paths:
            self.assertTrue(path.startswith("/aicg3d_csr/") or path == "/upload/image" or path == "/view", path)

        routes = (ROOT / "routes.py").read_text(encoding="utf-8")
        declared = re.findall(r'routes\.(?:get|post|put|delete)\("([^"]+)"', routes)
        self.assertEqual(declared, [
            "/aicg3d_csr/replacement_skills",
            "/aicg3d_csr/prompt_optimizer/config",
            "/aicg3d_csr/prompt_optimizer/config",
            "/aicg3d_csr/prompt_optimizer/models",
            "/aicg3d_csr/prompt_optimizer/optimize",
            "/aicg3d_csr/video_info",
        ])

    def test_packaged_files_do_not_embed_local_absolute_paths(self):
        suffixes = {".py", ".js", ".json", ".md", ".toml", ".txt"}
        forbidden = re.compile(r"(?:[A-Za-z]:\\Users\\|[A-Za-z]:\\Comfy|/home/|/Users/)")
        offenders = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if any(part in {"__pycache__", ".ruff_cache"} for part in path.parts):
                continue
            if path.name.endswith("_API.json"):
                continue
            if path.resolve() == Path(__file__).resolve():
                continue
            if forbidden.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_prompt_tags_cover_all_supported_combinations(self):
        script = (WEB / "csr_segment_preview.js").read_text(encoding="utf-8")
        for label in ("人物替换", "背景/场景替换", "物品/产品替换", "人物 + 背景", "人物 + 物品", "人物 + 背景 + 物品"):
            self.assertIn(f'"{label}":', script)
        docs = (ROOT / "docs" / "replacement-prompts.md").read_text(encoding="utf-8")
        for label in ("## 人物替换", "## 背景/场景替换", "## 物品/产品替换", "## 人物 + 背景", "## 人物 + 物品", "## 人物 + 背景 + 物品"):
            self.assertIn(label, docs)

    def test_dom_widget_height_syncs_legacy_layout_options(self):
        for filename in ("csr_media_assets.js", "csr_video_crop.js"):
            script = (WEB / filename).read_text(encoding="utf-8")
            self.assertIn("panel.options.getMinHeight = heightGetter", script)
            self.assertIn("panel.options.getMaxHeight = heightGetter", script)

    def test_media_assets_defaults_to_four_visible_cards_and_seven_slots(self):
        script = (WEB / "csr_media_assets.js").read_text(encoding="utf-8")
        self.assertIn("node.setSize?.([nodeWidth, panelHeight + 64]);", script)
        self.assertIn("function measuredContentHeight(root)", script)
        self.assertIn("new ResizeObserver(() => scheduleSlotLayout(node))", script)
        self.assertNotIn("Math.ceil(node._csrRoot?.scrollHeight", script)
        self.assertIn("const DEFAULT_VISIBLE_CHARACTERS = 2;", script)
        self.assertIn("const MAX_CHARACTERS = 7;", script)
        self.assertNotIn("character_8", script)
        self.assertNotIn("character_9", script)
        self.assertNotIn("背景替换已启用：参考/首帧不会锁住旧环境", script)

    def test_public_legal_and_feature_documents_are_present(self):
        required = {
            "LICENSE", "LEGAL.md", "PRIVACY.md", "SECURITY.md", "CONTRIBUTING.md",
            "THIRD_PARTY_NOTICES.md", "docs/features.zh-CN.md",
        }
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)
        legal = (ROOT / "LEGAL.md").read_text(encoding="utf-8")
        for phrase in ("未经同意的私密", "未成年人", "不是法律意见", "无担保"):
            self.assertIn(phrase, legal)
        notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("Permission is hereby granted", notices)

    def test_installation_docs_cover_ffmpeg_ffprobe_and_prompt_optimizer(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        install = (ROOT / "docs" / "install-and-troubleshooting.md").read_text(encoding="utf-8")
        optimizer = (ROOT / "docs" / "prompt-optimizer.md").read_text(encoding="utf-8")
        backend = (ROOT / "media.py").read_text(encoding="utf-8")
        for phrase in ("where.exe ffmpeg", "where.exe ffprobe", "ffmpeg -version", "ffprobe -version"):
            self.assertIn(phrase, readme)
            self.assertIn(phrase, install)
        for phrase in ("完全退出", "imageio-ffmpeg", "同一个 FFmpeg", "提示词优化器", "mmproj"):
            self.assertIn(phrase, install)
        self.assertIn("视觉分析", optimizer)
        self.assertIn("llama-cpp-python", optimizer)
        self.assertIn("install-and-troubleshooting.md", backend)

    def test_prompt_optimizer_is_independent_and_supports_local_models(self):
        frontend = (WEB / "csr_prompt_optimizer.js").read_text(encoding="utf-8")
        backend = (ROOT / "prompt_optimizer.py").read_text(encoding="utf-8")
        segment = (WEB / "csr_segment_preview.js").read_text(encoding="utf-8")
        self.assertIn("/aicg3d_csr/prompt_optimizer/optimize", frontend)
        self.assertIn("OpenAI 兼容 API", backend)
        self.assertIn("llama_cpp", backend)
        self.assertIn("vision_enabled", backend)
        self.assertIn("image_url", backend)
        self.assertIn("mmproj_files", backend)
        self.assertIn("启用视觉分析", frontend)
        self.assertIn("视觉模型", frontend)
        self.assertIn("background_repair", backend)
        self.assertIn("createPromptOptimizer", segment)
        self.assertIn("loadReplacementSkills", segment)
        skills = json.loads((ROOT / "skills" / "replacement_skills.json").read_text(encoding="utf-8"))
        self.assertEqual({item["tag"] for item in skills["skills"]}, {"单人替换", "多人替换", "商品替换", "背景/场景替换"})
        self.assertIn("强制背景/场景替换", segment)

    def test_video_crop_resolution_uses_horizontal_resolution_and_aspect_controls(self):
        script = (WEB / "csr_video_crop.js").read_text(encoding="utf-8")
        self.assertIn("csr-vc-res-main", script)
        self.assertIn("aspect_ratio", script)
        self.assertIn("模型画布 ${preview.modelWidth}×${preview.modelHeight}", script)
        workflow = json.loads((ROOT / "workflows" / "AICG3D-CSR_视频裁剪_资源库_单线.json").read_text(encoding="utf-8"))
        crop = next(item for item in workflow["nodes"] if item["type"] == "CSRVideoCrop")
        self.assertEqual(crop["widgets_values_named"]["resolution_preset"], "540P")
        self.assertEqual(crop["widgets_values_named"]["aspect_ratio"], "16:9")

    def test_second_pass_is_optional_and_collapsible(self):
        workflow = json.loads((ROOT / "workflows" / "AICG3D-CSR_视频裁剪_资源库_单线.json").read_text(encoding="utf-8"))
        node = next(item for item in workflow["nodes"] if item["type"] == "CSRSecondPass")
        self.assertFalse(node["widgets_values_named"]["enable_second_pass"])
        backend = (ROOT / "second_pass.py").read_text(encoding="utf-8")
        self.assertIn("if not enable_second_pass:", backend)
        self.assertNotIn("upscaled_video.shape[2] != placeholder_audio.shape[2]", backend)
        self.assertIn("upscaled_video.shape[1] != 24", backend)
        frontend = (WEB / "csr_second_pass.js").read_text(encoding="utf-8")
        self.assertIn("ui.bodyContainer.hidden = !enabled", frontend)
        self.assertIn("second_pass_model", frontend)
        self.assertIn("sampler_name", frontend)

    def test_saved_workflow_uses_only_one_output_per_processing_node(self):
        workflow = json.loads((ROOT / "workflows" / "AICG3D-CSR_视频裁剪_资源库_单线.json").read_text(encoding="utf-8"))
        processing = [node for node in workflow["nodes"] if node["type"] != "Note"]
        self.assertTrue(all(len(node["outputs"]) == 1 for node in processing))
        self.assertEqual(len(workflow["links"]), len(processing) - 1)


if __name__ == "__main__":
    unittest.main()
