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
               scales=None, shift=None, violations=()):
        """`scales`: per-image timestamp multipliers (default: first image only);
        `shift`: (image, frame, edge, ps) moves one edge; `violations`: image
        indices whose monitor reports a pin-contract violation."""
        scales = scales or (first_image_scale, 1, 1)
        captures = [
            [[round(t * scales[i]) for t in frame] for frame in image]
            for i, image in enumerate(EDGES_PS)
        ]
        if shift:
            i, f, e, ps = shift
            captures[i][f][e] += ps
        pending = iter(enumerate(captures))

        def replay_monitor(monitor):
            index, image = next(pending)
            if index in violations:
                monitor.violations.append("uo_out rose 4950 ps after the clk edge")
            for frame in image:
                for i, t in enumerate(frame):
                    monitor.transitions.append({"pin": "uo_out", "t_ps": t, "value": str(i % 2)})
            return monitor

        dut = SimpleNamespace(clk=object(), uo_out=SimpleNamespace(value=1),
                              _log=logging.getLogger(__name__))
        report = uart._align.ProtocolReport("uart_tx", "test_firmware_uart", None, None)
        with (
            tempfile.TemporaryDirectory() as out,
            patch.multiple(uart, REPORT=report, Clock=Mock(), load_program=tick, ReadOnly=tick,
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
        for image, captured in zip(images, captures):
            self.assertEqual(image["tx_edges_ps"], [t for frame in captured for t in frame])
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

    def test_nominal_capture(self):
        self.assert_decoded_controls(self.replay(1))

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

    def test_pin_contract_violation_keeps_capture_and_measured_frames(self):
        # 0x5a stop-bit rise moved +24 ns: both bytes still decode, frame 1
        # measures 2.4010%, and the monitor flags the late edge.
        first, *remaining = self.replay(
            1, "violated the pin contract", shift=(0, 0, 7, 24000), violations=(0,))
        self.assertEqual(self.saved["contract_violation_count"], 1)
        self.assertEqual(first["pin_contract_violations"]["count"], 1)
        self.assertAlmostEqual(first["frames"][0]["drift_pct"], 2.4010)
        self.assertFalse(first["frames"][0]["within_bound"])
        self.assertEqual(first["failures"], [])
        self.assert_decoded_controls(remaining)

    def test_failed_decode_keeps_completed_and_later_images(self):
        # 1.025x / 1.06x / 1.0 timestamp multipliers: image 0 measures, image 1
        # cannot decode, image 2 must still be collected and measured.
        first, second, third = self.replay(
            1, "row-10 drift bound failed", scales=(1.025, 1.06, 1), control_scale=1.025)
        self.assertAlmostEqual(first["frames"][0]["drift_pct"], 22.5010)
        self.assertAlmostEqual(first["frames"][1]["drift_pct"], 20.0010)
        self.assertEqual(second["frames"], [])
        self.assertTrue(second["failures"])
        self.assertIn("framing error at t=", second["failures"][0])
        self.assertTrue(second["tx_edges_ps"])
        self.assertEqual(third["failures"], [])
        self.assertEqual([f["decoded_hex"] for f in third["frames"]], ["0x5a", "0xa5"])


if __name__ == "__main__":
    unittest.main()
