#!/usr/bin/env python3
"""Stdlib tests for loadseq.py / loadseq_playback.py (issue #118).

    python3 firmware/tools/test_loadseq.py
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[1]
sys.path.insert(0, str(TOOLS))
import loadseq  # noqa: E402
import loadseq_playback as pb  # noqa: E402


class Parse(unittest.TestCase):
    def test_valid_and_blank_lines(self):
        self.assertEqual(loadseq.parse_words("12ab\n\n  FFFF  \r\n0000\n\n"),
                         [0x12AB, 0xFFFF, 0])

    def test_rejects(self):
        for bad in ("", "\n \n", "123\n", "12345\n", "0x12\n", "zzzz\n",
                    "1234 5678\n", "1234 ; c\n", "-001\n", "+123\n"):
            with self.assertRaises(loadseq.LoadSeqError, msg=repr(bad)):
                loadseq.parse_words(bad)

    def test_257_words_rejected_256_accepted(self):
        self.assertEqual(len(loadseq.parse_words("0001\n" * 256)), 256)
        with self.assertRaises(loadseq.LoadSeqError):
            loadseq.parse_words("0001\n" * 257)


class Generate(unittest.TestCase):
    def test_exact_shape_one_word(self):
        s = loadseq.generate_steps([0x8001])
        self.assertEqual(len(s), 12 + 16)
        self.assertEqual(s[:10], [(0x80, 0, 0, 1)] * 10)
        self.assertEqual(s[10], (0x80, 0, 1, 1))           # latch, no bit
        bits = [t[0] for t in s[11:27]]
        self.assertEqual(bits, [0x81] + [0x80] * 14 + [0x81])  # MSB first
        self.assertEqual(s[27], (0x00, 0, 1, 1))           # separate drop

    def test_msb_first_asymmetric(self):
        s = loadseq.generate_steps([0x0001, 0x8000, 0x1234])
        data = [t[0] & 1 for t in s[11:-1]]
        self.assertEqual(data[:16], [0] * 15 + [1])
        self.assertEqual(data[16:32], [1] + [0] * 15)
        self.assertEqual(int("".join(map(str, data[32:])), 2), 0x1234)

    def test_no_padding_and_deterministic(self):
        for n in (1, 2, 256):
            w = [(i * 0x9E37 + 1) & 0xFFFF for i in range(n)]
            self.assertEqual(len(loadseq.generate_steps(w)), 12 + 16 * n)
            self.assertEqual(loadseq.generate_steps(w), loadseq.generate_steps(w))
            self.assertEqual(loadseq.simulate_load(loadseq.generate_steps(w)), w)

    def test_generate_rejects(self):
        for bad in ([], [0] * 257, [0x10000], [-1]):
            with self.assertRaises(loadseq.LoadSeqError):
                loadseq.generate_steps(bad)

    def test_model_rejects_mutants(self):
        good = loadseq.generate_steps([0xA5C3])
        for mutant in (good[:10] + good[11:],            # no latch edge
                       good[:-1],                        # no MODE drop
                       good + [(0, 0, 1, 1)],            # extra edge after drop
                       [(0x80, 0, 0, 1)] * 9 + good[10:],  # nine reset clocks
                       good[:11] + [(0x80, 0, 1, 1)] + good[11:]):  # extra bit
            with self.assertRaises(loadseq.LoadSeqError):
                loadseq.simulate_load(mutant)


class Playback(unittest.TestCase):
    def test_call_order(self):
        m = pb.MockAdapter()
        steps = loadseq.generate_steps([0x0001])
        pb.play(m, steps, setup_us=3, high_us=5, low_us=7)
        self.assertEqual(m.calls[0], ("set_clk", 0))
        self.assertEqual(len(m.calls), 1 + 9 * len(steps))
        names = [c[0] for c in m.calls[1:10]]
        self.assertEqual(names, ["set_ena", "set_uio_in", "set_ui_in", "set_rst_n",
                                 "wait_us", "set_clk", "wait_us", "set_clk", "wait_us"])
        self.assertEqual([c[1] for c in m.calls[5:10]], [3, 1, 5, 0, 7])
        # inputs only change while clk is low; last call leaves clk low
        clk = 0
        for name, arg in m.calls:
            if name == "set_clk":
                clk = arg
            elif name.startswith("set_"):
                self.assertEqual(clk, 0)
        self.assertEqual(clk, 0)
        self.assertEqual(sum(1 for c in m.calls if c == ("set_clk", 1)), len(steps))

    def test_reload_replays_same_initial_sequence(self):
        steps = loadseq.generate_steps([0x1234])
        a, b = pb.MockAdapter(), pb.MockAdapter()
        pb.play(a, steps)
        pb.play(b, steps)
        self.assertEqual(a.calls, b.calls)
        self.assertEqual(a.calls[1:5], [("set_ena", 1), ("set_uio_in", 0),
                                        ("set_ui_in", 0x80), ("set_rst_n", 0)])

    def test_invalid_makes_zero_calls(self):
        steps = loadseq.generate_steps([1])
        for kw in ({"setup_us": 0}, {"high_us": -1}, {"low_us": 0}):
            m = pb.MockAdapter()
            with self.assertRaises(ValueError):
                pb.play(m, steps, **kw)
            self.assertEqual(m.calls, [])
        for bad in ([], [(0x80, 0, 2, 1)], [(256, 0, 0, 1)], [(0x80, 0, 0)]):
            m = pb.MockAdapter()
            with self.assertRaises(ValueError):
                pb.play(m, bad)
            self.assertEqual(m.calls, [])

    def test_encode_decode(self):
        steps = loadseq.generate_steps([0xBEEF])
        self.assertEqual(pb.decode_steps(pb.encode_steps(steps)), steps)


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(TOOLS / "loadseq.py"), *args],
                              capture_output=True, text=True)

    def test_json_and_python_formats(self):
        with tempfile.TemporaryDirectory() as d:
            hexf = Path(d) / "a.hex"
            hexf.write_text("a5c3\n0001\n")
            r = self.run_cli(str(hexf))
            self.assertEqual(r.returncode, 0, r.stderr)
            j = json.loads(r.stdout)
            self.assertEqual(j["version"], 1)
            self.assertEqual(len(j["steps"]), 12 + 32)
            self.assertEqual([tuple(s) for s in j["steps"]],
                             loadseq.generate_steps([0xA5C3, 1]))
            r2 = self.run_cli(str(hexf), "--format", "python")
            ns = {}
            exec(r2.stdout, ns)
            self.assertEqual(pb.decode_steps(ns["STEPS"]), loadseq.generate_steps([0xA5C3, 1]))

    def test_rejected_inputs_exit_nonzero_no_output(self):
        with tempfile.TemporaryDirectory() as d:
            for name, text in (("empty", ""), ("bad", "12g4\n"),
                               ("big", "0001\n" * 257)):
                f = Path(d) / (name + ".hex")
                f.write_text(text)
                out = Path(d) / (name + ".out")
                r = self.run_cli(str(f), "-o", str(out))
                self.assertEqual(r.returncode, 2)
                self.assertIn("loadseq: error", r.stderr)
                self.assertFalse(out.exists())
                self.assertEqual(r.stdout, "")

    def test_check_passes_on_committed_images(self):
        hexes = sorted((ROOT / "firmware" / "build").glob("*.hex"))
        self.assertTrue(hexes)
        r = self.run_cli("--check", *map(str, hexes))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_check_fails_on_generator_regression_and_writes_nothing(self):
        hexes = sorted((ROOT / "firmware" / "build").glob("*.hex"))
        before = {h: h.read_bytes() for h in hexes}
        orig = loadseq.generate_steps

        def broken(words):  # off-by-one: drop the MODE-latching edge
            s = orig(words)
            return s[:10] + s[11:]
        loadseq.generate_steps = broken
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = loadseq.main(["--check", str(hexes[0])])
        finally:
            loadseq.generate_steps = orig
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", buf.getvalue())
        self.assertEqual(before, {h: h.read_bytes() for h in hexes})


if __name__ == "__main__":
    unittest.main()
