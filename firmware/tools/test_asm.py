#!/usr/bin/env python3
"""Self-test for `firmware/tools/asm.py` (issue #22, AC: "unit tests over
the instruction set, including malformed input").

Every expected encoding below is hand-derived from DR 0001's opcode table
(`spec/decision-records/0001-isa.md` section "Encoding") and cites the row
it checks -- the test verifies the assembler against the ratified table,
not against itself.

Zero dependencies beyond the Python 3 standard library.

Usage:
    python3 firmware/tools/test_asm.py
Exit codes: 0 all cases pass, 1 at least one failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import asm  # noqa: E402  (path-shimmed sibling import)

FAILURES = []


def check(name, fn):
    try:
        fn()
    except AssertionError as err:
        FAILURES.append(name)
        print(f"FAIL {name}: {err}")
    except Exception as err:  # noqa: BLE001 - a crash is a failure
        FAILURES.append(name)
        print(f"FAIL {name}: unexpected {type(err).__name__}: {err}")
    else:
        print(f"pass {name}")


def one(source, name="t"):
    """Assemble a one-liner (plus optional label context) to a Program."""
    return asm.assemble_text(source, source_name=f"{name}.asm")


def word_of(source):
    return one(source).words[0]


def expect_error(source, needle, name):
    try:
        one(source, name)
    except asm.AsmError as err:
        assert needle in err.message, (
            f"error message {err.message!r} missing {needle!r}"
        )
        return err
    raise AssertionError(f"expected an AsmError containing {needle!r}")


# --- encoding: every opcode row of DR 0001's table -------------------------

def test_nop():
    # DR 0001: NOP, opcode 0000, no operands, 1 cycle.
    assert word_of("NOP") == 0x0000

def test_ldi():
    # LDI Rd, imm8: opcode 0001, Rd in [11:10], imm8 in [7:0].
    assert word_of("LDI R0, 0") == 0x1000
    assert word_of("LDI R3, 0xFF") == 0x1000 | (3 << 10) | 0xFF  # 0x1CFF
    assert word_of("LDI R1, 165") == 0x1000 | (1 << 10) | 0xA5   # 0x14A5

def test_mov_rr_ops():
    # MOV/ADD/SUB/AND/OR/XOR Rd, Rs: opcode 0010-0111, Rd [11:10], Rs [9:8].
    assert word_of("MOV R1, R2") == 0x2000 | (1 << 10) | (2 << 8)
    assert word_of("MOV R3, R1") == 0x2000 | (3 << 10) | (1 << 8)
    assert word_of("ADD R0, R3") == 0x3000 | (3 << 8)
    assert word_of("SUB R2, R1") == 0x4000 | (2 << 10) | (1 << 8)
    assert word_of("AND R3, R0") == 0x5000 | (3 << 10)
    assert word_of("OR R0, R0") == 0x6000
    assert word_of("XOR R1, R2") == 0x7000 | (1 << 10) | (2 << 8)

def test_shf():
    # SHF Rd, dir: opcode 1000, direction bit in Rs[0] (0=right, 1=left).
    assert word_of("SHF R2, LEFT") == 0x8000 | (2 << 10) | (1 << 8)
    assert word_of("SHF R2, RIGHT") == 0x8000 | (2 << 10)

def test_in():
    # IN Rd, port: opcode 1001, register [11:10], port code [9:8]
    # (DR 0001 port table: ui_in=00, uio_in=01, uo_out=10, uio_out=11).
    assert word_of("IN R0, UI_IN") == 0x9000
    assert word_of("IN R1, UIO_IN") == 0x9000 | (1 << 10) | (1 << 8)
    assert word_of("IN R3, UI_IN") == 0x9000 | (3 << 10)

def test_out():
    # OUT port, Rs: opcode 1010, port in [9:8] (the I/O-ops slot of DR
    # 0001's encoding diagram), source register in [11:10].
    assert word_of("OUT UO_OUT, R0") == 0xA000 | (2 << 8)
    assert word_of("OUT UIO_OUT, R3") == 0xA000 | (3 << 10) | (3 << 8)
    assert word_of("OUT UO_OUT, R2") == 0xA000 | (2 << 10) | (2 << 8)

def test_wait():
    # WAIT imm8: opcode 1011, imm8 in [7:0], stalls imm8+1 cycles.
    assert word_of("WAIT 0") == 0xB000
    assert word_of("WAIT 255") == 0xB0FF
    assert word_of("WAIT 0x10") == 0xB010

def test_branches():
    # JMP/BZ/BNZ imm8: opcodes 1100/1101/1110, absolute 8-bit target.
    assert word_of("JMP 0x42") == 0xC042
    assert word_of("BZ 7") == 0xD007
    assert word_of("BNZ 0xFF") == 0xE0FF

def test_halt():
    assert word_of("HALT") == 0xF000

def test_case_insensitive_mnemonics_and_operands():
    assert word_of("ldi r2, 5") == word_of("LDI R2, 5")
    assert word_of("out uo_out, r1") == word_of("OUT UO_OUT, R1")
    assert word_of("shf r0, left") == word_of("SHF R0, LEFT")


# --- labels, addresses, size limits ----------------------------------------

def test_label_resolution_absolute():
    p = one(
        "        NOP\n"
        "top:    LDI R0, 1\n"
        "        BZ top\n"
        "        JMP end\n"
        "end:    HALT\n"
    )
    assert p.words[2] == 0xD001, "BZ top must encode absolute address 1"
    assert p.words[3] == 0xC004, "JMP end must encode absolute address 4"

def test_forward_reference():
    p = one("        JMP skip\n        NOP\nskip:    HALT\n")
    assert p.words[0] == 0xC002

def test_program_size_limit():
    ok = one("\n".join(["NOP"] * 256))
    assert len(ok.words) == 256
    expect_error("\n".join(["NOP"] * 257), "256-word", "too_long")


# --- cycle accounting (DR 0001's timing model) ------------------------------

def test_wait_cycle_costs():
    p = one("WAIT 0\nWAIT 9\nWAIT 255\n")
    assert [i.cycles for i in p.instructions] == [1, 10, 256]

def test_all_other_ops_one_cycle():
    src = (
        "LDI R0, 1\nLDI R1, 2\nMOV R0, R1\nADD R0, R1\nSUB R0, R1\n"
        "AND R0, R1\nOR R0, R1\nXOR R0, R1\nSHF R0, LEFT\nSHF R0, RIGHT\n"
        "IN R2, UI_IN\nOUT UO_OUT, R0\nJMP 0\nBZ 0\nBNZ 0\nNOP\nHALT\n"
    )
    p = one(src)
    assert all(i.cycles == 1 for i in p.instructions)
    assert p.total_cycles == len(p.instructions) == 17

def test_cyclesec_exact_cycles():
    p = one(
        "NOP\n"
        ".cyclesec banner\n"
        "LDI R0, 0xA5\n"
        "OUT UO_OUT, R0\n"
        "WAIT 3\n"
        "LDI R0, 0x5A\n"
        "OUT UO_OUT, R0\n"
        ".endcyclesec\n"
        "HALT\n"
    )
    assert len(p.sections) == 1
    sec = p.sections[0]
    assert (sec.start_addr, sec.end_addr) == (1, 5)
    assert sec.cycles == 1 + 1 + 4 + 1 + 1, "exact entry->exit straight-line cost"
    assert sec.has_branch is False

def test_cyclesec_flags_branches():
    p = one(
        ".cyclesec loop\n"
        "top: SUB R0, R1\n"
        "     BZ done\n"
        "     JMP top\n"
        "done: NOP\n"
        ".endcyclesec\n"
    )
    assert p.sections[0].has_branch is True

def test_report_is_deterministic_and_greppable():
    src = "LDI R0, 1\nHALT\n"
    a = asm.render_cycles_report(one(src, "x.asm"))
    b = asm.render_cycles_report(one(src, "x.asm"))
    assert a == b, "committed artifact must be byte-reproducible"
    assert "WORDS 2" in a
    assert "TOTAL-CYCLES 2" in a
    assert "ADDR 0x00 WORD 0x1001 LDI R0, 0x01 cycles=1" in a
    assert "ADDR 0x01 WORD 0xF000 HALT cycles=1" in a

def test_hex_rendering():
    assert asm.render_hex(one("NOP\nHALT\n")) == "0000\nF000\n"


# --- the data-dependent-latency lint (DR 0001 'Timing model') ----------------

def test_lint_warns_on_pin_data_conditional_branch():
    p = one(
        "top: IN R0, UI_IN\n"
        "     LDI R1, 1\n"
        "     SUB R0, R1\n"
        "     BNZ top\n"
        "     HALT\n"
    )
    assert len(p.warnings) == 1, "BNZ over IN-derived flags must warn once"
    assert "data-dependent-latency" in p.warnings[0]

def test_lint_silent_on_constant_loop():
    p = one(
        "     LDI R0, 8\n"
        "     LDI R1, 1\n"
        "top: SUB R0, R1\n"
        "     BNZ top\n"
        "     HALT\n"
    )
    assert p.warnings == [], "assemble-time-constant trip count is DR 0001's blessed loop"

def test_lint_ldi_clears_taint():
    p = one(
        "     IN R0, UI_IN\n"
        "     LDI R0, 4\n"
        "     LDI R1, 1\n"
        "top: SUB R0, R1\n"
        "     BNZ top\n"
        "     HALT\n"
    )
    assert p.warnings == [], "LDI overwrites the sampled value; taint must clear"

def test_lint_mov_propagates_taint():
    p = one(
        "     IN R0, UI_IN\n"
        "     MOV R2, R0\n"
        "     LDI R1, 1\n"
        "     SUB R2, R1\n"
        "     BZ done\n"
        "done: HALT\n"
    )
    assert len(p.warnings) == 1, "taint flows through MOV"

def test_lint_shf_does_not_launder_tainted_flag():
    # SHF writes C only, never Z (rtl/protocol_core.v OP_SHF block; DR 0001
    # opcode table: "shifted-out bit -> C"), so it cannot supply -- or
    # displace -- the Z flag BZ/BNZ read. A shift between a tainted ALU op
    # and a conditional branch must not erase the governing-flag record.
    p = one(
        "     IN R0, UI_IN\n"
        "     LDI R1, 1\n"
        "top: SUB R0, R1\n"
        "     SHF R2, LEFT\n"
        "     BNZ top\n"
        "     HALT\n"
    )
    assert len(p.warnings) == 1, "SHF must not launder a tainted Z flag"
    assert "data-dependent-latency" in p.warnings[0]


# --- malformed input (each must raise AsmError with a line number) -----------

def test_unknown_mnemonic():
    expect_error("FOO R0, 1", "unknown mnemonic", "bad_mnemonic")

def test_bad_register():
    expect_error("LDI R4, 1", "R0-R3", "bad_reg")
    expect_error("MOV R0, X1", "R0-R3", "bad_reg2")

def test_imm_range():
    expect_error("LDI R0, 256", "out of range", "imm_hi")
    expect_error("LDI R0, -1", "negative", "imm_neg")
    expect_error("WAIT 0x1FF", "out of range", "imm_hex_hi")

def test_bad_arity():
    expect_error("LDI R0", "takes 2 operand", "arity1")
    expect_error("NOP R0", "takes 0 operand", "arity2")
    expect_error("HALT 3", "takes 0 operand", "arity3")
    expect_error("JMP", "takes 1 operand", "arity4")
    expect_error("IN R0", "takes 2 operand", "arity5")

def test_bad_port_and_direction():
    expect_error("IN R0, NOPE", "bad port", "bad_port")
    expect_error("SHF R0, UP", "LEFT/RIGHT", "bad_dir")

def test_io_direction_bugs():
    # DR 0001: IN to a write-only port / OUT to a read-only port is a
    # firmware bug the assembler must flag (hardware defines it a no-op).
    expect_error("IN R0, UO_OUT", "write-only", "in_wo")
    expect_error("IN R0, UIO_OUT", "write-only", "in_wo2")
    expect_error("OUT UI_IN, R0", "read-only", "out_ro")
    expect_error("OUT UIO_IN, R0", "read-only", "out_ro2")

def test_io_direction_errors_survive_allow_reserved():
    # Issue #135: --allow-reserved is about control indices only. OUT to
    # port 01 / IN from port 11 stay errors with it, and plain OUT/IN to
    # the two control encodings point at WCTL/RCTL instead of assembling.
    for src, needle in (
        ("OUT UIO_IN, R0", "read-only"),
        ("IN R0, UIO_OUT", "write-only"),
        ("OUT UI_IN, R0", "WCTL"),
        ("IN R0, UO_OUT", "RCTL"),
    ):
        try:
            asm.assemble_text(src, allow_reserved=True)
        except asm.AsmError as err:
            assert needle in err.message, (src, err.message)
        else:
            raise AssertionError(f"{src!r} assembled under --allow-reserved")


# --- DR 0012 control space (issue #135) ------------------------------------
# Expected words are hand-derived from DR 0012 section 1: WCTL k, Rs is
# OUT (opcode 1010) to port 00 with imm8 = k and Rs in [11:10]; RCTL Rd, k
# is IN (opcode 1001) from port 10 with imm8 = k and Rd in [11:10].

DR0012_MAP = {  # name: (k, W cycles or None, R cycles or None) -- DR 0012 section 2
    "UIO_DIR": (0x00, 1, 1), "UIO_OD": (0x01, 1, 1), "PM_ADDR": (0x02, 1, 1),
    "PM_DATA_HI": (0x03, 1, 2), "PM_DATA_LO": (0x04, 2, 1), "RUN": (0x05, 2, None),
    "PM_CRC_LO": (0x06, 1, 1), "PM_CRC_HI": (0x07, 1, 1),
    "BOOT_STATUS": (0x08, None, 1), "HW_ID": (0x09, None, 1),
}

def test_wctl_encoding():
    assert word_of("WCTL UIO_OD, R3") == 0xA000 | (3 << 10) | 0x01   # 0xAC01
    assert word_of("WCTL UIO_DIR, R0") == 0xA000
    assert word_of("WCTL PM_DATA_LO, R2") == 0xA000 | (2 << 10) | 0x04
    assert word_of("WCTL RUN, R1") == 0xA000 | (1 << 10) | 0x05
    assert word_of("wctl 0x02, r1") == 0xA000 | (1 << 10) | 0x02     # numeric k, any case
    for name, (k, wcyc, _r) in DR0012_MAP.items():
        if wcyc is not None:
            assert word_of(f"WCTL {name}, R1") == 0xA400 | k, name

def test_rctl_encoding():
    assert word_of("RCTL R0, HW_ID") == 0x9000 | (0b10 << 8) | 0x09  # 0x9209
    assert word_of("RCTL R3, PM_DATA_HI") == 0x9000 | (3 << 10) | (0b10 << 8) | 0x03
    assert word_of("rctl r2, 8") == 0x9000 | (2 << 10) | (0b10 << 8) | 0x08
    for name, (k, _w, rcyc) in DR0012_MAP.items():
        if rcyc is not None:
            assert word_of(f"RCTL R1, {name}") == 0x9600 | k, name

def test_ctl_cycle_costs_follow_dr0012_table():
    for name, (_k, wcyc, rcyc) in DR0012_MAP.items():
        if wcyc is not None:
            assert one(f"WCTL {name}, R0").instructions[0].cycles == wcyc, name
        if rcyc is not None:
            assert one(f"RCTL R0, {name}").instructions[0].cycles == rcyc, name
    # The table's 2-cycle entries, by name, so a silent table edit fails here.
    two = {(m, n) for m, n in (("WCTL", "PM_DATA_LO"), ("WCTL", "RUN"), ("RCTL", "PM_DATA_HI"))}
    got = set()
    for name, (_k, wcyc, rcyc) in DR0012_MAP.items():
        if wcyc == 2:
            got.add(("WCTL", name))
        if rcyc == 2:
            got.add(("RCTL", name))
    assert got == two
    # A cycle section sums them, and WCTL RUN counts as a control transfer.
    p = one(".cyclesec s\nWCTL PM_DATA_HI, R0\nWCTL PM_DATA_LO, R1\nRCTL R2, PM_DATA_HI\n"
            "RCTL R3, PM_DATA_LO\n.endcyclesec\n.cyclesec j\nWCTL RUN, R0\n.endcyclesec\n")
    assert p.sections[0].cycles == 1 + 2 + 2 + 1 and not p.sections[0].has_branch
    assert p.sections[1].cycles == 2 and p.sections[1].has_branch
    assert p.total_cycles == 8

def test_ctl_reserved_indices_are_errors_without_flag():
    expect_error("WCTL 0x10, R0", "reserved", "w_res")
    expect_error("RCTL R0, 0x1F", "reserved", "r_res")
    expect_error("WCTL 0x0A, R0", "reserved", "w_res2")
    expect_error("RCTL R0, 255", "reserved", "r_res3")
    expect_error("WCTL BOOT_STATUS, R0", "read-only", "w_ro")
    expect_error("WCTL HW_ID, R0", "read-only", "w_ro2")
    expect_error("WCTL 0x09, R0", "read-only", "w_ro_numeric")
    expect_error("RCTL R0, RUN", "write-only", "r_wo")
    expect_error("WCTL NOPE, R0", "bad control register", "bad_name")
    expect_error("WCTL UIO_DIR, R4", "bad register", "bad_reg")
    expect_error("RCTL UIO_DIR, R0", "bad register", "swapped")
    expect_error("WCTL UIO_DIR", "takes 2 operand", "arity")
    expect_error("WCTL 256, R0", "out of range", "k_range")

def test_ctl_allow_reserved_assembles_them_as_one_cycle():
    def w(src):
        return asm.assemble_text(src, allow_reserved=True).instructions[0]
    assert (w("WCTL 0x10, R1").word, w("WCTL 0x10, R1").cycles) == (0xA410, 1)
    assert (w("RCTL R1, 0xFF").word, w("RCTL R1, 0xFF").cycles) == (0x96FF, 1)
    assert (w("WCTL HW_ID, R0").word, w("WCTL HW_ID, R0").cycles) == (0xA009, 1)
    assert (w("RCTL R0, RUN").word, w("RCTL R0, RUN").cycles) == (0x9205, 1)

def test_ctl_lint_rctl_is_not_pin_data():
    # A status register is not a pin: branching on one is not the
    # data-dependent-latency hazard the lint exists for, and an RCTL of
    # one into a previously IN-tainted register clears the taint (like
    # LDI). Writable control state is a different matter: the tests below.
    p = one("IN R0, UI_IN\nRCTL R0, BOOT_STATUS\nLDI R1, 1\nAND R0, R1\nBZ 0\n")
    assert p.warnings == []

# Control-space taint (asm.py, "control-space taint"): each case is the
# shortest program that reads one class of control state and branches on it.
BRANCH_ON_R1 = "LDI R2, 1\nAND R1, R2\nBZ done\ndone: HALT\n"

def warns(src):
    p = one(src)
    assert all("data-dependent-latency" in w for w in p.warnings)
    return len(p.warnings)

def test_ctl_lint_taint_survives_wctl_rctl_roundtrip():
    # The Judge's repro on PR #160: PM_ADDR reads back the stored byte
    # unchanged (rtl/protocol_core.v rctl_val), so this is `MOV R1, R0`
    # with extra steps and must warn exactly as the MOV version does.
    roundtrip = (
        "loop:\nIN R0, UI_IN\nWCTL PM_ADDR, R0\nRCTL R1, PM_ADDR\n"
        "LDI R2, 1\nAND R1, R2\nBZ loop\n"
    )
    mov = "loop:\nIN R0, UI_IN\nMOV R1, R0\nLDI R2, 1\nAND R1, R2\nBZ loop\n"
    assert warns(mov) == 1
    assert warns(roundtrip) == 1, "WCTL/RCTL must not launder IN taint"
    for reg in ("UIO_DIR", "UIO_OD", "PM_ADDR"):
        src = f"IN R0, UI_IN\nWCTL {reg}, R0\nRCTL R1, {reg}\n" + BRANCH_ON_R1
        assert warns(src) == 1, f"{reg} stores what was written"

def test_ctl_lint_constant_write_readback_is_clean():
    for reg in ("UIO_DIR", "UIO_OD", "PM_ADDR"):
        src = f"LDI R0, 0x0F\nWCTL {reg}, R0\nRCTL R1, {reg}\n" + BRANCH_ON_R1
        assert warns(src) == 0, f"constant written to {reg} reads back constant"
    # A constant rewrite clears an earlier tainted write, per index:
    # PM_ADDR is rewritten, UIO_DIR is not.
    both = "IN R0, UI_IN\nWCTL PM_ADDR, R0\nWCTL UIO_DIR, R0\nLDI R0, 3\nWCTL PM_ADDR, R0\n"
    assert warns(both + "RCTL R1, PM_ADDR\n" + BRANCH_ON_R1) == 0
    assert warns(both + "RCTL R1, UIO_DIR\n" + BRANCH_ON_R1) == 1
    # Reset values are constants too: straight-line from entry is clean.
    assert warns("RCTL R1, UIO_DIR\n" + BRANCH_ON_R1) == 0
    # PM_DATA_LO's PM_ADDR post-increment neither adds nor removes taint.
    inc = "LDI R0, 1\nWCTL PM_ADDR, R0\nWCTL PM_DATA_LO, R0\nRCTL R1, PM_ADDR\n"
    assert warns(inc + BRANCH_ON_R1) == 0

def test_ctl_lint_unknown_provenance_is_tainted():
    # Stored state reached across a label, a numeric branch target or an
    # unconditional transfer could have been written anywhere.
    assert warns("top: RCTL R1, PM_ADDR\nLDI R2, 1\nAND R1, R2\nBZ top\n") == 1
    assert warns("RCTL R1, PM_ADDR\nLDI R2, 1\nAND R1, R2\nBZ 0\n") == 1
    assert warns("JMP 1\nRCTL R1, UIO_OD\n" + BRANCH_ON_R1) == 1
    assert warns("HALT\nRCTL R1, UIO_OD\n" + BRANCH_ON_R1) == 1
    # ...until the program rewrites it on the straight-line path.
    assert warns("top: LDI R0, 0\nWCTL PM_ADDR, R0\nRCTL R1, PM_ADDR\n"
                 "LDI R2, 1\nAND R1, R2\nBZ top\n") == 0
    # WCTL RUN can land anywhere, so a program with one never has known
    # stored state at an unwritten index -- even before the RUN.
    run = "RCTL R1, PM_ADDR\nLDI R2, 1\nAND R1, R2\nBZ 5\nLDI R0, 0\nWCTL RUN, R0\n"
    assert warns(run) == 1

def test_ctl_lint_run_landing_after_rewrite_is_tainted():
    # A RUN can land between a pin-derived rewrite and a later readback:
    # the rewrite does not make the state clean at an address the RUN can
    # reach. Without the RUN the same code is straight-line and clean.
    body = ("LDI R0, 0\nWCTL UIO_DIR, R0\nRCTL R1, UIO_DIR\nLDI R2, 1\nAND R1, R2\n"
            "BZ 8\nHALT\nNOP\nIN R0, UI_IN\nWCTL UIO_DIR, R0\nLDI R3, 2\n")
    assert warns(body + "WCTL RUN, R3\n") >= 1
    assert warns(body) == 0

def test_ctl_lint_pm_data_reads_are_always_tainted():
    # RCTL PM_DATA_HI returns PM[PM_ADDR][15:8] and latches the low byte
    # for RCTL PM_DATA_LO (protocol_core.v stall_pmrd); neither reads back
    # the WCTL PM_DATA_HI latch. Program-memory contents have no
    # provenance the assembler can establish, constant writes included.
    const = "LDI R0, 0\nWCTL PM_ADDR, R0\nWCTL PM_DATA_HI, R0\nWCTL PM_DATA_LO, R0\nWCTL PM_ADDR, R0\n"
    assert warns(const + "RCTL R1, PM_DATA_HI\n" + BRANCH_ON_R1) == 1
    assert warns(const + "RCTL R3, PM_DATA_HI\nRCTL R1, PM_DATA_LO\n" + BRANCH_ON_R1) == 1
    assert warns("RCTL R1, PM_DATA_LO\n" + BRANCH_ON_R1) == 1

def test_ctl_lint_crc_follows_committed_words():
    crc_branch = "RCTL R1, PM_CRC_LO\n" + BRANCH_ON_R1
    # Clean from reset, and after constant commits.
    assert warns(crc_branch) == 0
    const = "LDI R0, 7\nWCTL PM_DATA_HI, R0\nWCTL PM_DATA_LO, R0\n"
    assert warns(const + crc_branch) == 0
    assert warns(const + "RCTL R1, PM_CRC_HI\n" + BRANCH_ON_R1) == 0
    # A tainted low byte taints the sum; both halves read tainted.
    lo = "IN R0, UI_IN\nWCTL PM_DATA_LO, R0\n"
    assert warns(lo + crc_branch) == 1
    assert warns(lo + "RCTL R1, PM_CRC_HI\n" + BRANCH_ON_R1) == 1
    # So does a tainted high-byte latch, committed by a constant low byte.
    hi = "IN R0, UI_IN\nWCTL PM_DATA_HI, R0\nLDI R0, 0\nWCTL PM_DATA_LO, R0\n"
    assert warns(hi + crc_branch) == 1
    # A later constant commit folds into the tainted sum: still tainted.
    assert warns(lo + const + crc_branch) == 1
    # WCTL to either CRC index clears it whatever the register holds
    # (pm_crc_clr ignores the data), so a tainted Rs still clears.
    assert warns(lo + "WCTL PM_CRC_HI, R0\n" + crc_branch) == 0
    assert warns(lo + "LDI R3, 0\nWCTL PM_CRC_LO, R3\n" + crc_branch) == 0
    # The CRC covers data, not the address.
    addr = "IN R0, UI_IN\nWCTL PM_ADDR, R0\n" + const
    assert warns(addr + crc_branch) == 0
    # Unknown across a merge until cleared.
    assert warns("top: RCTL R1, PM_CRC_LO\nLDI R2, 1\nAND R1, R2\nBZ top\n") == 1

def test_ctl_lint_status_and_constant_reads_stay_clean():
    # Never tainted, wherever they are read: after tainted writes, across
    # a merge, in a program with a RUN, and into an IN-tainted register.
    dirty = "top: IN R0, UI_IN\nWCTL PM_ADDR, R0\nWCTL PM_DATA_LO, R0\n"
    for reg in ("HW_ID", "BOOT_STATUS"):
        tail = f"MOV R1, R0\nRCTL R1, {reg}\nLDI R2, 1\nAND R1, R2\nBZ top\n"
        assert warns(dirty + tail) == 0, f"{reg} is not stored program data"
        assert warns(dirty + tail + "WCTL RUN, R2\n") == 0
    # Write-only RUN and unassigned indices read a constant 0x00.
    for reg in ("RUN", "0x10"):
        p = asm.assemble_text(dirty + f"RCTL R1, {reg}\n" + BRANCH_ON_R1,
                              allow_reserved=True)
        assert p.warnings == []

def test_ctl_mnemonics_are_not_new_opcodes():
    # DR 0012 adds no opcode: DR 0001's table stays exactly 16.
    assert len(asm.OPCODES) == 16 and not (set(asm.CTL_MNEMONICS) & set(asm.OPCODES))
    assert {n: (e[0], e[3] if e[1] else None, e[4] if e[2] else None)
            for n, e in asm.CTL_REGS.items()} == DR0012_MAP

def test_cli_allow_reserved_flag():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "r.asm"
        src.write_text("WCTL 0x10, R0\nHALT\n", encoding="utf-8")
        assert asm.main([str(src), "--out-dir", tmp]) == 1
        assert not (Path(tmp) / "r.hex").exists()
        assert asm.main([str(src), "--out-dir", tmp, "--allow-reserved"]) == 0
        assert (Path(tmp) / "r.hex").read_text() == "A010\nF000\n"


def test_label_errors():
    expect_error("JMP nowhere", "undefined label", "undef_label")
    expect_error("x: NOP\nx: NOP\n", "duplicate label", "dup_label")

def test_directive_errors():
    expect_error(".cyclesec a\n.cyclesec b\nNOP\n.endcyclesec\nNOP\n.endcyclesec\n",
                 "inside another", "nested")
    expect_error(".cyclesec a\nNOP\n", "never closed", "unclosed")
    expect_error("NOP\n.endcyclesec\n", "no open", "stray_end")
    expect_error(".cyclesec a\n.endcyclesec\nNOP\n", "is empty", "empty_sec")
    expect_error(".frobnicate\n", "unknown directive", "bad_directive")

def test_error_carries_line_number():
    err = None
    try:
        one("NOP\nNOP\nFOO\n")
    except asm.AsmError as e:
        err = e
    assert err is not None and err.line_no == 3


# --- the committed demo program + artifacts ----------------------------------

DEMO_SRC = SCRIPT_DIR.parent / "asm" / "demo_roundtrip.asm"
BUILD_DIR = SCRIPT_DIR.parent / "build"


def test_demo_program_assembles_and_covers_all_opcodes():
    p = asm.assemble_file(DEMO_SRC)
    assert set(i.mnemonic for i in p.instructions) == set(asm.OPCODES), (
        "the round-trip demo exists to exercise all 16 DR 0001 mnemonics"
    )
    assert p.warnings == [], "committed demo program must be lint-clean"
    assert len(p.words) <= 256


def test_committed_artifacts_match_source():
    p = asm.assemble_file(DEMO_SRC)
    drift = asm.check_against(p, BUILD_DIR)
    assert drift == [], f"committed firmware/build/ artifacts drifted: {drift}"


ALL_TESTS = [
    test_nop, test_ldi, test_mov_rr_ops, test_shf, test_in, test_out,
    test_wait, test_branches, test_halt, test_case_insensitive_mnemonics_and_operands,
    test_label_resolution_absolute, test_forward_reference, test_program_size_limit,
    test_wait_cycle_costs, test_all_other_ops_one_cycle, test_cyclesec_exact_cycles,
    test_cyclesec_flags_branches, test_report_is_deterministic_and_greppable,
    test_hex_rendering,
    test_lint_warns_on_pin_data_conditional_branch,
    test_lint_silent_on_constant_loop,
    test_lint_ldi_clears_taint, test_lint_mov_propagates_taint,
    test_lint_shf_does_not_launder_tainted_flag,
    test_unknown_mnemonic, test_bad_register, test_imm_range, test_bad_arity,
    test_bad_port_and_direction, test_io_direction_bugs,
    test_io_direction_errors_survive_allow_reserved,
    test_wctl_encoding, test_rctl_encoding,
    test_ctl_cycle_costs_follow_dr0012_table,
    test_ctl_reserved_indices_are_errors_without_flag,
    test_ctl_allow_reserved_assembles_them_as_one_cycle,
    test_ctl_lint_rctl_is_not_pin_data,
    test_ctl_lint_taint_survives_wctl_rctl_roundtrip,
    test_ctl_lint_constant_write_readback_is_clean,
    test_ctl_lint_unknown_provenance_is_tainted,
    test_ctl_lint_run_landing_after_rewrite_is_tainted,
    test_ctl_lint_pm_data_reads_are_always_tainted,
    test_ctl_lint_crc_follows_committed_words,
    test_ctl_lint_status_and_constant_reads_stay_clean,
    test_ctl_mnemonics_are_not_new_opcodes,
    test_cli_allow_reserved_flag, test_label_errors,
    test_directive_errors, test_error_carries_line_number,
    test_demo_program_assembles_and_covers_all_opcodes,
    test_committed_artifacts_match_source,
]


def main() -> int:
    # The demo-program tests need the committed tree; run everything from
    # the repo layout this file lives in, per the convention of
    # verification/test_check_records.py (self-managed, exit-code contract).
    for fn in ALL_TESTS:
        check(fn.__name__, fn)
    if FAILURES:
        print(f"\n{len(FAILURES)} test(s) failed: {', '.join(FAILURES)}")
        return 1
    print(f"\nall {len(ALL_TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
