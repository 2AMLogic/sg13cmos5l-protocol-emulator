"""cocotb bench for DR 0015's protocol-neutral primitives P1 and P2 on
`tt_um_2amlogic_protocol_emulator` (issue #208).

`spec/decision-records/0015-stretch-protocols-with-neutral-primitives.md`
admits two primitives in DR 0012's control range 0x10-0x1F, and its
Consequences require, for each one, a bench against an **independent
oracle**, a fixed-latency check on the new indices, and negative controls.
This bench is that obligation. The index map and the step equations it
tests are the ones DR 0012 and DR 0015 record in their 2026-10-10 notes:

    0x10 CRC_CFG    0x11 CRC_POLY   0x12 CRC_STATE  0x13 CRC_BIT
    0x14 CRC_BYTE   0x15 CRC_NEXT   0x16 LINE_CFG   0x17 LINE_PUT
    0x18 LINE_OUT   0x19 LINE_STUF  (0x1A-0x1F stay unassigned)

The oracles, and why each is independent of the RTL:

- **P1 (CRC).** `catalogue_crc()` below is the textbook Rocksoft^tm model
  ("width, poly, init, refin, refout, xorout"), bit-serial, in the
  catalogue's own NORMAL orientation. It never uses a reflected polynomial,
  a right shift or the RTL's masking; the reflected forms the firmware
  writes are derived from the catalogue entry by `reflect()`. Each model is
  graded on the catalogue's own `check` value (the CRC of the ASCII string
  "123456789"), which is a published constant, not a computed one; and the
  oracle itself is cross-checked against Python's `zlib.crc32` (CRC-32)
  and `binascii.crc_hqx` (CRC-16/XMODEM) before it grades anything. The
  catalogue entries are those of the CRC RevEng catalogue: CRC-5/USB,
  CRC-16/USB, CRC-32 (ISO-HDLC), CRC-8/MAXIM-DOW, CRC-15/CAN, and
  CRC-16/XMODEM.
- **LFSR / PRBS.** With data 0, a normal-form step is multiplication by x
  modulo the generator. `gf2_mulx_mod()` computes the expected state as a
  polynomial remainder (`S * x^n mod G`) by carry-less arithmetic -- a
  different formulation from a shift register -- and the bench also
  checks the period of the ITU-T O.150 PRBS7 generator (x^7 + x^6 + 1:
  exactly 127 states, all distinct, all non-zero).
- **P2 (NRZI + stuffing).** `LineDecoder` is a receiver: it is given only
  the captured line levels, one per slot, and NRZI-decodes and de-stuffs
  them by the protocol's own rule (USB: a 0 after six 1s, zero-toggles
  NRZI; HDLC: a 0 after five 1s; CAN: the complement after five equal
  bits). It reports a stuff-rule violation as an error. It shares nothing
  with the RTL's run counter; the bench asserts that the decoded bits are
  exactly the data presented, that the stuff slots the decoder found are
  exactly the slots the design flagged in LINE_STUF, and that the decoder
  saw no violation.

How values are observed: programs are real firmware, assembled by the DR
0003 assembler (`firmware/tools/asm.py`, which knows the new names),
loaded over the real serial load phase, and read at the pins: `RCTL Rd, k`
then `OUT UO_OUT, Rd`, sampled on the edge that instruction-position
arithmetic predicts with this file's **own** latency table (`cycles()`),
not the assembler's. A few labelled white-box reads (`flag_z`/`flag_c`,
reset state) run in an RTL run only; under `GATES=yes` they are skipped
and everything else is pin-only.

All programs and data are fixed in source or drawn from `random.Random`
with literal seeds, so every run is byte-reproducible.
"""

import binascii
import os
import random
import sys
import zlib
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(__file__)
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))

import asm  # noqa: E402  (the DR 0003 assembler)

CLK_PERIOD_NS = 10
RUN_ENTRY_EDGES = 2  # DR 0005: edge 1 primes the fetch, edge 2 retires pc=0
GATE_LEVEL = os.environ.get("GATES") == "yes"

# The index map (DR 0012 / DR 0015 dated notes, 2026-10-10), written out here.
CRC_CFG, CRC_POLY, CRC_STATE, CRC_BIT, CRC_BYTE, CRC_NEXT = 0x10, 0x11, 0x12, 0x13, 0x14, 0x15
LINE_CFG, LINE_PUT, LINE_OUT, LINE_STUF = 0x16, 0x17, 0x18, 0x19
UNASSIGNED = (0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F)

OP_IN, OP_OUT, OP_WAIT = 0x9, 0xA, 0xB
PM_DATA_HI, PM_DATA_LO, RUN = 0x03, 0x04, 0x05


def cycles(word):
    """This bench's statement of the latency table: DR 0001 (1, WAIT
    imm8+1), DR 0012 (three fixed 2-cycle accesses) and DR 0015 (WCTL
    CRC_BYTE: 1 + 8 stall = 9). Everything else is 1."""
    op, port, k = word >> 12, (word >> 8) & 3, word & 0xFF
    if op == OP_WAIT:
        return k + 1
    if op == OP_OUT and port == 0:
        if k in (PM_DATA_LO, RUN):
            return 2
        if k == CRC_BYTE:
            return 9
    if op == OP_IN and port == 2 and k == PM_DATA_HI:
        return 2
    return 1


# ---------------------------------------------------------------------------
# Oracle 1: the Rocksoft CRC model, from the catalogue parameters.
# ---------------------------------------------------------------------------
def reflect(value, width):
    out = 0
    for i in range(width):
        if value >> i & 1:
            out |= 1 << (width - 1 - i)
    return out


# name: (width, poly, init, refin, refout, xorout, check) -- CRC RevEng catalogue
CATALOGUE = {
    "CRC-5/USB": (5, 0x05, 0x1F, True, True, 0x1F, 0x19),
    "CRC-16/USB": (16, 0x8005, 0xFFFF, True, True, 0xFFFF, 0xB4C8),
    "CRC-32/ISO-HDLC": (32, 0x04C11DB7, 0xFFFFFFFF, True, True, 0xFFFFFFFF, 0xCBF43926),
    "CRC-8/MAXIM-DOW": (8, 0x31, 0x00, True, True, 0x00, 0xA1),
    "CRC-15/CAN": (15, 0x4599, 0x0000, False, False, 0x0000, 0x059E),
    "CRC-16/XMODEM": (16, 0x1021, 0x0000, False, False, 0x0000, 0x31C3),
}


def bits_of(data, refin):
    """The bit stream a CRC sees: per byte LSB first when refin, else MSB first."""
    out = []
    for byte in data:
        order = range(8) if refin else range(7, -1, -1)
        out += [byte >> i & 1 for i in order]
    return out


def catalogue_crc(name, bits):
    """Rocksoft model over an explicit bit stream, normal orientation only."""
    width, poly, init, refin, refout, xorout, _ = CATALOGUE[name]
    mask = (1 << width) - 1
    reg = init
    for b in bits:
        top = reg >> (width - 1) & 1
        reg = (reg << 1) & mask
        if top ^ b:
            reg ^= poly
    if refout:
        reg = reflect(reg, width)
    return reg ^ xorout


def firmware_setup(name):
    """What the firmware writes for catalogue entry `name`: (CRC_CFG, POLY,
    initial STATE, invert). Reflected models take the bit-reversed
    polynomial and seed; the inversion bit stands for an all-ones xorout."""
    width, poly, init, refin, refout, xorout, _ = CATALOGUE[name]
    assert refin == refout, "the engine reads the register in its own orientation"
    mask = (1 << width) - 1
    assert xorout in (0, mask), "xorout is 0 or all-ones (the inversion bit)"
    inv = xorout == mask
    if refin:
        poly, init = reflect(poly, width), reflect(init, width)
    cfg = (width - 1) | (0x20 if refin else 0) | (0x40 if inv else 0)
    return cfg, poly, init, inv


def _oracle_self_check():
    data = b"123456789"
    for name, entry in CATALOGUE.items():
        got = catalogue_crc(name, bits_of(data, entry[3]))
        assert got == entry[6], f"oracle {name}: {got:#x} != catalogue check {entry[6]:#x}"
    rnd = random.Random(20261010)
    for _ in range(50):
        data = bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 40)))
        assert catalogue_crc("CRC-32/ISO-HDLC", bits_of(data, True)) == zlib.crc32(data)
        assert catalogue_crc("CRC-16/XMODEM", bits_of(data, False)) == binascii.crc_hqx(data, 0)


_oracle_self_check()


# ---------------------------------------------------------------------------
# Oracle 2: Galois LFSR as polynomial arithmetic over GF(2).
# ---------------------------------------------------------------------------
def gf2_mod(a, g):
    dg = g.bit_length() - 1
    while a and a.bit_length() - 1 >= dg:
        a ^= g << (a.bit_length() - 1 - dg)
    return a


def gf2_mulx_mod(seed, n, g):
    """seed * x^n mod g."""
    return gf2_mod(seed << n, g)


# ---------------------------------------------------------------------------
# Oracle 3: an NRZI / bit-stuffing receiver.
# ---------------------------------------------------------------------------
class LineDecoder:
    """Decode line levels (one per slot) into data bits.

    nrzi: "none" (level is the bit), "zero" (a transition is a 0: USB,
    HDLC-NRZI), "one" (a transition is a 1). rule: "ones" (after n
    consecutive 1s the next bit is a stuffed 0 and is dropped), "equal"
    (after n equal bits the next is their complement and is dropped),
    None. `idle` is the level before the first slot."""

    def __init__(self, nrzi, rule, n, idle):
        self.nrzi, self.rule, self.n, self.idle = nrzi, rule, n, idle

    def decode(self, levels):
        bits, stuffed, errors = [], [], []
        prev_level = self.idle
        run, last = 0, None
        for i, level in enumerate(levels):
            if self.nrzi == "zero":
                b = 1 if level == prev_level else 0
            elif self.nrzi == "one":
                b = 0 if level == prev_level else 1
            else:
                b = level
            prev_level = level
            if self.rule is not None and run == self.n:
                want = 0 if self.rule == "ones" else 1 - last
                if b != want:
                    errors.append(f"slot {i}: stuff bit {b}, rule needs {want}")
                stuffed.append(i)
            else:
                bits.append(b)
            if self.rule == "ones":
                run = run + 1 if b else 0
            else:
                run = run + 1 if b == last else 1
            last = b
        return bits, stuffed, errors


# ---------------------------------------------------------------------------
# Harness (the same load/run discipline as test_control_space.py).
# ---------------------------------------------------------------------------
class Prog:
    def __init__(self):
        self.lines = []

    def add(self, line):
        self.lines.append(line)
        return len(self.lines) - 1

    def ldi(self, reg, value):
        return self.add(f"LDI R{reg}, {value & 0xFF:#04x}")

    def wctl(self, k, reg):
        return self.add(f"WCTL {k:#04x}, R{reg}")

    def rctl(self, reg, k):
        return self.add(f"RCTL R{reg}, {k:#04x}")

    def out(self, reg):
        return self.add(f"OUT UO_OUT, R{reg}")

    def show(self, k, reg=0, poison=0xEE):
        self.ldi(reg, poison)
        self.rctl(reg, k)
        return self.out(reg)

    def write32(self, k, value, reg=0):
        """Four byte writes at the pointer, byte 0 first."""
        for i in range(4):
            self.ldi(reg, value >> (8 * i))
            self.wctl(k, reg)

    @property
    def words(self):
        key = tuple(self.lines)
        if getattr(self, "_key", None) != key:
            program = asm.assemble_text("\n".join(self.lines) + "\n", allow_reserved=True)
            self._key, self._words = key, list(program.words)
        return list(self._words)

    def edge(self, index):
        return RUN_ENTRY_EDGES + sum(cycles(w) for w in self.words[:index])

    def end_edge(self):
        return self.edge(len(self.lines))


async def settle(dut):
    await ReadOnly()
    sample = {"uo_out": int(dut.uo_out.value), "uio_out": int(dut.uio_out.value),
              "uio_oe": int(dut.uio_oe.value)}
    await Timer(1, unit="ns")
    return sample


async def load_image(dut, words):
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = 0x80
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    for word in words:
        for bit in range(15, -1, -1):
            dut.ui_in.value = 0x80 | ((word >> bit) & 1)
            await RisingEdge(dut.clk)
    dut.ui_in.value = 0x00
    await RisingEdge(dut.clk)  # edge 0


async def run_trace(dut, words, edges, per_edge=None):
    await load_image(dut, words)
    trace = [await settle(dut)]
    for e in range(1, edges + 1):
        await RisingEdge(dut.clk)
        trace.append(await settle(dut))
        if per_edge is not None:
            per_edge(e, trace)
    return trace


def expect(trace, prog, checks, pin="uo_out"):
    for index, want, label in checks:
        e = prog.edge(index)
        got = trace[e][pin]
        assert got == want, (f"{label}: {pin} after edge {e} (instruction {index}) is "
                             f"{got:#04x}, want {want:#04x}")


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


def core(dut):
    return None if GATE_LEVEL else dut.u_core


def crc_program(name, data=None, bits=None):
    """Configure P1 for catalogue entry `name`, feed `data` with CRC_BYTE
    (or `bits` with CRC_BIT), read the result with CRC_NEXT. Returns (prog,
    [OUT indices of the CRC bytes, byte 0 first])."""
    width = CATALOGUE[name][0]
    cfg, poly, init, _ = firmware_setup(name)
    p = Prog()
    p.ldi(0, cfg)
    p.wctl(CRC_CFG, 0)
    p.write32(CRC_POLY, poly)
    p.write32(CRC_STATE, init)
    if data is not None:
        for byte in data:
            p.ldi(1, byte)
            p.wctl(CRC_BYTE, 1)
    for b in bits or []:
        p.ldi(1, 0xFE | b)       # the other seven bits must not matter
        p.wctl(CRC_BIT, 1)
    outs = [p.show(CRC_NEXT, reg=2) for _ in range((width + 7) // 8)]
    p.add("HALT")
    return p, outs


async def run_crc(dut, name, data=None, bits=None):
    p, outs = crc_program(name, data, bits)
    trace = await run_trace(dut, p.words, p.end_edge() + 2)
    got = 0
    for i, idx in enumerate(outs):
        got |= trace[p.edge(idx)]["uo_out"] << (8 * i)
    return got


# ---------------------------------------------------------------------------
@cocotb.test()
async def test_crc_catalogue_check_values(dut):
    """P1 + CRC_BYTE: each catalogue model's CRC of "123456789", read with
    CRC_NEXT, equals the catalogue's published check value (and the
    oracle's). CRC-32 is additionally equal to zlib.crc32."""
    start_clock(dut)
    data = b"123456789"
    for name, entry in CATALOGUE.items():
        got = await run_crc(dut, name, data=data)
        want = catalogue_crc(name, bits_of(data, entry[3]))
        assert want == entry[6]
        assert got == want, f"{name}: design {got:#x}, catalogue check {want:#x}"
        if name == "CRC-32/ISO-HDLC":
            assert got == zlib.crc32(data)
        dut._log.info(f"{name}: check {got:#x} as catalogued")


@cocotb.test()
async def test_crc_random_messages(dut):
    """P1 + CRC_BYTE over random messages for every model, graded by the
    oracle; CRC-32 and CRC-16/XMODEM also by zlib / binascii."""
    start_clock(dut)
    rnd = random.Random(208001)
    for name, entry in CATALOGUE.items():
        for _ in range(3):
            data = bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 12)))
            got = await run_crc(dut, name, data=data)
            want = catalogue_crc(name, bits_of(data, entry[3]))
            assert got == want, f"{name} {data.hex()}: design {got:#x}, oracle {want:#x}"
            if name == "CRC-32/ISO-HDLC":
                assert got == zlib.crc32(data)
            if name == "CRC-16/XMODEM":
                assert got == binascii.crc_hqx(data, 0)


@cocotb.test()
async def test_crc_bit_steps(dut):
    """P1 + CRC_BIT: the CRC of an arbitrary-length bit stream (not a
    whole number of bytes), e.g. a USB token's 11 address/endpoint bits
    under CRC-5/USB and a CAN frame's bit stream under CRC-15/CAN, equals
    the oracle's. Only bit 0 of Rs is used."""
    start_clock(dut)
    rnd = random.Random(208002)
    # USB token: ADDR = 0x15, ENDP = 0xE (11 bits, LSB first).
    token = [0x15 >> i & 1 for i in range(7)] + [0xE >> i & 1 for i in range(4)]
    cases = [("CRC-5/USB", token)]
    for name in ("CRC-15/CAN", "CRC-5/USB", "CRC-16/USB", "CRC-8/MAXIM-DOW"):
        cases.append((name, [rnd.randrange(2) for _ in range(rnd.randrange(1, 30))]))
    for name, bits in cases:
        got = await run_crc(dut, name, bits=bits)
        want = catalogue_crc(name, bits)
        assert got == want, f"{name} bits {bits}: design {got:#x}, oracle {want:#x}"


@cocotb.test()
async def test_lfsr_prbs(dut):
    """P1 with data 0 is a Galois LFSR. PRBS7 (x^7 + x^6 + 1): the state
    after every step equals seed * x^n mod G (polynomial arithmetic), all
    127 states are distinct and non-zero, and step 127 returns to the
    seed. A 16-bit LFSR (x^16 + x^14 + x^13 + x^11 + 1) is checked the same
    way over 40 steps, reading both state bytes."""
    start_clock(dut)
    # PRBS7: one loop of 128 steps reading the state each step.
    g7, seed = (1 << 7) | 0x41, 0x01
    p = Prog()
    p.ldi(0, 6)                       # width 7, normal, no inversion
    p.wctl(CRC_CFG, 0)
    p.write32(CRC_POLY, 0x41)
    p.write32(CRC_STATE, seed)
    p.ldi(0, 0)                       # data bit 0
    p.ldi(3, 128)                     # step counter
    p.ldi(2, 1)
    top = len(p.lines)
    first = p.wctl(CRC_BIT, 0)
    p.ldi(1, 6)
    p.wctl(CRC_CFG, 1)                # rewind the pointer
    p.rctl(1, CRC_STATE)
    out = p.out(1)
    p.add("SUB R3, R2")
    p.add(f"BNZ {top}")
    p.add("HALT")
    body = sum(cycles(w) for w in p.words[top:top + 7])
    assert body == 7
    trace = await run_trace(dut, p.words, p.edge(top) + 128 * body + 4)
    states = [trace[p.edge(out) + n * body]["uo_out"] for n in range(128)]
    for n, s in enumerate(states, start=1):
        assert s == gf2_mulx_mod(seed, n, g7), f"PRBS7 step {n}: {s:#x}"
    assert len(set(states[:127])) == 127 and 0 not in states, "PRBS7 period is not 127"
    assert states[126] == seed, "PRBS7 does not return to its seed after 127 steps"
    del first

    # 16-bit: straight-line, 40 steps.
    g16, seed16 = (1 << 16) | 0x6801, 0xACE1
    p = Prog()
    p.ldi(0, 15)
    p.wctl(CRC_CFG, 0)
    p.write32(CRC_POLY, 0x6801)
    p.write32(CRC_STATE, seed16)
    p.ldi(1, 0xFE)                    # bit 0 is 0; the rest must not matter
    p.ldi(3, 15)                      # CRC_CFG, to rewind the pointer
    reads = []
    for n in range(1, 41):
        p.wctl(CRC_BIT, 1)
        if n % 8 == 0:
            p.wctl(CRC_CFG, 3)
            reads.append((n, p.show(CRC_STATE, reg=2), p.show(CRC_STATE, reg=2)))
    p.add("HALT")
    trace = await run_trace(dut, p.words, p.end_edge() + 2)
    for n, lo, hi in reads:
        got = trace[p.edge(lo)]["uo_out"] | trace[p.edge(hi)]["uo_out"] << 8
        assert got == gf2_mulx_mod(seed16, n, g16), f"LFSR16 step {n}: {got:#06x}"


@cocotb.test()
async def test_crc_registers_pointer_and_masking(dut):
    """Reset values, readback and the byte pointer: CRC_CFG reads back its
    7 bits; CRC_POLY reads back all four bytes, the pointer wraps after
    byte 3 and a CRC_CFG write rewinds it; CRC_STATE and CRC_NEXT mask to
    the width (bits above W read 0) and CRC_NEXT complements only the low
    W bits; a step in reflected mode never pulls state bits from above the
    width; CRC_NEXT writes and CRC_STATE reads still advance only as the
    table says."""
    start_clock(dut)
    p = Prog()
    checks = []
    # Reset: everything reads 0, each register at byte 0 (CRC_CFG reads 0,
    # i.e. width 1, so byte 0 bit 0 is the whole visible state; writing
    # that same 0 back rewinds the pointer between reads).
    p.ldi(3, 0x00)
    for k in (CRC_CFG, CRC_STATE, CRC_POLY, CRC_NEXT):
        checks.append((p.show(k), 0x00, f"reset value of {k:#04x}"))
        p.wctl(CRC_CFG, 3)
    p.ldi(0, 0x55)                    # bit 7 ignored, so 0x55 reads back 0x55
    p.wctl(CRC_CFG, 0)
    checks.append((p.show(CRC_CFG), 0x55, "CRC_CFG readback"))
    p.ldi(0, 0xD5)
    p.wctl(CRC_CFG, 0)
    checks.append((p.show(CRC_CFG), 0x55, "CRC_CFG bit 7 is not stored"))
    p.write32(CRC_POLY, 0x89ABCDEF)
    for i, b in enumerate((0xEF, 0xCD, 0xAB, 0x89, 0xEF)):
        checks.append((p.show(CRC_POLY), b, f"CRC_POLY byte {i % 4} (pointer wraps)"))
    p.ldi(0, 0x1F)                    # width 32, normal, rewind (pointer was at 1)
    p.wctl(CRC_CFG, 0)
    checks.append((p.show(CRC_POLY), 0xEF, "CRC_CFG write rewinds the pointer"))
    # Width 12 (wm1 = 11) with inversion: STATE 0xFFFFFFFF reads 0xFF, 0x0F, 0, 0.
    p.ldi(0, 0x4B)
    p.wctl(CRC_CFG, 0)
    p.write32(CRC_STATE, 0xFFFFF5A5)
    for i, b in enumerate((0xA5, 0x05, 0x00, 0x00)):
        checks.append((p.show(CRC_STATE), b, f"CRC_STATE byte {i} masked to width 12"))
    for i, b in enumerate((0x5A, 0x0A, 0x00, 0x00)):
        checks.append((p.show(CRC_NEXT), b, f"CRC_NEXT byte {i}: low 12 bits complemented"))
    # Writes to read-only CRC_NEXT and reads of write-only CRC_BIT/BYTE
    # neither change state nor move the pointer.
    p.ldi(0, 0x00)
    p.wctl(CRC_NEXT, 0)
    for k in (CRC_BIT, CRC_BYTE):
        checks.append((p.show(k, poison=0x77), 0x00, f"read of write-only {k:#04x}"))
    checks.append((p.show(CRC_STATE), 0xA5, "pointer unmoved by the no-op accesses"))
    # Reflected, width 4, poly 0: state 0xFFFFFFF8 (bits above W set), one
    # step with d = 0 is ((S & M) >> 1) = 0b0100, so bit 4 never enters.
    p.ldi(0, 0x23)
    p.wctl(CRC_CFG, 0)
    p.write32(CRC_POLY, 0)
    p.write32(CRC_STATE, 0xFFFFFFF8)
    p.ldi(1, 0)
    p.wctl(CRC_BIT, 1)
    checks.append((p.show(CRC_STATE), 0x04, "reflected step masks the shift-in"))
    # Normal, width 4, poly 0: bits only move up; the read masks them.
    p.ldi(0, 0x03)
    p.wctl(CRC_CFG, 0)
    p.write32(CRC_STATE, 0x0000000F)
    p.wctl(CRC_BIT, 1)
    checks.append((p.show(CRC_STATE), 0x0E, "normal step: bit 4 hidden by the mask"))
    p.add("HALT")
    c = core(dut)
    if c is not None:
        # White-box (RTL only): all 32 bits of POLY and STATE clear in reset,
        # including the bits a width-1 read cannot show.
        dut.ena.value = 1
        dut.ui_in.value = 0x80
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 3)
        await ReadOnly()
        for name in ("crc_state", "crc_poly", "crc_wm1", "crc_refl", "crc_inv", "crc_ptr",
                     "line_cfg", "line_lvl", "line_prev", "line_cnt", "line_stuf"):
            assert int(getattr(c, name).value) == 0, f"{name} must reset to 0"
        await Timer(1, unit="ns")
    trace = await run_trace(dut, p.words, p.end_edge() + 2)
    expect(trace, p, checks)


# ---------------------------------------------------------------------------
# P2
# ---------------------------------------------------------------------------
def line_cfg(nrzi, rule, n, level):
    m = {"none": 0, "zero": 1, "one": 2}[nrzi]
    r = {None: 0, "ones": 1, "equal": 2}[rule]
    return m | r << 2 | (n & 7) << 4 | (level & 1) << 7


def line_program(cfg, slots):
    """A program that runs `slots` fixed-length slots. In each slot it
    reads the data bit the bench presents on ui_in[0], LINE_PUTs it, and
    shows {stuffed, ~level, level} on uo_out[2:0] with a toggling strobe
    on uo_out[7]. The bench plays the firmware's shifter: it advances to
    the next data bit only when the slot it saw had LINE_STUF = 0."""
    p = Prog()
    p.ldi(0, cfg)
    p.wctl(LINE_CFG, 0)
    p.ldi(3, 0x00)                    # strobe
    p.ldi(0, 0x80)
    top = len(p.lines)
    p.add("XOR R3, R0")               # flip the strobe
    sample = p.add("IN R1, UI_IN")
    p.wctl(LINE_PUT, 1)
    p.rctl(1, LINE_OUT)
    p.rctl(2, LINE_STUF)
    p.add("SHF R2, LEFT")
    p.add("SHF R2, LEFT")
    p.add("OR R1, R2")
    p.add("OR R1, R3")
    out = p.out(1)
    p.add(f"JMP {top}")
    body = sum(cycles(w) for w in p.words[top:top + 11])
    return p, sample, out, body


async def run_line(dut, cfg, data, idle):
    """Drive `data` through P2; return (levels per slot, stuff flags per
    slot). Slots continue until every data bit was consumed."""
    p, sample, out, body = line_program(cfg, len(data))
    words = p.words
    state = {"i": 0, "levels": [], "stuffs": []}
    first_sample = p.edge(sample)
    first_out = p.edge(out)

    def present():
        i = state["i"]
        dut.ui_in.value = data[i] if i < len(data) else 0

    nslots = 2 * len(data) + 4
    await load_image(dut, words)
    present()
    for e in range(1, first_out + nslots * body + 1):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if e >= first_out and (e - first_out) % body == 0:
            v = int(dut.uo_out.value)
            slot = (e - first_out) // body
            assert (v >> 7 & 1) == ((slot + 1) & 1), f"slot {slot}: strobe out of step"
            assert (v >> 1 & 1) == 1 - (v & 1), "LINE_OUT bit 1 is not the complement of bit 0"
            if state["i"] < len(data):
                state["levels"].append(v & 1)
                state["stuffs"].append(v >> 2 & 1)
                if not v >> 2 & 1:
                    state["i"] += 1
            await Timer(1, unit="ns")
            present()
        else:
            await Timer(1, unit="ns")
        if state["i"] >= len(data) and e >= first_out and (e - first_out) % body == 0:
            break
    assert state["i"] == len(data), "not every data bit was consumed"
    del first_sample
    return state["levels"], state["stuffs"]


def _usb_data(rnd, n):
    """SYNC (KJKJKJKK = 0000_0001 LSB first: seven 0s then a 1) followed by
    payload bits with long runs of 1s, so stuffing happens often."""
    sync = [0, 0, 0, 0, 0, 0, 0, 1]
    payload = []
    while len(payload) < n:
        payload += [1] * rnd.choice([1, 5, 6, 7, 12]) + [rnd.randrange(2)]
    return sync + payload[:n]


async def _grade(dut, label, cfg, decoder, data):
    levels, stuffs = await run_line(dut, cfg, data, decoder.idle)
    bits, stuffed_slots, errors = decoder.decode(levels)
    assert not errors, f"{label}: decoder found stuffing violations {errors}"
    assert bits == data, f"{label}: decoded {bits} != sent {data}"
    flagged = [i for i, s in enumerate(stuffs) if s]
    assert flagged == stuffed_slots, (f"{label}: LINE_STUF flagged slots {flagged}, "
                                      f"the decoder found stuff bits in {stuffed_slots}")
    return len(stuffed_slots)


@cocotb.test()
async def test_line_usb_nrzi_stuff6(dut):
    """USB: zero-toggles NRZI with a 0 stuffed after six 1s, idle level J
    (taken as level 1 here). The run count starts at the SYNC (so the last
    1 of SYNC counts), and the independent decoder recovers the data and
    finds the stuff bits exactly where LINE_STUF said."""
    start_clock(dut)
    rnd = random.Random(208010)
    data = _usb_data(rnd, 60)
    n = await _grade(dut, "USB", line_cfg("zero", "ones", 6, 1),
                     LineDecoder("zero", "ones", 6, idle=1), data)
    assert n >= 4, f"test premise: stuffing exercised ({n} stuff bits)"


@cocotb.test()
async def test_line_hdlc_stuff5(dut):
    """HDLC/PPP: NRZ, a 0 stuffed after five 1s; and the same rule under
    NRZI that toggles on a 1, graded by the decoder in that mode."""
    start_clock(dut)
    rnd = random.Random(208011)
    data = [0, 1, 1, 1, 1, 1, 1, 0] + [rnd.choice([0, 1, 1, 1]) for _ in range(50)]
    n = await _grade(dut, "HDLC NRZ", line_cfg("none", "ones", 5, 1),
                     LineDecoder("none", "ones", 5, idle=1), data)
    assert n >= 3
    await _grade(dut, "HDLC one-toggles", line_cfg("one", "ones", 5, 0),
                 LineDecoder("one", "ones", 5, idle=0), data)


@cocotb.test()
async def test_line_can_stuff5_equal(dut):
    """CAN: NRZ, after five equal bits of either polarity the complement is
    stuffed; the stuff bit starts a new run."""
    start_clock(dut)
    rnd = random.Random(208012)
    data = [0] * 9 + [1] * 11 + [rnd.choice([0, 0, 1, 1, 1]) for _ in range(40)]
    n = await _grade(dut, "CAN", line_cfg("none", "equal", 5, 1),
                     LineDecoder("none", "equal", 5, idle=1), data)
    assert n >= 3, f"test premise: stuffing exercised ({n} stuff bits)"


@cocotb.test()
async def test_line_stuff_slot_ignores_rs_and_registers(dut):
    """A stuff slot emits the stuff bit whatever Rs holds (CAN: after five
    0s, a 0 is presented and the line shows 1); LINE_STUF reads 1 for that
    slot and 0 for the next, which consumes. Reset values (LINE_CFG 0,
    LINE_OUT {1, 0}, LINE_STUF 0), LINE_CFG readback (bit 7 loads the level
    and reads 0), a LINE_CFG write clears the stuffed flag and the run
    count, read-only LINE_OUT / LINE_STUF ignore writes, write-only LINE_PUT
    reads 0, and stuffing off never stuffs."""
    start_clock(dut)
    p = Prog()
    checks = []
    checks.append((p.show(LINE_CFG), 0x00, "LINE_CFG reset"))
    checks.append((p.show(LINE_OUT), 0x02, "LINE_OUT reset: level 0, complement 1"))
    checks.append((p.show(LINE_STUF), 0x00, "LINE_STUF reset"))
    checks.append((p.show(LINE_PUT, poison=0x77), 0x00, "read of write-only LINE_PUT"))
    p.ldi(0, line_cfg("none", "equal", 5, 1))
    p.wctl(LINE_CFG, 0)
    checks.append((p.show(LINE_CFG), line_cfg("none", "equal", 5, 0), "LINE_CFG readback"))
    checks.append((p.show(LINE_OUT), 0x01, "LINE_CFG bit 7 loaded level 1"))
    p.ldi(1, 0xFE)                    # data bit 0 (bit 0 of 0xFE)
    for _ in range(5):
        p.wctl(LINE_PUT, 1)
    checks.append((p.show(LINE_STUF), 0x00, "five data bits: no stuff yet"))
    p.wctl(LINE_PUT, 1)               # presents 0, but this is a stuff slot
    checks.append((p.show(LINE_OUT), 0x01, "stuff slot emits 1 although Rs[0] is 0"))
    checks.append((p.show(LINE_STUF), 0x01, "LINE_STUF set for the stuff slot"))
    p.ldi(0, 0x00)
    p.wctl(LINE_OUT, 0)
    p.wctl(LINE_STUF, 0)
    checks.append((p.show(LINE_STUF), 0x01, "LINE_STUF ignores a write"))
    p.wctl(LINE_PUT, 1)
    checks.append((p.show(LINE_OUT), 0x02, "the next slot consumes the 0"))
    checks.append((p.show(LINE_STUF), 0x00, "LINE_STUF clear after a data slot"))
    for _ in range(4):
        p.wctl(LINE_PUT, 1)           # 0s 2..5 after the stuff 1
    p.ldi(0, line_cfg("none", "equal", 5, 0))
    p.wctl(LINE_CFG, 0)               # clears the run count
    for _ in range(5):
        p.wctl(LINE_PUT, 1)
    checks.append((p.show(LINE_STUF), 0x00, "run count cleared by LINE_CFG"))
    p.wctl(LINE_PUT, 1)
    checks.append((p.show(LINE_STUF), 0x01, "stuff after 5 more equal bits"))
    p.ldi(0, line_cfg("none", "equal", 5, 0))
    p.wctl(LINE_CFG, 0)
    checks.append((p.show(LINE_STUF), 0x00, "LINE_CFG clears LINE_STUF"))
    p.ldi(0, line_cfg("zero", None, 1, 0))
    p.wctl(LINE_CFG, 0)
    p.ldi(1, 0x01)
    for _ in range(9):
        p.wctl(LINE_PUT, 1)
    checks.append((p.show(LINE_STUF), 0x00, "stuffing off: never a stuff slot"))
    checks.append((p.show(LINE_OUT), 0x02, "zero-toggles: 1s hold the level"))
    p.add("HALT")
    trace = await run_trace(dut, p.words, p.end_edge() + 2)
    expect(trace, p, checks)


# ---------------------------------------------------------------------------
# Latency, flags, unassigned indices
# ---------------------------------------------------------------------------
LATENCY_SEQ = [("w", CRC_CFG), ("w", CRC_POLY), ("w", CRC_STATE), ("w", CRC_BIT), ("w", CRC_BYTE),
           ("r", CRC_NEXT), ("r", CRC_STATE), ("r", CRC_POLY), ("r", CRC_CFG), ("w", LINE_CFG),
           ("w", LINE_PUT), ("r", LINE_OUT), ("r", LINE_STUF), ("r", LINE_CFG), ("w", 0x1A),
           ("r", 0x1F), ("w", CRC_BYTE), ("w", CRC_BYTE)]


def _latency_program(vals):
    """Every new access, with marker OUTs between them; `vals` changes
    only data, never the instruction stream's shape."""
    p = Prog()
    marks = []
    for n, (d, k) in enumerate(LATENCY_SEQ):
        p.ldi(1, vals[n % len(vals)])
        if d == "w":
            p.wctl(k, 1)
        else:
            p.rctl(2, k)
        p.ldi(0, n + 1)
        marks.append((p.out(0), n + 1))
    p.add("HALT")
    return p, marks


@cocotb.test()
async def test_fixed_latency_is_data_independent(dut):
    """Every new index has the latency DR 0015's table fixes -- 9 for WCTL
    CRC_BYTE, 1 for everything else -- and the same program over four data
    sets (CRC on or off, every config bit pattern, line levels, stuff slots)
    moves uo_out on identical edges."""
    start_clock(dut)
    data_sets = [[0x00], [0xFF], [0x5A, 0xA5, 0x3C, 0xC3, 0x01, 0x80], [0x7F, 0x6F, 0x2E, 0x91]]
    change_edges = []
    for vals in data_sets:
        p, marks = _latency_program(vals)
        n = p.end_edge() + 3
        trace = await run_trace(dut, p.words, n)
        prev = 0
        for idx, value in marks:
            e = p.edge(idx)
            assert trace[e]["uo_out"] == value and trace[e - 1]["uo_out"] == prev, (
                f"data {vals}: marker {value} not exactly on edge {e}")
            prev = value
        gaps = [p.edge(marks[i + 1][0]) - p.edge(marks[i][0]) for i in range(len(marks) - 1)]
        # marker to marker: OUT (1) + LDI (1) + the access + LDI (1)
        want = [3 + (9 if (d, k) == ("w", CRC_BYTE) else 1) for d, k in LATENCY_SEQ[1:]]
        assert gaps == want, f"marker spacing {gaps} != {want}"
        change_edges.append([e for e in range(1, n + 1)
                             if trace[e]["uo_out"] != trace[e - 1]["uo_out"]])
    assert all(c == change_edges[0] for c in change_edges), "pin timing depends on data"


@cocotb.test()
async def test_no_flag_side_effects_and_unassigned(dut):
    """No new access changes Z or C (a BZ after the block follows the Z set
    before it; white-box flag reads in an RTL run), and the six indices
    0x1A-0x1F stay unassigned: writes change nothing, reads return 0x00."""
    start_clock(dut)
    c = core(dut)
    for z in (1, 0):
        p = Prog()
        p.ldi(0, 0x80 if z else 0x01)
        p.ldi(1, 0x80 if z else 0x01)
        p.add("ADD R0, R1")
        start = len(p.lines)
        p.ldi(1, 0x7F)
        for k in (CRC_CFG, CRC_POLY, CRC_STATE, CRC_BIT, CRC_BYTE, LINE_CFG, LINE_PUT) + UNASSIGNED:
            p.wctl(k, 1)
        for k in (CRC_CFG, CRC_POLY, CRC_STATE, CRC_NEXT, LINE_CFG, LINE_OUT, LINE_STUF):
            p.rctl(2, k)              # some non-zero, some zero
        for k in UNASSIGNED:
            p.ldi(3, 0x77)
            p.rctl(3, k)
            p.out(3)
        br = p.add("BZ 0")
        p.ldi(0, 0x11)
        p.out(0)
        p.add("HALT")
        taken = p.ldi(0, 0x22)
        p.out(0)
        p.add("HALT")
        p.lines[br] = f"BZ {taken}"
        words = p.words
        seen = []

        def watch(e, trace, p=p, start=start, br=br):
            if c is not None and p.edge(start) <= e <= p.edge(br):
                seen.append((int(c.flag_z.value), int(c.flag_c.value)))

        trace = await run_trace(dut, words, p.edge(len(p.lines)) + 30, per_edge=watch)
        final = trace[-1]["uo_out"]
        assert final == (0x22 if z else 0x11), f"Z={z}: branch went the wrong way"
        outs = [i for i, line in enumerate(p.lines[:br]) if line.startswith("OUT")]
        for i in outs:
            assert trace[p.edge(i)]["uo_out"] == 0x00, "a read of 0x1A-0x1F returned non-zero"
        if c is not None:
            assert seen and all(s == (z, z) for s in seen), f"flags moved: {set(seen)}"
