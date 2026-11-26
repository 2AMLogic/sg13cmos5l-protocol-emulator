"""Simulator-free checks against hand-written MSB-first bus symbols."""
import unittest

from reference_models.dali import cells, decode_forward, forward_run


class DaliModelTest(unittest.TestCase):
    def test_backward_81(self):
        self.assertEqual(cells(0x81, 8), [0, 1, 0, 1] + [1, 0] * 6 + [0, 1] + [1] * 4)

    def test_forward_query(self):
        self.assertEqual(decode_forward([0, 1] + [1, 0] * 7 + [0, 1] * 2
                                        + [1, 0, 0, 1] + [1, 0] * 5), 0x01A0)

    def test_timing_and_biphase_errors(self):
        self.assertEqual(forward_run(20_833), 1)
        self.assertEqual(forward_run(41_667), 2)
        for bad in (18_939, 23_149, 30_000, 46_297):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                forward_run(bad)
        with self.assertRaises(ValueError):
            decode_forward([0, 1] + [1, 0] * 15 + [1, 1])


if __name__ == "__main__":
    unittest.main()
