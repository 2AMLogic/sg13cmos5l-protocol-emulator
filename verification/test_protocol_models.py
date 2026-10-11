"""Constrained-random reference-model validation suite (issue #25,
verification-plan.md section 4; target-spec rows 1, 10, 11, 12).

What this bench is -- and is not
--------------------------------

This bench validates the **reference models themselves**: the independent
UART/SPI/I2C waveform judges that verification-plan section 4 requires.
Each test generates constrained-random legal traffic with a **recorded
seed** (``RECORDED_SEED`` below, mirrored into
``request-protocol-models.json``'s ``random_seed`` so the run is citable
and byte-reproducible), judges it with the model, and asserts the model
agrees with the generating intent.  The deterministic **negative
controls** assert the models *flag* deliberately corrupted waveforms --
a suite that cannot fail cannot cite its passes (the issue's own words).

What this bench is **not**: a claim about any RTL.  The DUT-facing half of
section 4 -- the core running committed firmware, observed through these
same models -- starts once issues #18 (core datapath) and #22/#23
(firmware) land; the cocotb toplevel here is the declared fixture
``duts/model_validation_top.v``, which the bench never touches.  Every
result recorded from this suite is model-validation evidence only.

Seed discipline: one ``random.Random(RECORDED_SEED)`` per protocol drives
both case generation and jitter, so the whole run is a pure function of
this file's ``RECORDED_SEED``.
"""

import json
import random
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

import reference_models.spi as spi_model
import reference_models.stimulus as stimulus
import reference_models.uart as uart_model
from reference_models.i2c import check_transfer
from reference_models.waveform import Signal

#: The recorded seed.  Changing it changes every random case; any evidence
#: record citing this suite names this value, and the request JSON mirrors
#: it so the klt report carries it too.
RECORDED_SEED = 20260922

#: Draft core clock for the SPI ceiling check (target-spec row 4's target;
#: the ceiling itself, SCLK <= f_clk/4, is what row 11 binds -- the f_clk
#: value is an input to the check, not a claim that 50 MHz is closed).
F_CLK_HZ = 50e6

#: Rounds of constrained-random traffic per protocol.  Bounded so the
#: whole suite stays seconds-scale while still sweeping the constrained
#: dimensions (64 rounds x the generators' ranges).
ROUNDS = 64

_REQUEST = Path(__file__).with_name("request-protocol-models.json")


async def _tick():
    """Yield once to the scheduler so each test is a real coroutine."""
    await Timer(1, units="ns")


@cocotb.test()
async def test_recorded_seed_matches_request(dut):
    """The seed is recorded in the request document, not just in source.

    A passing run is only citable if the seed that produced it is on the
    record (the issue's acceptance criterion); this test mechanically ties
    ``RECORDED_SEED`` to the ``random_seed`` the klt report carries.
    """
    request = json.loads(_REQUEST.read_text())
    assert request["options"]["random_seed"] == RECORDED_SEED, (
        f"request random_seed {request['options']['random_seed']} does not "
        f"match the bench's RECORDED_SEED {RECORDED_SEED}"
    )
    await _tick()


@cocotb.test()
async def test_uart_random_legal_frames_round_trip_and_stay_in_budget(dut):
    """Random 8N1 frames at random legal bauds decode correctly, and their
    measured cumulative per-frame drift stays inside row 10's ~2% bound,
    at every baud in the ratified 9,600-1,000,000 range."""
    rng = random.Random(RECORDED_SEED)
    seen_bauds = set()
    for _ in range(ROUNDS):
        case = stimulus.random_uart_case(rng)
        seen_bauds.add(case.baud)
        line, _amplitude = stimulus.build_uart_waveform(case, rng)
        decoder = uart_model.UartDecoder(case.baud)
        reports = decoder.decode(line)
        assert len(reports) == 1, f"expected 1 frame, decoded {len(reports)}"
        report = reports[0]
        assert report.data == case.data, (
            f"round-trip mismatch: sent 0x{case.data:02x}, "
            f"decoded 0x{report.data:02x} at {case.baud} baud"
        )
        assert decoder.check_frame(report), (
            f"legal frame flagged: {report} (jitter {case.jitter_fraction:.4f})"
        )
    ladder = set(stimulus.UART_BAUD_LADDER)
    assert seen_bauds == ladder, f"rounds did not cover the baud ladder: {seen_bauds}"
    await _tick()


@cocotb.test()
async def test_uart_negative_control_flags_drift_over_bound(dut):
    """A frame clocked 2.5% slow must be flagged by the drift measurement
    (deterministic waveform -- fires the same way every run)."""
    line = stimulus.uart_negative_drift_case()
    decoder = uart_model.UartDecoder(115200)
    reports = decoder.decode(line)
    assert len(reports) == 1
    report = reports[0]
    assert not decoder.check_frame(report), (
        f"2.5%-slow frame passed the 2% bound: {report}"
    )
    assert report.drift_pct > uart_model.MAX_FRAME_DRIFT_PCT
    await _tick()


def _encode_late_mistimed_frame(data, baud, line, t0=0.0, later_scale=1.03):
    """One 8N1 frame whose start bit and first data bit are nominal and
    whose remaining eight bit periods (data bits 1-7 and the stop bit) are
    ``later_scale`` x nominal; returns the end of the stop bit.

    Issue #97's blind case: for payload 0xFF the only in-frame edge after
    the start fall is the rise at bit 1, so the in-frame last-edge drift
    reads 0 whatever ``later_scale`` is.  Only the frame's length -- the
    pitch to a following start -- carries the error.  Kept in this bench
    (not ``stimulus.py``, which the SPI and I2C evidence also hashes).
    """
    period = uart_model.bit_period_ns(baud)
    t = float(t0)
    line.add(t, 0)
    t += period
    line.add(t, data & 1)
    t += period
    for i in range(1, uart_model.UART_DATA_BITS):
        line.add(t, (data >> i) & 1)
        t += period * later_scale
    line.add(t, 1)
    return t + period * later_scale


@cocotb.test()
async def test_uart_frame_pitch_grades_back_to_back_0xff(dut):
    """Issue #97: 0xFF frames have no in-frame edge past bit 1, so the
    last-edge drift is blind to their later bit periods.  The frame pitch
    (start-to-start spacing to the following frame) is what sees them.

    Deterministic waveforms at 115,200 baud; "3 %" is 3 % of a bit period
    on the second start edge, 1.5x the row-10 bound."""
    baud = 115200
    period = uart_model.bit_period_ns(baud)
    bound = uart_model.MAX_FRAME_DRIFT_PCT

    def pair(second_offset_bits):
        line = Signal(1, name="uart_pair")
        end = uart_model.encode_frame(0xFF, baud, line, t0=period)
        uart_model.encode_frame(
            0xFF, baud, line, t0=end + second_offset_bits * period
        )
        return line

    # Nominal back-to-back pair: decoded as two frames, pitch 0, passes
    # in both decoder modes.
    for back_to_back in (False, True):
        decoder = uart_model.UartDecoder(baud, back_to_back=back_to_back)
        reports = decoder.decode(pair(0.0))
        assert [r.data for r in reports] == [0xFF, 0xFF], reports
        assert reports[0].pitch_drift_pct < 1e-6, reports[0]
        assert reports[1].pitch_ns is None, reports[1]
        assert all(decoder.check_frame(r) for r in reports), reports

    # Second start 3 % of a bit EARLY: reported (not skipped as before
    # #97) and failed on pitch in the default mode -- a short stop bit is
    # a violation on any line.
    decoder = uart_model.UartDecoder(baud)
    reports = decoder.decode(pair(-0.03))
    assert len(reports) == 2, f"early following start skipped: {reports}"
    assert abs(reports[0].pitch_drift_pct - 3.0) < 1e-6, reports[0]
    assert not decoder.check_frame(reports[0]), reports[0]

    # Second start 3 % of a bit LATE: the case the last-edge measurement
    # never saw (the edge is outside the frame window).  Failed on a
    # declared back-to-back stream; accepted as idle otherwise.
    line = pair(0.03)
    strict = uart_model.UartDecoder(baud, back_to_back=True)
    reports = strict.decode(line)
    assert reports[0].drift_pct == 0.0, reports[0]
    assert abs(reports[0].pitch_drift_pct - 3.0) < 1e-6, reports[0]
    assert not strict.check_frame(reports[0]), reports[0]
    lenient = uart_model.UartDecoder(baud)
    assert lenient.check_frame(lenient.decode(line)[0]), "late start != idle"

    # The realistic blind case: nominal start and bit 1, the other eight
    # bit periods 3 % slow / fast, followed back to back by a second 0xFF.
    # Last-edge drift reads 0 on the slow frame; pitch shows 8 x 3 % = 24 %.
    for scale, back_to_back in ((1.03, True), (0.97, False)):
        line = Signal(1, name="uart_stream")
        end = _encode_late_mistimed_frame(
            0xFF, baud, line, t0=period, later_scale=scale
        )
        uart_model.encode_frame(0xFF, baud, line, t0=end)
        decoder = uart_model.UartDecoder(baud, back_to_back=back_to_back)
        reports = decoder.decode(line)
        assert [r.data for r in reports] == [0xFF, 0xFF], reports
        assert abs(reports[0].pitch_drift_pct - 24.0) < 1e-6, reports[0]
        assert reports[0].pitch_drift_pct > bound
        assert not decoder.check_frame(reports[0]), (
            f"{scale}x later bits passed: {reports[0]}"
        )
        if scale > 1:
            assert reports[0].drift_pct == 0.0, (
                f"expected the last-edge measurement to be blind: {reports[0]}"
            )
    await _tick()


@cocotb.test()
async def test_uart_isolated_0xff_frame_is_documented_unobservable(dut):
    """The documented limitation (issue #97, model docstring): an isolated
    0xFF frame with a nominal start and first data bit has no edge after
    bit 1, so later mistiming is invisible to any measurement of that frame.
    This asserts the documented behaviour, so a change to it is noticed."""
    baud = 115200
    period = uart_model.bit_period_ns(baud)
    for scale in (0.97, 1.03):
        for back_to_back in (False, True):
            line = Signal(1, name="uart_isolated")
            _encode_late_mistimed_frame(
                0xFF, baud, line, t0=period, later_scale=scale
            )
            decoder = uart_model.UartDecoder(baud, back_to_back=back_to_back)
            (report,) = decoder.decode(line)
            assert report.data == 0xFF
            assert report.drift_pct == 0.0, report
            assert report.pitch_ns is None and report.pitch_drift_pct is None
            assert decoder.check_frame(report), (
                "isolated 0xFF frame changed verdict; update the documented "
                f"limitation: {report}"
            )
    await _tick()


@cocotb.test()
async def test_spi_random_legal_traffic_passes_in_all_modes(dut):
    """Random full-duplex bursts in all four modes decode bit-exactly on
    both data lines and satisfy the row-11 SCLK ceiling and CPOL idle
    rules, across the legal divider range."""
    rng = random.Random(RECORDED_SEED)
    seen_modes = set()
    for _ in range(ROUNDS):
        case = stimulus.random_spi_case(rng, F_CLK_HZ)
        seen_modes.add(case.mode.number)
        sclk, mosi, miso, cs = stimulus.build_spi_waveform(case)
        report = spi_model.check_burst(
            sclk, mosi, miso, cs, case.mode, F_CLK_HZ
        )
        assert report.ok, f"legal burst flagged: {report} (mode {case.mode})"
        assert report.mosi_bytes == case.mosi, (
            f"MOSI mismatch in {case.mode}: sent "
            f"{[f'0x{b:02x}' for b in case.mosi]}, decoded "
            f"{[f'0x{b:02x}' for b in report.mosi_bytes]}"
        )
        assert report.miso_bytes == case.miso, (
            f"MISO mismatch in {case.mode}: sent "
            f"{[f'0x{b:02x}' for b in case.miso]}, decoded "
            f"{[f'0x{b:02x}' for b in report.miso_bytes]}"
        )
    assert seen_modes == {0, 1, 2, 3}, f"modes not all covered: {seen_modes}"
    await _tick()


@cocotb.test()
async def test_spi_negative_control_flags_clock_ceiling_violation(dut):
    """A burst clocked at f_clk/3 -- over the row-11 SCLK <= f_clk/4
    ceiling -- must be flagged, with the ceiling named in the violation."""
    sclk, mosi, miso, cs, _mosi_bytes, _miso_bytes = (
        stimulus.spi_negative_ceiling_case(F_CLK_HZ)
    )
    report = spi_model.check_burst(sclk, mosi, miso, cs, spi_model.MODES[0], F_CLK_HZ)
    assert not report.ok, "over-ceiling burst passed"
    assert any("f_clk/4 ceiling" in v for v in report.violations), (
        f"ceiling violation not named: {report.violations}"
    )
    await _tick()


@cocotb.test()
async def test_spi_negative_control_wrong_mode_sampling_mismatches(dut):
    """Mode-0 traffic judged as mode 1 must NOT round-trip: the sample
    edges differ, so the deterministic pattern reads shifted -- the
    checker is mode-sensitive, not a byte echo."""
    sclk, mosi, miso, cs, mosi_bytes, miso_bytes = (
        stimulus.spi_negative_wrong_mode_case()
    )
    report = spi_model.check_burst(sclk, mosi, miso, cs, spi_model.MODES[1], F_CLK_HZ)
    assert report.mosi_bytes != mosi_bytes or report.miso_bytes != miso_bytes, (
        "mode-0 traffic round-tripped under mode-1 sampling rules"
    )
    await _tick()


@cocotb.test()
async def test_i2c_random_legal_traffic_meets_table10_minimums(dut):
    """Random transfers in both modes decode address/RW/data/ACKs
    correctly -- including repeated-START transfers -- and every measured
    t_LOW, t_HIGH, t_HD;STA, t_SU;STA and t_SU;STO meets the UM10204
    Table-10 minimum for the stated mode."""
    rng = random.Random(RECORDED_SEED)
    seen_modes = set()
    saw_repeated_start = False
    for _ in range(ROUNDS):
        case = stimulus.random_i2c_case(rng)
        seen_modes.add(case.fast_mode)
        scl, sda = stimulus.build_i2c_waveform(case)
        report = check_transfer(scl, sda, fast_mode=case.fast_mode)
        assert report.ok, (
            f"legal transfer flagged: {report} (fast={case.fast_mode}, "
            f"stretch={case.stretch_ns}, sr={case.repeated_start_after_byte})"
        )
        saw_repeated_start = saw_repeated_start or (
            case.repeated_start_after_byte is not None
        )
        if case.repeated_start_after_byte is None:
            assert report.address == case.address, (
                f"address mismatch: sent 0x{case.address:02x}, "
                f"decoded 0x{report.address:02x}"
            )
            assert report.read_bit == case.read_bit
            assert report.data_bytes == case.data, (
                f"data mismatch: sent {[f'0x{b:02x}' for b in case.data]}, "
                f"decoded {[f'0x{b:02x}' for b in report.data_bytes]}"
            )
            assert report.acks[1:] == case.acks, (
                f"ACK mismatch: sent {case.acks}, decoded {report.acks}"
            )
    assert seen_modes == {True, False}, f"modes not both covered: {seen_modes}"
    assert saw_repeated_start, "no repeated-START case was generated"
    await _tick()


@cocotb.test()
async def test_i2c_clock_stretching_is_legal_and_reported(dut):
    """Peripheral clock-stretching (UM10204 section 3.1.9) extends SCL low
    without violating Table 10 -- the checker must report the stretched
    clocks and flag nothing."""
    case = stimulus.I2cCase(
        address=0x2A, read_bit=False, data=[0x5A, 0xA5], acks=[True, True],
        fast_mode=False,
        stretch_ns=3.0 * stimulus.i2c.minimum_ns("t_LOW", False),
        stretch_after_byte=0, repeated_start_after_byte=None,
    )
    scl, sda = stimulus.build_i2c_waveform(case)
    report = check_transfer(scl, sda, fast_mode=case.fast_mode)
    assert report.ok, f"stretched transfer flagged: {report}"
    assert report.stretched_clocks >= 1, "stretch not reported"
    assert report.data_bytes == case.data
    await _tick()


@cocotb.test()
async def test_i2c_negative_control_flags_stop_setup_violation(dut):
    """A STOP with t_SU;STO at half the Table-10 minimum must be flagged,
    with t_SU;STO named in the violation."""
    scl, sda = stimulus.i2c_negative_short_stop_case()
    report = check_transfer(scl, sda, fast_mode=False)
    assert not report.ok, "short STOP setup passed"
    assert any(v.startswith("t_SU;STO") for v in report.violations), (
        f"t_SU;STO violation not named: {report.violations}"
    )
    await _tick()


@cocotb.test()
async def test_i2c_negative_control_flags_overspeed_period_only(dut):
    """Issue #125: clocks whose low and high sit exactly AT the Table-10
    minimums (Standard: 4700 + 4000 ns = 235 + 200 cycles at the nominal
    20 ns clock) pass t_LOW and t_HIGH but are over the f_SCL ceiling; the
    independent full-period bound must flag them, and only it. Both grades."""
    for fast_mode, limit in ((False, 10000.0), (True, 2500.0)):
        scl, sda = stimulus.i2c_negative_overspeed_case(fast_mode)
        report = check_transfer(scl, sda, fast_mode=fast_mode)
        assert not report.ok, f"overspeed passed (fast={fast_mode})"
        assert report.data_bytes == [0x5A] and report.address == 0x50
        assert all(v.startswith("t_SCL period") for v in report.violations), (
            f"only the period bound may fire: {report.violations}"
        )
        assert report.measurements["t_LOW(min)"] == stimulus.i2c.minimum_ns(
            "t_LOW", fast_mode
        )
        assert report.measurements["t_HIGH(min)"] == stimulus.i2c.minimum_ns(
            "t_HIGH", fast_mode
        )
        assert report.measurements["t_SCL(min)"] < limit
    await _tick()


@cocotb.test()
async def test_i2c_period_bound_edges_and_stretching(dut):
    """Exactly the f_SCL period passes (Standard 500 cycles = 10000 ns,
    Fast 125 cycles = 2500 ns); one cycle under fails (stretching, being longer, is
    covered by the stretch test above)."""
    for fast_mode, cycles in ((False, 500), (True, 125)):
        for total, want_ok in ((cycles, True), (cycles - 1, False)):
            low = stimulus.i2c.minimum_ns("t_LOW", fast_mode)
            high = total * 20.0 - low
            scl = Signal(1, name="scl")
            sda = Signal(1, name="sda")
            stimulus.i2c.encode_transfer(
                0x50, False, [0x5A], [True], fast_mode, scl, sda,
                clock_low_ns=low, clock_high_ns=high,
            )
            report = check_transfer(scl, sda, fast_mode=fast_mode)
            assert report.ok == want_ok, (fast_mode, total, report)
    await _tick()
