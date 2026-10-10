#!/usr/bin/env python3
"""Simulator-free unit tests for the ISA reference model
(`reference_models/isa.py`) and the lockstep generator
(`isa_lockstep_gen.py`) -- issue #152.

Every expected value below is computed by hand from the DR 0001 opcode
table and the DR 0012 register map, not read off the RTL or the model.  A
row index is a clock-edge number: `rows[0]` is the freshly reset machine,
`rows[1]` is the fetch-priming edge, and a one-cycle instruction at
program position n retires in `rows[2 + n]`.

Run directly (`python3 verification/test_isa_model.py`) or under pytest.
No simulator is involved.
"""

import binascii
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from reference_models import isa  # noqa: E402
import isa_lockstep_gen as gen  # noqa: E402

REQUEST = HERE / "request-isa-lockstep.json"


def enc(mn, **kw):
    return isa.encode(mn, **kw)


def rows_of(words, edges, ui=0, uio=0):
    """Run `words` for exactly `edges` edges with constant pin inputs."""
    m = isa.Machine(words)
    rows = [m.row]
    for _ in range(edges):
        rows.append(m.step(ui, uio))
    return rows, m


# --------------------------------------------------------------------------
# Table and encoding
# --------------------------------------------------------------------------
def test_sixteen_opcodes_exactly_filled():
    assert [o.code for o in isa.OPCODES] == list(range(16))
    names = [o.mnemonic for o in isa.OPCODES]
    assert names == ["NOP", "LDI", "MOV", "ADD", "SUB", "AND", "OR", "XOR",
                     "SHF", "IN", "OUT", "WAIT", "JMP", "BZ", "BNZ", "HALT"]


def test_encodings_by_hand():
    # [15:12] op, [11:10] Rd, [9:8] Rs/port, [7:0] imm8
    assert enc("LDI", rd=2, imm=0xA5) == 0b0001_10_00_10100101
    assert enc("ADD", rd=1, rs=3) == 0b0011_01_11_00000000
    assert enc("SHF", rd=3, rs=1) == 0b1000_11_01_00000000
    assert enc("IN", rd=1, port=1) == 0b1001_01_01_00000000
    assert enc("OUT", rd=2, port=3) == 0b1010_10_11_00000000   # source register rides [11:10]
    assert enc("WAIT", imm=255) == 0xB0FF
    assert enc("HALT") == 0xF000
    assert isa.wctl(0x04, 1) == 0b1010_01_00_00000100          # OUT port 00, imm8 = k
    assert isa.rctl(3, 0x03) == 0b1001_11_10_00000011          # IN port 10, imm8 = k


def test_static_costs_by_hand():
    assert isa.static_cost(enc("NOP")) == 1
    assert isa.static_cost(enc("WAIT", imm=0)) == 1
    assert isa.static_cost(enc("WAIT", imm=255)) == 256
    assert isa.static_cost(isa.wctl(0x04, 0)) == 2   # PM_DATA_LO write
    assert isa.static_cost(isa.wctl(0x05, 0)) == 2   # RUN
    assert isa.static_cost(isa.rctl(0, 0x03)) == 2   # PM_DATA_HI read
    for k in (0x00, 0x01, 0x02, 0x06, 0x07, 0x08, 0x09, 0x0A, 0xFF):
        assert isa.static_cost(isa.wctl(k, 0)) == 1
    for k in (0x00, 0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0xFF):
        assert isa.static_cost(isa.rctl(0, k)) == 1
    assert isa.static_cost(enc("OUT", rd=0, port=1, imm=0x04)) == 1   # reserved no-op ignores imm8
    assert isa.static_cost(enc("IN", rd=0, port=3, imm=0x03)) == 1


# --------------------------------------------------------------------------
# Run-phase entry, ALU, flags
# --------------------------------------------------------------------------
def test_entry_edge_and_ldi():
    rows, _ = rows_of([enc("LDI", rd=1, imm=0x80), enc("HALT")], 3)
    assert rows[0] == rows[1]                       # edge 1 only primes the fetch
    assert rows[1].pc == 0 and rows[1].regs == (0, 0, 0, 0)
    assert rows[2].pc == 1 and rows[2].regs == (0, 0x80, 0, 0)


def test_add_carry_and_zero():
    prog = [enc("LDI", rd=0, imm=0xF0), enc("LDI", rd=1, imm=0x20), enc("ADD", rd=0, rs=1),
            enc("LDI", rd=2, imm=0x80), enc("ADD", rd=2, rs=2), enc("HALT")]
    rows, _ = rows_of(prog, 7)
    assert rows[4].regs[0] == 0x10 and rows[4].c == 1 and rows[4].z == 0   # 0xF0 + 0x20 = 0x110
    assert rows[6].regs[2] == 0x00 and rows[6].c == 1 and rows[6].z == 1   # 0x80 + 0x80 = 0x100


def test_add_no_carry():
    prog = [enc("LDI", rd=0, imm=0x01), enc("LDI", rd=1, imm=0x02), enc("ADD", rd=0, rs=1)]
    rows, _ = rows_of(prog, 4)
    assert rows[4].regs[0] == 3 and rows[4].c == 0 and rows[4].z == 0


def test_sub_values_and_borrow_pin():
    # 3 - 5 = 0xFE (borrow); 5 - 5 = 0 (no borrow, Z); 7 - 5 = 2 (no borrow).
    # The C POLARITY is left open by DR 0001; DR 0016 Ruling 1 (Proposed) rules it a borrow.
    assert isa.SUB_C_POLARITY == "borrow"
    prog = [enc("LDI", rd=0, imm=3), enc("LDI", rd=1, imm=5), enc("SUB", rd=0, rs=1),
            enc("LDI", rd=0, imm=5), enc("SUB", rd=0, rs=1),
            enc("LDI", rd=0, imm=7), enc("SUB", rd=0, rs=1)]
    rows, m = rows_of(prog, 8)
    assert (rows[4].regs[0], rows[4].z, rows[4].c) == (0xFE, 0, 1)
    assert (rows[6].regs[0], rows[6].z, rows[6].c) == (0x00, 1, 0)
    assert (rows[8].regs[0], rows[8].z, rows[8].c) == (0x02, 0, 0)
    assert m.c_src == "sub"        # the bench labels C mismatches from SUB with DR 0016 Ruling 1


def test_logic_ops_set_z_leave_c():
    prog = [enc("LDI", rd=0, imm=0xFF), enc("LDI", rd=1, imm=0x01), enc("ADD", rd=0, rs=1),  # C=1, Z=1
            enc("LDI", rd=2, imm=0xF0), enc("LDI", rd=3, imm=0x0F),
            enc("AND", rd=2, rs=3),                                                           # 0, Z=1
            enc("LDI", rd=2, imm=0xF0), enc("OR", rd=2, rs=3),                                # 0xFF, Z=0
            enc("XOR", rd=2, rs=2)]                                                           # 0, Z=1
    rows, _ = rows_of(prog, 10)
    assert rows[4].c == 1 and rows[4].z == 1
    assert rows[7].regs[2] == 0 and rows[7].z == 1 and rows[7].c == 1     # AND: C unchanged
    assert rows[9].regs[2] == 0xFF and rows[9].z == 0 and rows[9].c == 1  # OR
    assert rows[10].regs[2] == 0 and rows[10].z == 1 and rows[10].c == 1  # XOR


def test_shf_directions_and_carry():
    prog = [enc("LDI", rd=0, imm=0x81), enc("SHF", rd=0, rs=1),   # left: 0x02, C=1 (old bit 7)
            enc("SHF", rd=0, rs=0),                              # right: 0x01, C=0 (old bit 0)
            enc("SHF", rd=0, rs=0)]                              # right: 0x00, C=1
    rows, _ = rows_of(prog, 5)
    assert (rows[3].regs[0], rows[3].c) == (0x02, 1)
    assert (rows[4].regs[0], rows[4].c) == (0x01, 0)
    assert (rows[5].regs[0], rows[5].c) == (0x00, 1)
    assert rows[5].z == 0            # SHF does not write Z (DR 0001 table; DR 0016 Ruling 2, 'shf-z')


def test_mov():
    rows, _ = rows_of([enc("LDI", rd=3, imm=0x5C), enc("MOV", rd=0, rs=3)], 3)
    assert rows[3].regs == (0x5C, 0, 0, 0x5C)


# --------------------------------------------------------------------------
# Ports
# --------------------------------------------------------------------------
def test_in_out_all_four_ports():
    prog = [enc("IN", rd=0, port=0), enc("IN", rd=1, port=1),
            enc("IN", rd=2, port=3, imm=0x77),                    # reserved no-op: R2 unchanged
            enc("OUT", rd=0, port=2), enc("OUT", rd=1, port=3),
            enc("OUT", rd=0, port=1, imm=0x33)]                   # reserved no-op: no pin moves
    rows, _ = rows_of(prog, 7, ui=0xA5, uio=0x3C)
    assert rows[2].regs[0] == 0xA5 and rows[3].regs[1] == 0x3C
    assert rows[4].regs[2] == 0x00 and rows[4].pc == 3
    assert rows[5].uo_out == 0xA5 and rows[5].uio_out == 0     # OUT shows on the retiring edge's row
    assert rows[6].uio_out == 0x3C
    assert rows[7].uo_out == 0xA5 and rows[7].uio_out == 0x3C and rows[7].pc == 6


def test_in_samples_the_pins_present_on_its_edge():
    m = isa.Machine([enc("NOP"), enc("IN", rd=0, port=0)])
    m.step(0x11, 0)          # prime
    m.step(0x22, 0)          # NOP
    row = m.step(0x33, 0)    # IN retires on this edge: samples 0x33
    assert row.regs[0] == 0x33


# --------------------------------------------------------------------------
# WAIT, branches, HALT
# --------------------------------------------------------------------------
def test_wait_costs_imm_plus_one():
    rows, _ = rows_of([enc("WAIT", imm=3), enc("LDI", rd=0, imm=9)], 6)
    # edges 2..5 are the WAIT (3 + 1 = 4 cycles): pc holds until the last
    assert [r.pc for r in rows[2:6]] == [0, 0, 0, 1]
    assert rows[6].regs[0] == 9 and rows[6].pc == 2


def test_wait_zero_and_255():
    rows, _ = rows_of([enc("WAIT", imm=0), enc("HALT")], 3)
    assert rows[2].pc == 1
    prog = [enc("WAIT", imm=255), enc("HALT")]
    rows, m = rows_of(prog, 2 + 256 + 1)
    assert rows[2 + 255 - 1].pc == 0 and rows[2 + 255].pc == 1   # 256 cycles total
    assert rows[-1].halted == 1


def test_branches_taken_and_not_taken():
    # Z resets to 0: BNZ taken, BZ not taken.
    rows, _ = rows_of([enc("BNZ", imm=5)], 2)
    assert rows[2].pc == 5
    rows, _ = rows_of([enc("BZ", imm=5), enc("HALT")], 2)
    assert rows[2].pc == 1
    # Z = 1 after 1 - 1: BZ taken, BNZ not taken.
    base = [enc("LDI", rd=0, imm=1), enc("SUB", rd=0, rs=0)]
    rows, _ = rows_of(base + [enc("BZ", imm=9)], 4)
    assert rows[4].pc == 9
    rows, _ = rows_of(base + [enc("BNZ", imm=9)], 4)
    assert rows[4].pc == 3
    rows, _ = rows_of([enc("JMP", imm=200)], 2)
    assert rows[2].pc == 200


def test_halt_holds_everything():
    prog = [enc("LDI", rd=0, imm=7), enc("OUT", rd=0, port=2), enc("HALT"), enc("LDI", rd=0, imm=1)]
    rows, m = rows_of(prog, 12)
    assert rows[4].halted == 1 and rows[4].pc == 2
    for r in rows[4:]:
        assert r == rows[4]
    assert rows[4].uo_out == 7


def test_counted_loop_cycle_count():
    # LDI R1,1; LDI R0,3; top: SUB R0,R1; BNZ top; HALT.  Loop body is 2 cycles x 3.
    prog = [enc("LDI", rd=1, imm=1), enc("LDI", rd=0, imm=3), enc("SUB", rd=0, rs=1),
            enc("BNZ", imm=2), enc("HALT")]
    rows, m = isa.run(prog, lambda e: (0, 0), 100)
    assert m.events[-1].mnemonic == "HALT"
    # edge 1 primes; edges 2-3 the two LDIs; edges 4-9 are 3 x (SUB, BNZ); HALT retires on edge 10
    assert m.events[-1].edge == 10


# --------------------------------------------------------------------------
# Control space (DR 0012)
# --------------------------------------------------------------------------
def ctl_prog(*body):
    return list(body) + [enc("HALT")]


def test_rctl_one_cycle_values_and_resets():
    prog = ctl_prog(
        enc("LDI", rd=1, imm=0xEE), enc("LDI", rd=2, imm=0xEE),   # poison, so a read that does nothing shows
        isa.rctl(0, 0x00), isa.rctl(1, 0x01), isa.rctl(2, 0x02),   # reset values: all 0
        isa.rctl(3, 0x08),                                         # BOOT_STATUS = 0x01 after a serial load
        isa.rctl(0, 0x09),                                         # HW_ID = 0x01
        isa.rctl(1, 0x05),                                         # RUN is write-only: reads 0x00
        isa.rctl(2, 0x0A),                                         # unassigned: reads 0x00
    )
    rows, _ = rows_of(prog, 11)
    assert rows[10].regs == (1, 0, 0, 1)
    for k in range(2, 11):                                         # every access is exactly one cycle
        assert rows[k].pc == k - 1


def test_wctl_readback_and_noops():
    prog = ctl_prog(
        enc("LDI", rd=0, imm=0xA5), isa.wctl(0x00, 0), isa.wctl(0x01, 0), isa.wctl(0x02, 0),
        isa.wctl(0x08, 0), isa.wctl(0x09, 0), isa.wctl(0x0A, 0),     # last three: no-ops
        isa.rctl(1, 0x00), isa.rctl(2, 0x01), isa.rctl(3, 0x02), isa.rctl(0, 0x08),
    )
    rows, _ = rows_of(prog, 13)
    assert rows[12].regs == (1, 0xA5, 0xA5, 0xA5)
    assert rows[12].z == 0 and rows[12].c == 0           # no control access touches Z or C


def test_pm_write_read_roundtrip_with_fixed_stalls():
    # PM_ADDR <- 0x40; HI <- 0xBE; LO <- 0xEF (commit PM[0x40] = 0xBEEF, 2 cycles, ADDR -> 0x41);
    # PM_ADDR <- 0x40; RCTL HI (2 cycles) -> R1 = 0xBE; RCTL LO -> R2 = 0xEF, ADDR -> 0x41.
    prog = ctl_prog(
        enc("LDI", rd=0, imm=0x40), isa.wctl(0x02, 0),
        enc("LDI", rd=0, imm=0xBE), isa.wctl(0x03, 0),
        enc("LDI", rd=0, imm=0xEF), isa.wctl(0x04, 0),
        enc("LDI", rd=3, imm=0x40), isa.wctl(0x02, 3),
        isa.rctl(1, 0x03),
        isa.rctl(2, 0x04),
        isa.rctl(3, 0x02),
    )
    m = isa.Machine(prog)
    rows = [m.row] + [m.step() for _ in range(40)]
    assert m.pm[0x40] == 0xBEEF
    ev_hi = [e for e in m.events if e.mnemonic == "IN" and e.info.get("name") == "PM_DATA_HI"][0]
    assert ev_hi.cost == 2
    # the register changes only at the END of the second cycle; the PC holds in between
    assert rows[ev_hi.edge].regs[1] == 0 and rows[ev_hi.edge].pc == ev_hi.pc
    assert rows[ev_hi.edge + 1].regs[1] == 0xBE and rows[ev_hi.edge + 1].pc == ev_hi.pc + 1
    assert rows[-1].regs[2] == 0xEF and rows[-1].regs[3] == 0x41     # the LO read advanced PM_ADDR
    ev_lo = [e for e in m.events if e.mnemonic == "OUT" and e.info.get("name") == "PM_DATA_LO"][0]
    assert ev_lo.cost == 2


def test_pm_addr_wraps_and_hi_latch_survives_commit():
    prog = ctl_prog(
        enc("LDI", rd=0, imm=0xFF), isa.wctl(0x02, 0),
        enc("LDI", rd=0, imm=0x12), isa.wctl(0x03, 0),
        enc("LDI", rd=0, imm=0x34), isa.wctl(0x04, 0),   # PM[0xFF] = 0x1234, ADDR wraps to 0x00
        isa.wctl(0x04, 0),                               # PM[0x00] = 0x1234 (HI latch unchanged), ADDR = 0x01
        isa.rctl(1, 0x02),
    )
    m = isa.Machine(prog)
    for _ in range(20):
        m.step()
    assert m.pm[0xFF] == 0x1234 and m.pm[0x00] == 0x1234
    assert m.regs[1] == 0x01


def test_run_jumps_to_rs_in_two_cycles():
    prog = [enc("LDI", rd=0, imm=7), isa.wctl(0x05, 0)]
    m = isa.Machine(prog + [enc("HALT")] * 5 + [enc("LDI", rd=1, imm=0xAA), enc("HALT")])
    rows = [m.row] + [m.step() for _ in range(6)]
    assert rows[3].pc == 1               # RUN's first edge: PC holds
    assert rows[4].pc == 7               # second edge: PC <- R0
    assert rows[5].regs[1] == 0xAA       # the word at 7 executes next


def test_crc_register_tracks_every_committed_word():
    image = [enc("LDI", rd=0, imm=0x11), isa.rctl(1, 0x06), isa.rctl(2, 0x07), enc("HALT")]
    m = isa.Machine(image)
    want = binascii.crc_hqx(b"".join(w.to_bytes(2, "big") for w in image), 0)
    assert m.crc == want
    for _ in range(6):
        m.step()
    assert (m.regs[2] << 8 | m.regs[1]) == want


def test_crc_clear_from_either_register():
    for k in (0x06, 0x07):
        m = isa.Machine([isa.wctl(k, 0), isa.rctl(1, 0x06), isa.rctl(2, 0x07), enc("HALT")])
        for _ in range(5):
            m.step()
        assert (m.regs[1], m.regs[2]) == (0, 0)


def test_crc16_xmodem_check_value():
    # The standard CRC-16/XMODEM check value over "123456789" is 0x31C3.
    crc = 0
    for b in b"123456789":
        crc = isa.crc16_update_byte(crc, b)
    assert crc == 0x31C3
    words = [0xDEAD, 0xBEEF, 0x0001, 0xFFFF]
    assert isa.crc16_words(words) == binascii.crc_hqx(b"".join(w.to_bytes(2, "big") for w in words), 0)


def test_pin_mode_rule():
    # DR 0012: OD set -> oe = ~out; else DIR set -> 1; else 0.  OD wins over DIR.
    assert isa.pin_mode_oe(0x00, 0x00, 0x00) == 0x00
    assert isa.pin_mode_oe(0xFF, 0x0F, 0x00) == 0x0F
    assert isa.pin_mode_oe(0x00, 0x00, 0x81) == 0x81     # both open-drain pins pulling low
    assert isa.pin_mode_oe(0x80, 0x00, 0x81) == 0x01     # bit 7 released
    assert isa.pin_mode_oe(0x00, 0xFF, 0x01) == 0xFF     # DIR everywhere; bit 0 OD driving low
    assert isa.pin_mode_oe(0x01, 0xFF, 0x01) == 0xFE     # OD wins over DIR: bit 0 released


def test_uio_oe_follows_control_registers_in_the_trace():
    prog = ctl_prog(enc("LDI", rd=0, imm=0x81), isa.wctl(0x01, 0),    # UIO_OD = 0x81, uio_out = 0
                    enc("LDI", rd=1, imm=0x80), enc("OUT", rd=1, port=3))   # release bit 7
    rows, _ = rows_of(prog, 7)
    assert rows[3].uio_oe == 0x81 and rows[6].uio_oe == 0x01 and rows[6].uio_out == 0x80


def test_unmodelled_fetch_is_an_error_not_a_guess():
    m = isa.Machine([enc("JMP", imm=0x80)])
    m.step(); m.step()
    try:
        m.step()
    except isa.ModelError:
        return
    raise AssertionError("fetch of a never-loaded word must raise ModelError")


# --------------------------------------------------------------------------
# Generator + coverage gate + cross-checks (still simulator-free)
# --------------------------------------------------------------------------
def _request():
    return json.loads(REQUEST.read_text())


def _params():
    o = _request()["options"]
    return o["random_seed"], o["isa_lockstep"]


def test_request_parameters_present():
    seed, p = _params()
    assert isinstance(seed, int) and p["programs"] >= 40
    assert p["min_retire"] >= 1 and p["min_bucket"] >= 1


def test_generator_is_deterministic_and_programs_replay_alone():
    a = gen.generate(7, 30)
    b = gen.generate(7, 30)
    assert [(p.code, p.pad, p.pins) for p in a] == [(p.code, p.pad, p.pins) for p in b]
    # a larger set is a prefix-extension, and a single random program replays alone
    big = gen.generate(7, 45)
    assert [p.code for p in big[:30]] == [p.code for p in a]
    one = gen.random_program(7, 40)
    assert one.code == big[40].code and one.pins == big[40].pins
    assert [p.code for p in gen.generate(8, 30)] != [p.code for p in a]


def test_every_program_terminates_within_its_bound():
    seed, p = _params()
    for prog in gen.generate(seed, p["programs"]):
        rows, m = isa.run(prog.image, prog.inputs, prog.max_edges, gen.IDLE_AFTER_HALT)
        assert m.halted and m.events[-1].mnemonic == "HALT", prog.name
        assert len(rows) - 1 <= prog.max_edges + gen.IDLE_AFTER_HALT, prog.name


def test_a_nonterminating_program_is_reported_not_passed():
    try:
        isa.run([enc("JMP", imm=0)], lambda e: (0, 0), 50)
    except isa.ModelError as e:
        assert "no HALT" in str(e)
        return
    raise AssertionError("an infinite loop must raise ModelError")


def test_coverage_gate_passes_on_the_committed_seed_and_fails_when_a_bucket_is_empty():
    seed, p = _params()
    events = []
    for prog in gen.generate(seed, p["programs"]):
        events.append(isa.run(prog.image, prog.inputs, prog.max_edges, gen.IDLE_AFTER_HALT)[1].events)
    counts = gen.tally(events)
    assert gen.gate(counts, p["min_retire"], p["min_bucket"]) == []
    # the gate is a gate: drop every program that executes WAIT 255 and a bucket empties
    kept = [e for e in events if not any(x.mnemonic == "WAIT" and x.info["n"] == 255 for x in e)]
    assert len(kept) < len(events)
    short = gen.gate(gen.tally(kept), p["min_retire"], p["min_bucket"])
    assert ("WAIT:255", 0, p["min_bucket"]) in short


def test_iss_assembler_cycle_cross_check_on_every_program():
    seed, p = _params()
    for prog in gen.generate(seed, p["programs"]):
        m = isa.run(prog.image, prog.inputs, prog.max_edges, gen.IDLE_AFTER_HALT)[1]
        assert gen.assembler_crosscheck(prog, m) == [], prog.name


def test_directed_edge_cases_are_present():
    names = [p.name for p in gen.generate(1, 12)]
    for want in ("halt-first", "wait255-then-bz", "wait255-then-bnz", "back-to-back-ctl",
                 "run-written-0", "run-written-1", "bounded-loop"):
        assert want in names, want


def test_run_written_programs_execute_the_written_code():
    for prog in gen.generate(1, 14):
        if prog.name.startswith("run-written"):
            m = isa.run(prog.image, prog.inputs, prog.max_edges, 0)[1]
            assert any(e.pc >= len(prog.image) for e in m.events), prog.name
            assert any(e.mnemonic == "OUT" and e.info.get("name") == "RUN" for e in m.events)


def main():
    tests = sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
