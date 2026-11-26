"""Run the serially loaded DALI image on the RTL against a single control gear."""
import sys
from math import ceil, floor

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ValueChange, with_timeout
from cocotb.utils import get_sim_time

from firmware_artifacts import parse_hex_image
from reference_models.dali import TE, TE_MAX, TE_MIN, cells, decode_forward, forward_run
from repo_root import find_repo_root
from test_protocol_emulator import load_program
from uio_pads import UioPads

ROOT = find_repo_root(__file__)
sys.path.insert(0, str(ROOT / "firmware/tools"))
import asm

SOURCE = ROOT / "firmware/asm/dali_master.asm"
IMAGE = ROOT / "firmware/build/dali_master.hex"
TX_BIT, RX_BIT = 0, 1
PERIOD_NS = 20  # target-spec row 4 (unconfirmed)
HALF = round(TE)
SHORT_LOW = 18_600  # observable low pulse below ceil(TE_MIN) = 18,940
LONG_LOW = 23_250  # observable low pulse above floor(TE_MAX) = 23,148
# Offsets from ceil(16 Te) after the query's stop edge. The original four
# land at the same point in the 25-cycle poll. At offset 1978 the previous
# sample ended a 250-poll block (query_stop + 335312).
PHASES = (0, 75, 150, 225)
START_SAMPLE_LAG = {0: 3, 75: 3, 150: 3, 225: 3, 1: 2, 4: 24, 14: 14, 1978: 28}
RX_IN = 0x9D00  # IN R3, UIO_IN


def cycle():
    return int(get_sim_time(unit="ns")) // PERIOD_NS


def delay(cycles):
    return Timer(cycles * PERIOD_NS, unit="ns")


class Gear:
    def __init__(self, dut):
        self.dut = dut
        self.pads = UioPads(dut, pulls={TX_BIT: "up"}, tie={
            i: 0 for i in range(8) if i not in (TX_BIT, RX_BIT)
        }).start()
        self.drive(1)

    def drive(self, gear_level):
        # Both sides can sink the physical bus. The Click presents its
        # resolved level on RX, including the master's own transmissions.
        tx = int(self.dut.uio_out.value) >> TX_BIT & 1 if int(self.dut.uio_oe.value) else 1
        self.pads.drive(RX_BIT, tx & gear_level)

    async def tx_edge(self):
        await with_timeout(ValueChange(self.dut.uio_out), 40, "ms")
        assert int(self.dut.uio_oe.value) == 1 << TX_BIT
        self.drive(1)
        return cycle(), int(self.dut.uio_out.value) >> TX_BIT & 1

    async def forward(self, wanted):
        start, level = await self.tx_edge()
        assert level == 0, "missing falling start edge"
        previous = start
        symbols, intervals = [], []
        while len(symbols) < 34:
            now, following = await self.tx_edge()
            assert following != level
            span = now - previous
            count = forward_run(span)
            intervals.append((span, count))
            symbols.extend([level] * count)
            previous, level = now, following
        # Both commands end in zero, so stop begins with an observable rise.
        assert decode_forward(symbols) == wanted
        assert level == 1, "stop must release the bus"
        self.dut._log.info("forward %04x: 1Te %s, 2Te %s cycles", wanted,
                           sorted({t for t, n in intervals if n == 1}),
                           sorted({t for t, n in intervals if n == 2}))
        return start, now

    async def trace_long_low(self, bad, word, phase):
        # Observe IN on the executing edge, while the gear holds RX low.
        fall = cycle()
        samples = []
        for _ in range(LONG_LOW):
            await RisingEdge(self.dut.clk)
            if int(self.dut.u_core.exec_word.value) == RX_IN:
                samples.append(cycle() - fall)
        await Timer(1, unit="ns")  # keep the next pad transition off the clock edge

        lag = samples[0]
        if bad == "long_start":
            assert lag == START_SAMPLE_LAG[phase]
            guard, rise, count = 18_660, 23_177, 188
        elif word & 2:  # penultimate one: the mid-bit fall ends a two-half run
            assert 1 <= lag <= 34
            guard, rise, count = 18_816, 23_164, 181
        else:           # penultimate zero: a boundary preceded the mid-bit fall
            assert 1 <= lag <= 24
            guard, rise, count = 18_820, 23_168, 181
        assert len(samples) == 1 + 74 + count
        assert (samples[74] - lag, samples[-1] - lag) == (guard, rise)
        self.dut._log.info("%s %02x offset %d: fall to IN %d, last guard %d, last rise %d cycles",
                           bad, word, phase, lag, samples[74], samples[-1])

    async def reply(self, word, half, bad, last, phase):
        levels = cells(word, 8)
        durations = [half] * len(levels)
        if bad == "short":
            durations[0] = half // 3
        if bad == "short_start":
            durations[0] = SHORT_LOW  # start low, 340 cycles under the minimum
        if bad in ("short_final", "long_final"):
            final = 17  # last data cell, before the four idle stop halves
            assert levels[final] == 0 and levels[final + 1:] == [1] * 4
            durations[final] = SHORT_LOW if bad == "short_final" else LONG_LOW
        if bad == "long_start":
            durations[0] = LONG_LOW  # start low, 102 cycles over the maximum
        shifts = {"late_boundary": (6, 8_000), "early_boundary": (6, -8_000),
                  "late_mid": (7, 3_000)}
        if bad in shifts:
            # Move one visible edge without moving its neighbors or either stop.
            edge, offset = shifts[bad]
            assert levels[edge - 1] != levels[edge]
            durations[edge - 1] += offset
            durations[edge] -= offset
        for i, (level, duration) in enumerate(zip(levels, durations)):
            assert int(self.dut.uo_out.value) == last, "published before backward stop completed"
            self.drive(0 if bad == "stop" and i == 21 else level)
            if duration == LONG_LOW:
                await self.trace_long_low(bad, word, phase)
            else:
                await delay(duration)
        self.drive(1)


async def boot(dut, words):
    Clock(dut.clk, PERIOD_NS, unit="ns", impl="gpi").start()
    await load_program(dut, words)
    gear = Gear(dut)
    await with_timeout(ValueChange(dut.uio_oe), 10, "us")
    assert int(dut.uio_oe.value) == 1 << TX_BIT
    assert int(dut.uio_out.value) >> TX_BIT & 1
    return gear


@cocotb.test()
async def transactions(dut):
    words = parse_hex_image(IMAGE)
    assert words == asm.assemble_text(SOURCE.read_text()).words and len(words) <= 256
    gear = await boot(dut, words)
    _, stop = await gear.forward(0x0054)  # short address zero, direct arc power 0x54
    start, query_stop = await gear.forward(0x01A0)  # QUERY ACTUAL LEVEL
    assert start - stop >= ceil(26 * TE), "short forward stops or settling time"
    dut._log.info("forward stop to next start: %d cycles", start - stop)

    last = 0
    for gap, half, reply, bad, *rest in (
        (22, floor(TE_MAX), 0x81, None),
        (9, HALF, 0x3C, "stop"), (10, HALF, 0xF0, "short"),
        (5, HALF, 0xEF, "early"), (None, HALF, 0, "missing"),
        (7, ceil(TE_MIN), 0x54, None),
        (12, HALF, 0x81, "late_boundary"), (12, HALF, 0x7E, "late_boundary"),
        (12, HALF, 0x81, "early_boundary"), (12, HALF, 0x81, "late_mid"),
        (12, HALF, 0xA7, None),
        *[(12, HALF, 0x82, "short_final", ph) for ph in PHASES],
        *[(12, HALF, 0x95, "short_start", ph) for ph in PHASES],
        *[(12, ceil(TE_MIN), b, None, ph) for b, ph in zip((0x82, 0x36) * 2, PHASES)],
        (12, ceil(TE_MIN), 0x95, None, 150),
        # Upper bound: valid floor(TE_MAX) replies (all end in a zero) publish
        # at each listed offset. Alternate bytes so each publication is visible.
        *[(12, floor(TE_MAX), (0x82, 0x36)[i % 2], None, ph)
          for i, ph in enumerate(START_SAMPLE_LAG)],
        *[(12, HALF, 0x95, "long_start", ph) for ph in START_SAMPLE_LAG],
        (12, HALF, 0x3C, None),
        (12, HALF, 0x36, "long_final", 0),  # original #546 reproduction
        *[(12, HALF, 0x4A if ph in PHASES else 0x54, "long_final", ph)
          for ph in START_SAMPLE_LAG],
        (12, HALF, 0xA7, None),
    ):
        # Watch concurrently even during the reply. An early TX falling edge
        # must be timestamped where it occurred, not mistaken for a later frame.
        phase = rest[0] if rest else 0
        following = cocotb.start_soon(gear.forward(0x01A0))
        if gap is not None:
            # Idle through both stop bits. Also watch RESULT until the gear
            # finishes the two backward stop bits, including the corrupt one.
            await delay(round(4 * TE))
            assert int(dut.uio_out.value) == 1 << TX_BIT
            offset = (floor if gap == 22 else ceil)((4 + gap) * TE)
            await delay(offset - round(4 * TE) + phase)
            await Timer(1, unit="ns")  # drive after the sampling edge, including at rollover
            assert cycle() - query_stop == offset + phase
            await gear.reply(reply, half, bad, last, phase)
            end = cycle()
        start, next_stop = await following
        if bad is None:
            assert start - end >= ceil(22 * TE), "short backward-to-forward settling time"
            dut._log.info("reply %02x, Te %d, gap %d Te, offset %d: next forward %d cycles after stop",
                          reply, half, gap, phase, start - end)
            last = reply
        else:
            # 4 Te of stop followed by >=22 Te of bus settling.
            assert start - query_stop >= ceil(26 * TE)
            if bad == "missing":
                dut._log.info("no reply: next start %d cycles after stop begins", start - query_stop)
                assert start - query_stop <= round(26 * TE) + 500, "missed timeout deadline"
        assert int(dut.uo_out.value) == last, f"{bad or 'valid'} reply: RESULT"
        if bad in ("late_boundary", "early_boundary", "late_mid", "short_start", "short_final",
                   "long_start", "long_final"):
            dut._log.info("Rejected %s on %02x at phase %d, RESULT held %02x", bad, reply, phase, last)
        query_stop = next_stop
    gear.pads.assert_no_contention()
    assert gear.pads.oe_seen == gear.pads.drove_high == gear.pads.drove_low == 1 << TX_BIT


@cocotb.test()
async def half_bit_mutant(dut):
    source = SOURCE.read_text()
    site = "WAIT  255              ; TX first half"
    assert source.count(site) == 1
    short = source.replace(site, "WAIT  160              ; shortened TX first half")
    gear = await boot(dut, asm.assemble_text(short).words)
    try:
        await gear.forward(0x0054)
    except ValueError as error:
        assert "outside timing tolerance" in str(error)
        dut._log.info("Short TX half-bit rejected: %s", error)
    else:
        raise AssertionError("shortened TX half-bit escaped the bus timing check")
