"""cocotb bench for DR 0013 layer 2, strap `01`: the SPI-flash boot program
on `tt_um_2amlogic_protocol_emulator` (issue #140).

With `MODE` low and `ui_in[6:5] = 01` the boot ROM drives the Tiny Tapeout
QSPI Pmod's flash (CS0 `uio[0]`, MOSI `uio[1]`, MISO `uio[2]`, SCK
`uio[3]`), reads 512 bytes from address 0 with command `0x03`, writes them
into program memory through `PM_*`, checks them against the image's
signature word (word 255 = CRC-16/XMODEM of words 0..254, the warm start's
format) and either hands over with `RUN 0` or releases every pin and halts.

The claims, each with the independent party that grades it
----------------------------------------------------------
* **The flash is a model, not the bench.** `reference_models/spi_flash.py`
  answers `0x03` reads from a byte image and checks SPI mode 0 on every
  edge it sees (SCK idle low at CS edges, CS setup and hold, MOSI setup and
  hold, pulse widths, the READ frequency ceiling, the MISO bit being valid
  when the master clocks it). It is driven only by the pins the design
  drives, resolved through the silicon-true pad model with the Pmod's CS
  pull-up. A clean boot has no violation and exactly one transaction:
  `0x03`, address 0, 512 bytes.
* **The ISA, not the RTL, says what the pins do.** `BootModel` in
  `test_boot_rom.py` (an interpreter written from DR 0001/DR 0012, no code
  shared with the RTL or the assembler) runs the committed boot image
  against its own instance of the flash model. The design's
  `uio_out`/`uio_oe` must equal the model's on every clock edge of the
  boot, and `uo_out` must stay 0. That is also where the cycle counts come
  from.
* **A blank or corrupt flash never reaches `RUN`.** All-0xFF (blank), no
  Pmod with MISO pulled high or low, a fitted flash of zeros, 7 images
  one defect away from a good one, a good image shifted by one byte, and a
  valid-CRC image whose signature is 0x0000: none runs. White-box (RTL
  only): the core never leaves the boot ROM and halts at `spi_fail`.
  Pin-level: from the edge the boot program releases its pins, every `uio`
  is an input and `uo_out` is 0 for the rest of the run.
* **A good image runs and is graded by its protocol's reference model.**
  The committed `uart_tx` and `spi_mode0` programs, signed and placed in
  the flash, boot and are graded by `UartDecoder` and `check_burst` exactly
  as the loaded-by-serial benches grade them. A probe program checks the
  state the program is entered with (R0-R3, Z, C = 0, `PM_ADDR` and
  `PM_CRC` = 0, `BOOT_STATUS` = 0).
* **Pin discipline.** Over every run, the design drives only `uio[0]`,
  `uio[1]` and `uio[3]`; the PSRAM chip selects `uio[6]` and `uio[7]` (and
  SD2/SD3, `uio[4]`/`uio[5]`) are never driven, so the Pmod's pull-ups
  decide them: deselected.

Pad model and the board. The Pmod's CS lines have a pull-up to 3.3 V
(`qspi-pmod.kicad_sch`: R1-R3, 10 k; the README says 1 k, see DR 0013's
notes), so `uio[0]`, `uio[6]`, `uio[7]` are pulled up here. A floating
SCK/MOSI input is read by the flash model as low, which only matters after
the boot program has released the pins, when CS0 is pulled high and the
flash ignores them.

Pin-only by default. Under the gate-level Makefile (`GATES=yes`,
`flow/run-firmware-gate-level.sh --boot-spi`) the hierarchy is gone and
only the pin checks run; the RTL run also reads, labelled as such,
`u_core.fetch_rom`, `u_core.halted` and `u_core.pc`.

Every image and seed is fixed in source, so every run is byte-reproducible.
The simulation clock is 20 ns, the nominal of the other protocol benches
(target-spec row 4 is unconfirmed; the number only names the ns/cycle
mapping and is never a measurement).
"""

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(__file__)
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))

import asm  # noqa: E402  (the DR 0003 assembler)
import test_boot_rom as br  # noqa: E402  (BootModel, probe program, image helpers; functions only)
import test_firmware_spi as fs  # noqa: E402  (the SPI program's constants and burst helpers)
import test_firmware_uart as fu  # noqa: E402  (CapturedPin and the UART program's constants)
from firmware_artifacts import parse_hex_image  # noqa: E402
from reference_models.spi import MODES, check_burst  # noqa: E402
from reference_models.spi_flash import SpiFlashModel  # noqa: E402
from reference_models.uart import UartDecoder  # noqa: E402
from test_protocol_emulator import load_program  # noqa: E402,F401
from uio_pads import UioPads, resolve_pin  # noqa: E402

GATE_LEVEL = os.environ.get("GATES") == "yes"

CLK_PERIOD_NS = 20
F_CLK_HZ = 1e9 / CLK_PERIOD_NS
RUN_ENTRY_EDGES = br.RUN_ENTRY_EDGES

# The Tiny Tapeout QSPI Pmod (mole99/qspi-pmod) pin plan, uio[n].
CS0, MOSI, MISO, SCK = 0, 1, 2, 3
SD2, SD3, CS1, CS2 = 4, 5, 6, 7
PMOD_DRIVEN_MASK = (1 << CS0) | (1 << MOSI) | (1 << SCK)  # what the program may drive

STRAP_SPI = br.STRAP_SPI
PM_WORDS = br.PM_WORDS
IMAGE_BYTES = 2 * PM_WORDS

# Pulls the board puts on the lines: CS0, CS1 and CS2 are pulled up (10 k,
# R1-R3 of qspi-pmod.kicad_sch); the others float.
PMOD_PULLS = {CS0: "up", CS1: "up", CS2: "up"}

BOOT_ASM = br.BOOT_ASM


def board_pulls(miso_pull):
    """The Pmod's pulls plus, for a board with no flash fitted, whatever
    holds the MISO line ("up", "down" or None = floating)."""
    pulls = dict(PMOD_PULLS)
    if miso_pull:
        pulls[MISO] = miso_pull
    return pulls

# Cap on instructions the model runs for one boot (the boot is ~62,000).
MODEL_LIMIT = 200_000


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
def to_flash_bytes(words):
    return b"".join(bytes(((w >> 8) & 0xFF, w & 0xFF)) for w in words)


def sign(words, filler=0x0000):
    """A flash image: `words` padded to 255 words and word 255 = the CRC-16
    of words 0..254 (`binascii.crc_hqx`, via test_boot_rom.crc_of_words)."""
    assert len(words) <= PM_WORDS - 1
    body = list(words) + [filler] * (PM_WORDS - 1 - len(words))
    return body + [br.crc_of_words(body)]


def zero_signature_image():
    """256 words whose CRC check passes (residue 0) and whose signature word
    is 0x0000: a body is searched for whose own CRC is zero. The search is
    over one filler word, deterministic, and ends at the first hit."""
    p, _ = br.probe_program()
    body = list(p.words) + [0] * (PM_WORDS - 1 - len(p.words))
    for value in range(0x10000):
        body[200] = value
        if br.crc_of_words(body) == 0:
            image = body + [0]
            assert br.crc_of_words(image) == 0
            return image
    raise AssertionError("no filler word gives a zero CRC")


# ---------------------------------------------------------------------------
# What the boot program should do, from the ISA (BootModel) and the flash model
# ---------------------------------------------------------------------------
def line_level(uio_out, uio_dir, pin, pulls):
    """The level the board puts on `pin` given the design's pad state, as
    0/1; a floating line reads 0 (see the module docstring)."""
    level, _ = resolve_pin(
        str((uio_dir >> pin) & 1), str((uio_out >> pin) & 1), None, pulls.get(pin)
    )
    assert level in "01z", level
    return 1 if level == "1" else 0


def predict(flash_image, miso_pull, pulls, straps=STRAP_SPI):
    """Run the committed boot ROM on `BootModel` with its own flash model.

    Returns (result, model, flash_or_None, pin_timeline) where pin_timeline
    is [(edge, uio_out, uio_dir)] in DUT edge numbering (edge 0 = the mode-
    sampling edge, the first instruction retires at edge 2, and a pin write
    made when `e` cycles have elapsed is visible after edge 2 + e).
    """
    flash = SpiFlashModel(flash_image) if flash_image is not None else None
    model = br.BootModel(br.rom_words(), straps, [None] * PM_WORDS)
    timeline = []

    def edge_t(k):
        return 1000.0 + k * CLK_PERIOD_NS

    def on_uio(elapsed, out, direction):
        k = RUN_ENTRY_EDGES + elapsed
        timeline.append((k, out, direction))
        if flash is not None:
            flash.step(
                edge_t(k),
                line_level(out, direction, CS0, pulls),
                line_level(out, direction, SCK, pulls),
                line_level(out, direction, MOSI, pulls),
            )

    def uio_in_at(elapsed):
        # IN retires at edge 2 + elapsed and sees the pad as the flash drives
        # it at that instant (the bench applies the same value one edge early).
        value = flash.miso(edge_t(RUN_ENTRY_EDGES + elapsed)) if flash is not None else None
        if value is None:
            value = 1 if miso_pull == "up" else 0
        return value << MISO

    model.on_uio = on_uio
    model.uio_in_at = uio_in_at
    result = model.run(limit=MODEL_LIMIT)
    return result, model, flash, timeline


def timeline_at(timeline, edges):
    """[(uio_out, uio_dir)] for edges 0..edges, forward-filled from reset."""
    out, direction, i = [], (0, 0), 0
    for k in range(edges + 1):
        while i < len(timeline) and timeline[i][0] <= k:
            direction = (timeline[i][1], timeline[i][2])
            i += 1
        out.append(direction)
    return out


# ---------------------------------------------------------------------------
# DUT helpers
# ---------------------------------------------------------------------------
def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


def whitebox(dut):
    return None if GATE_LEVEL else dut.u_core


async def serial_load(dut, words):
    """DR 0001 layer 1 (pads are not running during it)."""
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
    await RisingEdge(dut.clk)


class Boot:
    """One reset with strap 01 on a Pmod board, recorded edge by edge."""

    def __init__(self, dut, label, flash_image, miso_pull=None, miso_driver=None):
        self.dut = dut
        self.label = label
        self.flash_image = flash_image
        self.miso_pull = miso_pull
        pulls = board_pulls(miso_pull)
        self.pulls = pulls
        self.pads = UioPads(dut, pulls=pulls, name="qspi-pmod")
        self.flash = SpiFlashModel(flash_image) if flash_image is not None else None
        self.trace = []  # per edge: dict(uo_out, uio_out, uio_oe, uio0)
        self.times = []
        self.fetch_rom = []
        self.tasks = []
        self.miso_driver = miso_driver

    async def reset(self):
        dut = self.dut
        dut.ena.value = 1
        dut.ui_in.value = STRAP_SPI << 5  # MODE low
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 10)
        self.pads.start()
        await RisingEdge(dut.clk)  # let the pad model settle uio_in in reset
        dut.rst_n.value = 1
        await RisingEdge(dut.clk)  # the mode-sampling edge = edge 0

    async def record(self, edges):
        """Record edges 0..edges, and run the flash model alongside."""
        dut, pads, core = self.dut, self.pads, whitebox(self.dut)
        for k in range(edges + 1):
            if k:
                await RisingEdge(dut.clk)
            await ReadOnly()
            t = float(get_sim_time("ns"))
            sample = {}
            for name in ("uo_out", "uio_out", "uio_oe"):
                value = getattr(dut, name).value
                assert value.is_resolvable, f"{self.label}: edge {k}: {name} is {value}"
                sample[name] = int(value)
            sample["uio0"] = pads.line(0)
            self.trace.append(sample)
            self.times.append(t)
            if core is not None:
                self.fetch_rom.append(int(core.fetch_rom.value))
            out, oe = sample["uio_out"], sample["uio_oe"]
            if self.flash is not None:
                self.flash.step(
                    t,
                    line_level(out, oe, CS0, self.pulls),
                    line_level(out, oe, SCK, self.pulls),
                    line_level(out, oe, MOSI, self.pulls),
                )
                # what the pin shows when the core samples it, one clock on
                self._pending = self.flash.miso(t + CLK_PERIOD_NS)
            await Timer(1, unit="ns")
            if self.flash is not None:
                value = self._pending
                if value is None:
                    pads.release(MISO)
                else:
                    pads.drive(MISO, value)
            if self.miso_driver is not None:
                self.miso_driver(self, k, sample)

    def finish(self):
        self.pads.stop()


def assert_pin_discipline(boot, last_edge=None):
    """Up to `last_edge` (default: the whole run; for a boot that hands over,
    the edge before the image starts, since the image's pins are its own):
    the design only ever drives CS0, MOSI and SCK; never MISO, SD2, SD3 or
    the PSRAM chip selects, so the Pmod's pull-ups hold those."""
    seen = 0
    for k, s in enumerate(boot.trace[: None if last_edge is None else last_edge + 1]):
        seen |= s["uio_oe"]
        assert s["uio_oe"] & ~PMOD_DRIVEN_MASK & 0xFF == 0, (
            f"{boot.label}: edge {k}: uio_oe={s['uio_oe']:#04x} drives a pin the flash "
            f"boot may not (allowed {PMOD_DRIVEN_MASK:#04x}); the PSRAM chip selects "
            "uio[6] and uio[7] must be left to the Pmod's pull-ups"
        )
    boot.pads.assert_no_contention()
    return seen


def assert_matches_model(boot, timeline, last_edge):
    """DUT pins == the ISA model's pins on every edge up to `last_edge`, and
    uo_out never moves in that span."""
    want = timeline_at(timeline, last_edge)
    for k in range(last_edge + 1):
        s = boot.trace[k]
        assert (s["uio_out"], s["uio_oe"]) == want[k], (
            f"{boot.label}: edge {k}: DUT uio_out/uio_oe = {s['uio_out']:#04x}/"
            f"{s['uio_oe']:#04x}, the ISA model says {want[k][0]:#04x}/{want[k][1]:#04x}"
        )
        assert s["uo_out"] == 0, f"{boot.label}: edge {k}: uo_out={s['uo_out']:#04x} during the boot"


def assert_flash_clean(boot, label=None):
    flash = boot.flash
    assert flash.violations == [], f"{boot.label}: flash model: {flash.violations[:5]}"
    assert len(flash.transactions) == 1, (
        f"{boot.label}: {len(flash.transactions)} flash transactions, expected 1"
    )
    tx = flash.transactions[0]
    assert (tx["opcode"], tx["address"], tx["bytes_read"], tx["data_bits"]) == (
        0x03, 0, IMAGE_BYTES, 8 * IMAGE_BYTES,
    ), f"{boot.label}: transaction {tx}"
    assert tx["t_cs_rise"] is not None, f"{boot.label}: CS0 never rose"
    assert_cs_released_by_the_design(boot)


def assert_cs_released_by_the_design(boot):
    """The pad model's pull-up would raise CS0 anyway once the design stops
    driving it; a boot that relies on that has not deselected the flash. The
    edge on which the flash saw CS0 rise must have the design driving it
    high."""
    tx = boot.flash.transactions[0]
    k = boot.times.index(tx["t_cs_rise"])
    s = boot.trace[k]
    assert (s["uio_oe"] & 1) and (s["uio_out"] & 1), (
        f"{boot.label}: CS0 rose at edge {k} without the design driving it high "
        f"(uio_oe={s['uio_oe']:#04x} uio_out={s['uio_out']:#04x}): only the pull-up released the flash"
    )


def assert_released_and_quiet(boot, from_edge):
    """From `from_edge` on, every uio is an input and every output is 0."""
    for k in range(from_edge, len(boot.trace)):
        s = boot.trace[k]
        assert (s["uo_out"], s["uio_out"], s["uio_oe"]) == (0, 0, 0), (
            f"{boot.label}: edge {k}: uo_out={s['uo_out']:#04x} uio_out={s['uio_out']:#04x} "
            f"uio_oe={s['uio_oe']:#04x}; a failed boot must leave every pin an input"
        )


def assert_rom_halt(boot, result, entry_spi_fail=True):
    """White-box, RTL only: the core never left the ROM and halted at
    spi_fail, the address the boot source puts the failing HALT at."""
    if GATE_LEVEL:
        return
    assert all(boot.fetch_rom), f"{boot.label}: the core left the boot ROM (it ran an image)"
    core = whitebox(boot.dut)
    assert int(core.halted.value) == 1, f"{boot.label}: the boot program did not halt"
    want = br.stub_addresses()["spi_fail"]
    assert int(core.pc.value) == want, (
        f"{boot.label}: halted at ROM address {int(core.pc.value):#04x}, expected spi_fail {want:#04x}"
    )


async def failing_boot(dut, label, flash_image, miso_pull=None, preload=None):
    """Boot strap 01 against `flash_image` (None = no Pmod) and require that
    nothing runs. Returns the Boot."""
    result, model, mflash, timeline = predict(flash_image, miso_pull, board_pulls(miso_pull))
    assert result["outcome"] == "halt" and result["pc"] == br.stub_addresses()["spi_fail"], (
        f"{label}: the ISA model says the boot ends {result}, expected a halt at spi_fail"
    )
    if preload is not None:
        await serial_load(dut, preload)
        loaded = await br.trace_edges(dut, 12, f"{label}: preload")
        assert loaded[-1]["uo_out"] == 0xFF and loaded[-1]["uio_oe"] == 0xFF, (
            f"premise: the preloaded canary does not drive pins when it runs: {loaded[-1]}"
        )
    boot = Boot(dut, label, flash_image, miso_pull)
    await boot.reset()
    halt_edge = RUN_ENTRY_EDGES + result["cycles"]
    await boot.record(halt_edge + 80)
    boot.finish()
    assert_pin_discipline(boot)
    assert_matches_model(boot, timeline, halt_edge)
    if flash_image is not None:
        assert_flash_clean(boot)
        assert mflash.violations == [] and len(mflash.transactions) == 1
    # The release edge: the last pin write the model makes.
    release_edge = timeline[-1][0]
    assert_released_and_quiet(boot, release_edge)
    assert_rom_halt(boot, result)
    return boot


async def passing_boot(dut, label, image_words, extra_edges, miso_driver=None, pm_preload=None):
    """Boot strap 01 against a flash holding `image_words`; require the
    clean transaction, the model's pins, and the hand-over at the edge the
    model predicts. Returns (Boot, entry_cycles) with `extra_edges`
    recorded past the image's first instruction."""
    flash_image = to_flash_bytes(image_words)
    result, model, mflash, timeline = predict(flash_image, None, PMOD_PULLS)
    assert result["outcome"] == "run" and result["target"] == 0, f"{label}: model: {result}"
    assert model.pm == list(image_words), f"{label}: the model's program memory is not the image"
    assert (model.r, model.z, model.c) == ([0, 0, 0, 0], 0, 0), (
        f"{label}: model hands over R={model.r} Z={model.z} C={model.c}"
    )
    assert (model.pm_addr, model.crc) == (0, 0)
    assert mflash.violations == [] and len(mflash.transactions) == 1
    entry_cycles = result["cycles"] + 2  # the RUN's own two cycles
    if pm_preload is not None:
        await serial_load(dut, pm_preload)
    boot = Boot(dut, label, flash_image, miso_driver=miso_driver)
    await boot.reset()
    entry_edge = RUN_ENTRY_EDGES + entry_cycles
    boot.entry_edge = entry_edge
    await boot.record(entry_edge + extra_edges)
    boot.finish()
    assert_pin_discipline(boot, entry_edge - 1)
    assert_matches_model(boot, timeline, entry_edge - 1)
    # the flash saw exactly the one transaction before the image took over
    assert_flash_clean_at(boot, entry_edge)
    if not GATE_LEVEL:
        fr = boot.fetch_rom
        first = entry_edge - 1  # the edge that starts word 0's cycle
        assert all(fr[:first]), f"{label}: left the ROM before RUN retired"
        assert not any(fr[first:]), f"{label}: still in the ROM after RUN"
    return boot, entry_cycles, result


def assert_flash_clean_at(boot, entry_edge):
    """The flash's view up to the image's first instruction: one clean
    READ of the whole image (later activity is the image's own)."""
    flash = boot.flash
    tx = flash.transactions[0]
    t_entry = boot.times[entry_edge]
    assert tx["t_cs_rise"] is not None and tx["t_cs_rise"] < t_entry, (
        f"{boot.label}: CS0 had not risen when the image started"
    )
    assert (tx["opcode"], tx["address"], tx["bytes_read"], tx["data_bits"]) == (
        0x03, 0, IMAGE_BYTES, 8 * IMAGE_BYTES,
    ), f"{boot.label}: transaction {tx}"
    assert_cs_released_by_the_design(boot)
    early = [v for v in flash.violations if float(v.split()[0][2:]) < t_entry]
    assert early == [], f"{boot.label}: flash model: {early[:5]}"


# ---------------------------------------------------------------------------
# The probe program, entered from the flash
# ---------------------------------------------------------------------------
def check_probe_after_spi(boot, p, checks, entry_cycles):
    """`test_boot_rom.check_probe`, minus its "the pins never moved before the
    image" assertion (the boot drove the flash pins): uo_out is 0 until the
    image's first instruction and every uio is an input from the release on."""
    trace = boot.trace
    first = p.edge(0, entry_cycles)
    for e in range(first + 1):
        assert trace[e]["uo_out"] == 0, f"{boot.label}: uo_out moved at edge {e} before the image"
    assert (trace[first]["uio_out"], trace[first]["uio_oe"]) == (0, 0), (
        f"{boot.label}: the pins were not released when the image started"
    )
    for name, (index, want) in checks.items():
        if name == "BOOT_STATUS":
            want = 0x00
        e = p.edge(index, entry_cycles)
        pin = "uio_oe" if name == "uio_oe" else "uo_out"
        assert trace[e][pin] == want, (
            f"{boot.label}: {name}: {pin} after edge {e} is {trace[e][pin]:#04x}, want {want:#04x}"
        )
    marker_edge = p.edge(checks["marker"][0], entry_cycles)
    assert trace[marker_edge - 1]["uo_out"] != 0xA5, f"{boot.label}: the marker arrived early"
    assert trace[-1]["uo_out"] == 0xA5, f"{boot.label}: the probe took its Z=1 branch or did not finish"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@cocotb.test()
async def test_model_chain_and_prediction(dut):
    """No DUT activity: the committed image fits the cap and has the SPI
    boot in it; the ISA model, with its own flash model, predicts a pass for
    a signed image (with a clean READ of 512 bytes from address 0, the
    image in program memory, the reset-state hand-over) and a halt for each
    kind of bad flash. Pins the inputs the other tests use."""
    start_clock(dut)
    rom = br.rom_words()
    assert len(rom) <= br.ROM_WORDS_MAX, f"boot image is {len(rom)} words, cap {br.ROM_WORDS_MAX}"
    program = asm.assemble_file(BOOT_ASM)
    assert list(program.words) == rom
    dut._log.info(f"boot image: {len(rom)} of {br.ROM_WORDS_MAX} words")

    p, _ = br.probe_program()
    good = sign(p.words)
    assert br.crc_of_words(good) == 0 and good[-1] != 0
    result, model, flash, timeline = predict(to_flash_bytes(good), None, PMOD_PULLS)
    assert result["outcome"] == "run" and result["target"] == 0, result
    assert flash.violations == [], flash.violations
    tx = flash.transactions[0]
    assert (tx["opcode"], tx["address"], tx["bytes_read"]) == (0x03, 0, IMAGE_BYTES)
    assert model.pm == good
    assert model.pm_writes == PM_WORDS and model.pm_reads == 1  # the signature re-read
    assert {d for _, _, d in timeline} == {0, PMOD_DRIVEN_MASK}, "the program drives other pins"
    dut._log.info(f"model: a good flash reaches RUN {result['cycles'] + 2} cycles after the first instruction")

    blank = bytes([0xFF]) * IMAGE_BYTES
    for name, image, pull in (
        ("blank flash", blank, None),
        ("no Pmod, MISO low", None, "down"),
        ("no Pmod, MISO high", None, "up"),
        ("fitted flash of zeros", bytes(IMAGE_BYTES), None),
    ):
        result, model, _, _ = predict(image, pull, board_pulls(pull))
        assert result["outcome"] == "halt" and result["pc"] == br.stub_addresses()["spi_fail"], (name, result)
    await ClockCycles(dut.clk, 2)


@cocotb.test()
async def test_good_flash_boots_a_program_that_starts_in_the_reset_state(dut):
    """A signed image in the flash is read in one clean transaction and run:
    the probe program finds R0-R3 = 0, Z = 0, PM_ADDR = 0, PM_CRC = 0 and
    BOOT_STATUS = 0x00, can then drive pins, and every uio pin was released
    when it started. The design's pins equal the ISA model's on every edge
    of the boot. A second image with different filler boots to the same pin
    edges."""
    start_clock(dut)
    p, checks = br.probe_program()
    tail = p.edge(len(p.lines)) + 8
    edge_sets = []
    for seed in (1, 2):
        image = br.signed_image(p.words, filler_seed=seed)
        boot, entry_cycles, _ = await passing_boot(dut, f"probe image {seed}", image, tail)
        check_probe_after_spi(boot, p, checks, entry_cycles)
        edge_sets.append([e for e in range(1, len(boot.trace)) if boot.trace[e] != boot.trace[e - 1]])
    # two different images: the pin activity of the boot itself is identical
    first = RUN_ENTRY_EDGES + entry_cycles
    assert [e for e in edge_sets[0] if e < first] == [e for e in edge_sets[1] if e < first], (
        "the boot's pin timing depends on the image's contents"
    )


@cocotb.test()
async def test_protocol_programs_boot_from_flash_and_pass_reference_models(dut):
    """End to end. The committed `uart_tx` and `spi_mode0` images, signed
    and placed in the flash, boot over SPI and then do what they do when
    serial-loaded: `UartDecoder` recovers both frames and `check_burst`
    grades both SPI bursts, with the same cycle measurements the loaded
    benches assert (a 50-cycle UART bit, a 4- and 8-cycle SCLK period)."""
    start_clock(dut)

    # ---- UART ---------------------------------------------------------
    words = parse_hex_image(fu.UART_HEX)
    image = sign(words)
    run_cycles = fu.program_run_cycles() + fu.CAPTURE_MARGIN_CYCLES
    boot, entry_cycles, _ = await passing_boot(dut, "uart_tx from flash", image, run_cycles)
    entry = RUN_ENTRY_EDGES + entry_cycles
    tx = fu.CapturedPin("tx", boot.trace[entry]["uo_out"] & 1)
    for k in range(entry + 1, len(boot.trace)):
        tx.observe(k, boot.times[k], boot.trace[k]["uo_out"] & 1)
    baud = round(1e9 / (fu.BIT_PERIOD_CYCLES * CLK_PERIOD_NS))
    decoder = UartDecoder(baud)
    reports = decoder.decode(tx.signal)
    assert len(reports) == len(fu.FRAMES), f"decoded {len(reports)} frames: {reports}"
    for report, (payload, _section) in zip(reports, fu.FRAMES):
        assert report.data == payload and report.stop_ok, report
        assert decoder.check_frame(report), f"drift {report.drift_pct:.3f}%"
    starts = [fu.cycle_at_time(tx, r.t_start) for r in reports]
    assert starts[1] - starts[0] == fu.FRAME_PITCH_CYCLES
    for (payload, _section), start in zip(fu.FRAMES, starts):
        edges = [c for c in tx.transition_cycles if start <= c <= start + fu.UART_FRAME_BITS * fu.BIT_PERIOD_CYCLES]
        assert [c - start for c in edges] == [k * fu.BIT_PERIOD_CYCLES for k in fu.expected_edge_offsets(payload)]
    stretched = UartDecoder(baud)
    for report in stretched.decode(tx.time_scaled(fu.NEGATIVE_CONTROL_SCALE)):
        assert not stretched.check_frame(report), "UART negative control did not fail"

    # ---- SPI mode 0 ----------------------------------------------------
    words = fs.load_hex(0)
    image = sign(words)
    run_cycles = fs.committed_total_cycles(0) + fs.CAPTURE_MARGIN_CYCLES + 16
    mode = MODES[0]
    miso_bytes = [fs.CEIL_MISO, fs.FUNC_MISO]
    state = {"burst": -1, "bit": 0, "cs": None, "sclk": mode.cpol}

    def miso_driver(boot, k, sample):
        """The peripheral side of the SPI program, per edge, on the Pmod's
        uio[0] line. Same convention as test_firmware_spi.drive_miso: a
        1 -> 0 CS fall starts a burst, bit k+1 is presented after each
        trailing edge. The program's CS/SCLK are on uo_out[0]/[1]."""
        if k < boot.entry_edge:
            return
        cs, sclk = sample["uo_out"] & 1, (sample["uo_out"] >> 1) & 1
        write = None
        if state["cs"] == 1 and cs == 0 and state["burst"] < len(miso_bytes) - 1:
            state["burst"] += 1
            write = fs._bit(miso_bytes[state["burst"]], 0)
            state["bit"] = 1
        elif state["burst"] >= 0 and state["cs"] == 0 and cs == 0 and sclk != state["sclk"]:
            if sclk == mode.cpol and state["bit"] < 8:
                write = fs._bit(miso_bytes[state["burst"]], state["bit"])
                state["bit"] += 1
        if write is not None:
            boot.pads.drive(0, write)
        state["cs"], state["sclk"] = cs, sclk

    boot, entry_cycles, _ = await passing_boot(dut, "spi_mode0 from flash", image, run_cycles, miso_driver)
    entry = RUN_ENTRY_EDGES + entry_cycles
    caps = {name: fu.CapturedPin(name, 0) for name in ("cs", "sclk", "mosi", "miso")}
    for name, bit in (("cs", 0), ("sclk", 1), ("mosi", 2)):
        caps[name] = fu.CapturedPin(name, (boot.trace[entry]["uo_out"] >> bit) & 1)
    caps["miso"] = fu.CapturedPin("miso", 1 if boot.trace[entry]["uio0"] == "1" else 0)
    for k in range(entry + 1, len(boot.trace)):
        uo = boot.trace[k]["uo_out"]
        for name, bit in (("cs", 0), ("sclk", 1), ("mosi", 2)):
            caps[name].observe(k, boot.times[k], (uo >> bit) & 1)
        caps["miso"].observe(k, boot.times[k], 1 if boot.trace[k]["uio0"] == "1" else 0)
    windows = fs.burst_windows(caps["cs"])
    assert len(windows) == 2, f"expected 2 CS bursts, captured {len(windows)}"
    for index, (tx_byte, rx_byte, per_bit) in enumerate(
        ((fs.CEIL_TX, fs.CEIL_MISO, fs.CEIL_CYCLES_PER_BIT), (fs.FUNC_TX, fs.FUNC_MISO, fs.FUNC_CYCLES_PER_BIT))
    ):
        tf, tr, _cf, _cr = windows[index]
        report = check_burst(caps["sclk"].signal, caps["mosi"].signal, caps["miso"].signal,
                             caps["cs"].signal, mode, F_CLK_HZ, t0=tf, t1=tr)
        assert report.ok, f"burst {index}: {report.violations}"
        assert report.mosi_bytes == [tx_byte], report
        assert report.miso_bytes == [rx_byte], report
        assert report.sclk_period_ns == per_bit * CLK_PERIOD_NS, report
    # the grader can fail on this capture: the same ceiling burst, graded as mode 1
    tf, tr, _, _ = windows[0]
    wrong = check_burst(caps["sclk"].signal, caps["mosi"].signal, caps["miso"].signal,
                        caps["cs"].signal, MODES[1], F_CLK_HZ, t0=tf, t1=tr)
    assert not wrong.ok or wrong.mosi_bytes != [fs.CEIL_TX], "SPI negative control did not fail"


@cocotb.test()
async def test_blank_or_absent_flash_never_runs(dut):
    """Nothing in the flash that is a program: a blank (0xFF) flash, no
    Pmod with MISO pulled high, no Pmod with MISO pulled low, a fitted
    flash of zeros. None runs: the boot ends at spi_fail with every pin an
    input, even with a verified-looking canary in program memory."""
    start_clock(dut)
    canary = br.signed_image(br.canary_image()[:64], filler_seed=7)
    # the first case runs on a program memory nobody has written (X): the
    # boot writes all 256 words before it reads any
    await failing_boot(dut, "blank flash (unwritten memory)", bytes([0xFF]) * IMAGE_BYTES)
    await failing_boot(dut, "blank flash, canary in memory", bytes([0xFF]) * IMAGE_BYTES, preload=canary)
    await failing_boot(dut, "no Pmod, MISO pulled high", None, miso_pull="up")
    await failing_boot(dut, "no Pmod, MISO pulled low", None, miso_pull="down")
    await failing_boot(dut, "fitted flash of zeros", bytes(IMAGE_BYTES))


@cocotb.test()
async def test_corrupt_flash_never_runs(dut):
    """A good image one defect away, in the flash: a flipped bit in the first
    byte, in an odd-numbered word, in the last signed word and in the
    signature, two swapped words, residues with only one nonzero CRC byte,
    the image shifted one byte, and a truncated image (the rest blank). None
    runs, each ends at spi_fail with the pins released."""
    start_clock(dut)
    p, _ = br.probe_program()
    valid = br.signed_image(p.words, filler_seed=3)
    cases = list(br.corrupted_images(valid))
    shifted = to_flash_bytes(valid)[1:] + b"\x00"
    truncated = to_flash_bytes(valid)[:300] + bytes([0xFF]) * (IMAGE_BYTES - 300)
    for name, image in cases:
        await failing_boot(dut, f"corrupt flash ({name})", to_flash_bytes(image))
    await failing_boot(dut, "image shifted by one byte", shifted)
    await failing_boot(dut, "truncated image", truncated)


@cocotb.test()
async def test_zero_signature_is_refused(dut):
    """A finding, pinned. The all-zero image is its own valid signature (DR
    0013, Finding F1), and a flash that answers zeros to everything (no Pmod
    with MISO pulled low, a dead flash) delivers exactly that image. The warm
    start runs it; the SPI boot refuses any image whose signature word is
    0x0000. An image with such a signature and an otherwise valid CRC (found
    by search: it exists for 1 body in 65,536) is therefore refused too, and
    this is the cost: such an image must be given another filler word."""
    start_clock(dut)
    image = zero_signature_image()
    assert br.crc_of_words(image) == 0 and image[-1] == 0
    result, _, _, _ = predict(to_flash_bytes(image), None, PMOD_PULLS)
    assert result["outcome"] == "halt", f"model: {result}"
    await failing_boot(dut, "valid CRC, signature word 0x0000", to_flash_bytes(image))
    # one filler word changed: a valid image with a nonzero signature boots
    fixed = list(image[:-1])
    fixed[201] ^= 0x0001
    fixed = fixed + [br.crc_of_words(fixed)]
    assert fixed[-1] != 0
    boot, entry_cycles, _ = await passing_boot(dut, "same image, nonzero signature", fixed, 8)
    assert boot is not None
