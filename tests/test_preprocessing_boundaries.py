"""기존 28개 테스트에 없는 전처리 경계만 확인한다."""
import copy
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from contract import ContractError, FramePacket, load_frame, normalize_depth, validate_frame


class PreprocessingBoundaryTests(unittest.TestCase):
    def test_infinity_overflow_and_invalid_sentinel_are_canonical(self):
        raw = np.array([[1000, np.inf, -np.inf], [np.nan, -1, 65535]], dtype=np.float64)
        depth, mask = normalize_depth(raw, .001, invalid_values=(0, 65535))
        np.testing.assert_array_equal(depth, [[1, 0, 0], [0, 0, 0]])
        np.testing.assert_array_equal(mask, [[True, False, False], [False, False, False]])
        self.assertEqual(depth.dtype, np.float32)
        self.assertEqual(mask.dtype, np.bool_)
        depth, mask = normalize_depth([[1e300, 1]], 1)
        np.testing.assert_array_equal(depth, [[0, 1]])
        np.testing.assert_array_equal(mask, [[False, True]])

    def test_invalid_scale_values_use_unit_unknown(self):
        for value in [0, -1, float('nan'), float('inf'), float('-inf'), True, '0.001']:
            with self.subTest(scale=repr(value)), self.assertRaises(ContractError) as caught:
                normalize_depth([[1000]], value)
            self.assertEqual(caught.exception.code, 'UNIT_UNKNOWN')

    def test_raw_empty_nonnumeric_and_dimensions_are_rejected(self):
        for raw in [[], [1, 2], [[[1]]], [['1']], [[True]]]:
            with self.subTest(raw=raw), self.assertRaises(ContractError) as caught:
                normalize_depth(raw, .001)
            self.assertEqual(caught.exception.code, 'DEPTH_SHAPE_INVALID')

    def test_all_invalid_normalization_succeeds_but_frame_fails(self):
        frame = load_frame(ROOT / 'examples/synthetic/frame_000001/metadata.json')
        depth, mask = normalize_depth([[np.inf, np.nan], [-1, 0]], .001)
        np.testing.assert_array_equal(depth, np.zeros((2, 2), dtype=np.float32))
        self.assertFalse(mask.any())
        with self.assertRaises(ContractError) as caught:
            validate_frame(FramePacket(copy.deepcopy(frame.metadata), depth, mask))
        self.assertEqual(caught.exception.code, 'NO_VALID_DEPTH')


if __name__ == '__main__':
    unittest.main()
