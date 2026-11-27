"""Replay the November 21 typical-corner UART TX pin edges through the routed bench."""

import asyncio
import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cocotb

import sdf_protocol_uart_tx as uart


# Picoseconds from record 20261121-075641-f83859c, in image and payload order.
EDGES_PS = (
    ((63064943, 65064953, 66064943, 67064953, 69064943, 70064953, 71064943, 72064953),
     (77264943, 78264953, 79264943, 80264953, 81264943, 83264953, 84264943, 85264953)),
    ((161204943, 178564953, 187244943, 195924953, 213284943, 221964953, 230644943, 239324953),
     (256764943, 265444953, 274124943, 282804953, 291484943, 308844953, 317524943, 326204953)),
    ((660724943, 869044953, 973204943, 1077364953, 1285684943, 1389844953, 1494004943, 1598164953),
     (1806524943, 1910684953, 2014844943, 2119004953, 2223164943, 2431484953, 2535644943, 2639804953)),
)


async def tick(*args, **kwargs):
    pass


class UartReplayTests(unittest.TestCase):
    def replay(self, first_image_scale, expected_failure=None, control_scale=1.025,
               scales=None, shifts=(), violations=(), idle=None, unknown=None,
               initial_levels=(1, 1, 1), second_byte_edges=None, leading_rise=False,
               next_start_ps=None, unknown_gap=None, edges=EDGES_PS):
        """`scales`: per-image timestamp multipliers (default: first image only);
        `shifts`: (image, frame, edge, ps) offsets; `violations`: image
        indices whose monitor reports a pin-contract violation."""
        scales = scales or (first_image_scale, 1, 1)
        captures = [
            [[round(t * scales[i]) for t in frame] for frame in image]
            for i, image in enumerate(edges)
        ]
        for i, f, e, ps in shifts:
            captures[i][f][e] += ps
        if next_start_ps is not None:
            second = captures[0][1]
            captures[0][1] = [next_start_ps + (t - second[0]) for t in second]
        if idle is not None:
            captures[idle] = []
        if second_byte_edges is not None:
            captures[0][1] = captures[0][1][:second_byte_edges]

        pending = iter(enumerate(captures))
        starts = iter(initial_levels)
        self.checkpoints = []

        async def load_image(dut, words):
            if path.exists():
                doc = json.loads(path.read_text())
                measurement = doc.get("measurements", {}).get("uart_tx_drift", {})
                self.checkpoints.append([i["image"] for i in measurement.get("images", [])])
            dut.uo_out.value = next(starts)

        def replay_monitor(monitor):
            index, image = next(pending)
            if index in violations:
                monitor.violations.append("uo_out rose 4950 ps after the clk edge")
            if leading_rise and index == 0:
                monitor.transitions.append({"pin": "uo_out", "t_ps": 57864953, "value": "1"})
            for f, frame in enumerate(image):
                if index == 0 and f == 1 and unknown_gap:
                    for t, level in zip(unknown_gap, ("X", "1")):
                        monitor.transitions.append({"pin": "uo_out", "t_ps": t, "value": level})
                for i, t in enumerate(frame):
                    level = "X" if unknown == (index, f, i) else str(i % 2)
                    monitor.transitions.append({"pin": "uo_out", "t_ps": t, "value": level})
            return monitor

        dut = SimpleNamespace(clk=object(), uo_out=SimpleNamespace(value=1),
                              _log=logging.getLogger(__name__))
        report = uart._align.ProtocolReport("uart_tx", "test_firmware_uart", None, None)
        with (
            tempfile.TemporaryDirectory() as out,
            patch.multiple(uart, REPORT=report, Clock=Mock(), load_program=load_image, ReadOnly=tick,
                           Timer=tick, RisingEdge=tick, NEGATIVE_CONTROL_SCALE=control_scale),
            patch.object(cocotb, "start_soon"),
            patch.object(uart._align.PinDelayMonitor, "start", replay_monitor),
        ):
            path = Path(out) / "report.json"
            report.path = str(path)
            run = uart.test_uart_tx_bit_period_and_drift_in_time_units.func(dut)
            if expected_failure:
                with self.assertRaisesRegex(AssertionError, expected_failure):
                    asyncio.run(run)
            else:
                asyncio.run(run)
            saved = json.loads(path.read_text())
        self.saved = saved
        self.assertEqual(saved["captures"], 3)
        images = saved["measurements"]["uart_tx_drift"]["images"]
        self.assertEqual([i["image"] for i in images], ["uart_tx", "uart_tx_115200", "uart_tx_9600"])
        for index, (image, captured) in enumerate(zip(images, captures)):
            preamble = [57864953] if leading_rise and index == 0 else []
            raw_edges = [t for frame in captured for t in frame]
            if index == 0 and unknown_gap:
                raw_edges[len(captured[0]):len(captured[0])] = unknown_gap
            self.assertEqual(image["tx_edges_ps"], preamble + raw_edges)
            if image["failures"]:
                continue
            self.assertEqual([f["edges_ps"] for f in image["frames"]], captured)
            self.assertEqual([f["decoded_hex"] for f in image["frames"]], ["0x5a", "0xa5"])
            self.assertTrue(all(f["stop_ok"] for f in image["frames"]))
        return images

    def assert_decoded_controls(self, images):
        for image in images:
            control = image["negative_control"]
            self.assertEqual(control["decoded"], ["0x5a", "0xa5"])
            self.assertTrue(control["all_failed_check_frame"])
            self.assertTrue(all(drift > 2 for drift in control["drift_pct"]))

    def test_each_image_is_written_before_loading_the_next(self):
        self.replay(1)
        self.assertEqual(self.checkpoints, [["uart_tx"], ["uart_tx", "uart_tx_115200"]])

    def test_idle_or_unknown_pin_retains_polarity_and_other_images(self):
        cases = (
            ({"idle": 1}, 1, "no TX", []),
            ({"unknown": (1, 0, 1)}, 1, "X", [0, "X", 0, 1, 0, 1, 0, 1] + [0, 1] * 4),
            ({"initial_levels": (1, "X", 1)}, "X", "X", [0, 1] * 8),
        )
        for fault, initial, diagnostic, levels in cases:
            with self.subTest(fault=fault):
                first, second, third = self.replay(1.025, "row-10 drift bound failed", **fault)
                self.assertAlmostEqual(first["frames"][0]["drift_pct"], 22.5010)
                self.assertAlmostEqual(first["frames"][1]["drift_pct"], 20.0010)
                self.assertEqual(second["tx_initial"], initial)
                self.assertEqual(second["tx_edge_levels"], levels)
                self.assertIn(diagnostic, " ".join(second["failures"]))
                self.assertEqual(third["failures"], [])
                self.assert_decoded_controls([third])

    def test_missing_or_malformed_second_byte_preserves_first(self):
        for retained, diagnostic in ((0, "decoder recovered"), (1, "framing error")):
            with self.subTest(second_byte_edges=retained):
                first, *later = self.replay(1.025, diagnostic, second_byte_edges=retained)
                self.assertIn(diagnostic, " ".join(first["failures"]))
                frame, = first["frames"]
                self.assertEqual(frame["decoded_hex"], "0x5a")
                self.assertTrue(frame["stop_ok"])
                self.assertAlmostEqual(frame["drift_pct"], 22.5010)
                self.assertAlmostEqual(frame["mean_bit_period_ps"], 9_225_010 / 9)
                self.assertFalse(frame["within_bound"])
                self.assert_decoded_controls(later)

    def test_nominal_capture(self):
        images = self.replay(1, initial_levels=(0, 1, 1), leading_rise=True)
        self.assert_decoded_controls(images)
        self.assertEqual(images[0]["tx_initial"], 0)
        self.assertEqual(images[0]["tx_edge_levels"], [1] + [0, 1] * 8)
        self.assertEqual(images[0]["frames"][0]["t_start_ps"], 63064943)

    def test_over_limit_capture_survives_control_framing_error(self):
        first, *remaining = self.replay(1.04, "row-10 drift bound failed")
        for frame, expected in zip(first["frames"], (36.0010, 32.0010)):
            self.assertAlmostEqual(frame["drift_pct"], expected)
            self.assertFalse(frame["within_bound"])
        self.assertIn("framing error at t=67227.230ns", first["negative_control"]["framing_error"])
        self.assertFalse(first["negative_control"]["all_failed_check_frame"])
        self.assert_decoded_controls(remaining)

    def test_control_framing_error_alone_fails_after_write(self):
        self.replay(1, "stop bit sampled 0", control_scale=1.08)

    def test_back_to_back_frames_own_their_start_edge(self):
        for next_start, stop_delay in ((73064943, 0), (73064943, 24000), (73054943, 24000)):
            with self.subTest(next_start=next_start, stop_delay=stop_delay):
                first, *_ = self.replay(
                    1, "row-10 drift bound failed" if stop_delay else None,
                    next_start_ps=next_start, shifts=[(0, 0, 7, stop_delay)])
                a, b = first["frames"]
                self.assertEqual(a["last_edge_ps"], 72064953 + stop_delay)
                self.assertEqual(b["t_start_ps"], next_start)
                self.assertEqual(a["drift_ps"], 10 + stop_delay)
                self.assertAlmostEqual(a["drift_pct"], (10 + stop_delay) / 10000)
                self.assertAlmostEqual(a["model_drift_pct"], a["drift_pct"])
                self.assertEqual(a["within_bound"], stop_delay == 0)
                self.assertTrue(b["within_bound"])

    def test_last_edge_limit_is_inclusive_on_the_pin_timestamp_grid(self):
        # Fast-corner 1 Mbaud pin edges from record 20261127-012339-0a929db.
        fast = ((63064653, 65064653, 66064653, 67064653, 69064653, 70064653, 71064653, 72064653),
                (77264653, 78264653, 79264653, 80264653, 81264653, 83264653, 84264653, 85264653))
        for sign in (-1, 1):
            for magnitude in (19990, 20000, 20010):
                residual = sign * magnitude
                passes = magnitude <= 20000
                with self.subTest(residual_ps=residual):
                    first, *_ = self.replay(
                        1, None if passes else "row-10 drift bound failed",
                        edges=(fast, *EDGES_PS[1:]), shifts=[(0, 0, -1, residual)])
                    frame = first["frames"][0]
                    self.assertEqual(frame["last_edge_ps"], fast[0][-1] + residual)
                    self.assertEqual(frame["drift_ps"], residual)
                    self.assertEqual(frame["drift_pct"], magnitude / 10000)
                    self.assertAlmostEqual(frame["model_drift_pct"], frame["drift_pct"])
                    self.assertEqual(frame["within_bound"], passes)

    def test_decode_is_independent_of_capture_origin(self):
        # A capture 20 ms into the simulation decodes identically: the pre-edge
        # level comes from the ordered transitions, not an epsilon lookup.
        shift = 20_000_000_000
        shifted = tuple(
            tuple(tuple(t + shift for t in frame) for frame in image) for image in EDGES_PS
        )
        base = self.replay(1)
        late = self.replay(1, edges=shifted)
        for a, b in zip(base, late):
            self.assertEqual([f["decoded_hex"] for f in a["frames"]],
                             [f["decoded_hex"] for f in b["frames"]])
            self.assertEqual([f["drift_ps"] for f in a["frames"]],
                             [f["drift_ps"] for f in b["frames"]])
            for x, y in zip(a["negative_control"]["drift_pct"], b["negative_control"]["drift_pct"]):
                self.assertAlmostEqual(x, y, places=6)

    def test_half_bit_stop_excursion_is_retained_not_rounded_away(self):
        # First stop rise 9.5 bit periods after the start (1 Mbaud, typical).
        for late_ps in (499980, 499990):
            with self.subTest(late_ps=late_ps):
                first, *_ = self.replay(1, "row-10 drift bound failed",
                                        shifts=[(0, 0, -1, late_ps)])
                frame = first["frames"][0]
                self.assertEqual(frame["decoded_hex"], "0x5a")
                self.assertEqual(frame["last_edge_bit_index"], 9)
                self.assertEqual(frame["drift_ps"], late_ps + 10)  # plus the 10 ps nominal residual
                self.assertGreater(frame["drift_pct"], 49.99)
                self.assertFalse(frame["within_bound"])

    def test_early_next_start_is_graded_independently_of_last_edge(self):
        for early in (19990, 20000, 20010):
            passes = early <= 20000
            with self.subTest(early_ps=early):
                first, *_ = self.replay(
                    1, None if passes else "row-10 drift bound failed",
                    next_start_ps=EDGES_PS[0][0][0] + 10000000 - early)
                frame = first["frames"][0]
                self.assertEqual(frame["drift_ps"], 10)
                self.assertEqual(frame["pitch_error_ps"], early)
                self.assertEqual(frame["within_bound"], passes)

    def test_bad_first_stop_preserves_second_frame_and_its_drift(self):
        first, *others = self.replay(
            1, "stop bit sampled 0", shifts=[(0, 0, -1, 600000), (0, 1, -1, 24000)])
        self.assertIn("stop bit sampled 0", first["failures"][0])
        self.assertEqual(len(first["tx_edges_ps"]), 16)
        frame, = first["frames"]
        self.assertEqual(frame["decoded_hex"], "0xa5")
        self.assertTrue(frame["stop_ok"])
        self.assertEqual(frame["edges_ps"], [*EDGES_PS[0][1][:-1], 85288953])
        self.assertEqual(frame["last_edge_bit_index"], 8)
        self.assertEqual(frame["drift_ps"], 24010)
        self.assertAlmostEqual(frame["drift_pct"], 2.4010)
        self.assertFalse(frame["within_bound"])
        control = first["negative_control"]
        self.assertIn("stop bit sampled 0", control["framing_error"])
        self.assertEqual(control["decoded"], ["0xa5"])
        self.assert_decoded_controls(others)

    def test_unknown_at_frame_end_keeps_completed_frame(self):
        for offset in (-1, 0, 1):
            with self.subTest(offset=offset):
                unknown_at = 73064943 + offset
                first, *_ = self.replay(
                    1, "TX level is X", shifts=[(0, 0, 7, 24000)],
                    unknown_gap=(unknown_at, unknown_at + 20000))
                frames = first["frames"]
                self.assertEqual(frames[-1]["decoded_hex"], "0xa5")
                if offset < 0:
                    self.assertEqual(len(frames), 1)
                    continue
                self.assertEqual(len(frames), 2)
                a = frames[0]
                self.assertEqual(a["decoded_hex"], "0x5a")
                self.assertTrue(a["stop_ok"])
                self.assertEqual(a["edges_ps"], [*EDGES_PS[0][0][:-1], 72088953])
                self.assertEqual(a["drift_ps"], 24010)
                self.assertAlmostEqual(a["model_drift_pct"], 2.4010)
                self.assertAlmostEqual(a["drift_pct"], 2.4010)
                self.assertFalse(a["within_bound"])

    def test_pin_contract_violation_keeps_capture_and_measured_frames(self):
        # 0x5a stop-bit rise moved +24 ns: both bytes still decode, frame 1
        # measures 2.4010%, and the monitor flags the late edge.
        first, *remaining = self.replay(
            1, "violated the pin contract", shifts=[(0, 0, 7, 24000)], violations=(0,))
        self.assertEqual(self.saved["contract_violation_count"], 1)
        self.assertEqual(first["pin_contract_violations"]["count"], 1)
        self.assertAlmostEqual(first["frames"][0]["drift_pct"], 2.4010)
        self.assertFalse(first["frames"][0]["within_bound"])
        self.assertEqual(first["failures"], [])
        self.assert_decoded_controls(remaining)

    def test_failed_decode_keeps_completed_and_later_images(self):
        # 1.025x / 1.06x / 1.0 timestamp multipliers: image 0 measures, image 1 loses
        # its first stop, but its second byte and image 2 are still measurable.
        first, second, third = self.replay(
            1, "row-10 drift bound failed", scales=(1.025, 1.06, 1), control_scale=1.025)
        self.assertAlmostEqual(first["frames"][0]["drift_pct"], 22.5010)
        self.assertAlmostEqual(first["frames"][1]["drift_pct"], 20.0010)
        recovered, = second["frames"]
        self.assertEqual(recovered["decoded_hex"], "0xa5")
        self.assertEqual(recovered["drift_ps"], 4166410)
        self.assertFalse(recovered["within_bound"])
        self.assertTrue(second["failures"])
        self.assertIn("framing error at t=", second["failures"][0])
        self.assertTrue(second["tx_edges_ps"])
        self.assertEqual(third["failures"], [])
        self.assertEqual([f["decoded_hex"] for f in third["frames"]], ["0x5a", "0xa5"])


if __name__ == "__main__":
    unittest.main()
