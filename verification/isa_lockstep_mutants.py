#!/usr/bin/env python3
"""Negative controls for `test_isa_lockstep.py` (issue #152).

A bench that cannot fail cannot cite its passes. This runner copies the
sources the bench needs into a scratch tree, injects ONE defect into the
copy of the RTL, runs the unmodified bench on it through
`klt functional-verification`, and requires the bench to FAIL -- by a
parsed result with at least one failed test, not by a crash. It repeats
that for each defect below. `rtl/` and `src/` in the repository are never
edited.

Each defect is an exact-text substitution that must apply (the anchor must
be present exactly as many times as stated), so a later RTL edit cannot
silently turn a negative control into a second positive run.

Each mutant also names the tests that exist to catch it; the run fails if
none of them is among the failures (the defect was caught, but only by
accident).

Usage:
    python3 verification/isa_lockstep_mutants.py [--out DIR] [--only NAME]

Needs `klt` (with cocotb) and `iverilog` on PATH, like the bench itself.
Runs one simulation at a time. Writes `summary.json` and one directory per
mutant under --out (default: a temporary directory, removed on exit).
Exit 0 = the golden run passed and every mutant was caught as required.
"""

from __future__ import annotations

import sys
from pathlib import Path

from _mutant_runner import run, run_bench

REQUEST = "verification/request-isa-lockstep.json"
CORE = "rtl/protocol_core.v"

T_LOCK = "test_isa_lockstep_random_programs"
T_SUBPIN = "test_sub_carry_polarity_pin"

# (name, what the defect is, file, [(old, new, count)], tests that must catch it)
MUTANTS = [
    ("sub-carry-polarity-flipped",
     "SUB writes C as 'no borrow' instead of a borrow (DR 0016 Ruling 1, Proposed)",
     CORE,
     [("flag_c   <= sub_diff[8];  // borrow", "flag_c   <= ~sub_diff[8];  // borrow", 1)],
     {T_LOCK, T_SUBPIN}),
    ("shf-direction-swapped",
     "SHF shifts left when Rs[0] = 0 and right when 1",
     CORE,
     [("wire       shf_left = rs[0];", "wire       shf_left = ~rs[0];", 1)],
     {T_LOCK}),
    ("bz-bnz-swapped",
     "BZ branches when Z = 0 and BNZ when Z = 1",
     CORE,
     [("OP_BZ:   next_addr = flag_z  ? imm8 : pc_next;", "OP_BZ:   next_addr = !flag_z ? imm8 : pc_next;", 1),
      ("OP_BNZ:  next_addr = !flag_z ? imm8 : pc_next;", "OP_BNZ:  next_addr = flag_z  ? imm8 : pc_next;", 1)],
     {T_LOCK}),
    ("wait-off-by-one",
     "WAIT n stalls n+2 cycles instead of n+1",
     CORE,
     [("                waiting  <= 1'b1;\n                wait_cnt <= imm8;",
       "                waiting  <= 1'b1;\n                wait_cnt <= imm8 + 8'd1;", 1)],
     {T_LOCK}),
    ("add-carry-dropped",
     "ADD never sets C",
     CORE,
     [("flag_c   <= add_sum[8];", "flag_c   <= 1'b0;", 1)],
     {T_LOCK}),
    ("and-clears-c",
     "AND clears C (DR 0001: AND sets Z only; DR 0016 Ruling 3, Proposed: C is unchanged)",
     CORE,
     [("regs[rd] <= and_res;\n              flag_z   <= (and_res == 8'h00);",
       "regs[rd] <= and_res;\n              flag_z   <= (and_res == 8'h00);\n              flag_c   <= 1'b0;", 1)],
     {T_LOCK}),
    ("shf-writes-z",
     "SHF sets Z from its result (DR 0016 Ruling 2, Proposed: SHF leaves Z unchanged)",
     CORE,
     [("regs[rd] <= shf_res;\n              flag_c   <= shf_c;",
       "regs[rd] <= shf_res;\n              flag_c   <= shf_c;\n              flag_z   <= (shf_res == 8'h00);", 1)],
     {T_LOCK}),
    ("shf-fills-from-c",
     "SHF shifts C into the vacated bit, a rotate through carry (DR 0016 Ruling 4, Proposed: 0 fills)",
     CORE,
     [("wire [7:0] shf_res  = shf_left ? {rd_val[6:0], 1'b0} : {1'b0, rd_val[7:1]};",
       "wire [7:0] shf_res  = shf_left ? {rd_val[6:0], flag_c} : {flag_c, rd_val[7:1]};", 1)],
     {T_LOCK}),
    ("halt-does-not-hold-pc",
     "after HALT the fetch address keeps advancing",
     CORE,
     [("next_addr = pc;                                  // HALT: hold forever",
       "next_addr = pc_next;", 1)],
     {T_LOCK}),
    ("reserved-in-port-reads-uio",
     "IN from the reserved port 11 reads uio_in instead of being a no-op",
     CORE,
     [("wire       in_readable = (rs == PORT_UI_IN) || (rs == PORT_UIO_IN);",
       "wire       in_readable = (rs == PORT_UI_IN) || (rs == PORT_UIO_IN) || (rs == PORT_UIO_OUT);", 1)],
     {T_LOCK}),
]


def run_bench_with_first(tree: Path, request: str) -> dict:
    res = run_bench(tree, request)
    log = tree / "verification" / ".klt" / "functional-verification" / "test_icarus.log"
    first = ""
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            if "ISA LOCKSTEP MISMATCH" in line or "OPEN DETAIL" in line:
                first = " | ".join(x.strip() for x in lines[i:i + 3])
                break
    return {**res, "first": first}


def main(argv=None) -> int:
    return run(__doc__, argv, bench="verification/test_isa_lockstep.py", mutants=MUTANTS,
               request=REQUEST, run_bench_fn=run_bench_with_first,
               catch_phrase="the test meant to catch it",
               result_message="golden passes and every mutant is caught by its target test")


if __name__ == "__main__":
    sys.exit(main())
