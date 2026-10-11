"""DUT-facing I2C repeated-START / controller-read / clock-stretch bench
(issue #92, part of #23; target-spec rows 1 and 12, gap-to-submission row
12 unmet-reason (a)).

Extends `test_firmware_i2c.py` (which is unchanged and still hashed by its
own live record) with four committed programs -- `firmware/asm/
i2c_{fast,std}_sr.asm` (EXACT: no pin-dependent branch at all) and
`i2c_{fast,std}_sr_poll.asm` (the same transfer with an SCL poll after every
SCL rise, i.e. clock-stretch tolerant) -- each a complete

    START, 0xA0 (0x50 W) + ACK, 0x5A + ACK, repeated START, 0xA1 (0x50 R)
    + ACK, one byte read from the peripheral, controller NACK, STOP

loaded over the real serial load-phase pins onto the real top and executed
by the ISA core. As in the sibling bench, every run goes through the
silicon-true pad model (`verification/uio_pads.py`; issue #136, DR 0012):
the SCL and SDA lines are resolved per pin from the design's `uio_oe` /
`uio_out`, a pull-up each, and the peripheral as an external open-drain
driver, and read back on `uio_in`. The lines graded are the ones sampled
on `uio_in`; the peripheral watches the SCL line, not the controller's
intent; and every run ends with the check that the design drove exactly
SCL and SDA, only ever low, with no contention -- including the runs in
which the peripheral holds SCL low while the controller has released it,
which is the case a push-pull pad would turn into a fight. (Until #136
the bench composed `uio_out AND uio_in` itself and never read `uio_oe`;
the records minted that way are superseded.) The decode and every timing
verdict come from the independent model
`verification/reference_models/i2c.py` (which since issue #125 also bounds
each data/ACK clock's complete period by Table 10's f_SCL maximum -- the
Standard programs pace a 500-cycle clock, 258 low + 242 high, instead of
the former 235/200 = 435). The only bench-side inputs to a comparison are the expected bytes.

What this bench adds over the sibling
-------------------------------------
* **Repeated START at both speed grades.** `check_transfer` measures
  t_SU;STA (the SCL rise preceding the Sr to the SDA fall) and the Sr's
  t_HD;STA against Table 10. The programs pace t_SU;STA AT the Table 10
  minimum (30 cycles = 600 ns Fast, 235 cycles = 4700 ns Standard), so the
  negative control can be a single cycle short.
* **Controller read.** The peripheral drives a byte (0xB4, chosen so a
  bit-reversed or off-by-one capture cannot pass) on SDA while the core
  releases it (on the pads: `uio_oe[7]` drops, and the line is the
  peripheral's); the core samples it through its real `IN` path, shifts it in
  MSB first, and publishes it on `uo_out`, which the bench compares. The
  controller NACKs by releasing SDA on the 9th clock; the model decodes the
  final ACK slot as a NACK.
* **Clock stretching.** The poll programs read the peripheral's SCL level
  after every rise and loop while it is low. The reactive peripheral holds
  SCL low after three chosen falls (before the repeated START, inside the
  first read clock, before the STOP). **Determinism claims exclude the
  stretched interval**: unstretched, every phase is exact (and the poll
  variants are exact at budget+2 on rise phases); stretched, the time spent
  in a poll loop lasts as long as the peripheral holds SCL -- data-dependent
  by design -- and this bench checks mechanically that every OTHER SCL
  interval is byte-identical to the unstretched run's.

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
1. *Shortened repeated-START setup, in firmware.* The bench rewrites the
   `WAIT` marked `NEGCTL-SUSTA` in the committed source (one cycle short,
   and half), re-assembles it in memory, loads it on the DUT and grades the
   result: the independent model must FAIL it with t_SU;STA the ONLY
   violation while the transfer still decodes identically.
2. *DUT waveform compressed 0.9x* fails (t_LOW).
3. *Stretch against the non-polling program.* The same stretch script on the
   EXACT program must not yield a conforming, correctly decoded transfer --
   proof that the poll is load-bearing and that the stretch driver bites.
4. The model's own nominal repeated-START transfer passes in both grades
   (calibration that the minimums are not misread).
5. *`UIO_OD` left at reset* (issue #136). Each of the four images with its
   `WCTL UIO_OD` replaced by a reserved 1-cycle no-op: no pad is enabled,
   the lines never move, and the model finds no transfer. The poll
   programs are the sharper half of this control -- they read SCL back
   after every rise, and with the pads modelled what they read is the
   line the pull-up holds high, so they run to completion without ever
   having clocked the bus.

Everything is deterministic: committed programs, fixed scripts, no
randomization.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer

from reference_models.i2c import (
    check_transfer,
    encode_transfer,
    minimum_ns,
    minimum_period_ns,
)
from reference_models.waveform import Signal

from test_firmware_i2c import (  # noqa: E402  (helpers; no test objects)
    CAPTURE_MARGIN_CYCLES,
    CAPTURE_SPECS,
    CLK_PERIOD_NS,
    NEGATIVE_CONTROL_SCALE,
    REPO_ROOT,
    SCL_BIT,
    SDA_BIT,
    i2c_pads,
    scale_signal,
    without_uio_od,
)
from uio_pads import assert_i2c_open_drain  # noqa: E402
from test_firmware_uart import capture_pin_bits  # noqa: E402
from test_protocol_emulator import load_program  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402
import gen_i2c_sr  # noqa: E402

ADDRESS = 0x50
PTR_BYTE = 0x5A
ADDR_R_BYTE = 0xA1
READ_BYTE = 0xB4  # asymmetric: bit-reversed it is 0x2D

#: Peripheral ACK slots (SCL fall numbers; see `drive_peripheral_sr`).
ACK_FALLS = {9, 18, 28}
#: Falls that start the 8 read-data low phases (peripheral drives a bit).
READ_FALLS = {29 + i: (READ_BYTE >> (7 - i)) & 1 for i in range(8)}
#: Fall numbers after which the stretch script holds SCL low.
STRETCH_FALLS = (19, 29, 38)  # before Sr rise / first read clock / STOP rise


class Variant:
    def __init__(self, mode, poll):
        p = gen_i2c_sr.MODES[mode]
        self.mode, self.poll = mode, poll
        self.name = f"i2c_{mode}_sr" + ("_poll" if poll else "")
        self.fast_mode = mode == "fast"
        self.L, self.H = p["L"], p["H"]
        self.HD, self.SUSTA, self.SUSTO = p["HD"], p["SUSTA"], p["SUSTO"]
        self.extra = gen_i2c_sr.POLL_EXTRA if poll else 0
        self.src = Path("firmware") / "asm" / f"{self.name}.asm"
        self.hex = Path("firmware") / "build" / f"{self.name}.hex"
        self.cycles = Path("firmware") / "build" / f"{self.name}.cycles.txt"

    def stretches(self):
        """{fall: cycles the peripheral holds SCL low from that fall}."""
        return {
            19: self.L + 100,       # past the Sr's low phase
            29: 2 * self.L + 37,    # >= 2 x t_LOW: the model flags it stretched
            38: self.L + 77,        # before the STOP's SCL rise
        }

    def expected_sections(self):
        exp = {"i2c_start_hold": self.HD, "i2c_sr_low": self.L,
               "i2c_sr_rise": self.SUSTA + self.extra,
               "i2c_sr_hold": self.HD, "i2c_rd_low": self.L,
               "i2c_rd_high": self.H + self.extra, "i2c_nack_low": self.L,
               "i2c_nack_high": self.H + self.extra, "i2c_stop_low": self.L,
               "i2c_stop_setup": self.SUSTO + self.extra}
        for n in (1, 2, 3):
            exp[f"i2c_tx{n}_low"] = self.L
            exp[f"i2c_tx{n}_high"] = self.H + self.extra
            exp[f"i2c_ack{n}_low"] = self.L
            exp[f"i2c_ack{n}_high"] = self.H + self.extra
        return exp

    def run_cycles(self, stretches=None):
        clocks = 40
        return (clocks * (self.L + self.H + self.extra + 8)
                + 2 * (self.SUSTA + self.HD + self.SUSTO) + 700
                + sum((stretches or {}).values()) + CAPTURE_MARGIN_CYCLES)


VARIANTS = [Variant(m, p) for m in ("fast", "std") for p in (False, True)]
EXACT = [v for v in VARIANTS if not v.poll]
POLL = [v for v in VARIANTS if v.poll]


def committed_words(v):
    words = [int(l, 16) for l in (REPO_ROOT / v.hex).read_text().split()]
    assert words
    return words


def mutate_sr_wait(text, remove_cycles):
    """The committed source with the `NEGCTL-SUSTA` WAIT shortened."""
    out, hit = [], 0
    for line in text.splitlines():
        if "NEGCTL-SUSTA" in line and line.strip().upper().startswith("WAIT"):
            body, _, comment = line.partition(";")
            n = int(body.split()[1]) - remove_cycles
            assert n >= 0
            line = f"        WAIT  {n}      ;{comment}"
            hit += 1
        out.append(line)
    assert hit == 1, "expected exactly one NEGCTL-SUSTA WAIT"
    return "\n".join(out) + "\n"


# =======================================================================
# Reactive peripheral: ACKs, drives read data, stretches SCL
# =======================================================================


async def drive_peripheral_sr(dut, pads, ack_falls, read_bits, stretches):
    """Reactive open-drain peripheral on the pad model's external side
    (SCL = uio[2], SDA = uio[3]; it pulls a line low or lets go).

    Counts the falls of the SCL **line** -- fall N starts the low phase of
    the Nth SCL low period: 1-8 address bits, 9 ACK, 10-17 payload, 18 ACK,
    19 the low before the repeated START, 20-27 address-R bits, 28 ACK,
    29-36 read data, 37 the NACK clock, 38 the low before the STOP. On each
    fall the peripheral sets its SDA drive: low for an ACK slot, the data
    bit for a read-data fall, released otherwise; and, for a fall in
    `stretches`, pulls SCL low and holds it that many cycles. Its drive
    changes 1 ns after the read-only sample (never racing the bench
    captures).

    While the peripheral holds SCL the line stays low whatever the
    controller does, so a controller that does not wait for the release
    (the EXACT programs under a stretch) loses clocks here exactly as it
    would on a board: this peripheral cannot see a "fall" of a line that
    is already low.
    """
    previous, falls = pads.level(SCL_BIT), 0
    scl_drive, sda_drive, hold = 1, 1, 0
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        scl = pads.level(SCL_BIT)
        await Timer(1, unit="ns")
        if hold:
            hold -= 1
            if hold == 0:
                scl_drive = 1
        if previous == 1 and scl == 0:
            falls += 1
            if falls in ack_falls:
                sda_drive = 0
            else:
                sda_drive = read_bits.get(falls, 1)
            if falls in stretches:
                scl_drive, hold = 0, stretches[falls]
        pads.set_open_drain(SDA_BIT, sda_drive)
        pads.set_open_drain(SCL_BIT, scl_drive)
        previous = scl


async def run_on_pads(dut, tag, words, cycles, ack_falls, read_bits,
                      stretches, expect_open_drain=True):
    """Load `words`, run them on the I2C board (`test_firmware_i2c.i2c_pads`) with
    the reactive peripheral, and capture the SCL/SDA lines plus the
    controller's intent every clock edge. Returns `(captures, uo_out,
    pads)`. No pad may be enabled from reset release through the load; with
    `expect_open_drain` the run must have driven exactly SCL and SDA, only
    ever low, without contention."""
    assert len(words) <= 256
    pads = i2c_pads(dut).start()
    await load_program(dut, words)
    assert pads.resets == 1 and pads.oe_seen == 0, (
        f"{tag}: uio pads 0x{pads.oe_seen:02x} enabled between reset release and the end of the load"
    )
    driver = cocotb.start_soon(
        drive_peripheral_sr(dut, pads, ack_falls, read_bits, stretches)
    )
    caps = await capture_pin_bits(dut, CAPTURE_SPECS, cycles)
    uo = int(dut.uo_out.value)
    driver.kill()
    pads.stop()
    if expect_open_drain:
        assert_i2c_open_drain(pads, tag)
    return caps, uo, pads


async def run_words(dut, words, cycles, stretches=None, tag="i2c_sr"):
    caps, uo, _pads = await run_on_pads(
        dut, tag, words, cycles, ACK_FALLS, READ_FALLS, stretches or {}
    )
    return caps, uo


def grade(caps, v):
    """The two pad-resolved lines, judged by the independent model."""
    scl = caps["scl"].signal
    sda = caps["sda"].signal
    return scl, sda, check_transfer(scl, sda, fast_mode=v.fast_mode)


def assert_decode(report, tag):
    assert report.address == ADDRESS and report.read_bit is not None
    assert report.read_bit == 0, f"{tag}: first byte must be the W address"
    assert report.data_bytes == [PTR_BYTE, ADDR_R_BYTE, READ_BYTE], (
        f"{tag}: decoded {report.data_bytes!r}"
    )
    assert report.acks == [True, True, True, False], (
        f"{tag}: ACKs {report.acks!r} (last slot must be the controller NACK)"
    )


def meas(report):
    """Model measurements rounded to 1 ps (timestamps are float sim times;
    the +-1e-11 ns noise is representation, not signal)."""
    return {k: round(val, 3) for k, val in report.measurements.items()}


def sr_keys(report):
    start = sorted(
        (float(k.split("@")[1]), k, val)
        for k, val in meas(report).items() if k.startswith("t_HD;STA@")
    )
    sta = sorted(
        (float(k.split("@")[1]), k, val)
        for k, val in meas(report).items() if k.startswith("t_SU;STA@")
    )
    assert len(start) == 2 and len(sta) == 1, report.measurements
    return start, sta[0][2]


def intervals(signal):
    ts = [t for (t, _v) in signal.transitions]
    return [round(b - a, 3) for a, b in zip(ts, ts[1:])]


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_sr_images_fresh(dut):
    """Committed images/reports match the committed sources, the sources
    match the generator, the lint warnings are exactly the sanctioned ones,
    every `.cyclesec` states the budget this bench grades, and every
    program fits the 256-word program store."""
    for v in VARIANTS:
        text = (REPO_ROOT / v.src).read_text(encoding="utf-8")
        name, regenerated, sites = gen_i2c_sr.build(v.mode, v.poll)
        assert name == v.name and regenerated == text, f"{v.name}: gen drift"
        program = asm.assemble_file(REPO_ROOT / v.src)
        drift = asm.check_against(program, REPO_ROOT / v.hex.parent)
        assert not drift, f"{v.name}: build artifacts drifted: {drift}"
        if v.poll:
            assert len(program.warnings) == sites == 10
            assert all(" BZ " in w for w in program.warnings), program.warnings
        else:
            assert program.warnings == [], program.warnings
        got = {s.name: s.cycles for s in program.sections}
        assert got == v.expected_sections(), (
            f"{v.name}: sections {got} vs {v.expected_sections()}"
        )
        assert len(program.instructions) <= 256
        dut._log.info(
            f"{v.name}: {len(program.instructions)}/256 words, "
            f"{len(got)} sections at budget, {len(program.warnings)} "
            f"sanctioned warning(s)"
        )


@cocotb.test()
async def test_sr_exact_programs_pass_model_with_negative_controls(dut):
    """EXACT programs, both grades: write -> Sr -> read passes the
    independent model with every Table 10 minimum met in exact cycles; the
    core's received byte is on uo_out; and three controls fail."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    for v in EXACT:
        caps, uo = await run_words(dut, committed_words(v), v.run_cycles(),
                                   tag=v.name)
        scl, sda, report = grade(caps, v)
        dut._log.info(f"{v.name}: {report} measurements={report.measurements}")
        assert report.ok, f"{v.name}: {report}"
        assert_decode(report, v.name)
        assert report.stretched_clocks == 0
        assert uo == READ_BYTE, f"{v.name}: uo_out 0x{uo:02x}"
        m = meas(report)
        hd, su_sta = sr_keys(report)
        assert m["t_LOW(min)"] == v.L * CLK_PERIOD_NS
        assert m["t_HIGH(min)"] == v.H * CLK_PERIOD_NS
        assert [h[2] for h in hd] == [v.HD * CLK_PERIOD_NS] * 2, hd
        assert su_sta == v.SUSTA * CLK_PERIOD_NS
        assert su_sta == minimum_ns("t_SU;STA", v.fast_mode), (
            "t_SU;STA must sit exactly at the Table 10 minimum"
        )
        assert m["t_SU;STO"] == v.SUSTO * CLK_PERIOD_NS
        assert v.L * CLK_PERIOD_NS >= minimum_ns("t_LOW", v.fast_mode)
        assert v.H * CLK_PERIOD_NS >= minimum_ns("t_HIGH", v.fast_mode)
        # the complete clock: measured fall to fall, never an average. The
        # EXACT programs' shortest clock is exactly L + H, and meets f_SCL.
        assert m["t_SCL(min)"] == (v.L + v.H) * CLK_PERIOD_NS
        assert m["t_SCL(min)"] >= minimum_period_ns(v.fast_mode)
        if not v.fast_mode:
            assert v.L + v.H >= 500, "Standard clock under 500 cycles"

        # control: uniform compression of the DUT's own waveform
        sq = check_transfer(
            scale_signal(scl, NEGATIVE_CONTROL_SCALE),
            scale_signal(sda, NEGATIVE_CONTROL_SCALE),
            fast_mode=v.fast_mode,
        )
        assert not sq.ok and any(x.startswith("t_LOW") for x in sq.violations)
        assert any(x.startswith("t_SCL period") for x in sq.violations), (
            "the compression must also break the f_SCL period bound"
        )
        assert any(x.startswith("t_SU;STA") for x in sq.violations), (
            "the compression must also break the exactly-floored t_SU;STA"
        )

        # control: shortened repeated-START setup in the FIRMWARE
        text = (REPO_ROOT / v.src).read_text(encoding="utf-8")
        for remove in (1, v.SUSTA // 2):
            mutant = asm.assemble_text(mutate_sr_wait(text, remove), "mutant")
            caps_m, _ = await run_words(dut, mutant.words, v.run_cycles())
            _s, _d, rep_m = grade(caps_m, v)
            dut._log.info(f"{v.name} SUSTA-{remove}: {rep_m}")
            assert not rep_m.ok, (
                f"NEGATIVE CONTROL FAILED TO FAIL: {v.name} t_SU;STA "
                f"-{remove} cycle(s) passed the model"
            )
            assert len(rep_m.violations) == 1 and rep_m.violations[
                0
            ].startswith("t_SU;STA"), rep_m.violations
            assert_decode(rep_m, f"{v.name} mutant")
            _hd, su_m = sr_keys(rep_m)
            assert su_m == (v.SUSTA - remove) * CLK_PERIOD_NS, su_m


@cocotb.test()
async def test_sr_poll_programs_stretch(dut):
    """Poll programs, both grades: unstretched they are exact (rise phases
    at budget+2) and pass; with the peripheral stretching SCL at three
    points they still pass the model, decode identically, hold every
    minimum after each stretch, and differ from the unstretched run ONLY in
    the SCL intervals touching a stretch. The EXACT program, given the same
    stretches, does not survive."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    for v in POLL:
        caps_u, uo_u = await run_words(dut, committed_words(v), v.run_cycles())
        scl_u, sda_u, rep_u = grade(caps_u, v)
        assert rep_u.ok, f"{v.name} unstretched: {rep_u}"
        assert_decode(rep_u, v.name)
        assert rep_u.stretched_clocks == 0 and uo_u == READ_BYTE
        dut._log.info(
            f"{v.name} unstretched: {rep_u} {meas(rep_u)} uo_out=0x{uo_u:02x}"
        )
        mu = meas(rep_u)
        hd_u, sta_u = sr_keys(rep_u)
        assert mu["t_LOW(min)"] == v.L * CLK_PERIOD_NS
        assert mu["t_HIGH(min)"] == (v.H + v.extra) * CLK_PERIOD_NS
        assert mu["t_SCL(min)"] == (v.L + v.H + v.extra) * CLK_PERIOD_NS
        assert mu["t_SCL(min)"] >= minimum_period_ns(v.fast_mode)
        assert sta_u == (v.SUSTA + v.extra) * CLK_PERIOD_NS
        assert mu["t_SU;STO"] == (v.SUSTO + v.extra) * CLK_PERIOD_NS
        assert [h[2] for h in hd_u] == [v.HD * CLK_PERIOD_NS] * 2

        st = v.stretches()
        caps_s, uo_s = await run_words(
            dut, committed_words(v), v.run_cycles(st), stretches=st
        )
        scl_s, sda_s, rep_s = grade(caps_s, v)
        dut._log.info(f"{v.name} stretched: {rep_s} {rep_s.measurements}")
        assert rep_s.ok, f"{v.name} stretched: {rep_s}"
        assert_decode(rep_s, f"{v.name} stretched")
        assert uo_s == READ_BYTE, f"{v.name}: uo_out 0x{uo_s:02x}"
        assert rep_s.stretched_clocks == 1, (
            "exactly the read clock stretched past 2 x t_LOW is a data clock"
        )
        ms = meas(rep_s)
        _hd_s, sta_s = sr_keys(rep_s)
        slack = 3 * CLK_PERIOD_NS  # one poll pass (IN, AND, BZ)
        assert ms["t_LOW(min)"] == v.L * CLK_PERIOD_NS
        assert ms["t_HIGH(min)"] >= v.H * CLK_PERIOD_NS
        # stretched clocks are at least as long as the unstretched period
        assert ms["t_SCL(min)"] >= (v.L + v.H) * CLK_PERIOD_NS
        assert ms["t_SCL(min)"] >= minimum_period_ns(v.fast_mode)
        assert v.SUSTA * CLK_PERIOD_NS <= sta_s <= (v.SUSTA * CLK_PERIOD_NS
                                                    + slack)
        assert v.SUSTO * CLK_PERIOD_NS <= ms["t_SU;STO"] <= (
            v.SUSTO * CLK_PERIOD_NS + slack)

        # determinism excluding stretched intervals, mechanically
        iu, is_ = intervals(scl_u), intervals(scl_s)
        assert len(iu) == len(is_)
        # interval i runs transition i -> i+1; even i start with a fall
        # (low interval) after the START's first fall is accounted for
        first = scl_s.transitions[0][1]
        stretched_lows = [
            i for i, d in enumerate(is_)
            if scl_s.transitions[i][1] == 0 and d > (v.L + 10) * CLK_PERIOD_NS
        ]
        assert len(stretched_lows) == 3, (first, stretched_lows)
        allowed = {j for i in stretched_lows for j in (i, i + 1)}
        differing = [i for i, (a, b) in enumerate(zip(iu, is_)) if a != b]
        assert set(differing) <= allowed and len(differing) >= 3, (
            differing, sorted(allowed)
        )
        dut._log.info(
            f"{v.name}: stretched lows "
            f"{[round(is_[i] / CLK_PERIOD_NS) for i in stretched_lows]} cy; "
            f"{len(iu) - len(differing)} of {len(iu)} SCL intervals "
            "identical to the unstretched run"
        )

        # control: the EXACT sibling cannot survive the same stretches
        ex = Variant(v.mode, False)
        caps_x, _ = await run_words(
            dut, committed_words(ex), ex.run_cycles(st), stretches=st
        )
        try:
            _a, _b, rep_x = grade(caps_x, ex)
            survived = rep_x.ok and rep_x.data_bytes == [
                PTR_BYTE, ADDR_R_BYTE, READ_BYTE] and rep_x.acks == [
                True, True, True, False]
            detail = repr(rep_x)
        except ValueError as exc:
            survived, detail = False, f"model rejected the waveform: {exc}"
        dut._log.info(f"{ex.name} under stretch: {detail}")
        assert not survived, (
            "NEGATIVE CONTROL FAILED TO FAIL: the non-polling program "
            f"survived the stretches: {detail}"
        )


@cocotb.test()
async def test_sr_uio_od_left_at_reset_cannot_drive_the_bus(dut):
    """Negative control for the pad path (issue #136), all four images:
    with `WCTL UIO_OD` replaced by a reserved no-op of the same length no
    pad is ever enabled, SCL and SDA never leave the pulled-up level, the
    peripheral is never clocked, the model finds no transfer, and the
    byte the "read" leaves on `uo_out` is 0xFF -- eight samples of a
    released line, not the peripheral's 0xB4."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    for v in VARIANTS:
        tag = f"{v.name} with UIO_OD at reset"
        caps, uo, pads = await run_on_pads(
            dut, tag, without_uio_od(committed_words(v)), v.run_cycles(),
            ACK_FALLS, READ_FALLS, {}, expect_open_drain=False,
        )
        pads.assert_no_contention()
        assert pads.oe_unknown == 0
        assert pads.oe_seen == 0, (
            f"NEGATIVE CONTROL FAILED TO FAIL ({tag}): pads "
            f"0x{pads.oe_seen:02x} enabled without a UIO_OD write"
        )
        for line in ("scl", "sda"):
            sig = caps[line].signal
            assert sig.initial == 1 and not sig.transitions, (
                f"NEGATIVE CONTROL FAILED TO FAIL ({tag}): the {line} line moved"
            )
        assert pads.ext[SDA_BIT] is None and pads.ext[SCL_BIT] is None, (
            f"{tag}: the peripheral drove a line though SCL never fell"
        )
        assert caps["ctl_scl"].signal.transitions, (
            f"{tag}: the mutation must leave the controller's OUTs intact"
        )
        try:
            _scl, _sda, report = grade(caps, v)
            found, detail = True, repr(report)
        except ValueError as exc:
            found, detail = False, f"model rejected the lines: {exc}"
        assert not found, (
            f"NEGATIVE CONTROL FAILED TO FAIL ({tag}): the model found a "
            f"transfer on lines that never moved: {detail}"
        )
        assert uo != READ_BYTE and uo == 0xFF, (
            f"{tag}: uo_out 0x{uo:02x}; a controller that cannot clock the "
            "bus must read the released line (0xFF), not the peripheral"
        )
        dut._log.info(f"negative control ({tag}): {detail}; uo_out=0x{uo:02x}")


@cocotb.test()
async def test_sr_model_nominal_repeated_start_passes(dut):
    """Calibration of the grader: the model's own nominal Sr transfer
    passes in both grades, and measures t_SU;STA above the minimum."""
    for fast in (True, False):
        scl, sda = Signal(1, name="nom-scl"), Signal(1, name="nom-sda")
        encode_transfer(
            ADDRESS, False, [PTR_BYTE, READ_BYTE], [True, False], fast, scl,
            sda, repeated_start_after_byte=0,
        )
        report = check_transfer(scl, sda, fast_mode=fast)
        assert report.ok, report
        _hd, sta = sr_keys(report)
        assert sta >= minimum_ns("t_SU;STA", fast)
        dut._log.info(f"model nominal Sr (fast={fast}): {report}")
