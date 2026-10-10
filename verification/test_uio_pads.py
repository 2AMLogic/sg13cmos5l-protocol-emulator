"""Bench for the pad model itself (issue #136): `verification/uio_pads.py`
on the real top, driven by small programs assembled in memory.

`test_firmware_i2c.py`, `test_firmware_i2c_sr.py` and the I2C slices of
`test_random_regression.py` cite the pad model for two things -- "the
line the model grades is what the pads resolve" and "there was no
contention". This bench is what lets them: it checks, on the design's
own `uio_oe` / `uio_out`, each rule the model applies, and that the
contention detector fires when the design and the board really fight
(a detector that cannot fire cannot be cited for staying silent).

Every program configures the pads the way firmware does (`OUT UIO_OUT`,
`WCTL UIO_DIR`, `WCTL UIO_OD`; DR 0012) and then copies `uio_in` to
`uo_out` forever, so each case is checked twice: at the line
(`pads.line()`, and the `uio_in` port) and through the core's real `IN`
path (`uo_out`).

Cases:

* **Reset and load.** No pad is enabled; pull-up, pull-down, tie-off and
  floating lines read '1', '0', the tied level and 'z'. A `uio_out` bit
  that is 1 while its pad is an input does not reach the line.
* **Push-pull** (`UIO_DIR`). A driven 1 beats a pull-down, a driven 0
  beats a pull-up, the core reads its own drive back.
* **Open-drain** (`UIO_OD`). Writing 0 pulls the line low; writing 1
  releases it to the pull-up; a peripheral can hold a released line low
  and that is not contention -- also while the design toggles its pad
  under the peripheral's hold (clock stretching), where a model that
  judged contention on unsettled delta-cycle values would report a
  false fight on every release.
* **Contention (must be detected).** Push-pull 1 against an external 0,
  from either side (the board driving later, or the design enabling its
  pad later); an open-drain 0 against an external push-pull 1. Each is
  one recorded episode naming the pin and both levels, makes the line
  'x', and makes `assert_no_contention()` raise. Agreeing drivers and a
  released external driver are not contention.
* **Ownership of `uio_in`.** A write from the bench is overwritten with
  the resolved level in the same time step.

RTL only: the gate-level proof of the pad path is the I2C benches
themselves under `flow/run-firmware-gate-level.sh`, which run on this
model. Deterministic; no randomization. Driven by `klt
functional-verification` (see `request-uio-pads.json`).
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, Timer

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (the committed assembler)

from test_protocol_emulator import load_program  # noqa: E402
from uio_pads import PadContention, UioPads  # noqa: E402

CLK_PERIOD_NS = 20

#: Configure the pads, then mirror `uio_in` onto `uo_out` forever. The
#: `OUT` precedes the `WCTL`s for the reason the I2C programs give:
#: `uio_out` resets to 0, and enabling a pad first would drive that 0.
MIRROR = """
        LDI   R0, {out}
        OUT   UIO_OUT, R0
        LDI   R0, {direction}
        WCTL  UIO_DIR, R0
        LDI   R0, {od}
        WCTL  UIO_OD, R0
mirror:
        IN    R1, UIO_IN
        OUT   UO_OUT, R1
        JMP   mirror
"""

#: Open-drain on uio[0], toggled forever: 4 cycles asserted (0), 4
#: released (1). Nothing else is enabled.
TOGGLE_OD = """
        LDI   R0, 0x01
        LDI   R1, 0x00
        OUT   UIO_OUT, R0
        WCTL  UIO_OD, R0
toggle:
        OUT   UIO_OUT, R1
        WAIT  2
        OUT   UIO_OUT, R0
        WAIT  1
        JMP   toggle
"""

#: Cycles to let a freshly loaded MIRROR program configure the pads and
#: complete a few mirror passes.
SETTLE = 24


def mirror(out=0x00, direction=0x00, od=0x00) -> list:
    text = MIRROR.format(out=f"0x{out:02X}", direction=f"0x{direction:02X}",
                         od=f"0x{od:02X}")
    return asm.assemble_text(text, "pad-mirror").words


async def snapshot(dut, cycles: int) -> dict:
    """Advance `cycles` clock edges and return the settled `uio_in` /
    `uo_out` as 8-character level strings, MSB (bit 7) first."""
    await ClockCycles(dut.clk, cycles)
    await ReadOnly()
    snap = {
        "uio_in": str(dut.uio_in.value).lower(),
        "uo_out": str(dut.uo_out.value).lower(),
    }
    await Timer(1, unit="ns")  # leave the read-only region
    return snap


def bit(levels: str, pin: int) -> str:
    return levels[7 - pin]


def lines(pads) -> str:
    """The eight resolved lines, bit 7 first (the same order as a port
    value prints)."""
    return "".join(pads.line(pin) for pin in range(7, -1, -1))


async def boot(dut, pads, words):
    """Start the pads, load `words` through the real load phase, and
    check the reset rule every case depends on.

    Reset is asserted before the new board is attached: the previous
    case's program is still running, and its pads would otherwise fight
    the new board's tie-offs for the cycles before `load_program` resets
    the design (the model would report it, correctly, and then discard it
    at the reset release -- but it is not what any case here is about)."""
    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    pads.start()
    await load_program(dut, words)
    assert pads.resets == 1, f"{pads.resets} reset releases seen during the load"
    assert pads.oe_seen == 0 and pads.oe_unknown == 0, (
        f"uio pads 0x{pads.oe_seen:02x} enabled (0x{pads.oe_unknown:02x} "
        "unknown) between reset release and the end of the load phase "
        "(DR 0012: every uio pin is an input at reset)"
    )
    assert pads.contention == [], "contention before the program ran"


@cocotb.test()
async def test_reset_and_input_pads_follow_the_board(dut):
    """Out of reset, and with a program that never enables a pad, each
    line is whatever the board makes it -- including where `uio_out`
    holds the opposite level."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    pads = UioPads(dut, pulls={0: "up", 1: "down"}, tie={3: 1, 4: 0})
    # the program writes uio_out = 0xFF and enables nothing
    await boot(dut, pads, mirror(out=0xFF))
    snap = await snapshot(dut, SETTLE)
    pads.stop()
    assert lines(pads) == "zzz01z01", lines(pads)
    assert snap["uio_in"] == lines(pads), (
        f"uio_in {snap['uio_in']} is not the resolved lines {lines(pads)}"
    )
    assert pads.oe_seen == 0 and pads.oe_unknown == 0
    assert pads.line(1) == "0" and pads.line(4) == "0", (
        "uio_out = 1 reached a line whose pad is an input"
    )
    # the core's own view of the four lines that have a level
    for pin, want in ((0, "1"), (1, "0"), (3, "1"), (4, "0")):
        assert bit(snap["uo_out"], pin) == want, (
            f"core read uio[{pin}] as {bit(snap['uo_out'], pin)}, line is {want}"
        )
    pads.assert_no_contention()
    dut._log.info(
        f"input pads: lines {lines(pads)}, uio_in {snap['uio_in']}, core "
        f"read {snap['uo_out']} (uio_out = 0xFF, no pad enabled)"
    )


@cocotb.test()
async def test_push_pull_pads_drive_the_line(dut):
    """`UIO_DIR`: a driven 1 beats the pull-down, a driven 0 beats the
    pull-up, undriven pins keep the board's level, and the core reads its
    own drive back."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    pads = UioPads(dut, pulls={0: "up", 1: "down", 2: "up"},
                   tie={3: 0, 4: 0, 5: 0, 6: 0, 7: 0})
    await boot(dut, pads, mirror(out=0x02, direction=0x06))
    snap = await snapshot(dut, SETTLE)
    pads.stop()
    assert lines(pads) == "00000011", lines(pads)
    assert snap["uio_in"] == "00000011" and snap["uo_out"] == "00000011", snap
    assert pads.oe_seen == 0x06 and pads.oe_unknown == 0
    assert pads.drove_high == 0x02 and pads.drove_low == 0x04, (
        f"drove high 0x{pads.drove_high:02x} low 0x{pads.drove_low:02x}"
    )
    pads.assert_no_contention()
    dut._log.info(
        f"push-pull: lines {lines(pads)}, oe_seen 0x{pads.oe_seen:02x}, "
        f"core read {snap['uo_out']}"
    )


@cocotb.test()
async def test_open_drain_pads_pull_low_or_release(dut):
    """`UIO_OD`: a 0 pulls the line low; a 1 releases it to the pull-up;
    a peripheral may hold a released line low, and may hold it while the
    design toggles its pad underneath -- none of which is contention."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    tie = {pin: 0 for pin in range(1, 8)}

    # ---- writing 0: the pad pulls the line low
    pads = UioPads(dut, pulls={0: "up"}, tie=tie)
    await boot(dut, pads, mirror(out=0x00, od=0x01))
    snap = await snapshot(dut, SETTLE)
    assert pads.line(0) == "0" and bit(snap["uo_out"], 0) == "0", snap
    assert (pads.oe_seen, pads.drove_low, pads.drove_high) == (0x01, 0x01, 0)
    # a peripheral pulling the same line low agrees with the pad
    pads.pull_low(0)
    snap = await snapshot(dut, 4)
    assert pads.line(0) == "0"
    pads.release(0)
    pads.stop()
    pads.assert_no_contention()

    # ---- writing 1: the pad releases, the pull-up restores the line
    pads = UioPads(dut, pulls={0: "up"}, tie=tie)
    await boot(dut, pads, mirror(out=0x01, od=0x01))
    snap = await snapshot(dut, SETTLE)
    assert pads.line(0) == "1" and bit(snap["uo_out"], 0) == "1", snap
    assert pads.oe_seen == 0, (
        f"an open-drain pad writing 1 was enabled (0x{pads.oe_seen:02x}): "
        "it would drive the line high"
    )
    # the peripheral holds the released line low: the core reads 0
    pads.pull_low(0)
    snap = await snapshot(dut, 6)
    assert pads.line(0) == "0" and bit(snap["uo_out"], 0) == "0", snap
    pads.release(0)
    snap = await snapshot(dut, 6)
    assert pads.line(0) == "1" and bit(snap["uo_out"], 0) == "1", snap
    pads.stop()
    pads.assert_no_contention()

    # ---- the design toggles its pad under a peripheral's hold (stretch)
    pads = UioPads(dut, pulls={0: "up"}, tie=tie)
    await boot(dut, pads, asm.assemble_text(TOGGLE_OD, "pad-toggle").words)
    pads.pull_low(0)
    seen = set()
    for _ in range(40):
        await snapshot(dut, 1)
        seen.add(pads.line(0))
    assert seen == {"0"}, f"the held line moved: {seen}"
    assert pads.oe_seen == 0x01 and pads.drove_high == 0, (
        "the toggling program must have asserted and released under the hold"
    )
    pads.release(0)
    levels = ""
    for _ in range(40):
        await snapshot(dut, 1)
        levels += pads.line(0)
    pads.stop()
    assert "0" in levels and "1" in levels, (
        f"after the release the line must follow the design: {levels}"
    )
    # 4 cycles low, 4 high, as the program is written (WAIT n = n+1)
    assert "1000011110000" in levels, levels
    pads.assert_no_contention()
    dut._log.info(
        f"open-drain: held line stayed low for 40 cycles with the design "
        f"toggling, then followed it: {levels}; no contention"
    )


@cocotb.test()
async def test_contention_is_detected(dut):
    """The detector's positive controls: three real fights, each one
    recorded episode naming the pin and both levels, each making the line
    'x' and `assert_no_contention()` raise."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())

    # ---- 1. push-pull 1, then the board drives 0 (external side moves)
    pads = UioPads(dut, pulls={0: "up"}, tie={p: 0 for p in (2, 3, 4, 5, 6, 7)})
    await boot(dut, pads, mirror(out=0x02, direction=0x02))
    await snapshot(dut, SETTLE)
    assert pads.line(1) == "1"
    pads.drive(1, 1)  # agreeing drivers: not contention
    await snapshot(dut, 2)
    assert pads.contention == [] and pads.line(1) == "1"
    pads.drive(1, 0)
    snap = await snapshot(dut, 2)
    assert len(pads.contention) == 1, pads.contention
    event = pads.contention[0]
    assert (event.pin, event.design_level, event.external_level) == (1, 1, 0)
    assert pads.line(1) == "x" and bit(snap["uio_in"], 1) == "x", snap
    try:
        pads.assert_no_contention()
    except PadContention as exc:
        dut._log.info(f"contention 1 (expected): {exc}")
    else:
        raise AssertionError(
            "NEGATIVE CONTROL FAILED TO FAIL: assert_no_contention() passed "
            "with a recorded push-pull fight"
        )
    try:
        pads.level(1)
    except ValueError:
        pass
    else:
        raise AssertionError("level() returned a logic level for an 'x' line")
    # one episode is one record however long it lasts ...
    await snapshot(dut, 10)
    assert len(pads.contention) == 1
    # ... and a second fight after a release is a second record
    pads.release(1)
    await snapshot(dut, 2)
    assert pads.line(1) == "1" and len(pads.contention) == 1
    pads.drive(1, 0)
    await snapshot(dut, 2)
    assert len(pads.contention) == 2
    pads.stop()

    # ---- 2. the board ties a pin low, then the design enables push-pull 1
    # (design side moves: found by the model's own resolution, not by a
    # drive() call)
    pads = UioPads(dut, pulls={0: "up"}, tie={p: 0 for p in range(1, 8)})
    await boot(dut, pads, mirror(out=0x04, direction=0x04))
    t_loaded = float(cocotb.utils.get_sim_time("ns"))
    await snapshot(dut, SETTLE)
    pads.stop()
    assert len(pads.contention) == 1, pads.contention
    event = pads.contention[0]
    assert (event.pin, event.design_level, event.external_level) == (2, 1, 0)
    assert event.t_ns > t_loaded, "the fight must start when the pad is enabled"
    assert pads.line(2) == "x"
    dut._log.info(f"contention 2 (expected): {event}")

    # ---- 3. open-drain 0 against a push-pull 1 from the board
    pads = UioPads(dut, pulls={0: "up"}, tie={p: 0 for p in range(1, 8)})
    await boot(dut, pads, mirror(out=0x00, od=0x01))
    await snapshot(dut, SETTLE)
    assert pads.line(0) == "0" and pads.contention == []
    pads.drive(0, 1)
    await snapshot(dut, 2)
    pads.stop()
    assert len(pads.contention) == 1, pads.contention
    event = pads.contention[0]
    assert (event.pin, event.design_level, event.external_level) == (0, 0, 1)
    dut._log.info(f"contention 3 (expected): {event}")


@cocotb.test()
async def test_pad_model_owns_uio_in(dut):
    """A write to `uio_in` from anywhere else is replaced by the resolved
    level in the same time step, so a bench cannot bypass the pads by
    accident (`load_program` itself writes `uio_in = 0`)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    pads = UioPads(dut, pulls={pin: "up" for pin in range(8)})
    await boot(dut, pads, mirror())
    await snapshot(dut, 4)
    assert str(dut.uio_in.value) == "11111111"
    before = pads.resolutions
    dut.uio_in.value = 0x00
    await ReadOnly()
    got = str(dut.uio_in.value)
    await Timer(1, unit="ns")
    pads.stop()
    assert got == "11111111", f"a foreign write survived on uio_in: {got}"
    assert pads.resolutions > before, "the model did not re-resolve"
    # stopped: the model no longer owns the port
    dut.uio_in.value = 0x00
    await Timer(1, unit="ns")
    assert str(dut.uio_in.value) == "00000000"
