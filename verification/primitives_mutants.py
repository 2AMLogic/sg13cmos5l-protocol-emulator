#!/usr/bin/env python3
"""Negative controls for `test_primitives.py` (issue #208, DR 0015 P1/P2).

A bench that cannot fail cannot cite its passes. This runner copies the
sources the bench needs into a scratch tree, injects ONE defect into the
copy of `rtl/protocol_core.v`, runs the unmodified bench on it through
`klt functional-verification`, and requires the bench to FAIL -- by a
parsed result with at least one failed test, not by a crash -- and to fail
in at least one of the tests named as that defect's catchers (so a defect
caught only by accident does not count). `rtl/` and `src/` in the
repository are never edited.

Each defect is an exact-text substitution whose anchor must appear exactly
as often as stated, so a later RTL edit cannot silently turn a negative
control into a second positive run. Same mechanics as
`control_space_mutants.py`, via the shared `_mutant_runner.py`.

Usage:
    python3 verification/primitives_mutants.py [--out DIR] [--only NAME]

Needs `klt` (with cocotb) and `iverilog` on PATH. Writes `summary.json` and
one directory per mutant under --out (default: a temporary directory).
Exit 0 = the golden run passed and every mutant was caught as required.
"""

from __future__ import annotations

import sys

from _mutant_runner import run
REQUEST = "verification/request-primitives.json"
CORE = "rtl/protocol_core.v"

T_CHECK = "test_crc_catalogue_check_values"
T_RANDOM = "test_crc_random_messages"
T_BITS = "test_crc_bit_steps"
T_LFSR = "test_lfsr_prbs"
T_REGS = "test_crc_registers_pointer_and_masking"
T_USB = "test_line_usb_nrzi_stuff6"
T_HDLC = "test_line_hdlc_stuff5"
T_CAN = "test_line_can_stuff5_equal"
T_LINEREG = "test_line_stuff_slot_ignores_rs_and_registers"
T_LAT = "test_fixed_latency_is_data_independent"
T_FLAGS = "test_no_flag_side_effects_and_unassigned"

# (name, what the defect is, file, [(old, new, count)], tests that must catch it)
MUTANTS = [
    ("crc-byte-latency-data-dependent",
     "WCTL CRC_BYTE stalls 1 cycle instead of 8 when Rs is 0x00 (data-dependent latency)",
     CORE,
     [("                      wait_cnt <= 8'd8;\n",
       "                      wait_cnt <= (rd_val == 8'h00) ? 8'd1 : 8'd8;\n", 1)],
     {T_LAT}),
    ("crc-byte-seven-bits",
     "WCTL CRC_BYTE stalls (and steps) 7 cycles instead of 8",
     CORE,
     [("                      wait_cnt <= 8'd8;\n", "                      wait_cnt <= 8'd7;\n", 1)],
     {T_CHECK, T_RANDOM, T_LAT}),
    ("crc-byte-bit-order-fixed",
     "CRC_BYTE feeds Rs MSB first in reflected mode too",
     CORE,
     [("  wire [2:0] crc_j    = crc_refl ? ~crc_j0 : crc_j0;",
       "  wire [2:0] crc_j    = crc_j0;", 1)],
     {T_CHECK, T_RANDOM}),
    ("crc-tap-ignores-width",
     "the normal-mode feedback taps bit 31 instead of bit W-1",
     CORE,
     [("(crc_refl ? crc_state[0] : crc_state[crc_wm1])",
       "(crc_refl ? crc_state[0] : crc_state[31])", 1)],
     {T_CHECK, T_RANDOM, T_BITS, T_LFSR}),
    ("crc-reflected-shift-unmasked",
     "the reflected step shifts state bits from above the width into bit W-1",
     CORE,
     [("((crc_state & crc_mask) >> 1)", "(crc_state >> 1)", 1)],
     {T_REGS}),
    ("crc-next-not-inverted",
     "CRC_NEXT ignores the read-out inversion bit",
     CORE,
     [("(crc_state_b ^ {8{crc_inv}}) & crc_mask_b", "crc_state_b & crc_mask_b", 1)],
     {T_CHECK, T_RANDOM, T_REGS}),
    ("crc-cfg-keeps-pointer",
     "a CRC_CFG write does not rewind the byte pointer",
     CORE,
     [("                      crc_inv  <= rd_val[6];\n                      crc_ptr  <= 2'd0;\n",
       "                      crc_inv  <= rd_val[6];\n", 1)],
     {T_REGS, T_LFSR}),
    ("crc-bit-reads-bit7",
     "CRC_BIT takes its data bit from Rs[7] instead of Rs[0]",
     CORE,
     [("crc_busy ? rd_val[crc_j] : rd_val[0];", "crc_busy ? rd_val[crc_j] : rd_val[7];", 1)],
     {T_BITS, T_LFSR}),
    ("crc-state-reset-nonzero",
     "CRC_STATE resets to 0x00000001 instead of 0",
     CORE,
     [("      crc_state    <= 32'h0000_0000;", "      crc_state    <= 32'h0000_0001;", 1)],
     {T_REGS}),
    ("line-stuff-one-late",
     "P2 stuffs after N+1 bits instead of N",
     CORE,
     [("(line_cnt == line_cfg[6:4])", "(line_cnt == line_cfg[6:4] + 3'd1)", 1)],
     {T_USB, T_HDLC, T_CAN, T_LINEREG}),
    ("line-stuff-slot-emits-data",
     "a stuff slot emits Rs[0] (and still flags LINE_STUF) instead of the stuff bit",
     CORE,
     [("line_due ? (line_equal & ~line_prev) : rd_val[0]", "rd_val[0]", 1)],
     {T_USB, T_HDLC, T_CAN, T_LINEREG}),
    ("line-nrzi-wrong-polarity",
     "NRZI mode 01 toggles on a 1 instead of a 0",
     CORE,
     [("(line_lvl ^ ~line_e) :  // toggle on 0", "(line_lvl ^ line_e) :  // toggle on 0", 1)],
     {T_USB, T_LINEREG}),
    ("line-equal-run-restarts-at-zero",
     "the equal-bits rule restarts its run at 0 instead of 1 on a change",
     CORE,
     [("{2'b00, ~line_ones}", "3'd0", 1)],
     {T_CAN, T_LINEREG}),
    ("line-put-writes-z",
     "WCTL LINE_PUT writes the Z flag from the emitted bit",
     CORE,
     [("                      line_stuf <= line_due;\n",
       "                      line_stuf <= line_due;\n                      flag_z    <= line_e;\n", 1)],
     {T_FLAGS}),
]


def main(argv=None) -> int:
    return run(__doc__, argv, bench="verification/test_primitives.py", mutants=MUTANTS,
               request=REQUEST,
               catch_phrase="the test meant to catch it",
               result_message="golden passes and every mutant is caught by its target test")


if __name__ == "__main__":
    sys.exit(main())
