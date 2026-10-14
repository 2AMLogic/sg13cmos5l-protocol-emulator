#!/usr/bin/env python3
"""Negative controls for `test_load_integrity.py` (issue #137, DR 0013
layer 1).

A bench that cannot fail cannot cite its passes. Like
`control_space_mutants.py`, whose mechanics (shared in `_mutant_runner.py`) this reuses, this
runner injects ONE defect into a copy of the RTL, runs the unmodified
bench on it through `klt functional-verification`, and requires the bench
to FAIL -- by a parsed result with at least one failed test, not by a
crash -- and to fail in a test that exists to catch that defect. `rtl/`
and `src/` in the repository are never edited.

Each defect is an exact-text substitution that must apply exactly as many
times as stated, so a later RTL edit cannot silently turn a negative
control into a second positive run.

Usage:
    python3 verification/load_integrity_mutants.py [--out DIR] [--only NAME]

Needs `klt` (with cocotb) and `iverilog` on PATH, like the bench itself.
Runs one simulation at a time. Writes `summary.json` and one directory per
mutant under --out (default: a temporary directory, removed on exit).
Exit 0 = the golden run passed and every mutant was caught as required.
"""

from __future__ import annotations

import sys

from _mutant_runner import run
from control_space_mutants import PMEM, TOP

REQUEST = "verification/request-load-integrity.json"

T_READOUT = "test_readout_equals_crc_hqx_for_random_images"
T_RUNNING = "test_readout_is_the_running_crc_and_only_moves_on_a_commit"
T_SELECT = "test_byte_select_is_ui_in_1_alone_and_needs_no_clock"
T_TRUNC = "test_truncated_load_mismatches"
T_DROP = "test_dropped_clock_edge_mismatches"
T_DOUBLE = "test_doubled_clock_edge_mismatches"
T_PROTOCOL = "test_load_protocol_unchanged_by_the_readout"
T_OUTSIDE = "test_no_readout_outside_the_load_phase"
T_SATURATE = "test_readout_holds_at_saturation"

MUX = ("  assign uo_out = run_phase ? core_uo_out :\n"
       "                  ui_in[1]  ? pm_crc[15:8] :\n"
       "                              pm_crc[7:0];\n")

# (name, what the defect is, file, [(old, new, count)], tests that must catch it)
MUTANTS = [
    ("no-readout",
     "uo_out is the core's register in every phase (the design before issue #137)",
     TOP,
     [(MUX, "  assign uo_out = core_uo_out;\n", 1)],
     {T_READOUT}),
    ("bytes-swapped",
     "ui_in[1] = 0 selects the high byte and 1 the low byte",
     TOP,
     [(MUX, MUX.replace("pm_crc[15:8]", "pm_crc[7:0] ").replace(
         "                              pm_crc[7:0];", "                              pm_crc[15:8];"), 1)],
     {T_READOUT, T_SELECT}),
    ("select-on-ui_in-2",
     "the byte select is ui_in[2], not ui_in[1]",
     TOP,
     [(MUX, MUX.replace("ui_in[1]  ?", "ui_in[2]  ?"), 1)],
     {T_SELECT}),
    ("select-xor-serial-data",
     "the serial data pin flips the byte select",
     TOP,
     [(MUX, MUX.replace("ui_in[1]  ?", "(ui_in[1] ^ ui_in[0]) ?"), 1)],
     {T_SELECT}),
    ("readout-leaks-into-run-phase",
     "in the run phase ui_in[1] = 1 still puts the CRC high byte on uo_out",
     TOP,
     [(MUX, MUX.replace("run_phase ? core_uo_out", "(run_phase && !ui_in[1]) ? core_uo_out"), 1)],
     {T_PROTOCOL}),
    ("readout-follows-mode-pin",
     "the readout is gated on the MODE pin, not the latched phase: raising MODE in the run phase shows the CRC again",
     TOP,
     [(MUX, MUX.replace("run_phase ? core_uo_out", "!ui_in[7] ? core_uo_out"), 1)],
     {T_PROTOCOL}),
    ("crc-skips-serial-load",
     "PM_CRC covers PM_DATA_LO commits but not the serial load's",
     PMEM,
     [("      if (mem_wen) begin\n        pm_crc <=", "      if (run_wen) begin\n        pm_crc <=", 1)],
     {T_READOUT, T_RUNNING}),
    ("crc-byte-order-swapped",
     "PM_CRC feeds each word low byte first",
     PMEM,
     [("pm_crc <= crc16_word(pm_crc, mem_din);",
       "pm_crc <= crc16_word(pm_crc, {mem_din[7:0], mem_din[15:8]});", 1)],
     {T_READOUT}),
    ("crc-advances-on-every-bit",
     "PM_CRC advances on every load-phase edge, not only on a commit",
     PMEM,
     [("      if (mem_wen) begin\n        pm_crc <=",
       "      if (mem_wen || (load_active && mode_pin)) begin\n        pm_crc <=", 1)],
     {T_RUNNING, T_PROTOCOL}),
    ("crc-ignores-saturation",
     "PM_CRC keeps advancing on word boundaries after 256 words, when nothing is committed",
     PMEM,
     [("      if (mem_wen) begin\n        pm_crc <=",
       "      if (mem_wen || (load_active && mode_pin && bit_cnt == 4'd15)) begin\n        pm_crc <=", 1)],
     {T_SATURATE}),
    ("crc-survives-reset",
     "reset does not clear PM_CRC",
     PMEM,
     [("      pm_crc        <= 16'h0000;\n      serial_loaded <= 1'b0;",
       "      serial_loaded <= 1'b0;", 1)],
     {T_OUTSIDE}),
    ("boot-status-never-set",
     "BOOT_STATUS[0] is not set when the load phase ends",
     PMEM,
     [("        serial_loaded <= 1'b1;  // the load phase ends on this edge",
       "        serial_loaded <= 1'b0;", 1)],
     {T_PROTOCOL}),
]


def main(argv=None) -> int:
    return run(__doc__, argv, bench="verification/test_load_integrity.py", mutants=MUTANTS,
               request=REQUEST,
               catch_phrase="the test meant to catch it",
               result_message="golden passes and every mutant is caught by its target test")


if __name__ == "__main__":
    sys.exit(main())
