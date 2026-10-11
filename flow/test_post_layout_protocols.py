#!/usr/bin/env python3
"""Self-test for the post-layout protocol suite (issue #217), without a
routed run.

Two layers, both runnable on any host with Python 3 and bash:

1. `flow/post_layout_protocols.py` directly: protocol selection, the serial
   (corner, protocol) matrix, per-run grading (every way a run must fail:
   klt exit, annotation false or absent, a missing response, a missing or
   skipped test, a missing wrapper report, too few captures, an output
   transition at or after the observe point, zero pin delay, a timing
   control that did not run or did not fail), per-corner aggregation (one
   failing protocol among passing corners fails the suite; a missing cell
   fails it), and the SRAM / pad limitation metadata. Plus inventory
   checks against the committed benches, wrappers and
   `flow/run-firmware-gate-level.sh`.

2. The *real* `flow/run-post-layout-sdf.sh`, copied into a temporary repo
   root with a fake `klt` (`KLT_BIN`) and a synthetic `--from` artifact set
   (netlist with one SRAM macro, two SDF corners, an SDC). The fake klt
   logs every invocation and answers each (corner, testbench module) as a
   per-test plan says. Checked: the default core suite still runs
   `sdf_alignment` once per corner with the frozen request shape and never
   writes the protocol results; option validation; serial, corner-major
   dispatch; nonzero exit on each failure class while the rest of the
   matrix still runs.

Zero dependencies beyond the Python 3 standard library.

Usage:
    python3 flow/test_post_layout_protocols.py
Exit codes: 0 all cases pass, 1 otherwise.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

FLOW = Path(__file__).resolve().parent
REPO = FLOW.parent
sys.path.insert(0, str(FLOW))

import post_layout_protocols as plp  # noqa: E402

CORNERS = ("corner_a", "corner_b")
FROZEN_REQUEST = (
    REPO / "verification/records/post-layout-sdf-regression/artifacts/"
    "20261010-205119-af36071/request-nom_typ_1p20V_25C.json"
)


# ---------------------------------------------------------------------------
# Synthetic klt outputs
# ---------------------------------------------------------------------------


def good_envelope(protocol, annotated=True, status="pass"):
    spec = plp.PROTOCOLS[protocol]
    env = {"results_xml": None}
    if annotated is not None:
        env["sdf"] = {"annotated": annotated, "corner": "typ"}
    tests = [{"name": n, "status": "passed"} for n in spec["expected_tests"]]
    return {
        "schema_version": 1,
        "testbench": spec["testbench_module"],
        "status": status,
        "test_count": len(tests),
        "passed_count": len(tests),
        "failed_count": 0,
        "skipped_count": 0,
        "tests": tests,
        "environment": env,
    }


def good_report(protocol, max_delay=890, violations=0):
    spec = plp.PROTOCOLS[protocol]
    return {
        "schema": "pe.sdf_protocol_report/1",
        "protocol": protocol,
        "bench_module": spec["bench_module"],
        "alignment_ps": {"clock_period": 20000, "drive_offset": 4000,
                         "sample_offset": 16000, "observe_offset": 3000},
        "captures": spec["min_captures"],
        "captured_cycles": 1000,
        "pin_events": {
            "uo_out": {"count": 10, "zero_delay": 0 if max_delay else 10,
                       "min_delay_ps": max_delay, "max_delay_ps": max_delay},
            "uio_out": {"count": 0, "zero_delay": 0, "min_delay_ps": None, "max_delay_ps": None},
            "uio_oe": {"count": 0, "zero_delay": 0, "min_delay_ps": None, "max_delay_ps": None},
        },
        "contract_violation_count": violations,
        "contract_violations": ["uo_out changed 3500 ps after the clk edge"] * violations,
        "timing_controls": {
            name: {"run": n, "failed_as_required": n, "last": "x"}
            for name, n in spec["required_controls"].items()
        },
    }


# ---------------------------------------------------------------------------
# Layer 1: the helper
# ---------------------------------------------------------------------------


class SelectionTests(unittest.TestCase):
    def test_default_is_every_protocol_in_inventory_order(self):
        self.assertEqual(plp.select([]), ["uart_tx", "spi", "i2c_sr"])

    def test_subset_keeps_inventory_order_and_drops_duplicates(self):
        self.assertEqual(plp.select(["i2c_sr", "uart_tx", "i2c_sr"]), ["uart_tx", "i2c_sr"])

    def test_unknown_protocol_is_a_usage_error(self):
        with self.assertRaises(plp.UsageError):
            plp.select(["spi", "uart_rx"])

    def test_cli_unknown_protocol_exits_2(self):
        proc = subprocess.run(
            [sys.executable, str(FLOW / "post_layout_protocols.py"), "select", "--protocol", "can"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("unknown protocol", proc.stderr)

    def test_matrix_is_corner_major(self):
        self.assertEqual(
            plp.run_matrix(["a", "b"], ["spi", "uart_tx"]),
            [("a", "uart_tx"), ("a", "spi"), ("b", "uart_tx"), ("b", "spi")],
        )

    def test_matrix_rejects_no_or_duplicate_corners(self):
        with self.assertRaises(plp.UsageError):
            plp.run_matrix([], [])
        with self.assertRaises(plp.UsageError):
            plp.run_matrix(["a", "a"], [])


class GradeTests(unittest.TestCase):
    def grade(self, protocol="spi", envelope="good", rc=0, report="good"):
        env = good_envelope(protocol) if envelope == "good" else envelope
        rep = good_report(protocol) if report == "good" else report
        return plp.grade(protocol, "corner_a", env, rc, rep, 12)

    def assertFailsWith(self, entry, fragment):
        self.assertEqual(entry["verdict"], "fail")
        self.assertTrue(
            any(fragment in r for r in entry["reasons"]),
            f"no reason containing {fragment!r} in {entry['reasons']}",
        )

    def test_every_protocol_passes_on_a_complete_run(self):
        for protocol in plp.PROTOCOLS:
            entry = self.grade(protocol)
            self.assertEqual(entry["verdict"], "pass", entry["reasons"])
            self.assertTrue(entry["sdf_annotated"])

    def test_nonzero_klt_exit(self):
        self.assertFailsWith(self.grade(rc=1), "klt exited 1")

    def test_missing_response(self):
        self.assertFailsWith(self.grade(envelope=None), "missing result")

    def test_annotation_false(self):
        self.assertFailsWith(self.grade(envelope=good_envelope("spi", annotated=False)),
                             "environment.sdf.annotated")

    def test_annotation_absent(self):
        self.assertFailsWith(self.grade(envelope=good_envelope("spi", annotated=None)),
                             "environment.sdf.annotated")

    def test_failed_status(self):
        env = good_envelope("spi", status="fail")
        env["tests"][1]["status"] = "failed"
        env["failed_count"] = 1
        entry = self.grade(envelope=env)
        self.assertFailsWith(entry, "klt status 'fail'")
        self.assertFailsWith(entry, "test_all_four_modes_pass_independent_reference_model failed")

    def test_missing_test_result(self):
        env = good_envelope("i2c_sr")
        del env["tests"][2]
        self.assertFailsWith(self.grade("i2c_sr", envelope=env), "test_sr_poll_programs_stretch not reported")

    def test_skipped_test(self):
        env = good_envelope("uart_tx")
        env["tests"][1]["status"] = "skipped"
        env["skipped_count"] = 1
        entry = self.grade("uart_tx", envelope=env)
        self.assertFailsWith(entry, "skipped")

    def test_unexpected_test_means_stale_inventory(self):
        env = good_envelope("uart_tx")
        env["tests"].append({"name": "test_new", "status": "passed"})
        self.assertFailsWith(self.grade("uart_tx", envelope=env), "inventory is stale")

    def test_missing_report(self):
        self.assertFailsWith(self.grade(report=None), "no parsable protocol report")

    def test_report_for_another_protocol(self):
        self.assertFailsWith(self.grade("spi", report=good_report("uart_tx")), "is for 'uart_tx'")

    def test_unaligned_report(self):
        rep = good_report("spi")
        rep["alignment_ps"] = None
        self.assertFailsWith(self.grade(report=rep), "ran unaligned")

    def test_too_few_captures(self):
        rep = good_report("i2c_sr")
        rep["captures"] = 6
        self.assertFailsWith(self.grade("i2c_sr", report=rep), "6 capture(s), at least 16")

    def test_observe_point_violation(self):
        self.assertFailsWith(self.grade(report=good_report("spi", violations=2)),
                             "not before the observe point")

    def test_zero_pin_delay_means_annotation_had_no_effect(self):
        self.assertFailsWith(self.grade(report=good_report("spi", max_delay=0)),
                             "back-annotation had no effect")

    def test_no_pin_events(self):
        rep = good_report("spi")
        for e in rep["pin_events"].values():
            e["count"] = 0
        self.assertFailsWith(self.grade(report=rep), "no output transition observed")

    def test_spi_timing_control_must_run_and_fail(self):
        rep = good_report("spi")
        rep["timing_controls"] = {}
        self.assertFailsWith(self.grade(report=rep), "ran 0 time(s), at least 8")
        rep = good_report("spi")
        rep["timing_controls"]["spi_ceiling_compressed"]["failed_as_required"] = 7
        self.assertFailsWith(self.grade(report=rep), "1 of 8 did not fail as required")


class AggregateTests(unittest.TestCase):
    ALIGN = {"clock_period_ns": 20.0, "drive_offset_ns": 4.0, "sample_offset_ns": 16.0}

    def entries(self, corners=CORNERS, bad=()):
        out = []
        for corner in corners:
            for protocol in plp.PROTOCOLS:
                rc = 1 if (corner, protocol) in bad else 0
                out.append(plp.grade(protocol, corner, good_envelope(protocol), rc,
                                     good_report(protocol)))
        return out

    def test_all_pass(self):
        doc = plp.aggregate(self.entries(), CORNERS, [], self.ALIGN, {})
        self.assertEqual(doc["overall"], "pass")
        self.assertEqual(doc["matrix"]["spi"], {"corner_a": "pass", "corner_b": "pass"})
        self.assertEqual(len(doc["runs"]), 6)
        self.assertIn("LibreLane", doc["flow"])

    def test_one_failing_protocol_among_passing_corners_fails_the_suite(self):
        doc = plp.aggregate(self.entries(bad={("corner_b", "spi")}), CORNERS, [], self.ALIGN, {})
        self.assertEqual(doc["overall"], "fail")
        self.assertEqual(doc["matrix"]["spi"], {"corner_a": "pass", "corner_b": "fail"})
        self.assertEqual(doc["matrix"]["uart_tx"], {"corner_a": "pass", "corner_b": "pass"})
        self.assertTrue(any(f.startswith("corner_b/spi") for f in doc["failures"]))

    def test_missing_cell_fails(self):
        entries = [e for e in self.entries()
                   if not (e["corner"] == "corner_a" and e["protocol"] == "i2c_sr")]
        doc = plp.aggregate(entries, CORNERS, [], self.ALIGN, {})
        self.assertEqual(doc["overall"], "fail")
        self.assertEqual(doc["matrix"]["i2c_sr"]["corner_a"], "missing")

    def test_duplicate_or_unexpected_cell_fails(self):
        entries = self.entries()
        doc = plp.aggregate(entries + entries[:1], CORNERS, [], self.ALIGN, {})
        self.assertEqual(doc["overall"], "fail")
        doc = plp.aggregate(self.entries(), ["corner_a"], [], self.ALIGN, {})
        self.assertEqual(doc["overall"], "fail")


class LimitationTests(unittest.TestCase):
    NORM = {"macro_cell_blocks_dropped": [
        {"cell_type": "RM_IHPSG13_1P_256x16_c2_bm_bist", "iopath_entries_dropped": 17,
         "timingcheck_entries_dropped": 40}]}
    RENAMES = [{"kind": "macro", "instance": "u_prog_mem.u_sram"},
               {"kind": "stdcell", "instance": "u_prog_mem.u_ren_drv"}]

    def test_sram_macro_is_stated_as_zero_delay_functional(self):
        lim = plp.limitations(["RM_IHPSG13_1P_256x16_c2_bm_bist"], [("n.json", self.NORM)],
                              self.RENAMES)
        sram = lim["sram"]
        self.assertTrue(sram["present"])
        self.assertIn("zero-delay FUNCTIONAL", sram["model"])
        self.assertIn("STA", sram["timing_covered_by"])
        self.assertEqual(sram["dropped_per_corner"][0]["iopath_entries_dropped"], 17)
        self.assertEqual([r["instance"] for r in sram["macro_instance_renames"]],
                         ["u_prog_mem.u_sram"])

    def test_no_macro_is_stated_too(self):
        self.assertFalse(plp.limitations([], [], [])["sram"]["present"])

    def test_pads_observe_point_and_scope(self):
        lim = plp.limitations([], [], [])
        self.assertIn("zero-delay", lim["pads"]["uio"])
        self.assertIn("not in the netlist", lim["pads"]["io_cells"])
        self.assertIn("strictly before", lim["observe_point"])
        self.assertIn("no full-chip timing-closure claim", lim["claim_scope"])


class InventoryTests(unittest.TestCase):
    def cocotb_tests(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = []
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef):
                for deco in node.decorator_list:
                    if "cocotb.test" in ast.unparse(deco):
                        names.append(node.name)
        return names

    def test_expected_tests_are_exactly_the_benches_tests(self):
        for protocol, spec in plp.PROTOCOLS.items():
            bench = REPO / "verification" / f"{spec['bench_module']}.py"
            self.assertEqual(sorted(self.cocotb_tests(bench)), sorted(spec["expected_tests"]),
                             protocol)

    def test_wrappers_name_their_bench_and_protocol(self):
        for protocol, spec in plp.PROTOCOLS.items():
            text = (REPO / "verification" / f"{spec['testbench_module']}.py").read_text(encoding="utf-8")
            self.assertIn(f"import {spec['bench_module']} as bench", text)
            self.assertIn(f'PROTOCOL = "{protocol}"', text)

    def test_benches_are_in_the_gate_level_inventory(self):
        text = (FLOW / "run-firmware-gate-level.sh").read_text(encoding="utf-8")
        modules = set(re.search(r"^MODULES=\(([^)]*)\)", text, re.M).group(1).split())
        modules |= set(re.findall(r"--full\) MODULES\+=\((\w+)\)", text))
        for spec in plp.PROTOCOLS.values():
            self.assertIn(spec["bench_module"], modules)

    def test_protocol_results_file_is_gitignored(self):
        self.assertIn("flow/post-layout-sdf-protocol-results.json",
                      (REPO / ".gitignore").read_text(encoding="utf-8").split())


# ---------------------------------------------------------------------------
# Layer 2: the real runner, fake klt, synthetic artifacts
# ---------------------------------------------------------------------------

TOP = "tt_um_2amlogic_protocol_emulator"
MACRO = "RM_FAKEMACRO_1"

FAKE_KLT = r'''#!/usr/bin/env python3
import json, os, sys, time
root = os.environ["FAKE_KLT_ROOT"]
args = sys.argv[1:]
if args[:1] == ["--help"]:
    print("commands: functional-verification pdk")
    sys.exit(0)
if args[:2] == ["pdk", "find"]:
    print(json.dumps({"root": os.path.join(root, "pdk")}))
    sys.exit(0)
assert args[0] == "functional-verification", args
req_path = args[1]
req = json.load(open(req_path))
module = req["testbench"]["module"]
sdf = os.path.basename(req["options"]["sdf"]["file"])
corner = sdf.split(".")[0]
plan = json.load(open(os.path.join(root, "plan.json")))
action = plan.get(f"{corner}/{module}", "pass")
log = os.path.join(root, "klt.log")
with open(log, "a") as h:
    h.write(json.dumps({"event": "start", "t": time.time(), "corner": corner, "module": module,
                        "report": os.environ.get("PE_SDF_PROTOCOL_REPORT"),
                        "align": [os.environ.get(k) for k in ("PE_ALIGN_CLK_PERIOD_NS",
                                  "PE_ALIGN_DRIVE_OFFSET_NS", "PE_ALIGN_SAMPLE_OFFSET_NS")],
                        "request": req}) + "\n")
time.sleep(0.05)
answers = json.load(open(os.path.join(root, "answers.json")))
envelope, report = answers[module]["envelope"], answers[module]["report"]
rc = 0
if action == "fail_status":
    envelope["status"] = "fail"; envelope["tests"][-1]["status"] = "failed"; envelope["failed_count"] = 1
elif action == "not_annotated":
    envelope["environment"]["sdf"]["annotated"] = False
elif action == "rc1":
    rc = 1
if action == "no_output":
    rc = 1
else:
    print(json.dumps(envelope))
if report is not None and action != "no_report" and os.environ.get("PE_SDF_PROTOCOL_REPORT"):
    with open(os.environ["PE_SDF_PROTOCOL_REPORT"], "w") as h:
        json.dump(report, h)
with open(log, "a") as h:
    h.write(json.dumps({"event": "end", "t": time.time(), "corner": corner, "module": module}) + "\n")
sys.exit(rc)
'''


def sdf_text(corner):
    return textwrap.dedent(f"""\
        (DELAYFILE
         (SDFVERSION "3.0")
         (DESIGN "{TOP}")
         (VOLTAGE 1.200::1.200)
         (PROCESS "typ")
         (TEMPERATURE 25.000::25.000)
         (TIMESCALE 1ns)
         (CELL
          (CELLTYPE "{TOP}")
          (INSTANCE)
          (DELAY
           (ABSOLUTE
            (INTERCONNECT clk _1_/CLK (0.100:0.120:0.140) (0.100:0.120:0.140))
            (INTERCONNECT _2_/X uo_out[0] (0.000:0.000:0.000) (0.000:0.000:0.000))
            (INTERCONNECT _1_/Q u_prog_mem\\.u_sram/A_CLK (0.050:0.060:0.070) (0.050:0.060:0.070))
           )
          )
         )
         (CELL
          (CELLTYPE "{MACRO}")
          (INSTANCE u_prog_mem\\.u_sram)
          (DELAY
           (ABSOLUTE
            (IOPATH A_CLK A_DOUT[0] (1.0:1.0:1.0) (1.0:1.0:1.0))
           )
          )
         )
        )
        """)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pe217-"))
        self.root = self.tmp / "repo"
        (self.root / "flow").mkdir(parents=True)
        for name in ("run-post-layout-sdf.sh", "_klt.sh", "post_layout_protocols.py"):
            shutil.copy2(FLOW / name, self.root / "flow" / name)
        (self.root / "verification").mkdir()
        (self.root / "rtl" / "vendor").mkdir(parents=True)
        (self.root / "rtl" / "vendor" / f"{MACRO}.v").write_text(f"module {MACRO}(); endmodule\n")
        cells = self.tmp / "pdk" / "ihp-sg13cmos5l" / "libs.ref" / "sg13cmos5l_stdcell" / "verilog"
        cells.mkdir(parents=True)
        for name in ("sg13cmos5l_stdcell.v", "sg13cmos5l_udp.v"):
            (cells / name).write_text("// fake\n")
        art = self.tmp / "art"
        (art / "tt_submission").mkdir(parents=True)
        (art / "tt_submission" / f"{TOP}.v").write_text(textwrap.dedent(f"""\
            module {TOP}(input clk, output [7:0] uo_out);
              {MACRO} \\u_prog_mem.u_sram  (.A_CLK(clk));
            endmodule
            """))
        final = art / "GDS_logs" / "runs" / "r" / "final"
        for corner in CORNERS:
            (final / "sdf" / corner).mkdir(parents=True)
            (final / "sdf" / corner / f"{TOP}__{corner}.sdf").write_text(sdf_text(corner))
        (final / "sdc").mkdir(parents=True)
        (final / "sdc" / f"{TOP}.sdc").write_text(
            "create_clock -name clk -period 20.0 [get_ports {clk}]\n"
            "set_input_delay 4.0 -clock [get_clocks {clk}] -add_delay [get_ports {ui_in[0]}]\n"
            "set_output_delay 4.0 -clock [get_clocks {clk}] -add_delay [get_ports {uo_out[0]}]\n"
        )
        self.art = art
        klt = self.tmp / "klt"
        klt.write_text(FAKE_KLT)
        klt.chmod(klt.stat().st_mode | stat.S_IEXEC)
        self.klt = klt
        answers = {"sdf_alignment": {"envelope": {
            "status": "pass", "testbench": "sdf_alignment", "test_count": 1, "passed_count": 1,
            "failed_count": 0, "skipped_count": 0, "tests": [{"name": "t", "status": "passed"}],
            "environment": {"sdf": {"annotated": True}}}, "report": None}}
        for protocol, spec in plp.PROTOCOLS.items():
            answers[spec["testbench_module"]] = {"envelope": good_envelope(protocol),
                                                 "report": good_report(protocol)}
        (self.tmp / "answers.json").write_text(json.dumps(answers))
        self.plan({})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def plan(self, plan):
        (self.tmp / "plan.json").write_text(json.dumps(plan))

    def run_runner(self, *args):
        env = dict(os.environ, KLT_BIN=str(self.klt), FAKE_KLT_ROOT=str(self.tmp))
        for key in ("PE_ALIGN_CLK_PERIOD_NS", "PE_ALIGN_DRIVE_OFFSET_NS",
                    "PE_ALIGN_SAMPLE_OFFSET_NS", "PE_SDF_PROTOCOL_REPORT"):
            env.pop(key, None)
        return subprocess.run(
            ["bash", str(self.root / "flow" / "run-post-layout-sdf.sh"), "--from", str(self.art), *args],
            capture_output=True, text=True, env=env, timeout=300,
        )

    def calls(self):
        path = self.tmp / "klt.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def starts(self):
        return [(c["corner"], c["module"]) for c in self.calls() if c["event"] == "start"]

    def protocol_results(self):
        return json.loads((self.root / "flow" / "post-layout-sdf-protocol-results.json").read_text())

    # -- default suite ------------------------------------------------------

    def test_default_core_suite_is_unchanged(self):
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.starts(), [(c, "sdf_alignment") for c in CORNERS])
        results = json.loads((self.root / "flow" / "post-layout-sdf-results.json").read_text())
        self.assertEqual([r["corner"] for r in results], list(CORNERS))
        self.assertFalse((self.root / "flow" / "post-layout-sdf-protocol-results.json").exists())
        start = [c for c in self.calls() if c["event"] == "start"][0]
        self.assertIsNone(start["report"])
        self.assertEqual(start["align"], ["20.0", "4.0", "16.0"])
        # same request shape as the frozen core-suite request of the live record
        frozen = json.loads(FROZEN_REQUEST.read_text())
        request = start["request"]
        self.assertEqual(set(request), set(frozen))
        self.assertEqual(request["testbench"]["module"], frozen["testbench"]["module"])
        self.assertEqual(set(request["testbench"]), set(frozen["testbench"]))
        self.assertEqual({k: v for k, v in request["options"].items() if k != "sdf"},
                         {k: v for k, v in frozen["options"].items() if k != "sdf"})
        self.assertEqual(request["options"]["sdf"]["corner"], frozen["options"]["sdf"]["corner"])
        self.assertTrue(request["options"]["sdf"]["file"].endswith(".normalized.sdf"))
        self.assertEqual(len(request["sources"]), len(frozen["sources"]))
        self.assertTrue(request["sources"][-1].endswith("macro-models.sim.v"))

    def test_protocol_option_requires_protocol_suite(self):
        proc = self.run_runner("--protocol", "spi")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--protocol needs --suite protocols", proc.stderr)
        self.assertEqual(self.starts(), [])

    def test_unknown_suite_and_unknown_protocol_are_rejected_before_any_run(self):
        proc = self.run_runner("--suite", "everything")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("--suite must be", proc.stderr)
        proc = self.run_runner("--suite", "protocols", "--protocol", "usb")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("unknown protocol", proc.stderr)
        self.assertEqual(self.starts(), [])

    def test_unemitted_corner_is_fatal_before_any_run(self):
        proc = self.run_runner("--suite", "protocols", "corner_z")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no SDF for corner 'corner_z'", proc.stderr)
        self.assertEqual(self.starts(), [])

    # -- protocol suite -----------------------------------------------------

    def test_protocol_suite_runs_serially_corner_major_and_passes(self):
        proc = self.run_runner("--suite", "protocols")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        modules = [plp.PROTOCOLS[p]["testbench_module"] for p in plp.DEFAULT_ORDER]
        self.assertEqual(self.starts(), [(c, m) for c in CORNERS for m in modules])
        events = self.calls()
        # strictly one at a time: start, end, start, end, ...
        self.assertEqual([e["event"] for e in events], ["start", "end"] * 6)
        for a, b in zip(events[1::2], events[2::2]):
            self.assertLessEqual(a["t"], b["t"])
        reports = [e["report"] for e in events if e["event"] == "start"]
        self.assertEqual(len(set(reports)), 6)
        self.assertTrue(all(e["align"] == ["20.0", "4.0", "16.0"] for e in events if e["event"] == "start"))
        doc = self.protocol_results()
        self.assertEqual(doc["overall"], "pass")
        self.assertEqual(doc["matrix"], {p: {c: "pass" for c in CORNERS} for p in plp.DEFAULT_ORDER})
        self.assertTrue(doc["limitations"]["sram"]["present"])
        self.assertEqual(doc["limitations"]["sram"]["macro_types"], [MACRO])
        self.assertEqual(len(doc["limitations"]["sram"]["dropped_per_corner"]), 2)
        self.assertEqual(doc["alignment"]["drive_offset_ns"], 4.0)
        self.assertFalse((self.root / "flow" / "post-layout-sdf-results.json").exists())

    def test_protocol_subset_keeps_inventory_order(self):
        proc = self.run_runner("--suite", "protocols", "--protocol", "spi",
                               "--protocol", "uart_tx", "corner_b")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.starts(), [("corner_b", "sdf_protocol_uart_tx"),
                                         ("corner_b", "sdf_protocol_spi")])
        self.assertEqual(self.protocol_results()["matrix"],
                         {"uart_tx": {"corner_b": "pass"}, "spi": {"corner_b": "pass"}})

    def check_failure(self, action, corner, protocol, fragment):
        module = plp.PROTOCOLS[protocol]["testbench_module"]
        self.plan({f"{corner}/{module}": action})
        proc = self.run_runner("--suite", "protocols")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("FATAL: the protocol suite is not a pass", proc.stderr)
        self.assertEqual(len(self.starts()), 6, "every cell still runs after a failure")
        doc = self.protocol_results()
        self.assertEqual(doc["overall"], "fail")
        for p in plp.DEFAULT_ORDER:
            for c in CORNERS:
                want = "fail" if (c, p) == (corner, protocol) else "pass"
                self.assertEqual(doc["matrix"][p][c], want, (p, c))
        bad = [r for r in doc["runs"] if r["verdict"] == "fail"]
        self.assertTrue(any(fragment in reason for reason in bad[0]["reasons"]), bad[0]["reasons"])

    def test_failed_protocol_verdict_propagates(self):
        self.check_failure("fail_status", "corner_b", "spi", "klt status 'fail'")

    def test_annotation_false_propagates(self):
        self.check_failure("not_annotated", "corner_a", "uart_tx", "environment.sdf.annotated")

    def test_missing_response_propagates(self):
        self.check_failure("no_output", "corner_a", "i2c_sr", "missing result")

    def test_missing_report_propagates(self):
        self.check_failure("no_report", "corner_b", "uart_tx", "no parsable protocol report")

    def test_klt_error_exit_propagates(self):
        self.check_failure("rc1", "corner_a", "spi", "klt exited 1")


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=1).result
    sys.exit(0 if result.wasSuccessful() else 1)
