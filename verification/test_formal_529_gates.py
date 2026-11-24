#!/usr/bin/env python3
"""Self-test for issue #529's formal runners and negative-control gates.

Exercises both cold-start runners with deterministic tool shims in a scratch
PATH so CI's tool-light `records` job (`npm run lint`) verifies:
  1. `no_data_dependent_latency.sv` stays byte-identical to the live record;
  2. every sed-injected mutant against the real `rtl/protocol_core.v` and
     `rtl/protocol_program_memory.v` applies to the exact expected line count
     without modifying `rtl/`;
  3. `run-no-data-dependent-latency-second-engine.sh` enforces BMC_DEPTH >= 30,
     passes when rIC3 proves all positive legs and disproves all 3 core mutants,
     and rejects undecided proofs, missed mutants, and mutant-only tool crashes;
  4. `run-serial-load-shift-in.sh` passes when standalone + integrated positive
     legs and covers pass and all 3 loader mutants are disproved across BMC,
     ABC PDR and rIC3, and rejects unreached covers, missed mutants, and
     mutant-only solver crashes.

Run: python3 verification/test_formal_529_gates.py
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FORMAL_DIR = REPO_ROOT / "verification" / "formal"
SECOND_RUNNER = FORMAL_DIR / "run-no-data-dependent-latency-second-engine.sh"
SHIFT_RUNNER = FORMAL_DIR / "run-serial-load-shift-in.sh"
MONITOR_SV = FORMAL_DIR / "no_data_dependent_latency.sv"
LOAD_MON_SV = FORMAL_DIR / "serial_load_latency.sv"
LOAD_TOP_V = FORMAL_DIR / "formal_top_load.v"

LIVE_MONITOR_SHA256 = "6e9691ef026ff758e7a0b943bdec3d04aa49e84fb87b73227621b1661a469c18"


def write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_shims(bin_dir: Path) -> None:
    """Create deterministic tool shims driven by FAKE_* environment variables."""
    write_exec(
        bin_dir / "yosys",
        """#!/usr/bin/env python3
import re, sys
from pathlib import Path
if "-V" in sys.argv or "--version" in sys.argv:
    print("Yosys 0.67+post (mock)")
    sys.exit(0)
script = sys.argv[sys.argv.index("-p") + 1] if "-p" in sys.argv else ""
for m in re.finditer(r"write_smt2\\s+(?:-wires\\s+)?(\\S+)", script):
    Path(m.group(1)).write_text("; mock smt2\\n")
for m in re.finditer(r"-ywmap\\s+(\\S+)\\s+(\\S+)", script):
    Path(m.group(1)).write_text("{}\\n")
    Path(m.group(2)).write_bytes(b"aig 1 0 1 0 0 1\\n0\\n0\\n")
for m in re.finditer(r"write_aiger\\s+-zinit\\s+(?!-ywmap)(\\S+)", script):
    Path(m.group(1)).write_bytes(b"aig 1 0 1 0 0 1\\n0\\n0\\n")
for m in re.finditer(r"write_btor\\s+(\\S+)", script):
    Path(m.group(1)).write_text("1 sort bitvec 1\\n2 bad 1\\n")
""",
    )
    write_exec(
        bin_dir / "z3",
        """#!/usr/bin/env bash
echo "Z3 version 5.4.1 - 64 bit (mock)"
""",
    )
    write_exec(
        bin_dir / "yosys-smtbmc",
        """#!/usr/bin/env python3
import os, sys
from pathlib import Path
if "--help" in sys.argv:
    print("yosys-smtbmc [options] <yosys_smt2_output>")
    sys.exit(0)
model = sys.argv[-1]
is_mut = "mut" in Path(model).name
is_cov = "-c" in sys.argv
mode = os.environ.get("FAKE_SMTBMC_MODE", "ok")
if is_cov and mode == "cover_fail":
    print("## Unreached cover statement")
    sys.exit(1)
if is_mut:
    if mode == "mut_crash":
        print("ERROR: injected smtbmc crash")
        sys.exit(2)
    if mode == "mut_pass":
        print("## Status: PASSED")
        sys.exit(0)
    if "--dump-vcd" in sys.argv:
        vcd = sys.argv[sys.argv.index("--dump-vcd") + 1]
        Path(vcd).write_text("$date mock $end\\n")
    print("## Assert failed in formal_top: mock.v:1")
    print("## Status: FAILED")
    print("BMC failed!")
    sys.exit(1)
print("## Status: PASSED")
sys.exit(0)
""",
    )
    write_exec(
        bin_dir / "yosys-abc",
        """#!/usr/bin/env python3
import os, re, sys
cmd = sys.argv[sys.argv.index("-c") + 1] if "-c" in sys.argv else ""
if "-q" in sys.argv:
    print("UC Berkeley, ABC 1.01 (mock)")
    sys.exit(0)
m = re.search(r"read_aiger\\s+(\\S+?);", cmd)
aig = m.group(1) if m else ""
mode = os.environ.get("FAKE_ABC_MODE", "ok")
if "mut" in aig:
    if mode == "mut_missed":
        print("Properties:  All = 5. Proved = 5. Disproved = 0. Undecided = 0.   Time = 0.10 sec")
    elif mode == "mut_crash":
        print("ERROR: injected abc crash")
        sys.exit(2)
    else:
        print("Output 0 of miter was asserted in frame 3.")
        print("Properties:  All = 5. Proved = 2. Disproved = 3. Undecided = 0.   Time = 0.10 sec")
elif "integrated" in aig:
    print("Properties:  All = 13. Proved = 13. Disproved = 0. Undecided = 0.   Time = 0.20 sec")
else:
    print("Properties:  All = 5. Proved = 5. Disproved = 0. Undecided = 0.   Time = 0.10 sec")
""",
    )
    write_exec(
        bin_dir / "ric3",
        """#!/usr/bin/env python3
import os, sys
from pathlib import Path
if "--version" in sys.argv or "-V" in sys.argv:
    print("rIC3 1.5.2")
    sys.exit(0)
args = sys.argv[1:]
# ric3 check --ui false <MODEL> <SUBCMD> ...
idx = args.index("check")
pos = [a for a in args[idx + 1:] if a not in ("--ui", "false", "--cex", "--no-parallel")]
model = pos[0]
subcmd = pos[1]
name = Path(model).name
mode = os.environ.get("FAKE_RIC3_MODE", "ok")
if "mut" in name:
    if mode == "mut_crash":
        print("ERROR: injected ric3 crash")
        sys.exit(2)
    if mode == "mut_missed":
        print("[00:00:00 INFO] IC3 proved the property")
        print("UNSAT")
        sys.exit(0)
    print("[00:00:00 INFO] IC3 found a counterexample at depth 6")
    print("SAT")
    sys.exit(0)
if subcmd == "bmc":
    end = args[args.index("--end") + 1] if "--end" in args else "30"
    if mode == "bmc_sat":
        print("[00:00:00 INFO] BMC found a counterexample at depth 4")
        print("SAT")
        sys.exit(0)
    print(f"[00:00:00 INFO] BMC found no counterexample up to depth {end}")
    print(f"[00:00:00 INFO] bmc reached bound {end}, stopping search")
    print("UNKNOWN")
    sys.exit(0)
if subcmd == "multi-prop":
    n = 8 if name == "core.aig" else 5
    if mode == "undecided":
        for _ in range(n - 1):
            print("UNSAT")
        print("UNKNOWN")
        sys.exit(0)
    for _ in range(n):
        print("UNSAT")
    sys.exit(0)
if mode == "btor_undecided" and name.endswith(".btor2"):
    print("UNKNOWN")
    sys.exit(0)
print("[00:00:00 INFO] IC3 proved the property")
print("UNSAT")
sys.exit(0)
""",
    )


class Formal529GatesTest(unittest.TestCase):
    def run_script(
        self, script: Path, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            bin_dir = t / "bin"
            bin_dir.mkdir()
            make_shims(bin_dir)
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
            env["RIC3"] = str(bin_dir / "ric3")
            if extra_env:
                env.update(extra_env)
            return subprocess.run(
                [str(script), str(t / "art")],
                check=False,
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )

    def test_files_present_and_monitor_byte_identical(self) -> None:
        self.assertTrue(
            SECOND_RUNNER.is_file() and os.access(SECOND_RUNNER, os.X_OK), SECOND_RUNNER
        )
        self.assertTrue(
            SHIFT_RUNNER.is_file() and os.access(SHIFT_RUNNER, os.X_OK), SHIFT_RUNNER
        )
        self.assertTrue(LOAD_MON_SV.is_file(), LOAD_MON_SV)
        self.assertTrue(LOAD_TOP_V.is_file(), LOAD_TOP_V)
        digest = hashlib.sha256(MONITOR_SV.read_bytes()).hexdigest()
        self.assertEqual(digest, LIVE_MONITOR_SHA256)

    def test_second_engine_happy_path_and_rtl_untouched(self) -> None:
        core_before = (REPO_ROOT / "rtl" / "protocol_core.v").read_bytes()
        res = self.run_script(SECOND_RUNNER)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("RESULT: all expectations met", res.stdout)
        self.assertEqual(
            (REPO_ROOT / "rtl" / "protocol_core.v").read_bytes(), core_before
        )

    def test_second_engine_rejects_shallow_bmc_depth(self) -> None:
        res = self.run_script(SECOND_RUNNER, {"BMC_DEPTH": "29"})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("30", res.stderr)

    def test_second_engine_rejects_undecided_positive_proof(self) -> None:
        res = self.run_script(SECOND_RUNNER, {"FAKE_RIC3_MODE": "undecided"})
        self.assertNotEqual(res.returncode, 0)

    def test_second_engine_rejects_btor2_undecided(self) -> None:
        res = self.run_script(SECOND_RUNNER, {"FAKE_RIC3_MODE": "btor_undecided"})
        self.assertNotEqual(res.returncode, 0)

    def test_second_engine_rejects_mutant_crash_and_missed_mutant(self) -> None:
        crash = self.run_script(SECOND_RUNNER, {"FAKE_RIC3_MODE": "mut_crash"})
        self.assertNotEqual(crash.returncode, 0)
        self.assertIn("solver/tool failure", crash.stderr)

        missed = self.run_script(SECOND_RUNNER, {"FAKE_RIC3_MODE": "mut_missed"})
        self.assertNotEqual(missed.returncode, 0)

    def test_shift_in_happy_path_and_rtl_untouched(self) -> None:
        mem_before = (REPO_ROOT / "rtl" / "protocol_program_memory.v").read_bytes()
        res = self.run_script(SHIFT_RUNNER, {"REQUIRE_RIC3": "1"})
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("RESULT: all expectations met", res.stdout)
        self.assertEqual(
            (REPO_ROOT / "rtl" / "protocol_program_memory.v").read_bytes(), mem_before
        )

    def test_shift_in_rejects_unreached_cover(self) -> None:
        res = self.run_script(SHIFT_RUNNER, {"FAKE_SMTBMC_MODE": "cover_fail"})
        self.assertNotEqual(res.returncode, 0)

    def test_shift_in_rejects_mutant_crashes_and_missed_mutants(self) -> None:
        for var, val in (
            ("FAKE_SMTBMC_MODE", "mut_crash"),
            ("FAKE_SMTBMC_MODE", "mut_pass"),
            ("FAKE_ABC_MODE", "mut_crash"),
            ("FAKE_ABC_MODE", "mut_missed"),
            ("FAKE_RIC3_MODE", "mut_crash"),
            ("FAKE_RIC3_MODE", "mut_missed"),
        ):
            with self.subTest(var=var, val=val):
                res = self.run_script(SHIFT_RUNNER, {"REQUIRE_RIC3": "1", var: val})
                self.assertNotEqual(
                    res.returncode, 0, f"{var}={val} unexpectedly passed"
                )


if __name__ == "__main__":
    unittest.main()
