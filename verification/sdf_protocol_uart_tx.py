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
from reference_models.uart import UART_FRAME_BITS, UartDecoder
from reference_models.waveform import Signal
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
#: bit-7 data edge, so both stop-bit adjacencies are exercised).
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


def _tx_bit(value_str: str) -> int:
    """`uo_out`'s bit 0 (the TX pin) from the monitor's retained value
    string (MSB first, so the last character is bit 0)."""
    level = value_str[-1]
    assert level in "01", f"uo_out reads {value_str!r}; the TX measurement needs 0/1 pins"
    return int(level)


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
    line = Signal(tx_initial, name=f"{stem}-tx")
    for t_ps, level in tx_edges:
        line.add(t_ps / 1000.0, level)
    decoder = UartDecoder(nominal_baud)
    reports = decoder.decode(line)
    assert [r.data for r in reports] == list(TX_PAYLOADS), (
        f"{stem}: decoder recovered {[f'0x{r.data:02x}' for r in reports]}, "
        f"the committed program transmits {[f'0x{p:02x}' for p in TX_PAYLOADS]}"
    )
    frames = []
    for report, payload in zip(reports, TX_PAYLOADS):
        assert report.stop_ok, f"{stem}: framing error, stop bit sampled 0"
        assert decoder.check_frame(report), (
            f"{stem}: row-10 drift bound failed at {report.drift_pct:.4f}% of the "
            f"bit period (bound 2%)"
        )
        t_start_ps = round(report.t_start * 1000.0)
        window_ps = UART_FRAME_BITS * nominal_bit_period_ps
        edges_ps = [t for (t, _level) in tx_edges if t_start_ps <= t <= t_start_ps + window_ps]
        assert edges_ps and edges_ps[0] == t_start_ps, (
            f"{stem}: no TX edge list found around the model's start at {t_start_ps} ps"
        )
        last_edge_ps = edges_ps[-1]
        # The last edge's bit index on the nominal grid -- the model's own
        # placement (`_measure_drift`), cross-checked against the framing
        # convention's arithmetic (the bench's `expected_edge_offsets`).
        last_edge_bit_index = round((last_edge_ps - t_start_ps) / nominal_bit_period_ps)
        assert last_edge_bit_index == bench.expected_edge_offsets(payload)[-1], (
            f"{stem} 0x{payload:02x}: last edge at bit {last_edge_bit_index}, the 8N1 "
            f"framing convention puts the last edge at bit "
            f"{bench.expected_edge_offsets(payload)[-1]}"
        )
        delta_t_ps = last_edge_ps - t_start_ps
        drift_ps = delta_t_ps - last_edge_bit_index * nominal_bit_period_ps
        drift_pct = 100.0 * abs(drift_ps) / nominal_bit_period_ps
        assert abs(drift_pct - report.drift_pct) < 1e-6, (
            f"{stem} 0x{payload:02x}: arithmetic drift {drift_pct:.6f}% disagrees with "
            f"the model's {report.drift_pct:.6f}%"
        )
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
        })
        log(
            f"{stem} 0x{payload:02x}: start {t_start_ps} ps, last edge {last_edge_ps} ps "
            f"(bit {last_edge_bit_index}), mean bit period {mean_bit_period_ps:.3f} ps "
            f"({1e12 / mean_bit_period_ps:.1f} baud), drift {drift_pct:.4f}% of bit"
        )

    stretched = Signal(line.initial, name=f"{line.name}*{NEGATIVE_CONTROL_SCALE}")
    stretched.transitions = [(t * NEGATIVE_CONTROL_SCALE, v) for (t, v) in line.transitions]
    stretched_reports = decoder.decode(stretched)
    assert [r.data for r in stretched_reports] == list(TX_PAYLOADS), (
        f"{stem}: the {NEGATIVE_CONTROL_SCALE}x control must still decode the bytes"
    )
    for r in stretched_reports:
        assert not decoder.check_frame(r), (
            f"{stem}: NEGATIVE CONTROL FAILED TO FAIL: a {NEGATIVE_CONTROL_SCALE}x-mistimed "
            f"copy of the routed waveform passed check_frame at {r.drift_pct:.4f}%"
        )
    return {
        "image": stem,
        "cycles_per_bit": cycles_per_bit,
        "nominal_bit_period_ps": nominal_bit_period_ps,
        "nominal_baud": nominal_baud,
        "pin": "uo_out[0]",
        "frames": frames,
        "negative_control": {
            "scale": NEGATIVE_CONTROL_SCALE,
            "decoded": [f"0x{r.data:02x}" for r in stretched_reports],
            "drift_pct": [r.drift_pct for r in stretched_reports],
            "all_failed_check_frame": True,
        },
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
        tx_initial = _tx_bit(str(dut.uo_out.value))
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
        assert not monitor.violations, (
            f"{stem}: {len(monitor.violations)} output transition(s) violated the pin "
            f"contract: {monitor.violations[:3]}"
        )
        REPORT.add_capture(run_cycles, monitor)
        tx_edges = [
            (event["t_ps"], _tx_bit(event["value"]))
            for event in monitor.transitions
            if event["pin"] == "uo_out"
        ]
        assert tx_edges, f"{stem}: no uo_out transition observed at the pins"
        images.append(
            _measure_image(stem, cycles_per_bit, clock_period_ps, tx_initial, tx_edges, dut._log.info)
        )

    REPORT.add_measurement("uart_tx_drift", {
        "units": {
            "time": "ps (simulation time at the run's SDC clock)",
            "drift": "percent of one nominal bit period",
            "mean_bit_period": "ps per bit (delta-t / last-edge bit index)",
        },
        "clock_period_ps": clock_period_ps,
        "aligned": _align.ALIGNMENT is not None,
        "pin": "uo_out[0]",
        "images": images,
    })
