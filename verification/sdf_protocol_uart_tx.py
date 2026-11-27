"""Post-layout entry point for the UART TX firmware bench (issue #217),
plus the time-unit bit-period / per-frame-drift measurement (issue #531,
characterization row 10).

Runs `test_firmware_uart.py`'s tests, byte-unchanged, with the routed-delay
alignment of `sdf_protocol_alignment` (see that module for what is patched
and why). Named only by `flow/run-post-layout-sdf.sh --suite protocols`; no
RTL request names it.

Patched when `PE_ALIGN_*` is set: `test_firmware_uart.RisingEdge` (the
capture's edges, to the observe point) and `test_firmware_uart.
capture_pin_bits` (monitored for pin delay). The bench's own timing
negative control -- its captured TX waveform stretched 1.025x must fail
the row-10 drift bound -- runs on the routed capture unchanged.

This wrapper's own test (issue #531) measures what row 10 asks for in the
row's own units: each committed TX image (`firmware/asm/uart_tx*.asm`) is
loaded over the real load-phase pins and executed against the routed
netlist, every actual `uo_out[0]` transition is timestamped in ps at the
pin (`PinDelayMonitor(retain=True)` -- the true post-delay instants, not
the cycle-quantized observe-point samples the bench's captures grade), and
the independent UART model decodes the resulting waveform at the image's
nominal baud. Per frame the measurement reports the mean bit period
(delta-t between the start fall and the frame's last edge, divided by that
edge's bit index) and the last-edge drift as a percentage of one nominal
bit period -- 100*|delta-t - k*T_nom|/T_nom, the same quantity the model's
`check_frame` grades and the same arithmetic the row-10 record quotes.
The 1.025x re-timing control runs on the same timestamped waveform: the
bytes must still decode while the drift bound fails. Everything (units,
timestamps, payload, nominal figures) is filed under `measurements` in the
protocol report so the figures can be recomputed from the saved edges.
"""

import re

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer

import sdf_protocol_alignment as _align
import test_firmware_uart as bench
from firmware_artifacts import parse_hex_image
from reference_models.uart import MAX_FRAME_DRIFT_PCT, UART_FRAME_BITS, UartDecoder, UartFrameError
from reference_models.waveform import Signal
from sdf_tx_edges import tx_level, tx_level_changes
from test_protocol_emulator import load_program

PROTOCOL = "uart_tx"

#: The committed TX images measured in time units (issue #531): stem ->
#: cycles per bit, cross-checked against each committed `.asm`'s
#: `; BIT-PERIOD-CYCLES n` header below. The nominal baud is arithmetic at
#: the run's own clock -- 1e12/(cycles * clock_period_ps) -- and that clock
#: is the SDC period the runner exports (row 4's 20 ns target on the gds
#: runs this flow consumes; `install()` asserts the bench's
#: `CLK_PERIOD_NS` equals it when aligned).
TX_IMAGES = (
    ("uart_tx", 50),
    ("uart_tx_115200", 434),
    ("uart_tx_9600", 5208),
)

#: Every committed TX image transmits these payload bytes, in order (the
#: benches' images; 0x5A's last edge is the bit-9 stop rise, 0xA5's is the
#: bit-8 data edge, so both stop-bit adjacencies are exercised).
TX_PAYLOADS = (0x5A, 0xA5)

#: The reference model's own deterministic negative-control scale, re-run
#: here on the timestamped routed waveform (the bench's control re-runs it
#: on the observe-point capture).
NEGATIVE_CONTROL_SCALE = 1.025

REPORT = _align.install(
    PROTOCOL,
    bench,
    edge_modules=(bench,),
    capture_modules=(bench,),
    capture_source=bench,
    period_modules=(bench,),
)
TESTS = _align.register(bench, globals())

ASM_DIR = bench.REPO_ROOT / "firmware" / "asm"
BUILD_DIR = bench.REPO_ROOT / "firmware" / "build"


def _header_bit_period(stem: str):
    """The committed `.asm`'s own `; BIT-PERIOD-CYCLES n` header, or None
    when the image carries none (`uart_tx.asm` predates the header; its
    50-cycle period is guarded by the bench's committed-report section
    check in `test_committed_image_is_fresh`, which runs in this same
    module). A firmware change that moves the period of a header-carrying
    image fails here rather than silently re-grading the nominal the
    measurement decodes against."""
    text = (ASM_DIR / f"{stem}.asm").read_text(encoding="utf-8")
    match = re.search(r"^; BIT-PERIOD-CYCLES (\d+)$", text, re.M)
    return None if match is None else int(match.group(1))


def _known_intervals(initial, edges):
    """Split at unknown levels. A return to binary starts a new idle reference."""
    line = Signal(initial) if initial in (0, 1) else None
    for t_ps, level in edges:
        if level not in (0, 1):
            if line is not None:
                yield line, t_ps
            line = None
        elif line is None:
            line = Signal(level)
        else:
            line.add(t_ps / 1000.0, level)
    if line is not None:
        yield line, None


def _decode_capture(decoder, initial, edges, scale=1.0):
    """Collect each decodable frame and keep framing errors in capture order."""
    reports = []
    errors = []
    for line, end_ps in _known_intervals(initial, edges):
        if scale != 1.0:
            line.transitions = [(t * scale, v) for t, v in line.transitions]
        cursor = 0.0
        while True:
            try:
                decoded = decoder.decode(line, t_from=cursor, max_frames=1)
            except UartFrameError as exc:
                errors.append(str(exc))
                # Use the same start search and stop sample as decode(). The
                # next falling edge after that sample can start a new frame.
                failed_start = decoder._next_start(line, cursor)
                cursor = failed_start + (UART_FRAME_BITS - 0.5) * decoder.period
                continue
            if not decoded:
                break
            frame, = decoded
            if end_ps is not None and frame.pitch_ns is None:
                # The known interval is half-open. An X exactly one frame
                # after the start leaves the whole frame observed. Compare
                # durations from the original integer-ps timestamps.
                start_ps = round(frame.t_start * 1000 / scale)
                frame_ps = UART_FRAME_BITS * round(decoder.period * 1000)
                if (end_ps - start_ps) * scale < frame_ps:
                    break
            reports.append(frame)
            if frame.pitch_ns is None:
                break
            cursor = frame.t_start + (UART_FRAME_BITS - 0.5) * decoder.period
    return reports, errors


def _measure_image(stem, cycles_per_bit, clock_period_ps, tx_initial, tx_edges, log) -> dict:
    """Decode one image's timestamped TX waveform with the independent
    model at the image's nominal baud and build the measurement doc.

    `tx_edges` is the ordered list of `(t_ps, level)` changes of
    `uo_out[0]` as the monitor timestamped them at the pin;
    `tx_initial` is the settled level the pin carried before the first of
    them (the decoder's idle reference).
    """
    nominal_bit_period_ps = cycles_per_bit * clock_period_ps
    nominal_baud = 1e12 / nominal_bit_period_ps
    decoder = UartDecoder(nominal_baud)
    failures = []
    if tx_initial not in (0, 1):
        failures.append(f"initial TX level is {tx_initial}")
    if not tx_edges:
        failures.append("no TX level change observed at the pin")
    for t_ps, level in tx_edges:
        if level not in (0, 1):
            failures.append(f"TX level is {level} at {t_ps} ps")

    reports, errors = _decode_capture(decoder, tx_initial, tx_edges)
    failures.extend(f"original waveform decode: {error}" for error in errors)
    decoded_hex = [f"0x{r.data:02x}" for r in reports]
    expected_hex = [f"0x{payload:02x}" for payload in TX_PAYLOADS]
    if decoded_hex != expected_hex:
        failures.append(f"decoder recovered {decoded_hex}, the committed program transmits {expected_hex}")
    frames = []
    for report in reports:
        payload = report.data
        if not report.stop_ok:
            failures.append(f"0x{payload:02x}: framing error, stop bit sampled 0")
        # An over-limit frame is *recorded* (`within_bound`) and the bound is
        # asserted by the test only after every image's measurement is filed,
        # so the excursion's timestamps survive the failure (#531 test plan).
        t_start_ps = round(report.t_start * 1000.0)
        # A fall after the high stop sample belongs to the next start bit.
        stop_sample_ps = t_start_ps + (UART_FRAME_BITS - 0.5) * nominal_bit_period_ps
        edges_ps = [t for t, _level in tx_edges if t_start_ps <= t <= stop_sample_ps]
        if not (edges_ps and edges_ps[0] == t_start_ps):
            failures.append(f"0x{payload:02x}: no TX edge list found around the model's start at {t_start_ps} ps")
            continue
        last_edge_ps = edges_ps[-1]
        # The last edge's bit index on the nominal grid -- the model's own
        # placement (`_measure_drift`), cross-checked against the framing
        # convention's arithmetic (the bench's `expected_edge_offsets`).
        last_edge_bit_index = round((last_edge_ps - t_start_ps) / nominal_bit_period_ps)
        if last_edge_bit_index != bench.expected_edge_offsets(payload)[-1]:
            failures.append(
                f"0x{payload:02x}: last edge at bit {last_edge_bit_index}, the 8N1 "
                f"framing convention puts the last edge at bit "
                f"{bench.expected_edge_offsets(payload)[-1]}"
            )
            continue
        delta_t_ps = last_edge_ps - t_start_ps
        drift_ps = delta_t_ps - last_edge_bit_index * nominal_bit_period_ps
        drift_pct = 100.0 * abs(drift_ps) / nominal_bit_period_ps
        if abs(drift_pct - report.drift_pct) >= 1e-6:
            failures.append(
                f"0x{payload:02x}: arithmetic drift {drift_pct:.6f}% disagrees with "
                f"the model's {report.drift_pct:.6f}%"
            )
        # The decoder measures in floating-point ns. Its independent pitch
        # error and the pin residual both lie on the capture's integer-ps grid.
        pitch_error_ps = round((report.pitch_drift_pct or 0.0) * nominal_bit_period_ps / 100)
        max_error_ps = max(abs(drift_ps), pitch_error_ps)
        within_bound = report.stop_ok and 100 * max_error_ps <= MAX_FRAME_DRIFT_PCT * nominal_bit_period_ps
        mean_bit_period_ps = delta_t_ps / last_edge_bit_index
        frames.append({
            "payload_hex": f"0x{payload:02x}",
            "decoded_hex": f"0x{report.data:02x}",
            "stop_ok": bool(report.stop_ok),
            "t_start_ps": t_start_ps,
            "edges_ps": edges_ps,
            "last_edge_bit_index": last_edge_bit_index,
            "last_edge_ps": last_edge_ps,
            "delta_t_ps": delta_t_ps,
            "mean_bit_period_ps": mean_bit_period_ps,
            "mean_baud": 1e12 / mean_bit_period_ps,
            "drift_ps": drift_ps,
            "drift_pct": drift_pct,
            "model_drift_pct": report.drift_pct,
            "pitch_error_ps": None if report.pitch_ns is None else pitch_error_ps,
            "within_bound": within_bound,
        })
        log(
            f"{stem} 0x{payload:02x}: start {t_start_ps} ps, last edge {last_edge_ps} ps "
            f"(bit {last_edge_bit_index}), mean bit period {mean_bit_period_ps:.3f} ps "
            f"({1e12 / mean_bit_period_ps:.1f} baud), drift {drift_pct:.4f}% of bit"
        )

    stretched_reports, errors = _decode_capture(decoder, tx_initial, tx_edges, NEGATIVE_CONTROL_SCALE)
    control = {"scale": NEGATIVE_CONTROL_SCALE}
    if errors:
        control["framing_error"] = "; ".join(errors)
    control.update({
        "decoded": [f"0x{r.data:02x}" for r in stretched_reports],
        "drift_pct": [r.drift_pct for r in stretched_reports],
        "all_failed_check_frame": not errors and bool(stretched_reports) and all(
            not decoder.check_frame(r) for r in stretched_reports
        ),
    })
    return {
        "image": stem,
        "cycles_per_bit": cycles_per_bit,
        "nominal_bit_period_ps": nominal_bit_period_ps,
        "nominal_baud": nominal_baud,
        "pin": "uo_out[0]",
        "tx_initial": tx_initial,
        "tx_edge_levels": [level for _, level in tx_edges],
        "tx_edges_ps": [t for (t, _level) in tx_edges],
        "frames": frames,
        "failures": failures,
        "negative_control": control,
    }


@cocotb.test()
async def test_uart_tx_bit_period_and_drift_in_time_units(dut):
    """Issue #531 (characterization row 10): every committed TX image's
    bit period and per-frame last-edge drift measured in **time units**
    from the SDF-annotated routed simulation -- the true pin-transition
    timestamps, decoded and graded by the independent UART model at each
    image's nominal baud, with the 1.025x re-timing control proving the
    timestamped path can fail. The drift percentage is normalized to the
    nominal bit period, so it carries no clock-rate assumption; the
    absolute periods are in ps at the run's own (SDC) clock."""
    cocotb.start_soon(Clock(dut.clk, bench.CLK_PERIOD_NS, unit="ns").start())
    if _align.ALIGNMENT is not None:
        clock_period_ps = _align.ALIGNMENT[0]  # install() asserted == bench CLK_PERIOD_NS
        observe = _align.observe_offset_ps(_align.ALIGNMENT)
        sample = _align.ALIGNMENT[2]
    else:
        clock_period_ps = round(bench.CLK_PERIOD_NS * 1000)
        observe = sample = None  # retention only: no observe point exists unaligned

    images = []
    measurement = {
        "units": {
            "time": "ps (simulation time at the run's SDC clock)",
            "drift": "percent of one nominal bit period",
            "mean_bit_period": "ps per bit (delta-t / last-edge bit index)",
        },
        "clock_period_ps": clock_period_ps,
        "aligned": _align.ALIGNMENT is not None,
        "pin": "uo_out[0]",
        "images": images,
    }
    for stem, cycles_per_bit in TX_IMAGES:
        header = _header_bit_period(stem)
        if header is not None:
            assert header == cycles_per_bit, (
                f"{stem}: .asm header says {header} cycles/bit, "
                f"this measurement names {cycles_per_bit}"
            )
        else:
            assert cycles_per_bit == bench.BIT_PERIOD_CYCLES, (
                f"{stem}: no .asm header; this measurement's {cycles_per_bit} must be "
                f"the bench's own {bench.BIT_PERIOD_CYCLES}-cycle period, whose committed-"
                "report section check runs in this module's freshness test"
            )
        words = parse_hex_image(BUILD_DIR / f"{stem}.hex")
        assert len(words) <= 256, f"{stem}: exceeds DR 0001's 256-word memory"
        await load_program(dut, words)
        # Settle-read the TX level before watching (the same read
        # discipline `capture_pin_bits` uses for its cycle-0 sample): a
        # raw read right after `load_program` returns can catch the
        # MODE-drop timestep before its nonblocking assignments settle,
        # which would timestamp a phantom pre-settle "transition" no clk
        # edge accounts for.
        await ReadOnly()
        tx_initial = tx_level(str(dut.uo_out.value))
        await Timer(1, unit="ns")  # leave the read-only region
        # The benches' own run-length arithmetic for these images
        # (`test_firmware_uart_rx.run_tx_program`): header + two frames +
        # tail margin, in bit periods.
        run_cycles = (2 + 2 * (UART_FRAME_BITS + 2) + 3) * cycles_per_bit
        monitor = _align.PinDelayMonitor(dut, observe, sample, retain=True).start()
        try:
            for _ in range(run_cycles):
                await RisingEdge(dut.clk)
        finally:
            monitor.stop()
        # The capture (violations included) is filed before anything can fail;
        # the pin-contract violation is asserted after the report is written.
        REPORT.add_capture(run_cycles, monitor)
        # Bit-0 *changes* only: one list feeds both the decoder and the
        # published edge list, so a non-TX `uo_out` event cannot skew either.
        tx_edges = tx_level_changes(monitor.transitions, tx_initial)
        image = _measure_image(stem, cycles_per_bit, clock_period_ps, tx_initial, tx_edges, dut._log.info)
        image["pin_contract_violations"] = {
            "count": len(monitor.violations),
            "listed": [str(v) for v in monitor.violations[:3]],
        }
        images.append(image)
        REPORT.add_measurement("uart_tx_drift", measurement)

    for image in images:
        stem = image["image"]
        assert not image["pin_contract_violations"]["count"], (
            f"{stem}: {image['pin_contract_violations']['count']} output transition(s) violated "
            f"the pin contract: {image['pin_contract_violations']['listed']}; the capture and "
            "measurement are recorded in the protocol report"
        )
        assert not image["failures"], (
            f"{stem}: {image['failures']}; the measurement is recorded in the protocol report"
        )
        for frame in image["frames"]:
            assert frame["within_bound"], (
                f"{image['image']} {frame['payload_hex']}: row-10 drift bound failed: "
                f"last edge {frame['drift_pct']:.4f}%, pitch error (ps) {frame['pitch_error_ps']} "
                f"(bound {MAX_FRAME_DRIFT_PCT:g}% of the bit period); the measurement "
                "is recorded in the protocol report"
            )
        control = image["negative_control"]
        assert "framing_error" not in control, (
            f"{image['image']}: the {control['scale']}x control raised {control['framing_error']}"
        )
        assert control["decoded"] == [f"0x{payload:02x}" for payload in TX_PAYLOADS], (
            f"{image['image']}: the {control['scale']}x control decoded {control['decoded']}"
        )
        assert control["all_failed_check_frame"], (
            f"{image['image']}: expected every {control['scale']}x control frame to fail "
            f"the drift check, measured {control['drift_pct']}% of one bit"
        )
