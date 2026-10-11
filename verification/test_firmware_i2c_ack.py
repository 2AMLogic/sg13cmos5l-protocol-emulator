"""Where the I2C controller samples ACK, and what it does with a late one
(issue #258, part of #243; target-spec rows 1 and 12).

Extends `test_firmware_i2c.py` (which is unchanged and still hashed by its
own live records, including the gate-level ones) with the ACK-slot
regressions issue #258 asks for, on the same committed programs
(`firmware/asm/i2c_{fast,std}.asm`, images under `firmware/build/`), the
same load path, the same pad model (`verification/uio_pads.py`: the lines
graded are what `uio_in` reads, resolved from the design's `uio_oe` /
`uio_out`, a pull-up each and the peripheral) and the same independent
reference model (`verification/reference_models/i2c.py`).

The defect this bench exists for
--------------------------------
UM10204 lets a peripheral put its ACK on SDA anywhere in the ninth clock's
low phase, as long as it is there t_SU;DAT before SCL rises, and holds it
for the whole high phase. Until #258 both programs sampled the ACK with an
`IN` 22 (Fast) / 32 (Standard) cycles into the ninth *low* phase. A
peripheral that answered after that instant was a legal ACK on the line
-- the model decodes it as one -- but the controller had already read SDA
released, took the address-NACK branch and sent STOP instead of the data
byte. The sibling bench's peripheral answered one cycle after the fall,
so nothing exercised it.

The fix moves both ACK samples to the middle of the ninth SCL *high*
(Fast: 30 cycles after the rise, 25 before the fall; Standard: 121 / 121)
and keeps every phase budget, on both address-ACK outcomes.

What is checked
---------------
1. `test_ack_samples_sit_inside_ninth_high` (static, from the assembled
   listing): no `IN` in an ACK low phase; one `IN` strictly inside each
   ACK high; the `AND` that turns it into Z right after it and nothing
   flag-setting between that and the `BNZ`; the ninth high exactly
   t_high cycles on the taken (NACK) path as well as the fall-through
   `.cyclesec` count. (The last one found a defect: Standard's NACK path
   held the ninth high 284 cycles since issue #125, not 242; corrected in
   #258 -- see `i2c_std.asm`.)
2. `test_both_address_outcomes_early_response`: the early peripheral of
   the sibling bench (response one cycle after the fall), address ACK +
   data NACK, address ACK + data ACK, and address NACK. Each run: the
   model's decode and every committed budget; both ACK clocks legal on the
   line (SDA stable for the whole high, the high exactly t_high on either
   branch); the controller's own reading of its last ACK slot (white-box
   Z flag, RTL only).
3. `test_late_ack_responses_are_read_as_ack`: per grade two late
   responders, both ACK slots answered late: `after-former-IN` (the first
   response the old low-phase `IN` missed) and `latest-legal` (the latest
   response that still meets t_SU;DAT on the captured line). The address
   ACK must be acted on (data 0x5A sent, acks [True, True]) and the data
   ACK read as ACK (Z flag). Each response's set-up time is measured on
   the captured line and must be at least UM10204 Table 10's t_SU;DAT
   (100 ns Fast, 250 ns Standard; the model does not grade t_SU;DAT), so
   the stimulus is legal I2C, not a peripheral the controller is entitled
   to misread.

The peripheral (`drive_ack_responder`) is the sibling bench's reactive
open-drain peripheral with one added parameter, the response delay; at
delay 0 it behaves exactly like `test_firmware_i2c.drive_peripheral`.

Negative control
----------------
`verification/i2c_ack_schedule_mutants.py` assembles the ORIGINAL
low-phase schedule (the pre-#258 ACK sections, byte for byte) into fresh
scratch images, one ACK slot and one grade at a time, and requires
`test_late_ack_responses_are_read_as_ack` to fail on each with an
assertion (a parsed result whose failure is an `AssertionError`, never a
tool or compile error), while the scratch images still pass the
committed-artifact check.

What is NOT claimed
-------------------
Routed electrical behaviour of the open-drain release (issue #244), pad
delay and pull-up rise time (the pad model is zero-delay), the gate-level
netlist (not run here), clock stretching, and the read / repeated-START /
generated variants (`i2c_*_sr*.asm`, the random-regression templates'
own runs). The cycle counts are the claim; any ns figure is the bench's
nominal 20 ns clock (`test_firmware_i2c.CLK_PERIOD_NS`).

Driven by `klt functional-verification`
(`verification/request-firmware-i2c-ack.json`). Like its siblings, this
file is input to klt, not a pytest module. Deterministic: committed
programs, fixed response scripts, no randomization.
"""

import os
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer

from reference_models.i2c import minimum_ns, minimum_period_ns
from reference_models.waveform import Signal

from test_firmware_i2c import (  # noqa: E402  (helpers; no test objects)
    ADDRESS,
    CAPTURE_MARGIN_CYCLES,
    CAPTURE_SPECS,
    CLK_PERIOD_NS,
    DATA_BYTE,
    MODES,
    READ_BIT,
    REPO_ROOT,
    SCL_BIT,
    SDA_BIT,
    _Mode,
    committed_total_cycles,
    grade_transfer,
    i2c_pads,
    load_committed_image,
)
from uio_pads import assert_i2c_open_drain  # noqa: E402
from test_firmware_uart import capture_pin_bits  # noqa: E402
from test_protocol_emulator import load_program  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402

#: UM10204 Table 10 t_SU;DAT (data set-up time) minimums, ns, keyed by
#: fast_mode: Standard 250, Fast 100. The reference model samples SDA on
#: the SCL rise and does not grade t_SU;DAT, so the late responders check
#: their own set-up against these figures before they count as legal.
T_SU_DAT_NS = {True: 100, False: 250}

#: The ACK `IN` of the original schedule (issue #73 until #258) sat in the
#: ACK *low* phase at section offset 22 (Fast: OUT + WAIT 20) / 32
#: (Standard: OUT + WAIT 30) cycles after the SCL-fall OUT. On the
#: captured line, a response that first shows N cycles after the fall was
#: visible to that IN only for N <= that offset.
#: `i2c_ack_schedule_mutants.py` re-derives both numbers from the
#: original source it assembles and checks them against these.
FORMER_LOW_PHASE_IN_OFFSET = {"i2c_fast": 22, "i2c_std": 32}

#: Address byte's ACK clock = the 9th SCL fall; the data byte's = the 18th.
ADDR_ACK_FALL, DATA_ACK_FALL = 9, 18


# =======================================================================
# The peripheral, with a response delay
# =======================================================================


async def drive_ack_responder(dut, pads, ack_falls: set, ack_delay: int) -> None:
    """Reactive I2C peripheral on the pad model's external side: watch
    the SCL **line**, count its falls, and pull the SDA line low for the
    ACK slots named in `ack_falls`, `ack_delay` clock edges late.

    The decision rule is `test_firmware_i2c.drive_peripheral`'s: the
    pull answers the fall it is scheduled from, and every fall NOT in
    `ack_falls` releases SDA (and cancels a pull still pending), so the
    release lands at the next fall, inside the following low phase --
    the only place I2C lets SDA change. Timing: the peripheral reads the
    line in the `ReadOnly` region of each clock edge and changes its
    drive 1 ns later. With `ack_delay = 0` it pulls on the edge where it
    saw the fall (exactly the sibling bench's peripheral, so the captured
    line shows SDA low one cycle after the fall); with `ack_delay = d`
    it waits d more edges (the captured line shows it d + 1 cycles after
    the fall).

    Open-drain like every I2C device; it never touches SCL (no
    stretching).
    """
    previous = pads.level(SCL_BIT)
    falls = 0
    pending = None  # edges left before a scheduled pull lands
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        scl = pads.level(SCL_BIT)
        await Timer(1, unit="ns")
        if previous == 1 and scl == 0:
            falls += 1
            pending = ack_delay if falls in ack_falls else None
            if pending is None:
                pads.release(SDA_BIT)
        if pending is not None:
            if pending == 0:
                pending = None
                pads.pull_low(SDA_BIT)
            else:
                pending -= 1
        previous = scl


async def run_with_responder(dut, mode: _Mode, ack_falls: set, ack_delay: int) -> dict:
    """Load `mode`'s committed image over the real load-phase pins, run it
    on the I2C board (`test_firmware_i2c.i2c_pads`) with the responder
    above, and capture the lines and the controller's intent on every
    clock edge. Same discipline as the sibling's `run_words`: no pad
    enabled through the load, and the run must end having driven exactly
    SCL and SDA, only ever low, without contention."""
    words = load_committed_image(mode)
    assert len(words) <= 256, "program exceeds DR 0001's 256-word memory"
    run_cycles = committed_total_cycles(mode) + CAPTURE_MARGIN_CYCLES
    tag = f"{mode.name} acks {sorted(ack_falls)} delay {ack_delay}"
    dut._log.info(f"{tag}: capturing {run_cycles} cycles")
    pads = i2c_pads(dut).start()
    await load_program(dut, words)
    assert pads.resets == 1 and pads.oe_seen == 0, (
        f"{tag}: uio pads 0x{pads.oe_seen:02x} were enabled between reset "
        "release and the end of the load phase (DR 0012)"
    )
    driver = cocotb.start_soon(drive_ack_responder(dut, pads, ack_falls, ack_delay))
    caps = await capture_pin_bits(dut, CAPTURE_SPECS, run_cycles)
    driver.kill()
    pads.stop()
    assert_i2c_open_drain(pads, tag)
    return caps


# =======================================================================
# ACK-slot measurements on the captured lines
# =======================================================================


def late_ack_delays(mode: _Mode) -> list:
    """`(label, ack_delay)` of the two late responders per grade:

    * `after-former-IN`: shows on the line one cycle after the original
      low-phase `IN`'s sample edge -- the first response it missed;
    * `latest-legal`: the latest response whose set-up time to the
      ninth rise on the captured line is still at least t_SU;DAT
      (rounded up to whole cycles).
    """
    setup_cycles = -(-T_SU_DAT_NS[mode.fast_mode] // CLK_PERIOD_NS)  # ceil
    return [
        ("after-former-IN", FORMER_LOW_PHASE_IN_OFFSET[mode.name]),
        ("latest-legal", mode.t_low - setup_cycles - 1),
    ]


def scl_edges(scl: Signal):
    """`(falls, rises)` of the SCL line in order. The line idles high and
    nothing moves it before the controller's first fall (the end of the
    START hold), so `falls[k - 1]` is the k-th fall of the transfer and
    `rises[k - 1]` the rise that ends the low phase it opens."""
    assert scl.initial == 1 and scl.transitions and scl.transitions[0][1] == 0, (
        "the SCL line must idle high and first move by falling"
    )
    falls = [t for (t, v) in scl.transitions if v == 0]
    rises = [t for (t, v) in scl.transitions if v == 1]
    return falls, rises


def ack_slot(scl: Signal, sda: Signal, slot_fall: int) -> dict:
    """One ACK clock on the captured lines: its SCL fall (the
    `slot_fall`-th), rise and next fall; when SDA last went low inside the
    low phase (the response, or None); SDA at the rise; and every SDA
    transition while SCL was high."""
    falls, rises = scl_edges(scl)
    fall, rise = falls[slot_fall - 1], rises[slot_fall - 1]
    next_fall = falls[slot_fall] if len(falls) > slot_fall else None
    end = next_fall if next_fall is not None else float("inf")
    lows = [t for (t, v) in sda.transitions if fall < t <= rise and v == 0]
    return {
        "fall": fall,
        "rise": rise,
        "next_fall": next_fall,
        "response": lows[-1] if lows else None,
        "sda_at_rise": sda.value_at(rise),
        "sda_while_high": [(t, v) for (t, v) in sda.transitions if rise < t < end],
    }


def assert_ack_slot(mode: _Mode, run: str, scl: Signal, sda: Signal,
                    slot_fall: int, acked: bool, late: bool = False) -> dict:
    """The ACK clock was legal I2C on the line and answered as intended:
    SDA stable for the whole high phase; the high exactly t_high cycles
    (on BOTH address outcomes -- the model's t_HIGH(min) cannot see a high
    that is too long); SDA at the rise the intended answer; for an ACK, a
    response whose set-up to the rise is at least t_SU;DAT; with `late`,
    a response that shows strictly after the former low-phase `IN`."""
    s = ack_slot(scl, sda, slot_fall)
    tag = f"{mode.name} {run} ACK slot (SCL fall {slot_fall})"
    assert not s["sda_while_high"], (
        f"{tag}: SDA moved while SCL was high: {s['sda_while_high']}"
    )
    assert s["next_fall"] is not None, f"{tag}: SCL never fell after the ACK clock"
    high = ns(s["next_fall"] - s["rise"])
    assert high == mode.high_ns, (
        f"{tag}: ACK-clock high {high} ns, the committed budget is "
        f"{mode.t_high} cycles = {mode.high_ns} ns"
    )
    assert s["sda_at_rise"] == (0 if acked else 1), (
        f"{tag}: SDA was {s['sda_at_rise']} at the rise, expected "
        f"{'ACK (0)' if acked else 'NACK (1)'}"
    )
    if acked:
        assert s["response"] is not None, f"{tag}: no SDA response in the low phase"
        s["setup_ns"] = ns(s["rise"] - s["response"])
        s["response_offset"] = round((s["response"] - s["fall"]) / CLK_PERIOD_NS)
        assert s["setup_ns"] >= T_SU_DAT_NS[mode.fast_mode], (
            f"{tag}: response set-up {s['setup_ns']} ns to the SCL rise is "
            f"under t_SU;DAT {T_SU_DAT_NS[mode.fast_mode]} ns -- not legal "
            "stimulus"
        )
        if late:
            assert s["response_offset"] > FORMER_LOW_PHASE_IN_OFFSET[mode.name], (
                f"{tag}: the late response shows {s['response_offset']} "
                "cycles after the fall, not after the former low-phase IN "
                f"(offset {FORMER_LOW_PHASE_IN_OFFSET[mode.name]})"
            )
    return s


def assert_controller_read(dut, mode: _Mode, run: str, acked: bool) -> None:
    """Labelled white-box read (skipped on a gate-level netlist,
    `GATES=yes`): the core's Z flag after the program halted. Every
    flag-setting instruction after the last ACK sample's `AND` is absent
    (the STOP paths are LDI / OUT / WAIT / HALT), so Z is the controller's
    own reading of the last ACK slot it sampled: 1 = ACK (SDA 0), 0 =
    NACK. The data ACK is sampled but never branched on, so this is the
    only place that reading is observable at all."""
    if os.environ.get("GATES") == "yes":
        dut._log.info(f"{mode.name} {run}: gate level, Z-flag read skipped")
        return
    z = int(dut.u_core.flag_z.value)
    assert z == (1 if acked else 0), (
        f"{mode.name} {run}: the controller's last ACK sample (Z flag) read "
        f"{'ACK' if z else 'NACK'}, the line carried "
        f"{'ACK' if acked else 'NACK'} at the SCL rise"
    )


def ack_section_schedule(mode: _Mode) -> dict:
    """The committed program's ACK slots from the assembled listing: per
    ACK section the cycle offset (from the section's opening OUT) of each
    `IN` and each flag-setting instruction, and the `BNZ`; plus the
    ninth high's length along the address-NACK path (BNZ taken, through
    `stop_from_addr`, to the SCL-fall OUT opening `i2c_stop_addr_low`),
    which the fall-through `.cyclesec` count does not cover."""
    program = asm.assemble_file(REPO_ROOT / mode.src)
    by_addr = {ins.addr: ins for ins in program.instructions}
    out = {}
    for sec in program.sections:
        if not sec.name.startswith(("i2c_ack1_", "i2c_ack2_")):
            continue
        offset, ins_offsets, flag_ops, bnz = 0, [], [], None
        for addr in range(sec.start_addr, sec.end_addr + 1):
            ins = by_addr[addr]
            if ins.mnemonic == "IN":
                ins_offsets.append(offset)
            if ins.mnemonic in asm.FLAG_SETTING_OPS:
                flag_ops.append(offset)
            if ins.mnemonic == "BNZ":
                bnz = (offset, ins.cycles, ins.word & 0xFF)
            offset += ins.cycles
        out[sec.name] = {"in_offsets": ins_offsets, "flag_ops": flag_ops,
                         "bnz": bnz, "cycles": sec.cycles}
    stop_low = next(s for s in program.sections if s.name == "i2c_stop_addr_low")
    bnz_offset, bnz_cycles, target = out["i2c_ack1_high"]["bnz"]
    out["i2c_ack1_high"]["nack_path_cycles"] = bnz_offset + bnz_cycles + sum(
        by_addr[a].cycles for a in range(target, stop_low.start_addr)
    )
    return out


def ns(value: float) -> float:
    """A measured time rounded to 1 ps. Edge times are float simulation
    times; after a few runs in one simulation the +-1e-9 ns
    representation noise shows up in differences (seen: 4839.999999999767
    for a 4840 ns high), which is not signal."""
    return round(value, 3)


def assert_budgets(dut, mode: _Mode, run: str, report) -> None:
    """The sibling's `assert_measured_budgets`, on measurements rounded
    to 1 ps: the model's t_LOW(min), t_HIGH(min), t_HD;STA, t_SU;STO and
    shortest complete clock equal the committed cycle budgets at the
    nominal clock, and the budgets clear UM10204 Table 10."""
    m = {k: ns(v) for k, v in report.measurements.items()}
    hd_key = next(k for k in m if k.startswith("t_HD;STA@"))
    for key, want in (
        ("t_LOW(min)", mode.low_ns),
        ("t_HIGH(min)", mode.high_ns),
        (hd_key, mode.t_hd_sta * CLK_PERIOD_NS),
        ("t_SU;STO", mode.t_su_sto * CLK_PERIOD_NS),
        ("t_SCL(min)", mode.period_ns),
    ):
        assert m[key] == want, (
            f"{mode.name} {run}: model measured {key} {m[key]} ns, the "
            f"committed budget is {want} ns"
        )
    assert mode.period_ns >= minimum_period_ns(mode.fast_mode)
    assert mode.low_ns >= minimum_ns("t_LOW", mode.fast_mode)
    assert mode.high_ns >= minimum_ns("t_HIGH", mode.fast_mode)


def grade_run(dut, mode, run, caps):
    scl, sda, report = grade_transfer(caps, mode)
    dut._log.info(f"{mode.name} {run}: {report}")
    assert report.address == ADDRESS and report.read_bit == READ_BIT, (
        f"{mode.name} {run}: decoded {report}"
    )
    assert report.stretched_clocks == 0, "no clock stretching was driven"
    return scl, sda, report


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_ack_samples_sit_inside_ninth_high(dut):
    """Static schedule of both committed programs' ACK slots (no DUT run):
    no `IN` in an ACK low phase; exactly one `IN` per ACK high, strictly
    inside it (an `IN` at section offset k retires k edges after the
    SCL-rise OUT, i.e. it reads the line during the k-th cycle of the
    high, so 1 <= k <= t_high - 1 keeps it off both edges); the `AND`
    isolating SDA right after it; nothing flag-setting between that `AND`
    and the address `BNZ`; and the ninth high exactly t_high cycles on the
    taken (NACK) path as on the fall-through path."""
    for mode in MODES:
        sched = ack_section_schedule(mode)
        for slot in ("i2c_ack1", "i2c_ack2"):
            low, high = sched[f"{slot}_low"], sched[f"{slot}_high"]
            assert not low["in_offsets"], (
                f"{mode.name} {slot}: IN in the ACK low phase at offset(s) "
                f"{low['in_offsets']} -- sampled before the SCL rise"
            )
            assert low["cycles"] == mode.t_low and high["cycles"] == mode.t_high
            assert len(high["in_offsets"]) == 1, (
                f"{mode.name} {slot}: expected one IN in the ACK high, found "
                f"offsets {high['in_offsets']}"
            )
            k = high["in_offsets"][0]
            assert 1 <= k <= mode.t_high - 1, (
                f"{mode.name} {slot}: IN at high offset {k} is not strictly "
                f"inside the {mode.t_high}-cycle high"
            )
            assert k + 1 in high["flag_ops"], (
                f"{mode.name} {slot}: the instruction after the IN must be "
                f"the flag-setting AND, flag ops at {high['flag_ops']}"
            )
            dut._log.info(
                f"{mode.name} {slot}: IN samples {k} cycles after the SCL rise, "
                f"{mode.t_high - k} before the fall"
            )
        high = sched["i2c_ack1_high"]
        k, bnz_offset = high["in_offsets"][0], high["bnz"][0]
        between = [o for o in high["flag_ops"] if k + 1 < o < bnz_offset]
        assert bnz_offset > k + 1 and not between, (
            f"{mode.name}: flag-setting instruction(s) at {between} between "
            f"the ACK AND (offset {k + 1}) and the BNZ (offset {bnz_offset})"
        )
        assert high["nack_path_cycles"] == mode.t_high, (
            f"{mode.name}: the address-NACK path holds the ninth SCL high "
            f"{high['nack_path_cycles']} cycles, the budget is {mode.t_high}"
        )
        dut._log.info(
            f"{mode.name}: ninth high {high['cycles']} cycles fall-through, "
            f"{high['nack_path_cycles']} on the NACK path"
        )


@cocotb.test()
async def test_both_address_outcomes_early_response(dut):
    """The early peripheral (delay 0: the sibling bench's), three ACK
    scripts per grade: address ACK + data NACK, address ACK + data ACK,
    address NACK. Decode, every committed budget (model), both ACK clocks
    legal on the line with the high exactly t_high on either branch, and
    the controller's own reading of its last ACK slot."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())

    for mode in MODES:
        for run, ack_falls, data, acks in (
            ("addr ACK, data NACK", {ADDR_ACK_FALL}, [DATA_BYTE], [True, False]),
            ("addr ACK, data ACK", {ADDR_ACK_FALL, DATA_ACK_FALL}, [DATA_BYTE], [True, True]),
            ("addr NACK", set(), [], [False]),
        ):
            caps = await run_with_responder(dut, mode, ack_falls, 0)
            scl, sda, report = grade_run(dut, mode, run, caps)
            assert report.data_bytes == data and report.acks == acks, (
                f"{mode.name} {run}: decoded data {report.data_bytes} acks "
                f"{report.acks}, expected {data} / {acks}"
            )
            assert report.ok, f"{mode.name} {run} failed the independent model: {report}"
            assert_budgets(dut, mode, run, report)
            assert_ack_slot(mode, run, scl, sda, ADDR_ACK_FALL, acked=acks[0])
            if data:
                assert_ack_slot(mode, run, scl, sda, DATA_ACK_FALL, acked=acks[1])
            assert_controller_read(dut, mode, run, acked=acks[-1])


@cocotb.test()
async def test_late_ack_responses_are_read_as_ack(dut):
    """Issue #258's regression. Per grade, two late responders
    (`late_ack_delays`), each answering both the address and the data
    ACK late: the address ACK must be acted on (data 0x5A transmitted,
    acks [True, True]), the transfer must pass the model with every
    committed budget, both ACK clocks must be legal on the line with the
    response at least t_SU;DAT ahead of the rise and strictly after the
    former low-phase `IN`, and the controller must have read the data ACK
    as an ACK.

    Under the original schedule the address `IN` read SDA still released,
    the branch was taken, and the model decoded acks [True] with no data
    byte: this test fails there with an assertion
    (`verification/i2c_ack_schedule_mutants.py`)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())

    for mode in MODES:
        for label, delay in late_ack_delays(mode):
            run = f"late ACK ({label}, delay {delay})"
            caps = await run_with_responder(
                dut, mode, {ADDR_ACK_FALL, DATA_ACK_FALL}, delay
            )
            scl, sda, report = grade_run(dut, mode, run, caps)
            assert report.data_bytes == [DATA_BYTE] and report.acks == [True, True], (
                f"{mode.name} {run}: a late but legal address ACK must be "
                f"followed by the data byte; decoded data {report.data_bytes} "
                f"acks {report.acks} -- the controller read a NACK"
            )
            assert report.ok, f"{mode.name} {run} failed the independent model: {report}"
            assert_budgets(dut, mode, run, report)
            for slot_fall in (ADDR_ACK_FALL, DATA_ACK_FALL):
                s = assert_ack_slot(mode, run, scl, sda, slot_fall, acked=True, late=True)
                dut._log.info(
                    f"{mode.name} {run}, SCL fall {slot_fall}: response "
                    f"{s['response_offset']} cycles after the fall, set-up "
                    f"{s['setup_ns']:.0f} ns (t_SU;DAT "
                    f"{T_SU_DAT_NS[mode.fast_mode]} ns)"
                )
            assert_controller_read(dut, mode, run, acked=True)
