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
    test_unknown_mnemonic, test_bad_register, test_imm_range, test_bad_arity,
    test_bad_port_and_direction, test_io_direction_bugs, test_label_errors,
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
