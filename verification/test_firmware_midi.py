"""Run the MIDI TX and RX images on the serial-loaded RTL at a nominal 50 MHz."""

import random
from itertools import pairwise

import cocotb
from cocotb.clock import Clock
from cocotb.utils import get_sim_time
from reference_models import midi
from reference_models.uart import UartDecoder
from test_firmware_uart import CLK_PERIOD_NS, TX_BIT, TX_PIN, capture_pin_bits
from test_firmware_uart_rx import (
    FrameSpec,
    build_stimulus,
    capture_ports,
    drive_line,
    load_image,
    mark_rises,
    set_rx,
)
from test_protocol_emulator import load_program

BIT = 50_000_000 // midi.BAUD
TOL = BIT // 100


@cocotb.test()
async def test_midi_tx(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await load_program(dut, load_image("midi_tx"))
    capture = await capture_pin_bits(dut, {"tx": (TX_PIN, TX_BIT)}, 105 * BIT)
    line = capture["tx"].signal
    frames = UartDecoder(midi.BAUD).decode(line)
    wire = bytes(f.data for f in frames)
    expected = [
        ("note_on", 2, 60, 85),
        ("control_change", 2, 1, 64),
        ("note_off", 2, 60, 0),
    ]
    assert list(midi.decode(wire)) == expected, wire.hex()
    assert wire == b"".join(midi.encode(*msg) for msg in expected)
    measured = set()
    for n, frame in enumerate(frames):
        # Compare every observable run against its actual number of bit cells.
        bits = [0, *((frame.data >> k) & 1 for k in range(8)), 1]
        boundaries = [0] + [i for i in range(1, 10) if bits[i] != bits[i - 1]]
        edges = line.transitions_between(
            frame.t_start, frame.t_start + 9.5 * BIT * CLK_PERIOD_NS
        )
        assert len(edges) == len(boundaries)
        if n + 1 < len(frames):
            edges.append((frames[n + 1].t_start, 0))
            boundaries.append(10)  # Include the stop interval up to the next start.
        for (a, _), (b, _), i, j in zip(edges, edges[1:], boundaries, boundaries[1:]):
            cycles = (b - a) / CLK_PERIOD_NS
            measured.add(cycles / (j - i))
            assert (j - i) * (BIT - TOL) <= cycles <= (j - i) * (BIT + TOL), (
                f"0x{frame.data:02x} bits {i}..{j}: {cycles} cycles"
            )
    dut._log.info("TX cycles/bit across observed runs: %s", sorted(measured))
    assert line.current() == 1


@cocotb.test()
async def test_midi_rx(dut):
    on = midi.encode("note_on", 15, 0, 127)
    off = midi.encode("note_off", 0, 60, 0)
    cc = midi.encode("control_change", 4, 7, 7)
    # Stray data, full and running note-on, a replacement status mid-message,
    # an interleaved real-time byte, an unsupported program change, and a
    # bad stop interrupting an otherwise complete CC. Recover on a new status.
    before_error = (
        bytes([1]) + on + bytes([62, 0, 12]) + off + cc[:2] + b"\xf8" + cc[2:]
    )
    before_error += bytes([0xC4, 15, 16]) + cc[:2]
    after_error = bytes([3, 4]) + cc
    stream = before_error + cc[2:] + after_error
    frames = [
        FrameSpec(
            b, scale=(0.99, 1.01)[i % 2], gap_bits=0, stop_low=i == len(before_error)
        )
        for i, b in enumerate(stream)
    ]
    # A bad stop requires a high idle interval before the next frame.
    frames[len(before_error)].gap_bits = 1
    line = build_stimulus(BIT, frames, random.Random(444))
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await load_program(dut, load_image("midi_rx"))
    set_rx(dut, 1)
    base_ns = float(get_sim_time("ns"))
    cocotb.start_soon(drive_line(dut, line, base_ns))
    times, results, debug = await capture_ports(
        dut, int(frames[-1].t_end / CLK_PERIOD_NS) + BIT
    )
    marks = mark_rises(debug)
    assert len(marks) == 9 * len(frames)
    spacings = set()
    for i, frame in enumerate(frames):
        samples = marks[9 * i : 9 * (i + 1)]
        for a, b in pairwise(samples):
            spacings.add(b - a)
            assert BIT - TOL <= b - a <= BIT + TOL, (i, a, b)
        middle = (times[samples[0]] - base_ns - frame.t_start) / CLK_PERIOD_NS
        assert abs(middle - 1.5 * BIT) <= 4, (i, middle)

    dut._log.info("RX sample spacing (core clocks): %s", sorted(spacings))

    # The result bus idles at FF and publishes a completed message as three
    # successive clock samples. Reading by cycle also catches equal data bytes.
    first_idle = results.index(0xFF)
    actual = []
    i = first_idle + 1
    while i < len(results):
        if results[i] != 0xFF:
            actual.append(bytes(results[i : i + 3]))
            assert results[i + 3] == 0xFF
            i += 3
        i += 1
    expected = [*midi.decode(before_error), *midi.decode(after_error)]
    assert actual == [midi.encode(*msg) for msg in expected], actual
