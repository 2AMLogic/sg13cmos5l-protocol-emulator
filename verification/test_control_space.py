"""cocotb bench for DR 0012's control space on
`tt_um_2amlogic_protocol_emulator` (issue #135).

`spec/decision-records/0012-control-space-and-runtime-pin-direction.md`
gives two of DR 0001's no-op encodings a meaning -- `WCTL k, Rs` (OUT to
port 00, imm8 = k) and `RCTL Rd, k` (IN from port 10, imm8 = k) -- and
defines ten control registers behind them. This bench is that record's
"control-register bench" verification obligation, plus issue #135's
program-memory round trip and CRC check:

- **reset values**: every register reads as DR 0012 says it resets
  ("everything is an input"), and `uio_oe` is 0 from reset until a program
  writes a pin-mode register;
- **readback** of every read/write register, and the **pin-mode logic**
  (`UIO_OD` wins, then `UIO_DIR`, else input) checked at `uio_oe` against
  the rule written out independently here;
- **reserved-index behaviour**: a write to an unassigned or read-only index
  changes nothing, a read of an unassigned or write-only index returns
  0x00, both in exactly 1 cycle; and the two encodings DR 0012 keeps
  reserved (OUT port 01, IN port 11) stay no-ops whatever their imm8;
- **the fixed stall**: `WCTL PM_DATA_LO`, `RCTL PM_DATA_HI` and `WCTL RUN`
  cost exactly 2 cycles and every other access exactly 1, whatever data is
  involved -- the same program run over different data moves its pins on
  the same edges;
- **no flag side effects**: no control access changes Z or C;
- **program memory**: words written through `PM_ADDR`/`PM_DATA_*` read back
  through the same registers, leave their neighbours alone, auto-increment
  and wrap the address, are executed by the core when jumped to with `RUN`,
  and a write to the word fetched next takes effect;
- **PM_CRC** against an independent CRC-16/XMODEM, Python's
  `binascii.crc_hqx` (not this repository's own arithmetic), over the
  serial load, over `PM_DATA_LO` writes, over both together ("by any
  path"), and across both clear registers;
- **the I2C preamble** the committed I2C images gained: after it, the two
  open-drain pins only ever pull low or release.

How values are observed. Programs are real firmware, loaded over the real
serial load phase and assembled by the DR 0003 assembler
(`firmware/tools/asm.py`). A register value reaches the bench by
`RCTL Rd, k` followed by `OUT UO_OUT, Rd`, sampled at the pin on the edge
that instruction-position arithmetic predicts. That arithmetic uses this
file's **own** copy of the latency table (`cycles()` below, written from DR
0012's table), not the assembler's, so an assembler/RTL agreement on a
wrong latency would still fail here.

White-box reads (`dut.u_core.flag_z` / `flag_c`, the reset-time register
values before any program can run) are used only where no pin shows the
fact, and only in an RTL run. Under the gate-level Makefile (`GATES=yes`,
`flow/run-firmware-gate-level.sh`) the hierarchy is gone, those reads are
skipped, and every other check still runs, because it is pin-only.

This bench says nothing about pads: `uio_oe` is checked as the logic
output it is. The silicon-true pad model, and the I2C evidence re-run on
it, are issue #136. The load-phase CRC readout on `uo_out` is issue #137
and the boot ROM is issue #138; neither is exercised here.

All programs and data are fixed in source or drawn from `random.Random`
with the literal seeds below, so every run is byte-reproducible.
"""

import binascii
import os
import random
import sys
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

# DR 0012 section 2, written out here independently of asm.py / the RTL.
UIO_DIR, UIO_OD, PM_ADDR, PM_DATA_HI, PM_DATA_LO = 0x00, 0x01, 0x02, 0x03, 0x04
RUN, PM_CRC_LO, PM_CRC_HI, BOOT_STATUS, HW_ID = 0x05, 0x06, 0x07, 0x08, 0x09
HW_ID_VALUE = 0x01  # rtl/protocol_core.v's HW_ID parameter default

OP_IN, OP_OUT, OP_WAIT = 0x9, 0xA, 0xB


def cycles(word):
    """This bench's statement of the latency table: DR 0001's (1, or
    imm8+1 for WAIT) with DR 0012's three fixed 2-cycle control accesses."""
    op, port, k = word >> 12, (word >> 8) & 3, word & 0xFF
    if op == OP_WAIT:
        return k + 1
    if op == OP_OUT and port == 0 and k in (PM_DATA_LO, RUN):
        return 2
    if op == OP_IN and port == 2 and k == PM_DATA_HI:
        return 2
    return 1


def crc_of_words(words, crc=0):
    """CRC-16/XMODEM of `words` as a big-endian byte string, by the Python
    standard library -- the independent reference DR 0012 names."""
    data = b"".join(bytes(((w >> 8) & 0xFF, w & 0xFF)) for w in words)
    return binascii.crc_hqx(data, crc)


def pin_mode_oe(uio_out, uio_dir, uio_od):
    """DR 0012 "Pin mode, per uio[n]", bit by bit, as the record words it."""
    oe = 0
    for n in range(8):
        out_n, dir_n, od_n = (uio_out >> n) & 1, (uio_dir >> n) & 1, (uio_od >> n) & 1
        if od_n:
            bit = 0 if out_n else 1      # open-drain: drive low on 0, release on 1
        elif dir_n:
            bit = 1                      # push-pull
        else:
            bit = 0                      # input
        oe |= bit << n
    return oe


class Prog:
    """A straight-line program builder that remembers which instruction
    index each line of interest landed on, so a test can ask for the edge
    at which that instruction retires."""

    def __init__(self):
        self.lines = []
        self.raw_words = {}  # index -> raw word (encodings the assembler refuses)

    def add(self, line):
        self.lines.append(line)
        return len(self.lines) - 1

    def raw(self, word):
        """An instruction word the assembler rejects on purpose (the
        reserved no-op encodings). Assembled as a NOP, then patched."""
        idx = self.add("NOP")
        self.raw_words[idx] = word
        return idx

    def ldi(self, reg, value):
        return self.add(f"LDI R{reg}, {value:#04x}")

    def wctl(self, k, reg):
        return self.add(f"WCTL {k:#04x}, R{reg}")

    def rctl(self, reg, k):
        return self.add(f"RCTL R{reg}, {k:#04x}")

    def out(self, reg):
        """OUT UO_OUT, Rn -- returns the index whose retire edge shows the value."""
        return self.add(f"OUT UO_OUT, R{reg}")

    def show(self, k, reg=0, poison=0xEE):
        """LDI Rn, poison; RCTL Rn, k; OUT UO_OUT, Rn. The poison makes a
        read that silently did nothing visible. Returns the OUT's index."""
        self.ldi(reg, poison)
        self.rctl(reg, k)
        return self.out(reg)

    def write_word(self, word, reg=0):
        """Commit one word at PM_ADDR through the data registers."""
        self.ldi(reg, (word >> 8) & 0xFF)
        self.wctl(PM_DATA_HI, reg)
        self.ldi(reg, word & 0xFF)
        return self.wctl(PM_DATA_LO, reg)

    @property
    def words(self):
        key = (tuple(self.lines), tuple(sorted(self.raw_words.items())))
        if getattr(self, "_key", None) != key:
            program = asm.assemble_text("\n".join(self.lines) + "\n", allow_reserved=True)
            assert program.warnings == [], program.warnings
            words = list(program.words)
            for idx, word in self.raw_words.items():
                words[idx] = word
            self._key, self._words = key, words
        return list(self._words)

    def edge(self, index):
        """The rising edge (counted from the MODE-drop edge = 0) on which
        instruction `index` begins to retire: after it, a 1-cycle
        instruction's effect is visible."""
        words = self.words
        return RUN_ENTRY_EDGES + sum(cycles(w) for w in words[:index])

    def end_edge(self):
        return self.edge(len(self.lines))


async def settle(dut):
    await ReadOnly()
    sample = {
        "uo_out": int(dut.uo_out.value),
        "uio_out": int(dut.uio_out.value),
        "uio_oe": int(dut.uio_oe.value),
    }
    await Timer(1, unit="ns")
    return sample


async def load_image(dut, words, uio_in=0x00):
    """Reset with MODE high, shift `words` in MSB-first on ui_in[0], drop
    MODE. Returns right after the MODE-drop edge (edge 0). Asserts uio_oe
    is 0 on every load edge: nothing drives a uio pin before a program
    asks for it (DR 0012 reset values)."""
    dut.ena.value = 1
    dut.uio_in.value = uio_in
    dut.ui_in.value = 0x80
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    assert int(dut.uio_oe.value) == 0, "uio_oe must be 0 in reset"
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)  # the mode-sampling edge
    for word in words:
        for bit in range(15, -1, -1):
            dut.ui_in.value = 0x80 | ((word >> bit) & 1)
            await RisingEdge(dut.clk)
    assert int(dut.uio_oe.value) == 0, "uio_oe must stay 0 through the load phase"
    dut.ui_in.value = 0x00  # MODE drop
    await RisingEdge(dut.clk)  # edge 0


async def run_trace(dut, words, edges, uio_in=0x00, per_edge=None):
    """Load `words`, then return `trace` with trace[e] = the pins after
    edge e, for e in 1..edges (trace[0] is after the MODE-drop edge).
    `per_edge(e)` runs just after edge e's sample, if given."""
    await load_image(dut, words, uio_in=uio_in)
    trace = [await settle(dut)]
    for e in range(1, edges + 1):
        await RisingEdge(dut.clk)
        trace.append(await settle(dut))
        if per_edge is not None:
            per_edge(e)
    return trace


def expect(trace, prog, checks, pin="uo_out"):
    """`checks` is [(instruction index, expected value, label)]: the pin
    must read `expected` after that instruction's retire edge."""
    for index, want, label in checks:
        e = prog.edge(index)
        got = trace[e][pin]
        assert got == want, (
            f"{label}: {pin} after edge {e} (instruction {index}) is "
            f"{got:#04x}, want {want:#04x}"
        )


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


def core(dut):
    """The core's hierarchy handle for the few white-box reads, or None at
    gate level. An RTL run that cannot find it is an error, not a skip."""
    if GATE_LEVEL:
        return None
    return dut.u_core


# ---------------------------------------------------------------------------
@cocotb.test()
async def test_reset_values_and_identity(dut):
    """DR 0012 "Reset values: everything is an input": after reset and a
    serial load, UIO_DIR, UIO_OD, PM_ADDR and the low-byte latch read 0;
    BOOT_STATUS reads 0x01 (a serial load completed; not in a boot ROM);
    HW_ID reads its constant; PM_CRC already holds the CRC of the image
    that was just serially loaded; and uio_oe is 0 from reset to HALT."""
    start_clock(dut)
    p = Prog()
    order = [
        (UIO_DIR, 0x00, "UIO_DIR reset"),
        (UIO_OD, 0x00, "UIO_OD reset"),
        (PM_ADDR, 0x00, "PM_ADDR reset"),
        (PM_DATA_LO, 0x00, "PM_DATA_LO latch reset"),
        (BOOT_STATUS, 0x01, "BOOT_STATUS after a serial load"),
        (HW_ID, HW_ID_VALUE, "HW_ID"),
    ]
    checks = [(p.show(k), want, label) for k, want, label in order]
    crc_lo = p.show(PM_CRC_LO)
    crc_hi = p.show(PM_CRC_HI)
    p.add("HALT")
    words = p.words
    crc = crc_of_words(words)
    assert crc != 0, "test premise: the image's CRC is not the cleared value"
    checks += [(crc_lo, crc & 0xFF, "PM_CRC_LO over the serial load"),
               (crc_hi, crc >> 8, "PM_CRC_HI over the serial load")]

    # White-box: the reset values before any program has run (RTL only).
    c = core(dut)
    if c is not None:
        dut.ena.value = 1
        dut.ui_in.value = 0x80
        dut.uio_in.value = 0
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 3)
        await ReadOnly()
        for name in ("uio_dir", "uio_od", "pm_addr_r", "pm_hi", "pm_lo",
                     "ctl_stall", "stall_pmrd", "stall_run"):
            assert int(getattr(c, name).value) == 0, f"{name} must reset to 0"
        assert int(dut.u_prog_mem.pm_crc.value) == 0, "PM_CRC must reset to 0"
        assert int(dut.u_prog_mem.serial_loaded.value) == 0, "BOOT_STATUS[0] must reset to 0"
        await Timer(1, unit="ns")

    trace = await run_trace(dut, words, p.end_edge() + 3)
    expect(trace, p, checks)
    assert all(s["uio_oe"] == 0 for s in trace), "uio_oe moved without a pin-mode write"
    assert all(s["uio_out"] == 0 for s in trace), "uio_out moved without an OUT"


@cocotb.test()
async def test_readback_and_pin_mode_logic(dut):
    """Every read/write register reads back what was written, and uio_oe
    follows DR 0012's pin-mode rule on the edge the write retires: OD wins
    over DIR, an OD pin drives only while its uio_out bit is 0, and a
    later OUT to uio_out moves an OD pin's enable with it."""
    start_clock(dut)
    p = Prog()
    checks = []
    oe_checks = []
    state = {"out": 0x00, "dir": 0x00, "od": 0x00}

    def step(kind, value):
        p.ldi(1, value)
        if kind == "out":
            idx = p.add("OUT UIO_OUT, R1")
        else:
            idx = p.wctl(UIO_DIR if kind == "dir" else UIO_OD, 1)
        state[kind] = value
        oe_checks.append((idx, pin_mode_oe(state["out"], state["dir"], state["od"]),
                          f"uio_oe after {kind}={value:#04x} "
                          f"(out={state['out']:#04x} dir={state['dir']:#04x} od={state['od']:#04x})"))
        if kind != "out":
            checks.append((p.show(UIO_DIR if kind == "dir" else UIO_OD), value,
                           f"{'UIO_DIR' if kind == 'dir' else 'UIO_OD'} readback {value:#04x}"))

    for kind, value in [
        ("dir", 0xA5), ("dir", 0x5A), ("dir", 0xFF), ("dir", 0x0F),
        ("out", 0x33),                 # push-pull enables do not depend on the data
        ("od", 0xC3),                  # OD on pins also set in DIR, and on pins not set
        ("out", 0xFF), ("out", 0x00),  # OD pins release / drive with the data
        ("out", 0x81),
        ("od", 0xFF), ("dir", 0x00),   # all open-drain
        ("out", 0x7E), ("od", 0x00),   # back to inputs
        ("dir", 0x00), ("od", 0x81), ("out", 0x80), ("out", 0x01),
    ]:
        step(kind, value)

    # PM_ADDR and the HI latch (the latch is write-only; its readback is the
    # round-trip test's job) -- PM_ADDR reads back several patterns.
    for value in (0x01, 0xFE, 0x80, 0x00):
        p.ldi(1, value)
        p.wctl(PM_ADDR, 1)
        checks.append((p.show(PM_ADDR), value, f"PM_ADDR readback {value:#04x}"))
    p.add("HALT")

    # Sanity of the reference rule itself (so a wrong rule cannot pass by
    # agreeing with a wrong RTL on the one formula both might share).
    assert pin_mode_oe(0x00, 0x00, 0x00) == 0x00
    assert pin_mode_oe(0xFF, 0xFF, 0x00) == 0xFF and pin_mode_oe(0x00, 0xFF, 0x00) == 0xFF
    assert pin_mode_oe(0xFF, 0xFF, 0xFF) == 0x00 and pin_mode_oe(0x00, 0x00, 0xFF) == 0xFF
    assert pin_mode_oe(0x0F, 0xF0, 0x3C) == 0xF0  # 0xC0 push-pull + 0x30 OD-low

    trace = await run_trace(dut, p.words, p.end_edge() + 3)
    expect(trace, p, checks)
    expect(trace, p, oe_checks, pin="uio_oe")
    # ...and not one edge early: the enable is registered state.
    prev = 0x00
    for idx, want, label in oe_checks:
        before = trace[p.edge(idx) - 1]["uio_oe"]
        assert before == prev, f"{label}: uio_oe moved before its write retired"
        prev = want


@cocotb.test()
async def test_reserved_indices_and_remaining_noops(dut):
    """Writes to unassigned / read-only indices change nothing; reads of
    unassigned / write-only indices return 0x00; each takes 1 cycle (all
    later pin edges land on 1-cycle arithmetic). OUT to port 01 and IN from
    port 11 stay no-ops for every imm8 tried."""
    start_clock(dut)
    p = Prog()
    checks = []
    setup = {UIO_DIR: 0x3C, UIO_OD: 0x81, PM_ADDR: 0x40}
    for k, v in setup.items():
        p.ldi(1, v)
        p.wctl(k, 1)
    p.ldi(2, 0x5A)
    marker = p.out(2)
    checks.append((marker, 0x5A, "marker before the reserved writes"))

    p.ldi(1, 0xFF)
    reserved_w = [BOOT_STATUS, HW_ID, 0x0A, 0x0F, 0x10, 0x1F, 0x20, 0x7F, 0x80, 0xFF]
    last_w = None
    for k in reserved_w:
        last_w = p.wctl(k, 1)
    # OUT to port 01 (reserved no-op), with imm8 values that would hit a
    # register if the port field were mis-decoded as port 00.
    for imm in (0x00, 0x01, 0x02, 0x05):
        last_w = p.raw((OP_OUT << 12) | (1 << 10) | (0b01 << 8) | imm)

    for k, v in setup.items():
        checks.append((p.show(k), v, f"register {k:#04x} unchanged by reserved writes"))
    checks.append((p.show(BOOT_STATUS), 0x01, "BOOT_STATUS unchanged by a write"))
    checks.append((p.show(HW_ID), HW_ID_VALUE, "HW_ID unchanged by a write"))

    for k in (RUN, 0x0A, 0x0F, 0x10, 0x1F, 0x20, 0x7F, 0x80, 0xFF):
        checks.append((p.show(k, poison=0x77), 0x00, f"read of reserved index {k:#04x}"))

    # IN from port 11 (reserved no-op): the destination keeps its value.
    for imm in (0x00, 0x03, 0x09):
        p.ldi(0, 0x77)
        p.raw((OP_IN << 12) | (0 << 10) | (0b11 << 8) | imm)
        checks.append((p.out(0), 0x77, f"IN from port 11 imm {imm:#04x} is a no-op"))
    p.add("HALT")

    trace = await run_trace(dut, p.words, p.end_edge() + 3)
    expect(trace, p, checks)
    want_oe = pin_mode_oe(0x00, setup[UIO_DIR], setup[UIO_OD])
    for e in range(p.edge(marker), p.end_edge() + 1):
        assert trace[e]["uio_oe"] == want_oe, f"uio_oe moved at edge {e} during reserved accesses"
        assert trace[e]["uio_out"] == 0x00, f"uio_out moved at edge {e}"
    assert trace[p.edge(last_w)]["uo_out"] == 0x5A, "a reserved write moved uo_out"


def _stall_program(data):
    """One program, parameterised only by data: markers around each
    2-cycle access and around a run of 1-cycle accesses."""
    p = Prog()
    marks = []

    def mark(value):
        p.ldi(3, value)
        marks.append((p.out(3), value))

    p.ldi(1, data["addr"])
    p.wctl(PM_ADDR, 1)
    p.ldi(0, data["hi"])
    p.wctl(PM_DATA_HI, 0)
    p.ldi(0, data["lo"])
    mark(0x01)
    p.wctl(PM_DATA_LO, 0)          # 2 cycles
    mark(0x02)
    p.wctl(PM_ADDR, 1)
    mark(0x03)
    p.rctl(2, PM_DATA_HI)          # 2 cycles
    mark(0x04)
    p.rctl(2, PM_DATA_LO)          # 1 cycle
    mark(0x05)
    # RUN to the very next instruction: a 2-cycle straight-line step whose
    # target is data (R1), loaded here with the address after the WCTL.
    run_ldi = p.ldi(1, 0)
    run_idx = p.wctl(RUN, 1)        # 2 cycles
    p.lines[run_ldi] = f"LDI R1, {run_idx + 1:#04x}"
    mark(0x06)
    # Ten 1-cycle accesses in a row.
    p.ldi(1, data["misc"])
    for k in (UIO_DIR, UIO_OD, PM_ADDR, PM_DATA_HI, PM_CRC_LO, PM_CRC_HI):
        p.wctl(k, 1)
    for k in (UIO_DIR, PM_CRC_LO, BOOT_STATUS, HW_ID):
        p.rctl(2, k)
    mark(0x07)
    p.ldi(1, 0x00)
    p.wctl(UIO_DIR, 1)             # leave the pins as inputs
    p.wctl(UIO_OD, 1)
    p.add("HALT")
    return p, marks


@cocotb.test()
async def test_fixed_stall_is_exact_and_data_independent(dut):
    """The three 2-cycle accesses cost exactly 2 cycles and every other
    access exactly 1: each marker lands on the edge the table predicts and
    is absent the edge before. The same program over four different data
    sets moves uo_out on identical edges."""
    start_clock(dut)
    data_sets = [
        {"addr": 0xF0, "hi": 0x00, "lo": 0x00, "misc": 0x00},
        {"addr": 0xF1, "hi": 0xFF, "lo": 0xFF, "misc": 0xFF},
        {"addr": 0xE7, "hi": 0xA5, "lo": 0x5A, "misc": 0x81},
        {"addr": 0xFF, "hi": 0x12, "lo": 0xF0, "misc": 0x3C},  # PM_ADDR wraps on the commit
    ]
    change_edges = []
    for data in data_sets:
        p, marks = _stall_program(data)
        n = p.end_edge() + 3
        trace = await run_trace(dut, p.words, n)
        prev = 0x00
        for idx, value in marks:
            e = p.edge(idx)
            assert trace[e]["uo_out"] == value, (
                f"data {data}: marker {value:#04x} not on edge {e} "
                f"(got {trace[e]['uo_out']:#04x})"
            )
            assert trace[e - 1]["uo_out"] == prev, (
                f"data {data}: marker {value:#04x} arrived before edge {e}"
            )
            prev = value
        change_edges.append(
            [e for e in range(1, n + 1) if trace[e]["uo_out"] != trace[e - 1]["uo_out"]]
        )
        # Spacing between consecutive markers, from the pins alone: LDI+OUT
        # is 2; a 2-cycle access between them makes it 4.
        gaps = [p.edge(marks[i + 1][0]) - p.edge(marks[i][0]) for i in range(len(marks) - 1)]
        assert gaps == [4, 3, 4, 3, 5, 13], f"marker spacing {gaps}"
    assert all(edges == change_edges[0] for edges in change_edges), (
        f"pin timing depends on data: {change_edges}"
    )


@cocotb.test()
async def test_no_flag_side_effects(dut):
    """No control access changes Z or C. Pin-level: a BZ / BNZ placed
    after a block of control accesses -- including reads that return 0x00
    and reads that return non-zero -- still follows the Z set before the
    block. White-box (RTL only): flag_z and flag_c hold across the block."""
    start_clock(dut)
    c = core(dut)

    def block(p):
        p.ldi(1, 0xF0)
        p.wctl(PM_ADDR, 1)
        first = p.wctl(UIO_DIR, 1)
        p.wctl(UIO_OD, 1)
        p.wctl(PM_DATA_HI, 1)
        p.wctl(PM_DATA_LO, 1)
        p.wctl(PM_CRC_LO, 1)
        p.wctl(PM_CRC_HI, 1)
        p.wctl(BOOT_STATUS, 1)
        p.wctl(0x10, 1)
        p.wctl(PM_ADDR, 1)
        for k in (UIO_DIR, UIO_OD, PM_ADDR, PM_DATA_HI, PM_DATA_LO, PM_CRC_LO,
                  PM_CRC_HI, BOOT_STATUS, HW_ID, RUN, 0x10, 0xFF):
            p.rctl(2, k)             # some return 0x00, some non-zero
        run_ldi = p.ldi(1, 0)
        run_idx = p.wctl(RUN, 1)
        p.lines[run_ldi] = f"LDI R1, {run_idx + 1:#04x}"
        return first, run_idx

    for z_c in (1, 0):
        p = Prog()
        if z_c:
            p.ldi(0, 0x80)
            p.ldi(1, 0x80)           # 0x80 + 0x80 = 0x00 carry 1 -> Z=1, C=1
        else:
            p.ldi(0, 0x01)
            p.ldi(1, 0x01)           # 0x01 + 0x01 = 0x02 -> Z=0, C=0
        p.add("ADD R0, R1")
        first, last = block(p)
        branch = p.add("BZ 0x00")    # patched below to a real target
        p.ldi(3, 0x0F)               # fall-through marker
        p.out(3)
        p.add("HALT")
        target = p.ldi(3, 0xF0)      # taken marker
        p.out(3)
        p.add("HALT")
        p.lines[branch] = f"BZ {target:#04x}"

        flags = []
        e_first, e_last = p.edge(first), p.edge(last) + 2

        def sample(e, _flags=flags, _lo=e_first, _hi=e_last):
            if c is not None and _lo <= e <= _hi:
                _flags.append((int(c.flag_z.value), int(c.flag_c.value)))

        n = p.edge(branch) + 6
        trace = await run_trace(dut, p.words, n, per_edge=sample)
        e_branch = p.edge(branch)
        got = trace[e_branch + 2]["uo_out"]
        want = 0xF0 if z_c else 0x0F
        assert got == want, (
            f"Z={z_c} before the control block: branch marker {got:#04x}, want {want:#04x} "
            "(a control access changed Z)"
        )
        if c is not None:
            assert flags and all(f == (z_c, z_c) for f in flags), (
                f"flags moved across the control block: {sorted(set(flags))}"
            )


@cocotb.test()
async def test_program_memory_write_read_roundtrip(dut):
    """Words written through PM_ADDR / PM_DATA_HI / PM_DATA_LO read back
    through the same registers; PM_ADDR auto-increments on a LO write and a
    LO read, and wraps 0xFF -> 0x00; the words on either side of the
    written range still hold what the serial load put there (which also
    checks the read path against content the write path never touched)."""
    start_clock(dut)
    rng = random.Random(0x135A)
    base, count = 0x90, 10
    new = [rng.randrange(0x10000) for _ in range(count)]
    new[0], new[1] = 0x0000, 0xFFFF  # the two corner words, deliberately

    p = Prog()
    checks = []
    p.ldi(1, base)
    p.wctl(PM_ADDR, 1)
    for word in new:
        p.write_word(word)
    checks.append((p.show(PM_ADDR), base + count, "PM_ADDR after the writes"))

    def read_word_checks(addr_label):
        p.rctl(0, PM_DATA_HI)
        hi = p.out(0)
        p.rctl(0, PM_DATA_LO)
        lo = p.out(0)
        return hi, lo, addr_label

    p.ldi(1, base - 1)               # one before the range ...
    p.wctl(PM_ADDR, 1)
    reads = [read_word_checks(base - 1 + i) for i in range(count + 2)]  # ... to one after
    checks.append((p.show(PM_ADDR), base + count + 1, "PM_ADDR after the reads"))

    p.ldi(1, 0xFF)                   # wrap on a read
    p.wctl(PM_ADDR, 1)
    wrap_read = read_word_checks(0xFF)
    checks.append((p.show(PM_ADDR), 0x00, "PM_ADDR wraps 0xFF -> 0x00 on a LO read"))
    p.ldi(1, 0xFF)                   # wrap on a write (rewrites the word already there)
    p.wctl(PM_ADDR, 1)
    wrap_w_at = len(p.lines)
    p.write_word(0)                  # placeholder, patched below
    checks.append((p.show(PM_ADDR), 0x00, "PM_ADDR wraps 0xFF -> 0x00 on a LO write"))
    p.add("HALT")

    # The serially loaded image: the program, then a known pattern up to
    # 256 words, so every address read back has known contents.
    prog_len = len(p.lines)
    assert prog_len < base - 1, f"program ({prog_len} words) overlaps the test range"
    fill = [rng.randrange(0x10000) for _ in range(256)]
    last_word = fill[0xFF]
    p.lines[wrap_w_at] = f"LDI R0, {(last_word >> 8):#04x}"
    p.lines[wrap_w_at + 2] = f"LDI R0, {(last_word & 0xFF):#04x}"
    words = p.words
    image = words + fill[len(words):]
    assert len(image) == 256

    expected = list(image)
    expected[base:base + count] = new
    for hi, lo, addr in reads + [wrap_read]:
        checks.append((hi, expected[addr] >> 8, f"PM[{addr:#04x}] high byte"))
        checks.append((lo, expected[addr] & 0xFF, f"PM[{addr:#04x}] low byte"))

    trace = await run_trace(dut, image, p.end_edge() + 3)
    expect(trace, p, checks)


@cocotb.test()
async def test_written_code_executes_and_run_jumps(dut):
    """Firmware can load firmware: a routine written through the control
    space into unused program memory executes when `WCTL RUN` jumps to it,
    on the edge a fixed 2-cycle RUN predicts. And a write to the word that
    is fetched next takes effect (DR 0012 "Program-memory timing")."""
    start_clock(dut)
    routine_at = 0xC0
    routine = asm.assemble_text(
        "LDI R2, 0xC3\nOUT UO_OUT, R2\nLDI R2, 0x3C\nOUT UO_OUT, R2\nHALT\n"
    ).words

    p = Prog()
    # 1. Self-modify the next word: the LDI at `victim` is replaced, by the
    #    WCTL PM_DATA_LO immediately before it, with LDI R2, 0x22.
    replacement = asm.assemble_text("LDI R2, 0x22\n").words[0]
    p.ldi(0, replacement >> 8)
    p.wctl(PM_DATA_HI, 0)
    addr_ldi = p.ldi(1, 0)
    p.wctl(PM_ADDR, 1)
    p.ldi(0, replacement & 0xFF)
    p.wctl(PM_DATA_LO, 0)
    victim = p.ldi(2, 0x11)          # overwritten before it is fetched
    p.lines[addr_ldi] = f"LDI R1, {victim:#04x}"
    patched_out = p.out(2)

    # 2. Write a routine at 0xC0 and RUN to it.
    p.ldi(1, routine_at)
    p.wctl(PM_ADDR, 1)
    for word in routine:
        p.write_word(word)
    p.ldi(1, routine_at)
    run_idx = p.wctl(RUN, 1)
    p.ldi(3, 0xBD)                   # must never execute: RUN does not fall through
    p.out(3)
    p.add("HALT")

    words = p.words
    e_run = p.edge(run_idx)
    trace = await run_trace(dut, words, e_run + 12)
    expect(trace, p, [(patched_out, 0x22, "the rewritten next word executed")])
    # RUN occupies edges e_run and e_run+1; routine word 0 (LDI) retires at
    # e_run+2, its OUT at e_run+3, the second OUT at e_run+5.
    assert trace[e_run + 2]["uo_out"] == 0x22, "RUN target's OUT arrived early"
    assert trace[e_run + 3]["uo_out"] == 0xC3, (
        f"routine written through PM_DATA did not run on time: "
        f"uo_out {trace[e_run + 3]['uo_out']:#04x} after edge {e_run + 3}"
    )
    assert trace[e_run + 4]["uo_out"] == 0xC3
    assert trace[e_run + 5]["uo_out"] == 0x3C
    assert all(s["uo_out"] != 0xBD for s in trace), "RUN fell through"
    assert trace[e_run + 12]["uo_out"] == 0x3C, "the routine's HALT did not hold"


@cocotb.test()
async def test_pm_crc_matches_binascii_crc_hqx(dut):
    """PM_CRC is CRC-16/XMODEM over every committed word, by any path,
    checked against `binascii.crc_hqx`: over the serial load alone; over
    the serial load plus PM_DATA_LO commits (no clear in between); from a
    clear through PM_CRC_LO; from a clear through PM_CRC_HI; and it is not
    moved by program-memory reads, PM_ADDR writes or a PM_DATA_HI latch
    write. Two different images are run."""
    start_clock(dut)
    for seed, pad in ((0xC2C1, 0), (0x1021, 37)):
        rng = random.Random(seed)
        batch_a = [rng.randrange(0x10000) for _ in range(5)]
        batch_b = [rng.randrange(0x10000) for _ in range(7)]
        batch_c = [0x0000]           # a zero word still advances a non-zero CRC
        batch_d = [rng.randrange(0x10000)]

        p = Prog()
        tags = []

        def show_crc(label):
            tags.append((p.show(PM_CRC_LO), p.show(PM_CRC_HI), label))

        show_crc("serial")
        p.ldi(1, 0xD0)
        p.wctl(PM_ADDR, 1)
        for word in batch_a:
            p.write_word(word)
        show_crc("serial+a")
        # Things that must not move the CRC.
        p.ldi(1, 0xD0)
        p.wctl(PM_ADDR, 1)
        p.rctl(2, PM_DATA_HI)
        p.rctl(2, PM_DATA_LO)
        p.wctl(PM_DATA_HI, 1)
        show_crc("serial+a again")
        p.wctl(PM_CRC_LO, 1)         # clear through the LO register
        show_crc("cleared-lo")
        for word in batch_b:
            p.write_word(word)
        show_crc("b")
        for word in batch_c:
            p.write_word(word)
        show_crc("b+c")
        p.wctl(PM_CRC_HI, 1)         # clear through the HI register
        show_crc("cleared-hi")
        for word in batch_d:
            p.write_word(word)
        show_crc("d")
        p.add("HALT")

        words = p.words
        image = words + [rng.randrange(0x10000) for _ in range(pad)]
        serial = crc_of_words(image)
        want = {
            "serial": serial,
            "serial+a": crc_of_words(batch_a, serial),
            "serial+a again": crc_of_words(batch_a, serial),
            "cleared-lo": 0x0000,
            "b": crc_of_words(batch_b),
            "b+c": crc_of_words(batch_b + batch_c),
            "cleared-hi": 0x0000,
            "d": crc_of_words(batch_d),
        }
        assert want["b+c"] != want["b"], "test premise: the zero word moves the CRC"
        # Known-answer anchor for the reference itself (CRC-16/XMODEM check value).
        assert binascii.crc_hqx(b"123456789", 0) == 0x31C3

        trace = await run_trace(dut, image, p.end_edge() + 3)
        checks = []
        for lo, hi, label in tags:
            checks.append((lo, want[label] & 0xFF, f"seed {seed:#x}: PM_CRC_LO [{label}]"))
            checks.append((hi, want[label] >> 8, f"seed {seed:#x}: PM_CRC_HI [{label}]"))
        expect(trace, p, checks)


@cocotb.test()
async def test_i2c_images_open_drain_preamble(dut):
    """The six committed I2C images now carry `WCTL UIO_OD` with 0x81 (DR
    0012; SCL = uio[0], SDA = uio[7] per the images' pin plan). Run each
    with no peripheral (the bus reads released) and check, at the logic
    level, what a wired-AND bus needs: no uio pin is enabled before the
    preamble; after it uio_oe is exactly `~uio_out & 0x81` on every edge,
    so SCL and SDA are only ever pulled low or released, never driven
    high; no other uio pin is ever enabled; and the preamble itself does
    not pull a line low (the OUT of 0x81 precedes it). This is not a pad
    model -- that, and the I2C evidence re-run on it, are issue #136."""
    start_clock(dut)
    for name in ("i2c_fast", "i2c_std", "i2c_fast_sr", "i2c_fast_sr_poll",
                 "i2c_std_sr", "i2c_std_sr_poll"):
        text = (REPO_ROOT / "firmware" / "build" / f"{name}.hex").read_text()
        words = [int(line, 16) for line in text.split()]
        wctl = (OP_OUT << 12) | (3 << 10) | UIO_OD   # WCTL UIO_OD, R3
        assert words.count(wctl) == 1, f"{name}: expected exactly one WCTL UIO_OD, R3"
        pre = words.index(wctl)
        assert all(cycles(w) == 1 for w in words[:pre]), f"{name}: preamble arithmetic"
        e_pre = RUN_ENTRY_EDGES + pre
        n = e_pre + 2600
        trace = await run_trace(dut, words, n, uio_in=0xFF)
        for e in range(0, e_pre):
            assert trace[e]["uio_oe"] == 0, f"{name}: a uio pin enabled before the preamble"
        assert trace[e_pre - 1]["uio_out"] == 0x81, f"{name}: lines not released before UIO_OD"
        assert trace[e_pre]["uio_oe"] == 0x00, f"{name}: the preamble pulled a line low"
        pulled = False
        for e in range(e_pre, n + 1):
            s = trace[e]
            assert s["uio_oe"] == (~s["uio_out"] & 0x81), (
                f"{name}: uio_oe {s['uio_oe']:#04x} with uio_out {s['uio_out']:#04x} at edge {e}"
            )
            pulled = pulled or s["uio_oe"] != 0
        assert pulled, f"{name}: the program never pulled a line low (vacuous)"
