"""Focused checks for cross-segment exposure and hard-cut protection."""
from __future__ import annotations

from pathlib import Path
import importlib
import sys
import types
import unittest

import torch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "_csr_test_package"
if PACKAGE not in sys.modules:
    module = types.ModuleType(PACKAGE)
    module.__path__ = [str(ROOT)]
    sys.modules[PACKAGE] = module

SequenceSeamMatcher = importlib.import_module(
    f"{PACKAGE}.sequence_seam"
).SequenceSeamMatcher


class SequenceSeamMatcherTests(unittest.TestCase):
    def test_same_shot_opening_flash_is_flattened(self):
        tail = torch.full((6, 64, 64, 3), 0.40)
        opening = torch.full((8, 64, 64, 3), 0.40)
        opening[1].fill_(0.46)
        opening[2:].fill_(0.42)
        matcher = SequenceSeamMatcher(True)
        matcher.apply(tail, 0)
        repaired = matcher.apply(opening, 1)

        record = matcher.records[0]
        self.assertFalse(record["hard_cut"])
        self.assertLess(record["seam_gap_after"], 0.005)
        self.assertLess(record["opening_spike_after"], record["opening_spike_before"] * 0.35)
        self.assertLess(float((repaired[1] - repaired[2]).abs().mean()), 0.02)

    def test_hard_cut_is_not_blended(self):
        left = torch.zeros((4, 128, 128, 3))
        left[:, :, :64] = 0.90
        left[:, :, 64:] = 0.10
        right = torch.zeros((4, 128, 128, 3))
        right[:, :, :64] = 0.10
        right[:, :, 64:] = 0.90
        matcher = SequenceSeamMatcher(True)
        matcher.apply(left, 0)
        repaired = matcher.apply(right, 1)

        self.assertTrue(matcher.records[0]["hard_cut"])
        self.assertTrue(torch.equal(repaired, right))
        self.assertEqual(matcher.records[0]["global_offset"], 0.0)
        self.assertEqual(matcher.records[0]["bridge_weight"], 0.0)


if __name__ == "__main__":
    unittest.main()
