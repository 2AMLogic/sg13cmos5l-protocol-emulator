"""Unit tests for `sdf_tx_edges.tx_level_changes` (issue #531)."""

import unittest

from sdf_tx_edges import tx_level_changes


def ev(t, value, pin="uo_out"):
    return {"pin": pin, "t_ps": t, "value": value}


class TxLevelChangesTests(unittest.TestCase):
    def test_keeps_only_bit0_changes(self):
        events = [ev(100, "00000000"), ev(200, "00000001"), ev(300, "00000000")]
        self.assertEqual(tx_level_changes(events, 1), [(100, 0), (200, 1), (300, 0)])

    def test_other_uo_out_bit_moving_while_tx_holds_is_not_an_edge(self):
        # TX high, then bit 3 changes 100 ps after the last rise: not a TX edge.
        events = [ev(100, "00000000"), ev(1000, "00000001"), ev(1100, "00001001")]
        self.assertEqual(tx_level_changes(events, 1), [(100, 0), (1000, 1)])

    def test_event_matching_initial_level_is_dropped(self):
        self.assertEqual(tx_level_changes([ev(50, "00000011")], 1), [])

    def test_other_pins_ignored(self):
        self.assertEqual(tx_level_changes([ev(5, "1", pin="uio_out")], 0), [])


if __name__ == "__main__":
    unittest.main()
