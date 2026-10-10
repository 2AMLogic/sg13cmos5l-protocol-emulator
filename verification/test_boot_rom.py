"""cocotb bench for DR 0013 layer 2 on `tt_um_2amlogic_protocol_emulator`:
the boot ROM, the fetch-source switch and the warm start (issue #138).

`spec/decision-records/0013-program-loading.md`: "At `rst_n` release with
`MODE` low, fetch comes from a small boot ROM instead of program memory."
This bench is the part of that record's verification list that issue #138
owns, and target-spec row 14 (c) / `spec/verification-plan.md` section 8's
"uninitialized program memory" bullet:

- **the UART loader idles on memory nobody wrote**: straps 00 and 11 (the
  UART load and the reserved value; strap 01 is the SPI-flash boot since
  issue #140 and is test_boot_spi.py's) on a program memory that has never
  been written (all X in simulation) never read it. They reach the UART
  loader (issue #139), which idles with TX (`uo_out[0]`) high, `uio_out` at
  its 0xFF guard and `uio_oe` 0, all free of X;
- **`MODE` low never runs unverified memory**: with program memory holding
  a canary image -- one that visibly drives `uo_out` and every `uio` pin
  within five instructions from *any* entry address, and is shown doing so
  when it is serial-loaded and run -- or random images, a reset with `MODE` low
  moves no pin for any strap value, including strap 10 (warm start), whose
  check fails on them;
- **warm start runs a verified image**: an image whose word 255 is the
  CRC-16/XMODEM of words 0..254 (`binascii.crc_hqx`, not this repo's
  arithmetic) runs from address 0 on strap 10, with its first instruction
  on exactly the edge the boot program's cycle count predicts, with the
  register, flag and control state a reset leaves, and reading
  `BOOT_STATUS = 0x00`; a second image with different contents moves its
  pins on the same edges; a second warm start of the same memory passes
  too (the check re-commits every word and leaves the array as it was);
- **warm start rejects a corrupted image**: one flipped bit in word 0, in
  an odd-numbered word, in word 254 or in the signature, two swapped
  words, and two images crafted so that only one byte of the CRC residue is
  nonzero -- none ever runs;
- **warm start refuses a zero signature** (issue #168, DR 0013 Finding
  F1): CRC-16/XMODEM starts at 0x0000, so 256 zero words are their own
  valid signature. Until #168 a warm start ran them (256 NOPs); now the
  boot program refuses word 255 = 0x0000 as the SPI-flash boot does, so
  neither the all-zero image nor a real image whose CRC happens to be
  0x0000 (one in 65,536; it must be re-padded) is run;
- **warm start runs zero-padded images**: a program padded with zero words
  whose signature is nonzero runs, including signatures with a zero high
  byte or a zero low byte, so the refusal tests the whole word and nothing
  else;

How the expected numbers are derived. `BootModel` below is an independent
interpreter of the ISA, written from DR 0001's opcode table and DR 0012's
register map and latency table, that runs the **committed** boot image
(`firmware/build/boot/boot_rom.hex`) against a strap value and a
program-memory image. It shares no code with the RTL or the assembler. It
says where the boot program ends (which stub's `HALT`, or `RUN` and its
target) and after how many cycles; every edge number this bench asserts
comes from it, and the one number the boot source documents (a passing
warm start executes word 0 exactly 2,325 cycles after the boot program's
first instruction) is asserted against it too.

Pin-only by default. Under the gate-level Makefile (`GATES=yes`,
`flow/run-firmware-gate-level.sh --boot-rom`) the hierarchy is gone and
only the pin checks run. In an RTL run the bench also reads, white-box and
labelled as such: `u_core.fetch_rom` (the fetch source, `BOOT_STATUS[1]`),
`u_core.pm_fetch` and the macro's read enable (the core never fetches from
program memory while the ROM is the source), and `pc` / `halted` (which
stub the boot program stopped in). Those are the facts no pin shows.

X and the warm start. A never-written memory is X in simulation and is
only used with the stub straps, which never read it. The warm start reads
every word, so it is exercised on real (0/1) contents: a gate-level
simulator turns an X read into an X everywhere, which is a property of the
simulator's pessimism and says nothing about silicon, where the cells hold
some value. The random-image cases are that value.

All images are fixed in source or drawn from `random.Random` with the
literal seeds below, so every run is byte-reproducible.
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
import gen_boot_rom  # noqa: E402  (the ROM generator)

CLK_PERIOD_NS = 10
RUN_ENTRY_EDGES = 2  # DR 0005: edge 1 primes the fetch, edge 2 retires pc=0
PM_WORDS = 256
ROM_WORDS_MAX = gen_boot_rom.ROM_WORDS_MAX  # 256: DR 0013 finding F4 (the UART load does not fit 128)

GATE_LEVEL = os.environ.get("GATES") == "yes"

BOOT_ASM = REPO_ROOT / "firmware" / "asm" / "boot" / "boot_rom.asm"
BOOT_HEX = REPO_ROOT / "firmware" / "build" / "boot" / "boot_rom.hex"
BOOT_ROM_V = REPO_ROOT / "rtl" / "protocol_boot_rom.v"

# DR 0013 layer 2 strap table: ui_in[6:5].
STRAP_UART, STRAP_SPI, STRAP_WARM, STRAP_RESERVED = 0b00, 0b01, 0b10, 0b11
STRAPS = (STRAP_UART, STRAP_SPI, STRAP_WARM, STRAP_RESERVED)
# Strap 01 is no longer a stub (issue #140): the SPI-flash boot drives the
# flash pins, so its idle-pins properties live in test_boot_spi.py. These two
# tuples are the straps whose boot programs move no pin on an unverified
# or empty program memory.
STUB_STRAPS = (STRAP_UART, STRAP_RESERVED)
QUIET_STRAPS = (STRAP_UART, STRAP_WARM, STRAP_RESERVED)

# The number firmware/asm/boot/boot_rom.asm documents: word 0 of a verified
# image executes this many cycles after the boot program's first instruction.
WARM_START_CYCLES = 2325

# DR 0012 section 2, written out here independently of asm.py / the RTL.
UIO_DIR, UIO_OD, PM_ADDR, PM_DATA_HI, PM_DATA_LO = 0x00, 0x01, 0x02, 0x03, 0x04
RUN, PM_CRC_LO, PM_CRC_HI, BOOT_STATUS, HW_ID = 0x05, 0x06, 0x07, 0x08, 0x09
HW_ID_VALUE = 0x01

OP_HALT = 0xF


def cycles(word):
    """This bench's statement of the latency table: DR 0001's (1, or
    imm8+1 for WAIT) with DR 0012's three fixed 2-cycle control accesses."""
    op, port, k = word >> 12, (word >> 8) & 3, word & 0xFF
    if op == 0xB:
        return k + 1
    if op == 0xA and port == 0 and k in (PM_DATA_LO, RUN):
        return 2
    if op == 0x9 and port == 2 and k == PM_DATA_HI:
        return 2
    return 1


def crc_of_words(words, crc=0):
    """CRC-16/XMODEM of `words` as a big-endian byte string, by the Python
    standard library -- the independent reference DR 0012 names."""
    data = b"".join(bytes(((w >> 8) & 0xFF, w & 0xFF)) for w in words)
    return binascii.crc_hqx(data, crc)


def signed_image(program, filler_seed):
    """A warm-startable image: `program`, seeded random filler up to word
    254, and word 255 = the CRC of words 0..254 (DR 0013 open item 1)."""
    assert len(program) <= PM_WORDS - 1
    rng = random.Random(filler_seed)
    body = list(program) + [rng.randrange(0x10000) for _ in range(PM_WORDS - 1 - len(program))]
    return body + [crc_of_words(body)]


def rom_words():
    return [int(line, 16) for line in BOOT_HEX.read_text(encoding="utf-8").split()]


class BootModel:
    """An independent interpreter of the ISA, enough of it to run a boot
    program: DR 0001's sixteen opcodes and DR 0012's control registers,
    with program memory as a Python list and PM_CRC from `binascii`.

    `run()` executes the ROM image from address 0 until a `HALT` or a
    `WCTL RUN`, counting cycles with this file's own `cycles()`. Addresses
    past the image read as HALT, as the generated ROM does.
    """

    def __init__(self, rom, straps, pm, poll_pc=None):
        self.rom = list(rom)
        self.poll_pc = poll_pc             # the UART loader's start-edge poll
        self.ui_in = ((straps & 3) << 5) | 0x02   # MODE (bit 7) low, RX (bit 1) idle high
        self.pm = list(pm)                 # None entries = never written
        self.r = [0, 0, 0, 0]
        self.z = 0
        self.c = 0
        self.pm_addr = 0
        self.hi = 0
        self.lo = 0
        self.crc = 0
        self.uo = 0
        self.uio = 0
        self.dir = 0
        self.od = 0
        self.pm_reads = 0
        self.pm_writes = 0
        # Pin hooks for boot programs that talk to a device (issue #140):
        # `uio_in_at(elapsed)` supplies a `uio_in` read; `on_uio(elapsed,
        # uio_out, uio_dir)` is told about every write to either, `elapsed`
        # being the cycle count before the writing instruction. Unset, the
        # model is the one it always was: uio_in reads 0.
        self.uio_in_at = None
        self.on_uio = None

    def _rctl(self, k):
        if k == UIO_DIR:
            return self.dir
        if k == UIO_OD:
            return self.od
        if k == PM_ADDR:
            return self.pm_addr
        if k == PM_DATA_LO:
            value = self.lo
            self.pm_addr = (self.pm_addr + 1) & 0xFF
            return value
        if k == PM_CRC_LO:
            return self.crc & 0xFF
        if k == PM_CRC_HI:
            return self.crc >> 8
        if k == BOOT_STATUS:
            return 0x02                     # in the boot ROM, no serial load
        if k == HW_ID:
            return HW_ID_VALUE
        return 0x00

    def run(self, limit=100_000):
        pc, elapsed = 0, 0
        for _ in range(limit):
            if pc == self.poll_pc:
                return {"outcome": "uart_wait", "pc": pc, "cycles": elapsed}
            word = self.rom[pc] if pc < len(self.rom) else 0xF000
            op, rd, rs, imm = word >> 12, (word >> 10) & 3, (word >> 8) & 3, word & 0xFF
            a, b = self.r[rd], self.r[rs]
            nxt = (pc + 1) & 0xFF
            if op == 0x1:
                self.r[rd] = imm
            elif op == 0x2:
                self.r[rd] = b
            elif op in (0x3, 0x4):
                full = a + b if op == 0x3 else a - b
                self.r[rd] = full & 0xFF
                self.z = int(self.r[rd] == 0)
                self.c = int(full > 0xFF or full < 0)
            elif op in (0x5, 0x6, 0x7):
                self.r[rd] = {0x5: a & b, 0x6: a | b, 0x7: a ^ b}[op]
                self.z = int(self.r[rd] == 0)
            elif op == 0x8:
                if rs & 1:
                    self.c, self.r[rd] = a >> 7, (a << 1) & 0xFF
                else:
                    self.c, self.r[rd] = a & 1, a >> 1
            elif op == 0x9:
                if rs == 0:
                    self.r[rd] = self.ui_in
                elif rs == 1:
                    self.r[rd] = self.uio_in_at(elapsed) if self.uio_in_at else 0x00
                elif rs == 2:
                    if imm == PM_DATA_HI:
                        value = self.pm[self.pm_addr]
                        assert value is not None, "boot program read unwritten memory"
                        self.pm_reads += 1
                        self.r[rd], self.lo = value >> 8, value & 0xFF
                    else:
                        self.r[rd] = self._rctl(imm)
            elif op == 0xA:
                if rs == 2:
                    self.uo = a
                elif rs == 3:
                    self.uio = a
                    if self.on_uio:
                        self.on_uio(elapsed, self.uio, self.dir)
                elif rs == 0:
                    if imm == UIO_DIR:
                        self.dir = a
                        if self.on_uio:
                            self.on_uio(elapsed, self.uio, self.dir)
                    elif imm == UIO_OD:
                        self.od = a
                    elif imm == PM_ADDR:
                        self.pm_addr = a
                    elif imm == PM_DATA_HI:
                        self.hi = a
                    elif imm == PM_DATA_LO:
                        value = (self.hi << 8) | a
                        self.pm[self.pm_addr] = value
                        self.pm_writes += 1
                        self.crc = crc_of_words([value], self.crc)
                        self.pm_addr = (self.pm_addr + 1) & 0xFF
                    elif imm == RUN:
                        return {"outcome": "run", "target": a, "pc": pc, "cycles": elapsed}
                    elif imm in (PM_CRC_LO, PM_CRC_HI):
                        self.crc = 0
            elif op == 0xC:
                nxt = imm
            elif op == 0xD:
                nxt = imm if self.z else nxt
            elif op == 0xE:
                nxt = nxt if self.z else imm
            elif op == OP_HALT:
                return {"outcome": "halt", "pc": pc, "cycles": elapsed}
            elapsed += cycles(word)
            pc = nxt
        raise AssertionError("boot model did not terminate")


def boot_outcome(straps, pm):
    """(result, model) of the committed boot image on `straps` and `pm`."""
    model = BootModel(rom_words(), straps, pm, stub_addresses()["uart_load"])
    result = model.run()
    state = (model.uo, model.uio, model.dir, model.od)
    if result["outcome"] == "uart_wait":
        # The UART loader: TX idle high, and the guard that lets UIO_DIR be
        # scratch without driving a pin (uio_out and UIO_OD all ones).
        assert state == (0x01, 0xFF, 0, 0xFF), f"the UART loader's idle state is {state}"
    else:
        assert state == (0, 0, 0, 0), "the boot program wrote a pin or a pin-mode register"
    return result, model


def stub_addresses():
    """Where the boot program waits, from the boot source: `uart_load` is
    the UART loader's start-edge poll (its `IN` after the `rx_poll:` label)
    and `spi_fail` the SPI-flash boot's HALT (issue #140), the only HALT in
    the source, whose properties test_boot_spi.py owns."""
    program = asm.assemble_file(BOOT_ASM)
    lines = BOOT_ASM.read_text(encoding="utf-8").splitlines()
    poll_line = 1 + next(i for i, text in enumerate(lines) if text.startswith("rx_poll:"))
    poll = min((ins for ins in program.instructions if ins.line_no > poll_line),
               key=lambda ins: ins.line_no)
    assert poll.mnemonic == "IN", f"the instruction after rx_poll: is {poll.mnemonic}"
    halts = [ins.addr for ins in program.instructions if ins.mnemonic == "HALT"]
    assert len(halts) == 1, f"boot source has {len(halts)} HALTs, expected the SPI boot's"
    return {"uart_load": poll.addr, "spi_fail": halts[0]}


# ---------------------------------------------------------------------------
# DUT helpers
# ---------------------------------------------------------------------------
def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


def whitebox(dut):
    """(core, program memory) handles for the labelled white-box reads, or
    None at gate level. An RTL run that cannot find them is an error."""
    if GATE_LEVEL:
        return None
    return dut.u_core, dut.u_prog_mem


async def settle(dut, label):
    """The pins after the edge just taken. A pin that is X or Z is a
    failure here, not a conversion error somewhere else."""
    await ReadOnly()
    sample = {}
    for name in ("uo_out", "uio_out", "uio_oe"):
        value = getattr(dut, name).value
        assert value.is_resolvable, f"{label}: {name} is {value} (X/Z on a pin)"
        sample[name] = int(value)
    await Timer(1, unit="ns")
    return sample


async def serial_load(dut, words):
    """DR 0001 layer 1: reset with MODE high, shift `words` in MSB-first on
    ui_in[0], drop MODE. Returns right after the MODE-drop edge (edge 0)."""
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = 0x80
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)  # the mode-sampling edge
    for word in words:
        for bit in range(15, -1, -1):
            dut.ui_in.value = 0x80 | ((word >> bit) & 1)
            await RisingEdge(dut.clk)
    dut.ui_in.value = 0x00  # MODE drop
    await RisingEdge(dut.clk)  # edge 0


async def boot_reset(dut, straps):
    """Reset with MODE low and `straps` on ui_in[6:5], the rest of ui_in 0.
    Returns right after the mode-sampling edge, which starts the run phase
    (edge 0, the same numbering as the MODE-drop edge of a serial load)."""
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = ((straps & 3) << 5) | 0x02    # RX (ui_in[1]) idles high
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    await settle(dut, "in reset")
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)  # the mode-sampling edge = edge 0


async def trace_edges(dut, edges, label, per_edge=None):
    """trace[e] = the pins after edge e, for e in 0..edges."""
    trace = [await settle(dut, f"{label}, edge 0")]
    if per_edge is not None:
        per_edge(0)
    for e in range(1, edges + 1):
        await RisingEdge(dut.clk)
        trace.append(await settle(dut, f"{label}, edge {e}"))
        if per_edge is not None:
            per_edge(e)
    return trace


def assert_quiet(trace, label, waiting_at=None):
    """No pin left its reset value: uo_out 0, uio_out 0, every uio an input.

    `waiting_at` is the address the boot program ends in. When it is the UART
    loader's poll, the loader's own state is allowed and checked instead: TX
    (uo_out[0]) idles high, `uio_out` is 0 until the loader's guard sets it
    to 0xFF, and `uio_oe` is 0 at every edge -- no uio pin ever drives."""
    if waiting_at is not None and waiting_at == stub_addresses()["uart_load"]:
        for e, s in enumerate(trace):
            assert s["uio_oe"] == 0, f"{label}: a uio pin drove at edge {e}: {s['uio_oe']:#04x}"
            assert s["uo_out"] in (0x00, 0x01), f"{label}: uo_out={s['uo_out']:#04x} at edge {e}"
            assert s["uio_out"] in (0x00, 0xFF), f"{label}: uio_out={s['uio_out']:#04x} at edge {e}"
        assert trace[-1] == {"uo_out": 0x01, "uio_out": 0xFF, "uio_oe": 0}, (
            f"{label}: the loader is not idling with TX high: {trace[-1]}"
        )
        return
    for e, s in enumerate(trace):
        assert s == {"uo_out": 0, "uio_out": 0, "uio_oe": 0}, (
            f"{label}: a pin moved at edge {e}: uo_out={s['uo_out']:#04x} "
            f"uio_out={s['uio_out']:#04x} uio_oe={s['uio_oe']:#04x}"
        )


class RomWatch:
    """White-box, RTL only: while the boot ROM is the fetch source the core
    asks program memory for no fetch, and the macro is read only by a
    program-memory data access (`pm_re`). Sampled after every edge, i.e.
    for the cycle that follows it."""

    def __init__(self, dut, label):
        self.handles = whitebox(dut)
        self.label = label
        self.fetch_rom = []
        self.macro_reads = 0

    def __call__(self, e):
        if self.handles is None:
            return
        core, pmem = self.handles
        fetch_rom = int(core.fetch_rom.value)
        pm_fetch = int(core.pm_fetch.value)
        pm_re = int(core.pm_re.value)
        mem_ren = int(pmem.mem_ren.value)
        self.fetch_rom.append(fetch_rom)
        self.macro_reads += mem_ren
        if fetch_rom:
            # The one cycle in which the ROM is still the source and a fetch
            # goes to program memory is the stall cycle of the RUN that
            # leaves it.
            leaving = int(core.ctl_stall.value) and int(core.stall_run.value)
            assert pm_fetch == leaving, (
                f"{self.label}: edge {e}: pm_fetch={pm_fetch} while fetching from the ROM"
            )
            assert mem_ren == (pm_re or leaving), (
                f"{self.label}: edge {e}: the macro is read (A_REN={mem_ren}) "
                f"with pm_re={pm_re} while the ROM is the fetch source"
            )

    def assert_never_left(self):
        if self.handles is not None:
            assert all(self.fetch_rom), f"{self.label}: the core left the boot ROM"

    def assert_stopped_at(self, addr):
        """The boot program ended where the model says: halted in a stub, or
        spinning in the UART loader's three-instruction start-edge poll."""
        if self.handles is not None:
            core = self.handles[0]
            if addr == stub_addresses()["uart_load"]:
                pc = int(core.pc.value)
                assert int(core.halted.value) == 0 and addr <= pc <= addr + 3, (
                    f"{self.label}: pc={pc:#04x}, expected the UART poll at {addr:#04x}"
                )
                return
            assert int(core.halted.value) == 1, f"{self.label}: the boot program did not halt"
            assert int(core.pc.value) == addr, (
                f"{self.label}: halted at ROM address {int(core.pc.value):#04x}, "
                f"expected {addr:#04x}"
            )


def expected_stub(straps, result):
    """Which stub DR 0013's strap table sends `straps` to when no image is
    run, checked against the model's verdict."""
    assert straps in STUB_STRAPS or straps == STRAP_WARM, "strap 01 is test_boot_spi.py's"
    want = stub_addresses()["uart_load"]
    assert result["outcome"] == "uart_wait" and result["pc"] == want, (
        f"model: straps {straps:02b} ended {result}, expected the UART loader's poll at {want:#04x}"
    )
    return want


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------
class Prog:
    """Straight-line program builder with the retire edge of each line."""

    def __init__(self):
        self.lines = []

    def add(self, line):
        self.lines.append(line)
        return len(self.lines) - 1

    def show(self, k, reg=0, poison=0xEE):
        """LDI Rn, poison; RCTL Rn, k; OUT UO_OUT, Rn -> the OUT's index."""
        self.add(f"LDI R{reg}, {poison:#04x}")
        self.add(f"RCTL R{reg}, {k:#04x}")
        return self.add(f"OUT UO_OUT, R{reg}")

    @property
    def words(self):
        program = asm.assemble_text("\n".join(self.lines) + "\n")
        return list(program.words)

    def edge(self, index, entry_cycles=0):
        """The edge (from edge 0) on which instruction `index` retires,
        when the program's word 0 starts `entry_cycles` after the first
        instruction slot of the run phase."""
        return RUN_ENTRY_EDGES + entry_cycles + sum(cycles(w) for w in self.words[:index])


def canary_image():
    """256 words that drive pins soon after entry at ANY address: the unit
    `LDI R0, 0xFF` / `OUT UO_OUT, R0` / `WCTL UIO_DIR, R0` repeated. From
    any entry point the LDI is at most two instructions away, and uo_out
    and every uio enable read 0xFF within five."""
    unit = asm.assemble_text(
        "LDI R0, 0xFF\nOUT UO_OUT, R0\nWCTL UIO_DIR, R0\n"
    ).words
    return [unit[i % 3] for i in range(PM_WORDS)]


def probe_program():
    """The image a warm start runs: it reports the state it was entered
    with, then proves it can drive pins."""
    p = Prog()
    checks = {}
    p.add("BZ bad")                       # Z is 0 after reset; a warm start must hand over the same
    for reg in range(4):                  # R0-R3 are 0 after reset
        checks[f"R{reg} at entry"] = (p.add(f"OUT UO_OUT, R{reg}"), 0x00)
    checks["BOOT_STATUS"] = (p.show(BOOT_STATUS), None)     # 0x00 warm, 0x01 serial
    checks["PM_ADDR"] = (p.show(PM_ADDR), 0x00)
    checks["PM_CRC_LO"] = (p.show(PM_CRC_LO), 0x00)         # a signed image's residue
    checks["PM_CRC_HI"] = (p.show(PM_CRC_HI), 0x00)
    p.add("LDI R0, 0xA5")
    checks["marker"] = (p.add("OUT UO_OUT, R0"), 0xA5)
    p.add("LDI R1, 0x0F")
    checks["uio_oe"] = (p.add("WCTL 0x00, R1"), 0x0F)       # UIO_DIR: a verified program may drive
    p.add("HALT")
    p.add("bad: LDI R0, 0xBD")
    p.add("OUT UO_OUT, R0")
    p.add("HALT")
    return p, checks


def check_probe(trace, p, checks, entry_cycles, boot_status, label):
    """The probe program's pin timeline, edge by edge."""
    first = p.edge(0, entry_cycles)
    assert_quiet(trace[:first + 1], f"{label}: before the image's first instruction")
    for name, (index, want) in checks.items():
        if name == "BOOT_STATUS":
            want = boot_status
        e = p.edge(index, entry_cycles)
        pin = "uio_oe" if name == "uio_oe" else "uo_out"
        assert trace[e][pin] == want, (
            f"{label}: {name}: {pin} after edge {e} is {trace[e][pin]:#04x}, want {want:#04x}"
        )
    # The marker is absent one edge early: the entry edge is exact, not a bound.
    marker_edge = p.edge(checks["marker"][0], entry_cycles)
    assert trace[marker_edge - 1]["uo_out"] != 0xA5, f"{label}: the marker arrived early"
    assert trace[-1]["uo_out"] == 0xA5, f"{label}: the image took its Z=1 branch or did not finish"
    return [e for e in range(1, len(trace)) if trace[e] != trace[e - 1]]


# ---------------------------------------------------------------------------
@cocotb.test()
async def test_boot_image_chain_and_model(dut):
    """The committed image is what the committed source assembles to, the
    committed ROM Verilog is what the generator makes of that image, the
    image fits the generator's cap (DR 0013 finding F4), and the independent model agrees
    with DR 0013's strap table and with the cycle count the source
    documents. No DUT activity: this pins the inputs the other tests use."""
    start_clock(dut)
    program = asm.assemble_file(BOOT_ASM)
    rom = rom_words()
    assert list(program.words) == rom, "boot_rom.hex is not what boot_rom.asm assembles to"
    assert len(rom) <= ROM_WORDS_MAX, f"boot image is {len(rom)} words, cap {ROM_WORDS_MAX}"
    hex_text = BOOT_HEX.read_text(encoding="utf-8")
    assert BOOT_ROM_V.read_text(encoding="utf-8") == gen_boot_rom.render(rom, hex_text), (
        "rtl/protocol_boot_rom.v is not what gen_boot_rom.py makes of boot_rom.hex"
    )
    dut._log.info(f"boot image: {len(rom)} of {ROM_WORDS_MAX} words")

    p, _ = probe_program()
    valid = signed_image(p.words, filler_seed=1)
    assert crc_of_words(valid) == 0, "premise: a signed image's CRC over all 256 words is 0"
    for straps in STUB_STRAPS:
        result, model = boot_outcome(straps, valid)
        expected_stub(straps, result)
        assert model.pm_reads == 0 and model.pm_writes == 0, "the UART loader touched program memory"
    result, model = boot_outcome(STRAP_WARM, valid)
    assert result["outcome"] == "run" and result["target"] == 0, result
    assert result["cycles"] + 2 == WARM_START_CYCLES, (
        f"model: a warm start reaches word 0 after {result['cycles'] + 2} cycles; "
        f"boot_rom.asm documents {WARM_START_CYCLES}"
    )
    assert model.pm == valid, "model: the warm start changed program memory"
    assert model.pm_reads == PM_WORDS and model.pm_writes == PM_WORDS
    assert (model.r, model.z, model.c) == ([0, 0, 0, 0], 0, 0), (
        f"model: warm start hands over R={model.r} Z={model.z} C={model.c}, not the reset state"
    )
    assert (model.pm_addr, model.crc) == (0, 0)
    await ClockCycles(dut.clk, 2)


@cocotb.test()
async def test_stub_straps_idle_on_unwritten_memory(dut):
    """Straps 00, 01 and 11 on a program memory nothing has written (this
    is the first test to touch the DUT, so the array is all X): every pin
    stays at its reset value and free of X, in reset and for 64 cycles
    after. White-box (RTL): the boot program halted in the stub DR 0013's
    strap table names, the core never left the ROM, and the macro was not
    read once."""
    start_clock(dut)
    never_written = [None] * PM_WORDS
    for straps in STUB_STRAPS:
        label = f"unwritten memory, straps {straps:02b}"
        result, _ = boot_outcome(straps, never_written)
        stub = expected_stub(straps, result)
        watch = RomWatch(dut, label)
        await boot_reset(dut, straps)
        trace = await trace_edges(dut, RUN_ENTRY_EDGES + result["cycles"] + 64, label, watch)
        assert_quiet(trace, label, stub)
        watch.assert_never_left()
        watch.assert_stopped_at(stub)
        if watch.handles is not None:
            assert watch.macro_reads == 0, f"{label}: the macro was read {watch.macro_reads} time(s)"


@cocotb.test()
async def test_mode_low_never_runs_unverified_memory(dut):
    """Target-spec row 14 (c). Program memory holds the canary image, then
    four random images. Each is serial-loaded (which runs it: the canary
    is seen driving uo_out and uio_oe, so it is a live detector), and then
    `rst_n` is pulsed with MODE low for each of the four strap values. No
    pin moves, for longer than a warm start takes. White-box (RTL): the
    core never leaves the ROM, never asks program memory for a fetch, and
    halts in the stub the strap table names -- for strap 10 by falling
    through from a failed check."""
    start_clock(dut)
    images = [("canary", canary_image())]
    rng = random.Random(0x138)
    for n in range(4):
        images.append((f"random#{n}", [rng.randrange(0x10000) for _ in range(PM_WORDS)]))
    for name, image in images:
        assert crc_of_words(image) != 0, f"premise: {name} must not be a verified image"
        await serial_load(dut, image)
        loaded = await trace_edges(dut, 12, f"{name}, serial-loaded")
        if name == "canary":
            assert loaded[-1]["uo_out"] == 0xFF and loaded[-1]["uio_oe"] == 0xFF, (
                f"premise: the canary does not drive pins when it runs: {loaded[-1]}"
            )
        for straps in QUIET_STRAPS:
            label = f"{name}, MODE low, straps {straps:02b}"
            result, model = boot_outcome(straps, image)
            stub = expected_stub(straps, result)
            assert model.pm == image, "model: a boot program changed program memory"
            watch = RomWatch(dut, label)
            await boot_reset(dut, straps)
            trace = await trace_edges(dut, RUN_ENTRY_EDGES + result["cycles"] + 64, label, watch)
            assert_quiet(trace, label, stub)
            watch.assert_never_left()
            watch.assert_stopped_at(stub)
            if straps == STRAP_WARM and watch.handles is not None:
                # The check read all 256 words as data, and nothing else did.
                assert watch.macro_reads == PM_WORDS, (
                    f"{label}: {watch.macro_reads} macro reads, expected {PM_WORDS} data reads"
                )


@cocotb.test()
async def test_warm_start_runs_a_verified_image(dut):
    """Strap 10 with a signed image: it runs from address 0, its first
    instruction retires on the edge the boot program's cycle count
    predicts, it finds R0-R3 = 0 and Z = 0, PM_ADDR = 0, PM_CRC = 0 and
    BOOT_STATUS = 0x00, and it can then drive pins. A second image with
    different filler moves its pins on the same edges, and a second warm
    start of the same memory passes again. The same image entered by a
    serial load reads BOOT_STATUS = 0x01. On straps 00, 01 and 11 the
    same verified image is not run."""
    start_clock(dut)
    p, checks = probe_program()
    tail = p.edge(len(p.lines)) + 8
    warm_edges = []
    for seed in (1, 2):
        image = signed_image(p.words, filler_seed=seed)
        result, _ = boot_outcome(STRAP_WARM, image)
        assert result == {"outcome": "run", "target": 0, "pc": result["pc"],
                          "cycles": WARM_START_CYCLES - 2}, result

        # Layer 1 entry: the image runs straight after the load.
        label = f"image {seed}, serial load"
        await serial_load(dut, image)
        watch = RomWatch(dut, label)
        trace = await trace_edges(dut, tail, label, watch)
        check_probe(trace, p, checks, 0, 0x01, label)
        if watch.handles is not None:
            assert not any(watch.fetch_rom), f"{label}: a serial load decoded the boot ROM"

        # Layer 2 entry, twice: the second pass shows the first left the
        # array (and so its signature) intact.
        for attempt in (1, 2):
            label = f"image {seed}, warm start {attempt}"
            watch = RomWatch(dut, label)
            await boot_reset(dut, STRAP_WARM)
            trace = await trace_edges(dut, WARM_START_CYCLES + tail, label, watch)
            warm_edges.append(check_probe(trace, p, checks, WARM_START_CYCLES, 0x00, label))
            if watch.handles is not None:
                first = RUN_ENTRY_EDGES - 1 + WARM_START_CYCLES  # the edge that starts word 0's cycle
                assert all(watch.fetch_rom[:first]), f"{label}: left the ROM before RUN retired"
                assert not any(watch.fetch_rom[first:]), f"{label}: still in the ROM after RUN"
                core = watch.handles[0]
                assert int(core.flag_c.value) == 0, f"{label}: C was not restored"

        for straps in STUB_STRAPS:
            label = f"image {seed}, straps {straps:02b}"
            stub_result, _ = boot_outcome(straps, image)
            stub = expected_stub(straps, stub_result)
            watch = RomWatch(dut, label)
            await boot_reset(dut, straps)
            trace = await trace_edges(dut, RUN_ENTRY_EDGES + 96, label, watch)
            assert_quiet(trace, label, stub)
            watch.assert_never_left()
            watch.assert_stopped_at(stub)
    assert all(edges == warm_edges[0] for edges in warm_edges), (
        f"warm-start pin timing depends on the image: {warm_edges}"
    )


def corrupted_images(valid):
    """(name, image) pairs, each one defect away from `valid`."""
    out = []

    def flip(index, bit, name):
        image = list(valid)
        image[index] ^= 1 << bit
        out.append((name, image))

    flip(0, 0, "bit 0 of word 0")
    flip(127, 9, "bit 9 of word 127 (an odd-numbered word)")
    flip(254, 15, "bit 15 of word 254 (the last signed word)")
    flip(255, 3, "bit 3 of the signature word")
    swapped = list(valid)
    swapped[100], swapped[101] = swapped[101], swapped[100]
    assert swapped != valid
    out.append(("words 100 and 101 swapped", swapped))
    # Residues with exactly one zero byte: a check that compares only half
    # of PM_CRC passes one of these.
    need = {"residue high byte only": lambda r: r & 0xFF == 0 and r >> 8 != 0,
            "residue low byte only": lambda r: r >> 8 == 0 and r & 0xFF != 0}
    for value in range(1, 0x10000):
        image = list(valid)
        image[200] ^= value
        residue = crc_of_words(image)
        for name in list(need):
            if need[name](residue):
                out.append((f"{name} ({residue:#06x})", image))
                del need[name]
        if not need:
            break
    assert not need, f"could not craft: {sorted(need)}"
    return out


@cocotb.test()
async def test_warm_start_rejects_corrupted_images(dut):
    """Strap 10 with an image one defect away from a verified one: it is
    never run. No pin moves for longer than a passing warm start takes
    plus the whole probe program. White-box (RTL): the core never leaves
    the ROM and halts in the UART-load stub (DR 0013: "If it fails, fall
    through to UART load")."""
    start_clock(dut)
    p, _ = probe_program()
    valid = signed_image(p.words, filler_seed=3)
    uart_stub = stub_addresses()["uart_load"]
    for name, image in corrupted_images(valid):
        assert crc_of_words(image) != 0, f"premise: '{name}' must fail the check"
        result, model = boot_outcome(STRAP_WARM, image)
        assert result["outcome"] == "uart_wait" and result["pc"] == uart_stub, (name, result)
        label = f"corrupted image ({name})"
        await serial_load(dut, image)
        watch = RomWatch(dut, label)
        await boot_reset(dut, STRAP_WARM)
        trace = await trace_edges(dut, WARM_START_CYCLES + p.edge(len(p.lines)) + 32, label, watch)
        assert_quiet(trace, label, uart_stub)
        watch.assert_never_left()
        watch.assert_stopped_at(uart_stub)


def zero_padded_image(program, signature_ok=lambda s: s != 0):
    """`program`, zero words up to word 253, word 254 the first value from
    0 up that makes the signature (the CRC of words 0..254) satisfy
    `signature_ok`, and word 255 that signature. Word 254 is the only free
    word, as in a host re-padding an image by changing one filler word."""
    assert len(program) <= PM_WORDS - 2
    head = list(program) + [0x0000] * (PM_WORDS - 2 - len(program))
    for last in range(0x10000):
        body = head + [last]
        signature = crc_of_words(body)
        if signature_ok(signature):
            return body + [signature]
    raise AssertionError("no word 254 gives the wanted signature")


def run_zero_signature_cases(p):
    """(name, image) pairs whose word 255 is 0x0000 and whose CRC check
    passes: the all-zero image (Finding F1), and the probe program padded
    so that its real CRC is 0x0000 (the one-in-65,536 image a host must
    re-pad). The second would visibly drive pins if it ran."""
    zeros = [0x0000] * PM_WORDS
    real = zero_padded_image(p.words, lambda s: s == 0)
    return [("all-zero image", zeros), ("probe image whose real CRC is 0x0000", real)]


@cocotb.test()
async def test_warm_start_refuses_a_zero_signature(dut):
    """DR 0013 Finding F1, closed by issue #168 (option 4). CRC-16/XMODEM
    starts at 0x0000 (DR 0012), so 256 zero words carry their own valid
    signature, and an SRAM that powered up all-zero used to pass the warm
    start's check and run (256 NOPs). The boot program now refuses a
    signature of 0x0000 before it looks at the CRC, as the SPI-flash boot
    does, and falls through to the UART load. The same rule refuses a real
    image whose CRC happens to be 0x0000; here that is the probe program,
    which drives pins within a few instructions if it runs. No pin moves.
    White-box (RTL): the core never leaves the ROM and halts in the
    UART-load stub."""
    start_clock(dut)
    p, _ = probe_program()
    uart_stub = stub_addresses()["uart_load"]
    for name, image in run_zero_signature_cases(p):
        assert image[-1] == 0x0000 and crc_of_words(image) == 0, (
            f"premise: '{name}' must pass the CRC and carry a zero signature"
        )
        result, model = boot_outcome(STRAP_WARM, image)
        assert result["outcome"] == "halt" and result["pc"] == uart_stub, (name, result)
        assert model.pm == image, f"model: the warm start changed program memory ({name})"
        label = f"{name}, warm start"
        await serial_load(dut, image)
        watch = RomWatch(dut, label)
        await boot_reset(dut, STRAP_WARM)
        trace = await trace_edges(dut, WARM_START_CYCLES + p.edge(len(p.lines)) + 32, label, watch)
        assert_quiet(trace, label)
        watch.assert_never_left()
        watch.assert_stopped_at(uart_stub)


@cocotb.test()
async def test_warm_start_runs_zero_padded_images(dut):
    """The refusal is of the word 0x0000 and nothing wider. The probe
    program padded with zero words, signed with a nonzero signature, runs
    on strap 10 exactly as a randomly padded one does: on the same entry
    edge, with the reset state. So do two padded images whose signature has
    a zero high byte (0x00nn) or a zero low byte (0xnn00): a check that
    tested one byte of the signature would refuse one of them."""
    start_clock(dut)
    p, checks = probe_program()
    tail = p.edge(len(p.lines)) + 8
    cases = [
        ("zero padding", zero_padded_image(p.words)),
        ("signature 0x00nn", zero_padded_image(p.words, lambda s: s >> 8 == 0 and s & 0xFF != 0)),
        ("signature 0xnn00", zero_padded_image(p.words, lambda s: s & 0xFF == 0 and s >> 8 != 0)),
    ]
    for name, image in cases:
        assert image[-1] != 0x0000 and crc_of_words(image) == 0, f"premise: '{name}'"
        result, _ = boot_outcome(STRAP_WARM, image)
        assert result == {"outcome": "run", "target": 0, "pc": result["pc"],
                          "cycles": WARM_START_CYCLES - 2}, (name, result)
        label = f"{name} (signature {image[-1]:#06x}), warm start"
        await serial_load(dut, image)
        watch = RomWatch(dut, label)
        await boot_reset(dut, STRAP_WARM)
        trace = await trace_edges(dut, WARM_START_CYCLES + tail, label, watch)
        check_probe(trace, p, checks, WARM_START_CYCLES, 0x00, label)
        if watch.handles is not None:
            first = RUN_ENTRY_EDGES - 1 + WARM_START_CYCLES
            assert all(watch.fetch_rom[:first]), f"{label}: left the ROM before RUN retired"
            assert not any(watch.fetch_rom[first:]), f"{label}: still in the ROM after RUN"
