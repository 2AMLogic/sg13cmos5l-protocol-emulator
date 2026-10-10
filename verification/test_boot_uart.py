"""cocotb bench for DR 0013 layer 2's UART load, strap `00` (issue #139).

The claim: a PC (or any 3.3 V UART) on the demo board's USB-UART bridge pins
-- Tiny Tapeout "option B", RX `ui_in[1]`, TX `uo_out[0]` -- can load a program
into an unprogrammed chip with nothing else attached, and the chip runs the
image only if it arrived intact. The loader is firmware
(`firmware/asm/boot/boot_rom.asm`, the `uart_load` block): there is no UART
peripheral in the RTL.

The host is `verification/uart_boot_host.py`, an independent model: it
frames the image, plays the line levels into `ui_in[1]` at a chosen bit-rate
error, optionally toggles the unrelated `ui_in` bits, and says what the reply
must be. The reply is read off `uo_out[0]` and decoded by the repo's
independent UART reference model (`reference_models/uart.py`, `UartDecoder`),
which also grades each reply frame's timing against target-spec row 10. Nothing
in the host model or the checks below is derived from the firmware's source;
the one thing shared is the committed boot image under test.

What is checked (verification-plan section 7, "Boot programs"):

- **nominal**: a framed image is accepted, the reply is `0x06` + the CRC the
  host computes, and the program then runs from address 0 in the state a
  reset leaves (registers 0, `PM_ADDR` 0, `UIO_*` 0, `BOOT_STATUS` 0x00),
  with program memory equal to the image word for word (white-box, RTL);
- **row-10 tolerance**: the same at host bit-rate errors of -2 % and +2 %, back
  to back and with idle bits between bytes, with edge jitter and with the
  unrelated `ui_in` bits toggling, and a sweep past the edge that records
  where it stops working (a record, not a spec);
- **never run a bad image**: one flipped payload bit, a bad CRC (high byte,
  low byte, both), a length that is too small, a length that is too large
  (the chip stalls and the host recovers by padding), a wrong magic byte. In
  each, the reply is `0x15` (or none), the core never leaves the boot ROM
  (white-box), `uio_oe` stays 0, and `uo_out` stays at its idle level; a
  correct frame sent afterwards is accepted;
- **end to end**: the committed `uart_tx` program is loaded over the UART,
  runs, and its frames pass the reference model's `check_frame`;
  a full 256-word image loads, and (it being a signed image) survives a warm
  start; a failed warm start falls through to this loader; strap `11` behaves
  as `00`;
- **no pin is driven but TX**: `uio_oe` is 0 for as long as the boot program
  runs (the loader keeps a byte in `UIO_DIR` under `UIO_OD`/`uio_out` guards,
  see the boot source), and `uio_out` is 0xFF only while it does.

Timing is in core cycles. The 20 ns clock period only names the unconfirmed
50 MHz of target-spec row 4 for the ns-based reference model; every claim
here is a cycle count, and 115,200 baud is arithmetic at that clock.

All randomness is seeded; every run is byte-reproducible. White-box reads are
labelled and skipped at gate level (`GATES=yes`), where only pins are checked.
"""

import binascii
import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Edge, First, ReadOnly, Timer
from cocotb.utils import get_sim_time

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(__file__)
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))

import asm  # noqa: E402  (the DR 0003 assembler)
import gen_boot_rom  # noqa: E402
import loadseq  # noqa: E402  (the tool under test for the frame)
import uart_boot_host as host  # noqa: E402  (the independent host model)
from firmware_artifacts import parse_cycle_sections, parse_hex_image  # noqa: E402
from reference_models.uart import UartDecoder, UartFrameError  # noqa: E402
from reference_models.waveform import Signal  # noqa: E402
from test_boot_rom import Prog  # noqa: E402  (a straight-line program builder; no tests come with it)

CLK_NS = 20           # names the unconfirmed 50 MHz of row 4; see the module docstring
BIT = host.NOMINAL_CYCLES_PER_BIT
BAUD = 1e9 / (BIT * CLK_NS)
GATE_LEVEL = os.environ.get("GATES") == "yes"

BOOT_ASM = REPO_ROOT / "firmware" / "asm" / "boot" / "boot_rom.asm"
BOOT_HEX = REPO_ROOT / "firmware" / "build" / "boot" / "boot_rom.hex"
BOOT_CYCLES = REPO_ROOT / "firmware" / "build" / "boot" / "boot_rom.cycles.txt"
BOOT_ROM_V = REPO_ROOT / "rtl" / "protocol_boot_rom.v"

RX_BIT = 0x02            # ui_in[1], option B
STRAP_UART, STRAP_WARM, STRAP_RESERVED = 0b00, 0b10, 0b11
PM_WORDS = 256
FILL = 0xFF              # uo_out marker used by the probe image

# Longest the reply can take after the host's last stop bit: three frames of
# 10 bits plus the padding, and the loader's own latency.
REPLY_WINDOW = 3 * 10 * BIT + 3 * 400 + 2000


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
def probe_image():
    """A program that reports the state it was entered with, then proves it
    can drive pins. Returns (words, expected uo_out sequence)."""
    p = Prog()
    p.add("BZ bad")                         # Z is 0 at entry
    p.add("OR R0, R1")
    p.add("OR R0, R2")
    p.add("OR R0, R3")                      # R0 = the OR of all four registers
    p.add("LDI R1, 0xFF")
    p.add("OUT UO_OUT, R1")
    p.add("OUT UO_OUT, R0")                 # 0x00: R0-R3 were all 0
    want = [0x00]
    for name, value in (("BOOT_STATUS", 0x00), ("PM_ADDR", 0x00),
                        ("UIO_DIR", 0x00), ("UIO_OD", 0x00)):
        p.add("LDI R1, 0xFF")
        p.add("OUT UO_OUT, R1")
        p.add(f"RCTL R0, {name}")
        p.add("OUT UO_OUT, R0")
        want.append(value)
    p.add("LDI R1, 0xFF")
    p.add("OUT UO_OUT, R1")
    p.add("LDI R0, 0xA5")
    p.add("OUT UO_OUT, R0")                 # marker: the image ran to here
    want.append(0xA5)
    p.add("LDI R1, 0x0F")
    p.add("WCTL UIO_DIR, R1")               # a loaded program may drive pins
    p.add("HALT")
    p.add("bad: LDI R0, 0xBD")
    p.add("OUT UO_OUT, R0")
    p.add("HALT")
    return p.words, want


def padded(program, total, seed):
    """`program` then seeded filler words up to `total` words. No filler
    byte is 0xA5 (the magic) unless a test asks for it."""
    rng = random.Random(seed)
    words = list(program)
    while len(words) < total:
        word = rng.randrange(0x10000)
        if 0xA5 in (word >> 8, word & 0xFF):
            continue
        words.append(word)
    return words


def committed_words(stem):
    return parse_hex_image(REPO_ROOT / "firmware" / "build" / f"{stem}.hex")


# ---------------------------------------------------------------------------
# The session: reset, play a host, watch the pins
# ---------------------------------------------------------------------------
class Session:
    """One reset-to-end run. Pins are watched by edge, so a long frame costs
    simulator time, not Python time per cycle."""

    def __init__(self, dut):
        self.dut = dut
        self.log = []                  # (t_ns, name, int value)
        self.tasks = []
        self.t_release = None
        self.ui = 0
        self.cycle = 0                 # cycles since reset release, our own count

    # -- pins ---------------------------------------------------------------
    async def _watch(self, name):
        sig = getattr(self.dut, name)
        while True:
            await Edge(sig)
            value = sig.value
            assert value.is_resolvable, f"{name} is {value} (X/Z on a pin) at {get_sim_time('ns')} ns"
            self.log.append((float(get_sim_time("ns")), name, int(value)))

    def start_watching(self):
        for name in ("uo_out", "uio_out", "uio_oe"):
            self.log.append((float(get_sim_time("ns")), name, int(getattr(self.dut, name).value)))
            self.tasks.append(cocotb.start_soon(self._watch(name)))

    def stop(self):
        for task in self.tasks:
            task.cancel()
        self.tasks = []

    def values(self, name, t_from=0.0, t_to=float("inf")):
        return [(t, v) for (t, n, v) in self.log if n == name and t_from <= t <= t_to]

    def value_at(self, name, t_ns):
        current = None
        for t, v in self.values(name):
            if t > t_ns:
                break
            current = v
        return current

    # -- reset --------------------------------------------------------------
    async def reset(self, straps=STRAP_UART, settle=100):
        """MODE low (boot ROM), `straps` on ui_in[6:5], RX idle high."""
        dut = self.dut
        dut.ena.value = 1
        dut.uio_in.value = 0
        self.ui = (straps << 5) | RX_BIT
        dut.ui_in.value = self.ui
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 10)
        dut.rst_n.value = 1
        self.t_release = float(get_sim_time("ns"))
        self.cycle = 0
        self.start_watching()
        await ClockCycles(dut.clk, settle)
        self.cycle += settle

    async def serial_load(self, words):
        """DR 0001 layer 1, to put a known image in program memory first."""
        dut = self.dut
        dut.ena.value = 1
        dut.uio_in.value = 0
        dut.ui_in.value = 0x80
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 10)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 1)
        for word in words:
            for bit in range(15, -1, -1):
                dut.ui_in.value = 0x80 | ((word >> bit) & 1)
                await ClockCycles(dut.clk, 1)
        dut.ui_in.value = 0x00
        await ClockCycles(dut.clk, 1)

    # -- the host -----------------------------------------------------------
    async def play(self, data, rate_error=0.0, gap_bits=0, jitter=0, noise=False,
                   seed=1, lead=0):
        """Send `data` on the RX pin. Returns the cycle (since reset release)
        at which the host's first start bit began. Does not return until the
        last stop bit has been on the line for a full bit."""
        start = self.cycle + 1 + lead
        line = host.edges(data, start, rate_error, gap_bits, jitter, seed)
        stop = host.end_cycle(data, start, rate_error, gap_bits)
        events = [(c, "rx", level) for c, level in line]
        if noise:
            rng = random.Random(seed ^ 0x5EED)
            events += [(c, "noise", bit) for c, bit in host.noise_edges(start - 50, stop, rng)]
        events.sort(key=lambda e: (e[0], e[1] != "rx"))
        ui = self.ui
        for cycle, kind, arg in events:
            if cycle > self.cycle:
                await ClockCycles(self.dut.clk, cycle - self.cycle)
                self.cycle = cycle
            if kind == "rx":
                ui = (ui & ~RX_BIT) | (RX_BIT if arg else 0)
            else:
                ui ^= 1 << arg
            self.dut.ui_in.value = ui
        self.ui = ui
        if stop > self.cycle:
            await ClockCycles(self.dut.clk, stop - self.cycle)
            self.cycle = stop
        return start

    async def idle(self, cycles):
        await ClockCycles(self.dut.clk, cycles)
        self.cycle += cycles

    def t_of(self, cycle):
        return self.t_release + cycle * CLK_NS

    # -- reading the chip ---------------------------------------------------
    def reply(self, t_from, count=3):
        """Decode up to `count` TX frames that start after `t_from`, with the
        repo's UART reference model. Returns (bytes, reports); each report
        gains `t_abs`, its start in absolute ns.

        The model looks for a falling edge by sampling 1e-9 ns before it,
        which is below float resolution at the ~1e8 ns absolute times a long
        run reaches, so the signal is handed over rebased to `t_from`."""
        sig = Signal(self.value_at("uo_out", t_from) & 1, name="uo_out[0]")
        for t, v in self.values("uo_out", t_from):
            if t > t_from:
                sig.add(t - t_from, v & 1)
        try:
            reports = UartDecoder(BAUD).decode(sig, t_from=0.0, max_frames=count)
        except UartFrameError:
            return None, []
        for r in reports:
            r.t_abs = r.t_start + t_from
        return bytes(r.data for r in reports), reports


def whitebox(dut):
    """(core, program-memory array) for the labelled white-box reads, or
    None at gate level."""
    if GATE_LEVEL:
        return None
    return dut.u_core, dut.u_prog_mem.u_sram.i_SRAM_1P_behavioral_bm_bist.memory


def read_memory(dut, count):
    """The first `count` program-memory words (white-box, RTL). Words nothing
    wrote are X in simulation, so only a range the test knows was written is
    read."""
    handles = whitebox(dut)
    if handles is None:
        return None
    return [int(handles[1][i].value) for i in range(count)]


class RomWatch:
    """White-box (RTL): did the core ever leave the boot ROM? Sampled on a
    slow poll plus at the end; `RUN` is a one-way switch, so a coarse poll
    cannot miss it."""

    def __init__(self, dut):
        self.handles = whitebox(dut)

    def left_rom(self):
        if self.handles is None:
            return None
        return not int(self.handles[0].fetch_rom.value)


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------
def assert_pins_quiet(session, t_from, t_to, label):
    """While the boot program runs: no uio pin drives; uio_out is 0xFF only
    after the loader's guard (it is never anything else but 0)."""
    for t, v in session.values("uio_oe", t_from, t_to):
        assert v == 0, f"{label}: uio_oe={v:#04x} at {t} ns"
    for t, v in session.values("uio_out", t_from, t_to):
        assert v in (0x00, 0xFF), f"{label}: uio_out={v:#04x} at {t} ns"
    for t, v in session.values("uo_out", t_from, t_to):
        assert v in (0x00, 0x01), f"{label}: uo_out={v:#04x} at {t} ns (only TX may move)"


def check_reply_timing(reports, label):
    """Each reply frame: every edge on a multiple of 434 cycles, graded by the
    model's own check_frame (row 10)."""
    for r in reports:
        assert r.stop_ok, f"{label}: framing error in reply"
        assert UartDecoder(BAUD).check_frame(r), (
            f"{label}: reply drift {r.drift_pct:.3f}% over the row-10 bound")
    for a, b in zip(reports, reports[1:]):
        pitch = (b.t_abs - a.t_abs) / CLK_NS
        assert pitch >= 10 * BIT, f"{label}: reply bytes {pitch:.0f} cycles apart, a frame is {10 * BIT}"


def tx_edge_gaps_cycles(session, t_from, t_to):
    """Gaps between consecutive uo_out[0] edges in [t_from, t_to], in cycles."""
    edges, last = [], None
    for t, v in session.values("uo_out"):
        bit = v & 1
        if last is not None and bit != last and t_from <= t <= t_to:
            edges.append(t)
        last = bit
    return [round((b - a) / CLK_NS) for a, b in zip(edges, edges[1:])]


async def load_and_check(dut, session, words, label, expect_accept=True, rate_error=0.0,
                         gap_bits=0, jitter=0, noise=False, seed=1, run_after=400,
                         data=None, reset=True, lead=0):
    """Reset (unless told not to), send `words` framed, read the reply.
    Returns dict(start, reply, reports, left_rom)."""
    if reset:
        await session.reset()
    payload = host.frame(words) if data is None else data
    t_before = session.t_of(session.cycle)
    start = await session.play(payload, rate_error, gap_bits, jitter, noise, seed, lead)
    t_sent = session.t_of(session.cycle)
    await session.idle(REPLY_WINDOW)
    got, reports = session.reply(t_sent - 10 * BIT * CLK_NS)
    result = {"start": start, "reply": got, "reports": reports, "t_sent": t_sent,
              "t_before": t_before}
    await session.idle(run_after)
    result["left_rom"] = RomWatch(dut).left_rom()
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_boot_image_chain_and_host_agreement(dut):
    """The committed boot image is what its source assembles to, the ROM is
    what the generator makes of it, the UART load's bit period is 434 in the
    cycle report, and the independent host model and `loadseq` frame the same
    bytes (checked against binascii as a third opinion). No DUT activity."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    program = asm.assemble_file(BOOT_ASM)
    rom = [int(x, 16) for x in BOOT_HEX.read_text().split()]
    assert list(program.words) == rom, "boot_rom.hex is not what boot_rom.asm assembles to"
    assert len(rom) <= gen_boot_rom.ROM_WORDS_MAX
    assert BOOT_ROM_V.read_text() == gen_boot_rom.render(rom, BOOT_HEX.read_text())
    sections = parse_cycle_sections(BOOT_CYCLES.read_text())
    assert sections["uart_rx_bit"][2] == BIT, sections["uart_rx_bit"]
    dut._log.info(f"boot image: {len(rom)} of {gen_boot_rom.ROM_WORDS_MAX} words")

    images = [[0x0000], [0x1234, 0xABCD], padded(probe_image()[0], 40, 7)]
    images += [committed_words(s) for s in ("uart_tx", "spi_mode0", "i2c_fast", "demo_roundtrip")]
    images.append(padded([], 256, 9))
    for words in images:
        a, b = host.frame(words), loadseq.uart_frame(words)
        assert a == b, f"host model and loadseq disagree on a {len(words)}-word frame"
        body = a[2:-2]
        assert binascii.crc_hqx(body, 0) == (a[-2] << 8) | a[-1]
        assert a[0] == 0xA5 and a[1] == len(words) - 1 and len(a) == 2 * len(words) + 4
        assert binascii.crc_hqx(a[2:], 0) == 0
    # The host model's line levels are 8N1: start low, LSB first, stop high.
    assert host.edges(bytes([0x00]), 0) == [(0, 0), (9 * BIT, 1)]
    assert host.edges(bytes([0xFF]), 0) == [(0, 0), (BIT, 1)]
    assert host.edges(bytes([0x01]), 10) == [(10, 0), (10 + BIT, 1), (10 + 2 * BIT, 0), (10 + 9 * BIT, 1)]
    await ClockCycles(dut.clk, 2)


@cocotb.test()
async def test_nominal_load_runs_the_image(dut):
    """A framed image at the nominal rate: accepted, replied `0x06` + CRC,
    run from address 0 in the state a reset leaves, program memory equal to
    the image. White-box (RTL): the core left the ROM; program memory words."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    program, want = probe_image()
    words = padded(program, 48, 11)
    session = Session(dut)
    r = await load_and_check(dut, session, words, "nominal")
    session.stop()
    assert r["reply"] == host.expected_reply(words), (r["reply"], host.expected_reply(words))
    check_reply_timing(r["reports"], "nominal")
    assert r["left_rom"] in (True, None)
    t_run = r["reports"][-1].t_abs + 10 * BIT * CLK_NS
    # Quiet until the program's own first marker, which is after the
    # hand-over's writes and before it could drive anything.
    t_first_marker = next(t for t, v in session.values("uo_out", t_run - 10 * CLK_NS) if v == FILL)
    assert_pins_quiet(session, session.t_release, t_first_marker - 1.0, "nominal, through the hand-over")
    # TX idled high the whole time until the first reply frame.
    first_reply = r["reports"][0].t_abs
    assert session.value_at("uo_out", first_reply - CLK_NS) == 0x01
    # The probe's report, in order, after the hand-over.
    seq = [v for t, v in session.values("uo_out", t_run) if v != FILL]
    assert seq[:1] == [0x00] or seq[:2] == [0x00, 0x00], seq[:4]
    seq = [v for v in seq if v != 0x01]
    assert seq[-len(want):] == want, f"probe saw {seq}, wanted {want}"
    assert session.value_at("uio_oe", float("inf")) == 0x0F, "the loaded program could not drive uio"
    assert session.value_at("uio_out", t_run + 200) == 0x00
    mem = read_memory(dut, len(words))
    if mem is not None:
        assert mem == words, "program memory differs from the image"
    # The reply's own timing: inside each frame every edge is a whole number
    # of bit periods from the start edge; each stop bit is at least one bit
    # period and at most a few cycles longer (the padding that keeps a late
    # RUN from shortening it).
    for r_ in r["reports"]:
        gaps = tx_edge_gaps_cycles(session, r_.t_abs, r_.t_abs + 9 * BIT * CLK_NS)
        assert gaps and all(g % BIT == 0 for g in gaps), f"reply edge gaps {gaps}"
    pitches = [round((b.t_abs - a.t_abs) / CLK_NS) for a, b in zip(r["reports"], r["reports"][1:])]
    assert all(10 * BIT <= p <= 10 * BIT + 24 for p in pitches), f"reply byte pitch {pitches}"
    dut._log.info(f"nominal: reply {r['reply'].hex()} byte pitch {pitches} cycles")


async def accepted_at(dut, words, **kw):
    session = Session(dut)
    r = await load_and_check(dut, session, words, "tolerance", **kw)
    session.stop()
    ok = r["reply"] == host.expected_reply(words) and r["left_rom"] in (True, None)
    return ok, r, session


@cocotb.test()
async def test_row10_tolerance_edges(dut):
    """Host bit-rate errors of -2 % and +2 % (target-spec row 10's bound),
    back to back and with idle bits, with edge jitter, and with the unrelated
    ui_in bits toggling: every one is accepted and runs. Then a sweep to
    find the rate error at which the loader stops working, recorded in the
    log -- and a negative control: a host 12 % off must NOT be accepted, so
    the check can fail."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    words = padded(probe_image()[0], 24, 21)
    cases = [
        ("-2%", dict(rate_error=-0.02)),
        ("+2%", dict(rate_error=+0.02)),
        ("-2%, 2 idle bits", dict(rate_error=-0.02, gap_bits=2)),
        ("+2%, 2 idle bits", dict(rate_error=+0.02, gap_bits=2)),
        ("-2%, jitter 3", dict(rate_error=-0.02, jitter=3, seed=5)),
        ("+2%, jitter 3", dict(rate_error=+0.02, jitter=3, seed=6)),
        ("nominal, noise", dict(noise=True, seed=7)),
        ("+2%, noise", dict(rate_error=+0.02, noise=True, seed=8)),
        ("-2%, noise, idle", dict(rate_error=-0.02, noise=True, gap_bits=1, seed=9)),
        ("late start", dict(lead=7)),
    ]
    for label, kw in cases:
        ok, r, _ = await accepted_at(dut, words, **kw)
        assert ok, f"{label}: reply {r['reply']!r}, left ROM {r['left_rom']}"
        check_reply_timing(r["reports"], label)
    if GATE_LEVEL:
        dut._log.info("gate level: the rate-error sweep and the negative control run at RTL only")
        return
    small = padded(probe_image()[0], 22, 22)
    edge = {}
    for sign, name in ((+1, "slow"), (-1, "fast")):
        passing = 0.0
        for pct in (3, 4, 5, 6, 7, 8):
            ok, _, _ = await accepted_at(dut, small, rate_error=sign * pct / 100.0)
            if not ok:
                break
            passing = pct
        edge[name] = passing
    dut._log.info(f"row-10 sweep, back to back, whole-percent steps: works to "
                  f"+{edge['slow']} % (host slow) and -{edge['fast']} % (host fast); margin over 2 %")
    assert edge["slow"] >= 2 and edge["fast"] >= 2
    for sign in (+1, -1):
        ok, r, _ = await accepted_at(dut, small, rate_error=sign * 0.12)
        assert not ok, f"NEGATIVE CONTROL FAILED TO FAIL: a host {sign * 12:+d} % off was accepted"
        assert r["left_rom"] in (False, None), "a mistimed frame ran"


def flip_bit(frame, index, bit):
    out = bytearray(frame)
    out[index] ^= 1 << bit
    return bytes(out)


@cocotb.test()
async def test_bad_images_never_run(dut):
    """Corrupted payloads, bad CRCs, bad lengths and a wrong magic: none
    runs. A rejected frame is answered `0x15` + the chip's CRC (a different
    CRC from the trailer's), the core stays in the ROM, no uio pin drives,
    uo_out stays at idle high, and a correct frame sent afterwards is
    accepted. White-box (RTL): the core's fetch source."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    program, want = probe_image()
    words = padded(program, 32, 31)
    good = host.frame(words)
    n_body = 2 * len(words)

    def with_count(count):          # a header lying about the length
        return bytes((good[0], count)) + good[2:]

    cases = []
    for name, index, bit in (("payload first byte", 2, 0), ("payload middle", 2 + n_body // 2, 5),
                             ("payload last byte", 1 + n_body, 7)):
        cases.append((f"flipped bit, {name}", flip_bit(good, index, bit), "nak"))
    cases += [
        ("bad CRC, high byte", flip_bit(good, len(good) - 2, 3), "nak"),
        ("bad CRC, low byte", flip_bit(good, len(good) - 1, 0), "nak"),
        ("bad CRC, both bytes", good[:-2] + bytes((good[-2] ^ 0xFF, good[-1] ^ 0xFF)), "nak"),
        ("length too small by one word", with_count(len(words) - 2), "nak+reset"),
        ("length too small by half the image", with_count(len(words) // 2 - 1), "nak+reset"),
        ("length 1 word", with_count(0), "nak+reset"),
        ("length too large (stalls)", with_count(len(words) + 4), "stall"),
        ("wrong magic", bytes((0xA4,)) + good[1:], "silent"),
        ("magic only, then silence", good[:1], "stall+reset"),
    ]
    for label, data, kind in cases:
        session = Session(dut)
        await session.reset()
        watch = RomWatch(dut)
        t0 = session.t_of(session.cycle)
        if kind in ("stall", "stall+reset"):
            # The chip waits for bytes that never come: no reply, no RUN.
            await session.play(data)
            await session.idle(REPLY_WINDOW)
            assert session.reply(t0)[0] == b"", f"{label}: a reply came for an unfinished frame"
            assert watch.left_rom() in (False, None), f"{label}: ran"
        if kind == "stall":
            # The host recovers by padding until the loader answers (the
            # shortfall here is a few words; a "stall+reset" case is missing
            # too much for padding to be a sensible recovery).
            # Zero padding would be a trap: the CRC of a message followed by
            # its own CRC and then zeros is still 0, so the chip would read
            # the stream as a valid longer image. Pad with 0x5A.
            pad = bytes((0x5A,)) * (2 * len(words) + 4)
            t_pad = session.t_of(session.cycle)
            await session.play(pad)
            await session.idle(REPLY_WINDOW)
            got, reports = session.reply(t_pad)
            assert got is not None and len(got) == 3 and got[0] == host.NAK, f"{label}: padding gave {got!r}"
        elif kind != "stall+reset":
            await session.play(data)
            await session.idle(REPLY_WINDOW)
            got, reports = session.reply(t0)
            if kind in ("nak", "nak+reset"):
                assert got is not None and len(got) == 3 and got[0] == host.NAK, f"{label}: reply {got!r}"
                check_reply_timing(reports, label)
            else:
                assert got == b"", f"{label}: replied {got!r} to a frame with no magic"
        assert watch.left_rom() in (False, None), f"{label}: the core left the boot ROM"
        assert_pins_quiet(session, session.t_release, float("inf"), label)
        if kind in ("nak+reset", "silent", "stall+reset"):
            # The bytes the loader did not take as part of the frame were
            # still sent, and any of them may be 0xA5 (this image has several):
            # the loader reads that as the start of a frame and waits for the
            # rest. A host that sent a wrong length or a wrong first byte
            # recovers by resetting the chip (rst_n); the retry then starts
            # from the top.
            session.stop()
            await session.reset()
            watch = RomWatch(dut)
        # Retry: the loader is back at the start.
        t_retry = session.t_of(session.cycle)
        await session.play(good)
        await session.idle(REPLY_WINDOW)
        got, reports = session.reply(t_retry)
        assert got == host.expected_reply(words), f"{label}: retry gave {got!r}"
        await session.idle(300)
        assert watch.left_rom() in (True, None), f"{label}: the retry did not run"
        mem = read_memory(dut, len(words))
        if mem is not None:
            assert mem == words, f"{label}: memory after the retry"
        session.stop()
        dut._log.info(f"{label}: not run, retry ran")


@cocotb.test()
async def test_garbage_before_the_magic_is_ignored(dut):
    """Bytes other than 0xA5 ahead of a frame are skipped (the loader's
    resync), including 0x00, 0xFF, 0x55 and a frame-shaped run that begins
    with the wrong magic."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    words = padded(probe_image()[0], 24, 41)
    noise = bytes((0x00, 0xFF, 0x55, 0x5A, 0xA4, 0xA6, 0x12, 0x00)) + host.frame(words)[1:7]
    session = Session(dut)
    r = await load_and_check(dut, session, words, "garbage", data=noise + host.frame(words))
    session.stop()
    assert r["reply"] == host.expected_reply(words), r["reply"]
    assert r["left_rom"] in (True, None)


@cocotb.test()
async def test_end_to_end_protocol_program_over_uart(dut):
    """Load the committed `uart_tx` program (a protocol program, not a boot
    image) over the UART, let it run, and grade its output with the
    existing independent reference model: `UartDecoder` finds the frames
    and `check_frame` grades them against row 10, at the 50-cycle bit
    period `uart_tx` implements. The loader's own handover must not look
    like a frame to that decoder: it hands over a low TX line."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    words = committed_words("uart_tx")
    session = Session(dut)
    r = await load_and_check(dut, session, words, "e2e uart_tx", run_after=0)
    assert r["reply"] == host.expected_reply(words), r["reply"]
    last = r["reports"][-1]
    t_handover = last.t_abs + 10 * BIT * CLK_NS
    await session.idle(60 * 50 * 6)
    session.stop()
    prog_bit = 50
    t_ref = t_handover - 2 * CLK_NS      # rebased: see Session.reply on float resolution
    sig = Signal(0, name="uo_out[0]")
    last_level = 0
    for t, v in session.values("uo_out", t_ref):
        if t > t_ref and (v & 1) != last_level:
            sig.add(t - t_ref, v & 1)
            last_level = v & 1
    decoder = UartDecoder(1e9 / (prog_bit * CLK_NS))
    reports = decoder.decode(sig, t_from=0.0)
    assert [rep.data for rep in reports] == [0x5A, 0xA5], reports
    for rep in reports:
        assert rep.stop_ok and decoder.check_frame(rep), rep
    dut._log.info(f"uart_tx loaded over UART ({len(words)} words) and graded: {reports}")


@cocotb.test()
async def test_full_image_and_warm_start(dut):
    """256 words: the largest frame (count byte 0xFF, 516 bytes). The image
    is signed (word 255 = the CRC of words 0..254), so a warm start of the
    same program memory verifies and runs it too. A first byte-for-byte
    memory comparison is white-box (RTL)."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    if GATE_LEVEL:
        dut._log.info("gate level: the 256-word image (about 2.2 million cycles) runs at RTL only")
        return
    program, want = probe_image()
    body = padded(program, 255, 51)
    sig = loadseq.crc16_xmodem(host.image_bytes(body))
    words = body + [sig]
    session = Session(dut)
    r = await load_and_check(dut, session, words, "256 words")
    assert r["reply"] == host.expected_reply(words), r["reply"]
    assert host.expected_reply(words)[1:] == bytes((0x00, 0x00)), "premise: a signed image has residue 0"
    assert r["left_rom"] in (True, None)
    mem = read_memory(dut, PM_WORDS)
    if mem is not None:
        assert mem == words, "program memory differs from the 256-word image"
    session.stop()
    # Warm start: boot ROM strap 10 on the memory the UART just filled.
    warm = Session(dut)
    await warm.reset(STRAP_WARM, settle=2400)
    await warm.idle(400)
    warm.stop()
    seq = [v for t, v in warm.values("uo_out") if v != FILL]
    assert seq[-len(want):] == want, f"warm start of the UART-loaded image saw {seq}"
    assert RomWatch(dut).left_rom() in (True, None)


@cocotb.test()
async def test_fallthroughs_into_the_uart_load(dut):
    """Strap `11` (reserved) behaves as `00`, and a warm start whose image
    fails its check falls through to this loader (DR 0013: "If it fails, fall
    through to UART load"), which then loads and runs an image."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    words = padded(probe_image()[0], 20, 61)
    session = Session(dut)
    await session.reset(STRAP_RESERVED)
    t0 = session.t_of(session.cycle)
    await session.play(host.frame(words))
    await session.idle(REPLY_WINDOW + 300)
    session.stop()
    assert session.reply(t0)[0] == host.expected_reply(words)
    assert RomWatch(dut).left_rom() in (True, None)

    garbage = [random.Random(71).randrange(0x10000) for _ in range(PM_WORDS)]
    loader = Session(dut)
    await loader.serial_load(garbage)
    loader.stop()
    session = Session(dut)
    await session.reset(STRAP_WARM, settle=2500)       # the failed check takes ~2,300 cycles
    t0 = session.t_of(session.cycle)
    assert RomWatch(dut).left_rom() in (False, None), "an unsigned image ran on a warm start"
    await session.play(host.frame(words))
    await session.idle(REPLY_WINDOW + 300)
    session.stop()
    assert session.reply(t0)[0] == host.expected_reply(words)
    assert RomWatch(dut).left_rom() in (True, None)
