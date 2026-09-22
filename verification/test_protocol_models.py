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
