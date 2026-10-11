"""Independent, table-driven instruction-set simulator (ISS) for the
protocol-emulator ISA (issue #152; verification-plan section 4.1).

This is the ISA-level golden model that `verification/test_isa_lockstep.py`
compares, cycle by cycle, against `src/protocol_core.v`.  It is written
from two records, and from nothing else:

* DR 0001, `spec/decision-records/0001-isa.md`: the 16-opcode table
  ("Encoding"), the register and pin model, the port table, the 1-cycle /
  `WAIT imm8` = `imm8 + 1` cycle column, "`HALT` ... core idles until
  reset", and the two reserved no-op I/O encodings;
* DR 0012, `spec/decision-records/0012-control-space-and-runtime-pin-direction.md`:
  section 1 (`WCTL`/`RCTL` are `OUT` port 00 / `IN` port 10 with the index
  `k` in imm8), section 2 (the register map and its fixed 1- or 2-cycle
  costs, "Pin mode, per `uio[n]`", "Program-memory timing", reset values)
  and the table of "Points the first RTL build had to choose" (HW_ID
  0x01, CRC byte order, what clears the CRC, read-only / write-only /
  unassigned behaviour, the `BOOT_STATUS` value after a serial load);
* DR 0015, `spec/decision-records/0015-stretch-protocols-with-neutral-primitives.md`,
  with the index map and step equations its 2026-10-10 dated note (issue
  #208) records for P1 (CRC / LFSR step, 0x10-0x15) and P2 (NRZI + bit
  stuffing, 0x16-0x19).  The CRC and line state are internal: no trace
  field shows them, so the lockstep sees them only through `RCTL` reads
  into a register, which it compares on every edge.

It imports nothing from `rtl/`, `firmware/tools/asm.py` or any other
`verification/*.py` bench, and no Verilog was transcribed: decoding and
flag logic are restated from the DR text.  It is a pure-Python module (no
simulator, no cocotb), so its own unit tests
(`verification/test_isa_model.py`) run anywhere.

Machine model and the trace
---------------------------
The model executes one *clock edge* per `Machine.step()` and returns the
architectural state visible after that edge -- a `Row`.  Edge numbers
count from the edge on which the serial load phase ends (the MODE-drop
edge is edge 0, whose state is the freshly-reset machine: `Machine()` is
row 0).  Cycle structure, with the DR that states it:

* **Run-phase entry (DR 0005 amendment, quoted in DR 0001's note):** the
  first edge after entry only primes the fetch (nothing executes); the
  instruction at address 0 executes on the second edge.  A one-time +1
  cycle per reset.
* **Instruction cost (DR 0001 table, DR 0012 section 2):** an instruction
  of cost n occupies n consecutive edges.  Its architectural effects
  (registers, flags, pin registers, control registers, and the PC
  update) become visible at the END of its last edge; during the first
  n-1 edges the visible state is unchanged and the PC holds the
  instruction's own address (a stall).  That is what "`WAIT imm8`: stall
  `imm8 + 1` cycles" and "the 2 entries mean one fetch stall" say at the
  architectural level.  Internal bookkeeping that is not visible in the
  trace (when exactly `PM_ADDR` increments inside a two-cycle access) is
  committed with the rest, at the end.
* **`HALT`:** retires in 1 cycle; afterwards every visible field holds.
* **Inputs:** `IN` samples its port as it is on the edge it retires on
  (DR 0001, "Sample on edge"); `step(ui_in, uio_in)` is told the pin
  values present on that edge.  `OUT` updates the pin register at the
  retiring edge, so the pin changes in the row of that edge.
* **Execution entry:** programs are loaded over the serial load phase and
  run from program memory.  The boot ROM fetch source, warm start and the
  SPI boot path (DR 0013 layer 2) are OUT OF SCOPE and not modelled;
  `BOOT_STATUS` therefore reads 0x01 (serial load completed, not fetching
  from the ROM), as DR 0012's choice table states for a serial load.

Open details: where DR 0001 is silent this model does not copy the RTL
silently; it names the choice.  See `OPEN_DETAILS` below -- the bench
reports any mismatch that touches one of them as such, and never relaxes
the spec to make it pass.  All four are now ruled by DR 0016
(`spec/decision-records/0016-isa-flag-and-shift-details.md`, issue #203),
which is Proposed, not ratified (issue #44); each label cites its ruling.

The opcode table (`OPCODES`) and the control-register table (`CONTROL`)
are data.  A future decision record that adds an encoding is a row in
one of them plus a record; a bench failure on the new RTL behaviour is
the signal that the table was not updated.
"""

from __future__ import annotations

from collections import namedtuple

# ---------------------------------------------------------------------------
# Open details (DR 0001's text is silent or ambiguous).  Each is a named,
# labelled choice, not a silent copy of the RTL.  `tag` is what a Row/event
# carries.  DR 0016 (issue #203) rules all four, each as modelled here; it is
# Proposed, not ratified (issue #44), so the labels say "proposed ruling".
# The keys are stable: benches and records cite them.
# ---------------------------------------------------------------------------
OPEN_DETAILS = {
    "sub-c-polarity": (
        "DR 0001 says SUB 'sets Z, C' and does not define the polarity of C.  "
        "DR 0016 Ruling 1 (Proposed): C is a BORROW, C=1 when minuend < "
        "subtrahend (unsigned), bit 8 of the 9-bit difference; any later "
        "instruction that reads C uses this definition.  rtl/protocol_core.v "
        "implements the same.  Not yet ratified (issue #44)."
    ),
    "shf-z": (
        "DR 0001's prose lists SHF among the instructions that write the "
        "flag register, but its opcode table gives only 'shifted-out bit -> "
        "C'.  DR 0016 Ruling 2 (Proposed): SHF writes C and leaves Z "
        "unchanged."
    ),
    "logic-c": (
        "AND/OR/XOR 'set Z' (DR 0001 table) and C is not mentioned.  DR 0016 "
        "Ruling 3 (Proposed): C is left unchanged."
    ),
    "shf-fill": (
        "DR 0001 says 'shift Rd by 1' and does not name the fill bit.  DR 0016 "
        "Ruling 4 (Proposed): a logical shift, 0 fills the vacated bit in both "
        "directions (DR 0001's 2026-10-10 dated note already relies on it)."
    ),
}

SUB_C_POLARITY = "borrow"  # DR 0016 Ruling 1 ('sub-c-polarity'): 'borrow' | 'carry'

# ---------------------------------------------------------------------------
# Constants from the DRs.
# ---------------------------------------------------------------------------
WORDS = 256                # DR 0001: 256 x 16-bit program memory, 8-bit PC
NREGS = 4                  # DR 0001: R0..R3
HW_ID_VALUE = 0x01         # DR 0012 choice table: HW_ID reads 0x01
BOOT_STATUS_SERIAL = 0x01  # DR 0012: bit 0 = a serial load completed; bit 1 (boot ROM) out of scope

PORT_UI_IN, PORT_UIO_IN, PORT_UO_OUT, PORT_UIO_OUT = 0, 1, 2, 3  # DR 0001 port table

CRC_POLY = 0x1021  # DR 0012: CRC-16/XMODEM, init 0x0000, high byte of a word first


class ModelError(Exception):
    """The program did something the model cannot define (fetch of a word
    that was never loaded or written, ...).  A generator bug, not a pass."""


# ---------------------------------------------------------------------------
# CRC-16/XMODEM, bit by bit (own implementation; the unit tests check it
# against binascii.crc_hqx).
# ---------------------------------------------------------------------------
def crc16_update_byte(crc: int, byte: int) -> int:
    crc ^= (byte & 0xFF) << 8
    for _ in range(8):
        crc = ((crc << 1) ^ CRC_POLY) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def crc16_update_word(crc: int, word: int) -> int:
    """High byte first (DR 0012 choice table)."""
    return crc16_update_byte(crc16_update_byte(crc, word >> 8), word & 0xFF)


def crc16_words(words, crc: int = 0) -> int:
    for w in words:
        crc = crc16_update_word(crc, w)
    return crc


# ---------------------------------------------------------------------------
# Effects.  Each takes (machine, ins, ui_in, uio_in) and returns
# (cost, writes, info).  `writes` is a list of visible/internal state
# updates applied at the end of the instruction's last edge.
#   ("reg", i, v) ("pc", v) ("z", v) ("c", v, tag) ("uo", v) ("uio", v)
#   ("dir", v) ("od", v) ("pm_addr", v) ("pm_hi", v) ("pm_lo", v)
#   ("pm", addr, word) ("crc_clear",) ("halt",) ("set", attr, value)
# `ins` is an Ins (decoded fields).  No effect touches state directly.
# ---------------------------------------------------------------------------
Ins = namedtuple("Ins", "word op rd rs imm")


def decode(word: int) -> Ins:
    """DR 0001 'Encoding': [15:12] opcode, [11:10] Rd, [9:8] Rs/port, [7:0] imm8."""
    return Ins(word, (word >> 12) & 0xF, (word >> 10) & 3, (word >> 8) & 3, word & 0xFF)


def _fx_nop(m, i, ui, uio):
    return 1, [], {}


def _fx_ldi(m, i, ui, uio):
    return 1, [("reg", i.rd, i.imm)], {}


def _fx_mov(m, i, ui, uio):
    return 1, [("reg", i.rd, m.regs[i.rs])], {}


def _fx_add(m, i, ui, uio):
    s = m.regs[i.rd] + m.regs[i.rs]
    r = s & 0xFF
    return 1, [("reg", i.rd, r), ("z", int(r == 0)), ("c", s >> 8, "add")], \
        {"c": s >> 8, "z": int(r == 0)}


def _fx_sub(m, i, ui, uio):
    a, b = m.regs[i.rd], m.regs[i.rs]
    r = (a - b) & 0xFF
    borrow = int(a < b)
    c = borrow if SUB_C_POLARITY == "borrow" else 1 - borrow
    return 1, [("reg", i.rd, r), ("z", int(r == 0)), ("c", c, "sub")], \
        {"c": c, "z": int(r == 0), "borrow": borrow}


def _logic(fn):
    def fx(m, i, ui, uio):
        r = fn(m.regs[i.rd], m.regs[i.rs]) & 0xFF
        return 1, [("reg", i.rd, r), ("z", int(r == 0))], {"z": int(r == 0)}
    return fx


def _fx_shf(m, i, ui, uio):
    v = m.regs[i.rd]
    left = i.rs & 1  # DR 0001: dir bit in Rs[0]: 0 = right, 1 = left
    if left:
        r, out = (v << 1) & 0xFF, (v >> 7) & 1
    else:
        r, out = v >> 1, v & 1
    return 1, [("reg", i.rd, r), ("c", out, "shf")], {"left": left, "out": out}


def _fx_in(m, i, ui, uio):
    port = i.rs
    if port == PORT_UI_IN:
        return 1, [("reg", i.rd, ui & 0xFF)], {"port": port}
    if port == PORT_UIO_IN:
        return 1, [("reg", i.rd, uio & 0xFF)], {"port": port}
    if port == PORT_UO_OUT:  # DR 0012: RCTL Rd, k
        return _rctl(m, i)
    return 1, [], {"port": port, "noop": True}  # IN port 11: reserved 1-cycle no-op


def _fx_out(m, i, ui, uio):
    port, src = i.rs, m.regs[i.rd]  # OUT: source register rides [11:10]
    if port == PORT_UO_OUT:
        return 1, [("uo", src)], {"port": port}
    if port == PORT_UIO_OUT:
        return 1, [("uio", src)], {"port": port}
    if port == PORT_UI_IN:  # DR 0012: WCTL k, Rs
        return _wctl(m, i)
    return 1, [], {"port": port, "noop": True}  # OUT port 01: reserved 1-cycle no-op


def _fx_wait(m, i, ui, uio):
    return i.imm + 1, [], {"n": i.imm}


def _fx_jmp(m, i, ui, uio):
    return 1, [("pc", i.imm)], {}


def _fx_bz(m, i, ui, uio):
    taken = m.z == 1
    return 1, [("pc", i.imm)] if taken else [], {"taken": taken}


def _fx_bnz(m, i, ui, uio):
    taken = m.z == 0
    return 1, [("pc", i.imm)] if taken else [], {"taken": taken}


def _fx_halt(m, i, ui, uio):
    return 1, [("halt",)], {}


# ---------------------------------------------------------------------------
# DR 0001 'Encoding' table, as data.
#   (opcode, mnemonic, operand form, effect)
# ---------------------------------------------------------------------------
Op = namedtuple("Op", "code mnemonic form effect")

OPCODES = (
    Op(0x0, "NOP", "none", _fx_nop),
    Op(0x1, "LDI", "rd,imm8", _fx_ldi),
    Op(0x2, "MOV", "rd,rs", _fx_mov),
    Op(0x3, "ADD", "rd,rs", _fx_add),
    Op(0x4, "SUB", "rd,rs", _fx_sub),
    Op(0x5, "AND", "rd,rs", _logic(lambda a, b: a & b)),
    Op(0x6, "OR", "rd,rs", _logic(lambda a, b: a | b)),
    Op(0x7, "XOR", "rd,rs", _logic(lambda a, b: a ^ b)),
    Op(0x8, "SHF", "rd,dir", _fx_shf),
    Op(0x9, "IN", "rd,port", _fx_in),
    Op(0xA, "OUT", "port,rs", _fx_out),
    Op(0xB, "WAIT", "imm8", _fx_wait),
    Op(0xC, "JMP", "imm8", _fx_jmp),
    Op(0xD, "BZ", "imm8", _fx_bz),
    Op(0xE, "BNZ", "imm8", _fx_bnz),
    Op(0xF, "HALT", "none", _fx_halt),
)
BY_CODE = {o.code: o for o in OPCODES}
BY_MNEMONIC = {o.mnemonic: o for o in OPCODES}
assert len(OPCODES) == 16 and sorted(BY_CODE) == list(range(16))


# ---------------------------------------------------------------------------
# DR 0012 section 2, the register map, as data.
#   name, readable, writable, read cost, write cost
# plus read / write semantics as small functions over the machine.
# ---------------------------------------------------------------------------
Ctl = namedtuple("Ctl", "k name readable writable rcost wcost read write")


def _r_attr(attr):
    return lambda m: (getattr(m, attr), [])


def _w_attr(wname):
    return lambda m, v: [(wname, v)]


def _r_pm_hi(m):
    # R: read PM[PM_ADDR], return the high byte, latch the low byte.
    word = m.pm_read(m.pm_addr)
    return word >> 8, [("pm_lo", word & 0xFF)]


def _r_pm_lo(m):
    # R: return the latched low byte, then PM_ADDR++.
    return m.pm_lo, [("pm_addr", (m.pm_addr + 1) & 0xFF)]


def _w_pm_lo(m, v):
    # W: commit {HI, LO} to PM[PM_ADDR], then PM_ADDR++.
    word = (m.pm_hi << 8) | v
    return [("pm", m.pm_addr, word), ("pm_addr", (m.pm_addr + 1) & 0xFF)]


def _w_run(m, v):
    # RUN: switch the fetch source to program memory, PC <- Rs.
    return [("pc", v)]


# ---------------------------------------------------------------------------
# DR 0015 P1 and P2, restated from the 2026-10-10 dated note.
#   P1: W = CRC_CFG[4:0] + 1, M = 2^W - 1, all registers 32 bits.
#     normal:    fb = d ^ STATE[W-1]; STATE <- (STATE << 1) ^ (fb ? POLY : 0)
#     reflected: fb = d ^ STATE[0];   STATE <- ((STATE & M) >> 1) ^ (fb ? POLY : 0)
#     CRC_BYTE = eight steps, Rs LSB first if reflected, else MSB first.
#     CRC_STATE reads (STATE & M), CRC_NEXT reads ((STATE ^ inv) & M), each at
#     the byte pointer; POLY / STATE / NEXT accesses advance the pointer, a
#     CRC_CFG write rewinds it.
#   P2: LINE_CFG [1:0] NRZI (01 toggle on 0, 10 toggle on 1, else NRZ),
#     [3:2] stuff rule (01 after N ones -> a 0; 10 after N equal -> the
#     complement of the last bit; else off), [6:4] N, [7] loads the level.
# ---------------------------------------------------------------------------
CRC_BYTE_COST = 9
MASK32 = 0xFFFFFFFF


def crc_step(state, poly, wm1, refl, d):
    width_mask = (1 << (wm1 + 1)) - 1
    if refl:
        fb = (d ^ state) & 1
        new = (state & width_mask) >> 1
    else:
        fb = (d ^ (state >> wm1)) & 1
        new = (state << 1) & MASK32
    return new ^ (poly if fb else 0)


def _byte_at(value, ptr):
    return (value >> (8 * ptr)) & 0xFF


def _r_crc_cfg(m):
    return m.crc_wm1 | (m.crc_refl << 5) | (m.crc_inv << 6), []


def _r_crc(which):
    def rd(m):
        width_mask = (1 << (m.crc_wm1 + 1)) - 1
        if which == "poly":
            v = m.crc_poly
        elif which == "state":
            v = m.crc_state & width_mask
        else:
            v = (m.crc_state ^ (MASK32 if m.crc_inv else 0)) & width_mask
        return _byte_at(v, m.crc_ptr), [("set", "crc_ptr", (m.crc_ptr + 1) & 3)]
    return rd


def _w_crc_cfg(m, v):
    return [("set", "crc_wm1", v & 0x1F), ("set", "crc_refl", v >> 5 & 1),
            ("set", "crc_inv", v >> 6 & 1), ("set", "crc_ptr", 0)]


def _w_crc_byte_reg(attr):
    def wr(m, v):
        shift = 8 * m.crc_ptr
        cur = getattr(m, attr)
        new = (cur & ~(0xFF << shift) & MASK32) | ((v & 0xFF) << shift)
        return [("set", attr, new), ("set", "crc_ptr", (m.crc_ptr + 1) & 3)]
    return wr


def _w_crc_bit(m, v):
    return [("set", "crc_state", crc_step(m.crc_state, m.crc_poly, m.crc_wm1, m.crc_refl, v & 1))]


def _w_crc_byte(m, v):
    order = range(8) if m.crc_refl else range(7, -1, -1)
    s = m.crc_state
    for i in order:
        s = crc_step(s, m.crc_poly, m.crc_wm1, m.crc_refl, v >> i & 1)
    return [("set", "crc_state", s)]


def _w_line_cfg(m, v):
    return [("set", "line_cfg", v & 0x7F), ("set", "line_lvl", v >> 7 & 1),
            ("set", "line_cnt", 0), ("set", "line_stuf", 0)]


def _w_line_put(m, v):
    mode, rule, n = m.line_cfg & 3, m.line_cfg >> 2 & 3, m.line_cfg >> 4 & 7
    due = rule in (1, 2) and m.line_cnt == n
    if due:
        e = 0 if rule == 1 else 1 - m.line_prev
    else:
        e = v & 1
    if rule == 1:
        cnt = m.line_cnt + 1 if e else 0
    else:
        cnt = m.line_cnt + 1 if e == m.line_prev else 1
    if mode == 1:
        lvl = m.line_lvl if e else 1 - m.line_lvl
    elif mode == 2:
        lvl = 1 - m.line_lvl if e else m.line_lvl
    else:
        lvl = e
    return [("set", "line_lvl", lvl), ("set", "line_prev", e),
            ("set", "line_cnt", cnt & 7), ("set", "line_stuf", int(due))]


CONTROL = {c.k: c for c in (
    Ctl(0x00, "UIO_DIR", True, True, 1, 1, _r_attr("uio_dir"), _w_attr("dir")),
    Ctl(0x01, "UIO_OD", True, True, 1, 1, _r_attr("uio_od"), _w_attr("od")),
    Ctl(0x02, "PM_ADDR", True, True, 1, 1, _r_attr("pm_addr"), _w_attr("pm_addr")),
    Ctl(0x03, "PM_DATA_HI", True, True, 2, 1, _r_pm_hi, _w_attr("pm_hi")),
    Ctl(0x04, "PM_DATA_LO", True, True, 1, 2, _r_pm_lo, _w_pm_lo),
    Ctl(0x05, "RUN", False, True, 1, 2, None, _w_run),
    Ctl(0x06, "PM_CRC_LO", True, True, 1, 1, lambda m: (m.crc & 0xFF, []),
        lambda m, v: [("crc_clear",)]),
    Ctl(0x07, "PM_CRC_HI", True, True, 1, 1, lambda m: (m.crc >> 8, []),
        lambda m, v: [("crc_clear",)]),
    Ctl(0x08, "BOOT_STATUS", True, False, 1, 1, lambda m: (BOOT_STATUS_SERIAL, []), None),
    Ctl(0x09, "HW_ID", True, False, 1, 1, lambda m: (HW_ID_VALUE, []), None),
    # DR 0015 P1 (2026-10-10 note): CRC / LFSR step.
    Ctl(0x10, "CRC_CFG", True, True, 1, 1, _r_crc_cfg, _w_crc_cfg),
    Ctl(0x11, "CRC_POLY", True, True, 1, 1, _r_crc("poly"), _w_crc_byte_reg("crc_poly")),
    Ctl(0x12, "CRC_STATE", True, True, 1, 1, _r_crc("state"), _w_crc_byte_reg("crc_state")),
    Ctl(0x13, "CRC_BIT", False, True, 1, 1, None, _w_crc_bit),
    Ctl(0x14, "CRC_BYTE", False, True, 1, CRC_BYTE_COST, None, _w_crc_byte),
    Ctl(0x15, "CRC_NEXT", True, False, 1, 1, _r_crc("next"), None),
    # DR 0015 P2: NRZI + bit stuffing.
    Ctl(0x16, "LINE_CFG", True, True, 1, 1, lambda m: (m.line_cfg, []), _w_line_cfg),
    Ctl(0x17, "LINE_PUT", False, True, 1, 1, None, _w_line_put),
    Ctl(0x18, "LINE_OUT", True, False, 1, 1,
        lambda m: (((1 - m.line_lvl) << 1) | m.line_lvl, []), None),
    Ctl(0x19, "LINE_STUF", True, False, 1, 1, lambda m: (m.line_stuf, []), None),
)}
# 0x1A-0x1F stay reserved (DR 0015: held for P3/P4) and unassigned; every k
# not in CONTROL is unassigned: write = 1-cycle no-op, read = 0x00 in 1 cycle.


def _wctl(m, i):
    k = i.imm
    c = CONTROL.get(k)
    if c is None or not c.writable:
        return 1, [], {"ctl": k, "dir": "w", "noop": True,
                       "kind": "unassigned" if c is None else "read-only"}
    return c.wcost, c.write(m, m.regs[i.rd]), {"ctl": k, "dir": "w", "name": c.name}


def _rctl(m, i):
    k = i.imm
    c = CONTROL.get(k)
    if c is None or not c.readable:
        # unassigned, or write-only RUN: 0x00 in 1 cycle
        return 1, [("reg", i.rd, 0)], {"ctl": k, "dir": "r", "noop": True,
                                       "kind": "unassigned" if c is None else "write-only"}
    val, side = c.read(m)
    return c.rcost, [("reg", i.rd, val)] + side, {"ctl": k, "dir": "r", "name": c.name}


# ---------------------------------------------------------------------------
# DR 0012 "Pin mode, per uio[n]", restated bit by bit.
# ---------------------------------------------------------------------------
def pin_mode_oe(uio_out: int, uio_dir: int, uio_od: int) -> int:
    oe = 0
    for n in range(8):
        out_n, dir_n, od_n = (uio_out >> n) & 1, (uio_dir >> n) & 1, (uio_od >> n) & 1
        if od_n:
            bit = 0 if out_n else 1  # open drain: drive low on 0, release on 1
        elif dir_n:
            bit = 1                  # push-pull
        else:
            bit = 0                  # input
        oe |= bit << n
    return oe


# ---------------------------------------------------------------------------
# Encoding helpers (from the DR 0001 field diagram).
# ---------------------------------------------------------------------------
def encode(mnemonic: str, rd: int = 0, rs: int = 0, port: int = 0, imm: int = 0) -> int:
    """Pack fields.  For IN, `rd` is the destination and `port` the port; for
    OUT, `rd` is the SOURCE register (it rides [11:10]) and `port` the port;
    for SHF, `rs` is the direction (0 right, 1 left)."""
    op = BY_MNEMONIC[mnemonic].code
    return (op << 12) | ((rd & 3) << 10) | (((rs | port) & 3) << 8) | (imm & 0xFF)


def wctl(k: int, src: int) -> int:
    return encode("OUT", rd=src, port=PORT_UI_IN, imm=k)


def rctl(rd: int, k: int) -> int:
    return encode("IN", rd=rd, port=PORT_UO_OUT, imm=k)


def disasm(word: int) -> str:
    i = decode(word)
    mn = BY_CODE[i.op].mnemonic
    if mn in ("NOP", "HALT"):
        return mn
    if mn == "LDI":
        return f"LDI R{i.rd}, {i.imm:#04x}"
    if mn in ("MOV", "ADD", "SUB", "AND", "OR", "XOR"):
        return f"{mn} R{i.rd}, R{i.rs}"
    if mn == "SHF":
        return f"SHF R{i.rd}, {'LEFT' if i.rs & 1 else 'RIGHT'}"
    if mn == "IN":
        if i.rs == PORT_UO_OUT:
            c = CONTROL.get(i.imm)
            return f"RCTL R{i.rd}, {c.name if c else hex(i.imm)}"
        return f"IN R{i.rd}, port{i.rs:02b}"
    if mn == "OUT":
        if i.rs == PORT_UI_IN:
            c = CONTROL.get(i.imm)
            return f"WCTL {c.name if c else hex(i.imm)}, R{i.rd}"
        return f"OUT port{i.rs:02b}, R{i.rd}"
    return f"{mn} {i.imm}"


# ---------------------------------------------------------------------------
# The machine.
# ---------------------------------------------------------------------------
Row = namedtuple("Row", "pc regs z c halted uo_out uio_out uio_oe")
ROW_FIELDS = Row._fields

Event = namedtuple("Event", "edge pc word mnemonic cost info")


class Machine:
    """State after a serial load of `image` (list of 16-bit words, address 0
    upward).  `Machine(image)` is row 0; each `step()` is one clock edge."""

    def __init__(self, image):
        if not 0 < len(image) <= WORDS:
            raise ModelError("image must be 1..256 words")
        self.pm = {a: w & 0xFFFF for a, w in enumerate(image)}  # known words only
        self.regs = [0] * NREGS
        self.z = 0
        self.c = 0
        self.c_src = None   # which instruction class last wrote C (open-detail labelling)
        self.c_src_log = [None]  # c_src after each edge, indexed like the trace rows
        self.pc = 0
        self.halted = False
        self.uo = 0
        self.uio = 0
        self.uio_dir = 0
        self.uio_od = 0
        self.pm_addr = 0
        self.pm_hi = 0
        self.pm_lo = 0
        self.crc = crc16_words(image)  # DR 0012: CRC covers every committed word, load included
        # DR 0015 P1 / P2: every register clears at reset.
        self.crc_wm1 = self.crc_refl = self.crc_inv = self.crc_ptr = 0
        self.crc_poly = self.crc_state = 0
        self.line_cfg = self.line_lvl = self.line_prev = self.line_cnt = self.line_stuf = 0
        self.primed = False
        self.edge = 0
        self._remaining = 0
        self._pending = None
        self.events = []

    # -- program memory -----------------------------------------------------
    def pm_read(self, addr):
        if addr not in self.pm:
            raise ModelError(f"read of program-memory word {addr:#04x} that was never loaded or written")
        return self.pm[addr]

    # -- state ----------------------------------------------------------------
    @property
    def row(self) -> Row:
        return Row(self.pc, tuple(self.regs), self.z, self.c, int(self.halted),
                   self.uo, self.uio, pin_mode_oe(self.uio, self.uio_dir, self.uio_od))

    def _apply(self, writes):
        for w in writes:
            kind = w[0]
            if kind == "reg":
                self.regs[w[1]] = w[2] & 0xFF
            elif kind == "pc":
                self.pc = w[1] & 0xFF
            elif kind == "z":
                self.z = w[1]
            elif kind == "c":
                self.c, self.c_src = w[1], w[2]
            elif kind == "uo":
                self.uo = w[1]
            elif kind == "uio":
                self.uio = w[1]
            elif kind == "dir":
                self.uio_dir = w[1]
            elif kind == "od":
                self.uio_od = w[1]
            elif kind == "pm_addr":
                self.pm_addr = w[1] & 0xFF
            elif kind == "pm_hi":
                self.pm_hi = w[1]
            elif kind == "pm_lo":
                self.pm_lo = w[1]
            elif kind == "pm":
                self.pm[w[1]] = w[2]
                self.crc = crc16_update_word(self.crc, w[2])
            elif kind == "crc_clear":
                self.crc = 0
            elif kind == "halt":
                self.halted = True
            elif kind == "set":
                setattr(self, w[1], w[2])
            else:
                raise ModelError(f"unknown write {w!r}")

    def step(self, ui_in: int = 0, uio_in: int = 0) -> Row:
        """One clock edge; `ui_in` / `uio_in` are the pin values on that edge."""
        row = self._step(ui_in, uio_in)
        self.c_src_log.append(self.c_src)
        return row

    def _step(self, ui_in, uio_in) -> Row:
        self.edge += 1
        if not self.primed:
            self.primed = True      # run-phase entry: prime the fetch, execute nothing
            return self.row
        if self.halted:
            return self.row
        if self._remaining:
            self._remaining -= 1
            if self._remaining == 0:
                self._apply(self._pending)
                self._pending = None
            return self.row
        word = self.pm_read(self.pc)
        ins = decode(word)
        op = BY_CODE[ins.op]
        cost, writes, info = op.effect(self, ins, ui_in & 0xFF, uio_in & 0xFF)
        if not any(w[0] in ("pc", "halt") for w in writes):
            writes = writes + [("pc", (self.pc + 1) & 0xFF)]
        elif any(w[0] == "halt" for w in writes):
            writes = writes + [("pc", self.pc)]  # HALT: PC holds
        self.events.append(Event(self.edge, self.pc, word, op.mnemonic, cost, info))
        if cost == 1:
            self._apply(writes)
        else:
            self._remaining = cost - 1
            self._pending = writes
        return self.row


def static_cost(word: int) -> int:
    """Cycle cost of one instruction word, from the tables alone (no state):
    DR 0001's 1 / imm8+1 and DR 0012's per-index control costs."""
    i = decode(word)
    mn = BY_CODE[i.op].mnemonic
    if mn == "WAIT":
        return i.imm + 1
    if mn == "OUT" and i.rs == PORT_UI_IN:
        c = CONTROL.get(i.imm)
        return c.wcost if c and c.writable else 1
    if mn == "IN" and i.rs == PORT_UO_OUT:
        c = CONTROL.get(i.imm)
        return c.rcost if c and c.readable else 1
    return 1


def run(image, inputs, max_edges: int, idle_after_halt: int = 0):
    """Run `image` until HALT (plus `idle_after_halt` hold edges).

    `inputs(edge) -> (ui_in, uio_in)` gives the pin values on that edge.
    Returns (rows, machine) with rows[e] = state after edge e (rows[0] is
    the reset state).  Raises ModelError if HALT is not reached within
    `max_edges` edges (a non-terminating program is a generator bug)."""
    m = Machine(image)
    rows = [m.row]
    halted_at = None
    while True:
        if m.edge >= max_edges:
            raise ModelError(f"no HALT within {max_edges} edges (pc={m.pc:#04x})")
        rows.append(m.step(*inputs(m.edge + 1)))
        if m.halted and halted_at is None:
            halted_at = m.edge
        if halted_at is not None and m.edge >= halted_at + idle_after_halt:
            return rows, m
