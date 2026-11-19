"""DUT-facing 1-Wire master firmware bench (multi-protocol extra credit,
issue #447; the catalog is #443).

The claim: the committed program `firmware/asm/onewire_master.asm` (image
`firmware/build/onewire_master.hex`), loaded over the real serial load-phase
pins onto the real top and run by the ISA core, acts as a 1-Wire **bus
master** on one open-drain, pulled-up DQ line (`uio[3]`, DR 0010's
`onewire` profile, `UIO_OD` = 0x08) and completes a DS18B20 temperature
read: reset + presence, Read ROM with the CRC checked, Skip ROM + Convert T
with the conversion poll, reset, Skip ROM + Read Scratchpad with the CRC
checked, and the temperature plus a status byte published on `uo_out`.

The device is the independent model
(`verification/reference_models/onewire.py`, written from the DS18B20
datasheet's timing table and AN27's CRC alone). It decodes every slot the
master emits, measures every pulse in ns against the datasheet's numbers,
answers the presence pulse, serves ROM and scratchpad bits, and holds the
conversion poll busy for a configured few read slots -- the real part's
750 ms t_CONVMAX is not simulated, which this bench says out loud. The bus
is the silicon-true pad model (`verification/uio_pads.py`): DQ resolves
from the design's own `uio_oe` / `uio_out`, the slave's open-drain pull and
the 4.7 kOhm-class external pull-up; the other seven `uio` lines are tied
low, so a program that drove one would be reported as contention.

What is graded, and by whom
---------------------------
1. **The bus.** The model sees a snapshot of DQ and the master's enable at
   every change (and at least every 50 ns): reset low/high widths, write-1 /
   write-0 / read slot low widths, slot fall-to-fall, recovery -- every
   limit is the datasheet's, none is the firmware's own arithmetic.
2. **The bytes.** The ROM and scratchpad bytes the model served are the
   ones the master must publish: the bench captures every `uo_out` write
   after the load and compares the whole sequence, the temperature decode
   (bytes 0..1 of the scratchpad, /16 per the datasheet) and the final
   status: 0x01 ok, 0x02 no presence, 0x03 ROM CRC error, 0x04 scratchpad
   CRC error.
3. **The pads.** After each run: no contention, no unknown `uio_oe`,
   exactly DQ enabled, driven only low (open drain), and the line released
   (high) while the master idles.

Time base. The simulation clock is 20 ns, target-spec row 4's **target**
50 MHz, which is not confirmed. Every microsecond figure is core cycles x
20 ns; the pad model has zero delay by design.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
Three mutant programs, each assembled in memory from the committed source
with one defect, run on the same DUT and bus and must be rejected for the
defect's own reason: a reset 250 cycles short of 480 us (the model flags
`reset-low-short`, the device never answers, the master must report no
presence), a write-1 low pulse of ~0.2 us (below the 1 us minimum, flagged
`write1-low-width`), and the scratchpad CRC check disabled (a corrupted
scratchpad is then wrongly reported as ok -- only the byte comparison can
catch that one, and does).

Driven by `klt functional-verification` (`verification/request-firmware-
onewire.json`) at RTL. All of it is pin-observable, so the same file runs
unchanged on gates.
"""

import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import First, ReadOnly, Timer, ValueChange
from cocotb.utils import get_sim_time

from reference_models.onewire import Ds18b20, Snap, crc8
from uio_pads import UioPads

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))

sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)
from firmware_artifacts import parse_hex_image  # noqa: E402

# The load-phase driver is the one every other bench uses.
from test_protocol_emulator import load_program  # noqa: E402

SRC = REPO_ROOT / "firmware" / "asm" / "onewire_master.asm"
HEX = REPO_ROOT / "firmware" / "build" / "onewire_master.hex"
CYCLES = REPO_ROOT / "firmware" / "build" / "onewire_master.cycles.txt"

#: Simulation clock: names row 4's target 50 MHz; not a measurement.
CLK_PERIOD_NS = 20
#: The bus: DQ on the standard I2C Pmod's SDA position, with its pull-up.
DQ_BIT = 3
#: `UIO_OD` value the program must write: the DQ mask alone.
OD_MASK = 1 << DQ_BIT
US = 1000

#: The single device on the bus: a DS18B20 family code (0x28) with its CRC
#: byte, and the datasheet's own +25.0625 C scratchpad example (0x0191,
#: 12-bit config 0x7F). Both CRC bytes are asserted against the model's
#: own `crc8` (held to AN27's worked example by test_onewire_model.py).
ROM = (0x28, 0x8E, 0x2F, 0x43, 0x01, 0x0C, 0x00, 0xFE)
SCRATCHPAD = (0x91, 0x01, 0x4B, 0x46, 0x7F, 0xFF, 0xFF, 0xFF, 0x14)
assert crc8(ROM[:7]) == ROM[7] and crc8(SCRATCHPAD[:8]) == SCRATCHPAD[8]
#: How many read slots the conversion poll stays busy (not t_CONVMAX).
BUSY_SLOTS = 3

#: Result publication: every received byte reaches `uo_out` as it completes,
#: the status byte last. The values and their meaning:
STATUS_OK, STATUS_NO_PRESENCE, STATUS_CRC_ROM, STATUS_CRC_SCR = 1, 2, 3, 4

#: The assembler's data-dependent-latency warnings, as (mnemonic, branch
#: target label) in program order. Four are pin-data handshakes (presence
#: detect, conversion poll) or data-neutral skips (the two CRC feedback
#: branches); five branch on the PM_ADDR bit counter, whose pin taint is an
#: artifact of the lint's linear scan forgetting control state at labels
#: (the firmware header documents each). No timing budget rides on any of
#: them: every wait loop runs on constants.
EXPECTED_WARNINGS = (
    ("BNZ", "rsnop"),
    ("BNZ", "wrtwo"),
    ("BZ", "poll"),
    ("BZ", "rd1cn"),
    ("BNZ", "rd1chk"),
    ("BNZ", "rd1bit"),
    ("BZ", "rd2cn"),
    ("BNZ", "rd2chk"),
    ("BNZ", "rd2bit"),
)


# =======================================================================
# The board and the device
# =======================================================================


def onewire_board(dut):
    """Pads as a 1-Wire board: a pull-up on DQ, the seven other `uio`
    lines tied low (a strong driver, so a program that drove one of them
    high would be reported as contention). Not started."""
    return UioPads(
        dut,
        pulls={DQ_BIT: "up"},
        tie={p: 0 for p in range(8) if p != DQ_BIT},
        name="onewire-board",
    )


def assert_onewire_open_drain(pads, tag):
    """After a 1-Wire run: the design drove exactly DQ, only ever low,
    with no unknown `uio_oe` and no contention."""
    pads.assert_no_contention()
    assert pads.oe_unknown == 0, f"{tag}: uio_oe unknown on pins 0x{pads.oe_unknown:02x}"
    assert pads.oe_seen == OD_MASK, (
        f"{tag}: the design drove uio pins 0x{pads.oe_seen:02x}; a 1-Wire master "
        f"must drive exactly DQ = 0x{OD_MASK:02x}"
    )
    assert pads.drove_high == 0, (
        f"{tag}: the design drove uio pins 0x{pads.drove_high:02x} HIGH; an open-drain pad only pulls low"
    )
    assert pads.drove_low == OD_MASK, (
        f"{tag}: the design pulled pins 0x{pads.drove_low:02x} low, expected DQ 0x{OD_MASK:02x}"
    )


class Device:
    """The DS18B20 model wired to the pads.

    A monitor coroutine feeds the model a `Snap` of DQ and the master's
    enable at every change and at least every 50 ns (the model's scheduled
    presence pulse fires inside `observe`), then applies the model's
    open-drain intent one ns later, outside `ReadOnly`. A second coroutine
    samples `uo_out` every 40 ns into a history -- the result publication
    writes consecutive equal bytes (the scratchpad ends in three 0xFF), so
    an edge-triggered capture would lose them; the tests instead read the
    value the DUT held at instants the model itself derives (each served
    byte's slot, plus the halt)."""

    def __init__(self, dut, pads, slave):
        self.dut = dut
        self.pads = pads
        self.slave = slave
        self.uo_history = []        # (t ns, uo_out) at every change
        self._uo_times = []
        self.bad_level = []
        self._task = None
        self._uo_task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())
        return self

    def start_results(self):
        self._uo_task = cocotb.start_soon(self._uo_sample())
        return self

    def stop(self):
        for task in (self._task, self._uo_task):
            if task is not None:
                task.kill()
        self._task = self._uo_task = None

    def now(self):
        return float(get_sim_time("ns"))

    def value_at(self, t):
        """The sampled `uo_out` value at time `t` (the last change <= t)."""
        import bisect
        i = bisect.bisect_right(self._uo_times, t) - 1
        assert i >= 0, f"no uo_out sample at or before {t:.0f} ns"
        return self.uo_history[i][1]

    def published_bytes(self, byte_events):
        """What the DUT published for each served byte.

        The program publishes each byte ~62 us after its last slot release
        (the model's event time), half a millisecond before the next byte's
        publication -- except after the very last byte, where the status
        write follows within a few cycles. So per byte: the FIRST `uo_out`
        change inside (te, te + 70 us] is that byte's publication; a byte
        equal to its predecessor writes nothing observable (the pin already
        holds it -- the scratchpad ends in three 0xFF), and the held value
        plus the model's served sequence stand in for it."""
        out = []
        for _kind, value, te in byte_events:
            window = [v for t, v in self.uo_history if te < t <= te + 70 * US]
            out.append(window[0] if window else self.value_at(te + 70 * US))
        return out

    async def _run(self):
        while True:
            await First(ValueChange(self.dut.uio_in), ValueChange(self.dut.uio_oe),
                         Timer(50, "ns"))
            await ReadOnly()
            t = self.now()
            try:
                dq = self.pads.level(DQ_BIT)
                oe = int(self.dut.uio_oe.value)
            except ValueError:
                self.bad_level.append(t)
                continue
            moe = (oe >> DQ_BIT) & 1
            want = self.slave.pull
            self.slave.observe(Snap(t, dq, moe))
            if self.slave.pull == want:
                continue
            await Timer(1, "ns")     # leave ReadOnly; the pads are writable
            if self.slave.pull:
                self.pads.pull_low(DQ_BIT)
            else:
                self.pads.release(DQ_BIT)

    async def _uo_sample(self):
        await ReadOnly()                      # the load/run-phase mux settles
        last = None
        self._uo_times = []
        while True:
            await Timer(40, "ns")
            await ReadOnly()
            value = int(self.dut.uo_out.value)
            if value != last:
                self.uo_history.append((self.now(), value))
                self._uo_times.append(self.now())
                last = value


# =======================================================================
# Running a program and grading it
# =======================================================================


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


def committed_words():
    return parse_hex_image(HEX)


async def boot(dut, words, slave):
    """Load `words` onto the 1-Wire board; return the wired device. No pad
    may be enabled from reset release to the end of the load."""
    assert len(words) <= 256
    pads = onewire_board(dut).start()
    await load_program(dut, words)
    assert pads.resets == 1 and pads.oe_seen == 0, (
        f"uio pads 0x{pads.oe_seen:02x} enabled between reset release and the end of the load"
    )
    device = Device(dut, pads, slave).start()
    device.start_results()
    return device


async def run_to_halt(dut, device, timeout_ms=60):
    """Wait until the core has executed HALT (`u_core.halted`), bounded by
    `timeout_ms` (a mutant that never halts still ends the test). Returns
    the captured publications."""
    deadline = device.now() + timeout_ms * US * US
    while device.now() < deadline and int(dut.u_core.halted.value) != 1:
        await Timer(200 * US, "ns")
    await Timer(400 * US, "ns")   # let the final status settle on uo_out


def finish(device, tag, *, open_drain=True):
    """Stop the monitor; grade the bus; return the model's result."""
    device.stop()
    if open_drain:
        assert_onewire_open_drain(device.pads, tag)
        assert not device.bad_level, f"{tag}: DQ was unknown or floating: {device.bad_level[:3]}"
    return device.slave.check()


def report(dut, tag, result):
    for v in result.violations[:10]:
        dut._log.error(f"[{tag}] {v}")
    kinds = [e[0] for e in result.events]
    dut._log.info(f"[{tag}] events {kinds}; margins (ns) "
                  f"{ {k: round(v) for k, v in sorted(result.margins.items())} }; "
                  f"measured (min, max ns) "
                  f"{ {k: (round(lo), round(hi)) for k, (lo, hi) in sorted(result.measured.items())} }")


def assert_clean(dut, tag, result):
    report(dut, tag, result)
    assert result.violations == [], (
        f"[{tag}] {len(result.violations)} violation(s): {[str(v) for v in result.violations[:5]]}"
    )


def temperature(scratch_lsb, scratch_msb):
    """DS18B20 scratchpad bytes 0..1 as a degree-C value (the datasheet's
    /16, 12-bit resolution)."""
    return ((scratch_msb << 8) | scratch_lsb) / 16.0


def mutate(text, old, new):
    assert text.count(old) == 1, f"mutation site {old!r} found {text.count(old)} times"
    return text.replace(old, new)


def mutant_words(name, text):
    return asm.assemble_text(text, source_name=f"<mutant {name}>").words


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed image and report match the source; the program fits;
    every assembler lint warning is one of the nine documented ones."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    lines = SRC.read_text(encoding="utf-8").splitlines()
    got = []
    for w in program.warnings:
        m = re.match(r"line (\d+): (BNZ|BZ) ", w)
        assert m, w
        text = lines[int(m.group(1)) - 1]
        got.append((m.group(2), text.split(";")[0].split()[1]))
    assert tuple(got) == EXPECTED_WARNINGS, got
    words = committed_words()
    assert len(words) <= 256
    # the open-drain setup is the very first thing the program does to the pads
    text = SRC.read_text(encoding="utf-8")
    code = re.sub(r";.*", "", text)
    assert code.count("WCTL  UIO_OD") == 1 and "UIO_DIR" not in code
    assert code.index("OUT   UIO_OUT") < code.index("WCTL  UIO_OD"), (
        "DQ must be written released before UIO_OD enables it (uio_out resets to 0)"
    )
    dut._log.info(f"{len(words)} words, {len(program.warnings)} documented lint warnings")


@cocotb.test()
async def test_read_rom_convert_read_scratchpad(dut):
    """The whole transaction: reset/presence, Read ROM (CRC ok), Skip ROM +
    Convert T + poll, reset, Skip ROM + Read Scratchpad (CRC ok), the
    temperature and status 0x01 published -- with every pulse the master
    emitted inside the datasheet's numbers."""
    start_clock(dut)
    slave = Ds18b20(ROM, SCRATCHPAD, busy_slots=BUSY_SLOTS)
    device = await boot(dut, committed_words(), slave)
    await run_to_halt(dut, device)
    result = finish(device, "happy")
    assert_clean(dut, "happy", result)
    assert result.commands() == [0x33, 0xCC, 0x44, 0xCC, 0xBE]
    served = [(e[0], e[1], e[2]) for e in result.events
              if e[0] in ("rom-byte", "scratchpad-byte")]
    assert [v for _k, v, _t in served] == list(ROM) + list(SCRATCHPAD)
    assert sum(1 for e in result.events if e[0] == "poll-busy") == BUSY_SLOTS
    values = device.published_bytes(served) + [device.value_at(device.now() - 100)]
    assert values == list(ROM) + list(SCRATCHPAD) + [STATUS_OK], f"{values} vs {list(ROM) + list(SCRATCHPAD) + [STATUS_OK]}"
    assert temperature(values[8], values[9]) == 25.0625
    assert int(dut.uo_out.value) == STATUS_OK
    dut._log.info(f"happy: temperature {temperature(values[8], values[9])} C, "
                  f"{len(values)} published values, margins "
                  f"{ {k: round(v) for k, v in sorted(result.margins.items())} }")


@cocotb.test()
async def test_no_presence_is_reported(dut):
    """An empty bus (pull-up, no device): the reset is still legal, the
    master reports status 0x02 and never emits a slot afterwards."""
    start_clock(dut)
    slave = Ds18b20(ROM, SCRATCHPAD, present=False)
    device = await boot(dut, committed_words(), slave)
    await run_to_halt(dut, device)
    result = finish(device, "no-presence")
    assert_clean(dut, "no-presence", result)
    assert [e[0] for e in result.events] == ["reset"]
    assert device.value_at(device.now() - 100) == STATUS_NO_PRESENCE
    assert int(dut.uo_out.value) == STATUS_NO_PRESENCE


@cocotb.test()
async def test_bad_scratchpad_crc_is_reported(dut):
    """A scratchpad byte corrupted in transit (data bit flipped, CRC byte
    left alone): the master still reads all nine bytes, publishes them, and
    reports status 0x04."""
    start_clock(dut)
    slave = Ds18b20(ROM, SCRATCHPAD, busy_slots=BUSY_SLOTS, corrupt_scr_byte=0)
    device = await boot(dut, committed_words(), slave)
    await run_to_halt(dut, device)
    result = finish(device, "scr-crc")
    assert_clean(dut, "scr-crc", result)
    served = [(e[0], e[1], e[2]) for e in result.events
              if e[0] in ("rom-byte", "scratchpad-byte")]
    values = device.published_bytes(served) + [device.value_at(device.now() - 100)]
    want = list(SCRATCHPAD)
    want[0] ^= 0x01
    assert [v for _k, v, _t in served] == list(ROM) + want
    assert values == list(ROM) + want + [STATUS_CRC_SCR], values
    assert temperature(values[8], values[9]) != 25.0625
    assert int(dut.uo_out.value) == STATUS_CRC_SCR


@cocotb.test()
async def test_bad_rom_crc_is_reported(dut):
    """A corrupted ROM CRC byte: the master reads the ROM, publishes it,
    reports status 0x03 and stops there (no Convert T)."""
    start_clock(dut)
    slave = Ds18b20(ROM, SCRATCHPAD, busy_slots=BUSY_SLOTS, corrupt_rom_byte=7)
    device = await boot(dut, committed_words(), slave)
    await run_to_halt(dut, device)
    result = finish(device, "rom-crc")
    assert_clean(dut, "rom-crc", result)
    served = [(e[0], e[1], e[2]) for e in result.events
              if e[0] in ("rom-byte", "scratchpad-byte")]
    values = device.published_bytes(served) + [device.value_at(device.now() - 100)]
    want = list(ROM)
    want[7] ^= 0x01
    assert [v for _k, v, _t in served] == want
    assert values == want + [STATUS_CRC_ROM], values
    assert int(dut.uo_out.value) == STATUS_CRC_ROM


@cocotb.test()
async def test_idle_bus_is_released(dut):
    """While the program is halted after a good run, DQ is released: the
    pad is not enabled and the pull-up holds the line high."""
    start_clock(dut)
    slave = Ds18b20(ROM, SCRATCHPAD, busy_slots=BUSY_SLOTS)
    device = await boot(dut, committed_words(), slave)
    await run_to_halt(dut, device)
    oe = int(dut.uio_oe.value)
    assert oe & ~OD_MASK == 0, f"uio_oe = {oe:#04x}: a pin outside DQ is enabled"
    assert oe & OD_MASK == 0, f"idle bus: uio_oe {oe:#04x}; DQ should be released"
    assert device.pads.level(DQ_BIT) == 1, "the pull-up should hold DQ high"
    finish(device, "idle")


# =======================================================================
# Negative controls
# =======================================================================


@cocotb.test()
async def test_negative_reset_too_short(dut):
    """A reset 250 cycles (~5 us) short of 480 us: the model flags
    `reset-low-short`, answers no presence, and the master must report
    status 0x02."""
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "        LDI   R3, 96\nrsl:    WAIT  246",
                  "        LDI   R3, 95\nrsl:    WAIT  246")
    start_clock(dut)
    slave = Ds18b20(ROM, SCRATCHPAD, busy_slots=BUSY_SLOTS)
    device = await boot(dut, mutant_words("reset-short", text), slave)
    await run_to_halt(dut, device)
    result = finish(device, "mutant reset-short", open_drain=False)
    kinds = {v.kind for v in result.violations}
    assert "reset-low-short" in kinds, sorted(kinds)
    assert not [e for e in result.events if e[0] == "presence"], "a short reset must not be answered"
    assert device.value_at(device.now() - 100) == STATUS_NO_PRESENCE
    dut._log.info(f"mutant reset-short: violations {sorted(kinds)}")


@cocotb.test()
async def test_negative_write1_too_short(dut):
    """A write-1 low pulse of ~0.24 us (below the 1 us minimum): the model
    flags `write1-low-width`; the command still decodes (the slot is
    shorter than 15 us), so only the timing grade catches it."""
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "wrone:  WAIT  96               ; ---- write 1: ~2 us low",
                  "wrone:  WAIT  4                ; (mutant) ~0.24 us low")
    start_clock(dut)
    slave = Ds18b20(ROM, SCRATCHPAD, busy_slots=BUSY_SLOTS)
    device = await boot(dut, mutant_words("write1-short", text), slave)
    await run_to_halt(dut, device)
    result = finish(device, "mutant write1-short", open_drain=False)
    kinds = {v.kind for v in result.violations}
    assert "write1-low-width" in kinds, sorted(kinds)
    status = device.value_at(device.now() - 100)
    dut._log.info(f"mutant write1-short: violations {sorted(kinds)}; status {status}")


@cocotb.test()
async def test_negative_crc_check_disabled(dut):
    """Skipping the scratchpad CRC check is invisible to the bus (every
    pulse stays legal). The byte comparison catches it: a corrupted
    scratchpad is wrongly reported as ok."""
    text = mutate(SRC.read_text(encoding="utf-8"),
                  "        BZ    scrok",
                  "        JMP   scrok             ; (mutant) CRC not checked")
    start_clock(dut)
    slave = Ds18b20(ROM, SCRATCHPAD, busy_slots=BUSY_SLOTS, corrupt_scr_byte=0)
    device = await boot(dut, mutant_words("crc-disabled", text), slave)
    await run_to_halt(dut, device)
    result = finish(device, "mutant crc-disabled")
    assert_clean(dut, "mutant crc-disabled", result)
    served = [(e[0], e[1], e[2]) for e in result.events
              if e[0] in ("rom-byte", "scratchpad-byte")]
    values = device.published_bytes(served) + [device.value_at(device.now() - 100)]
    want = list(SCRATCHPAD)
    want[0] ^= 0x01
    assert values == list(ROM) + want + [STATUS_OK], f"{values} vs {list(ROM) + want + [STATUS_OK]}"
    assert values[-1] == STATUS_OK and values[-1] != STATUS_CRC_SCR, (
        "NEGATIVE CONTROL FAILED TO FAIL: the golden answer is status 4"
    )
    dut._log.info("mutant crc-disabled: reported ok with a corrupted scratchpad "
                  "(the golden answer is 4); the bus stayed legal, as expected")
