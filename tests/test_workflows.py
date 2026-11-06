"""Structural checks for the split single-wire workflow."""
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows" / "AICG3D-CSR_视频裁剪_资源库_单线.json"
API_WORKFLOW = ROOT / "workflows" / "AICG3D-CSR_视频裁剪_资源库_单线_API.json"


class SplitWorkflowTests(unittest.TestCase):
    def test_split_workflow_keeps_one_output_per_node(self):
        workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        nodes = [node for node in workflow["nodes"] if node["type"] != "Note"]
        self.assertEqual(
            [node["type"] for node in nodes],
            [
                "CSRModelLoader",
                "CSRVideoCrop",
                "CSRMediaAssets",
                "CSRSegmentReplace",
                "CSRSecondPass",
                "CSRMerge",
                "SaveVideo",
            ],
        )
        self.assertEqual(len(workflow["links"]), 6)
        self.assertTrue(all(sum(len(output.get("links") or []) for output in node["outputs"]) <= 1 for node in nodes))
        loader = nodes[0]
        self.assertEqual([output["name"] for output in loader["outputs"]], ["model_bundle", "model"])
        crop = nodes[1]
        self.assertIn("model_patch", [item["name"] for item in crop["inputs"]])

    def test_split_api_uses_flat_save_video_inputs(self):
        workflow = json.loads(API_WORKFLOW.read_text(encoding="utf-8"))
        self.assertEqual(workflow["5"]["class_type"], "CSRSecondPass")
        self.assertFalse(workflow["5"]["inputs"]["enable_second_pass"])
        inputs = workflow["7"]["inputs"]
        self.assertEqual(inputs["format"], "mp4")
        self.assertEqual(inputs["format.codec"], "auto")
        self.assertEqual(inputs["video"], ["6", 0])


if __name__ == "__main__":
    unittest.main()
