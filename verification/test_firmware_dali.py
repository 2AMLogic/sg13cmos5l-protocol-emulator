"""Run the serially loaded DALI image on the RTL against a single control gear."""
import sys
from math import ceil, floor

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, ValueChange, with_timeout
from cocotb.utils import get_sim_time

from firmware_artifacts import parse_hex_image
from reference_models.dali import TE, cells, decode_forward, forward_run
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

    async def reply(self, word, half, bad, last):
        for i, level in enumerate(cells(word, 8)):
            assert int(self.dut.uo_out.value) == last, "published before backward stop completed"
            self.drive(0 if bad == "stop" and i == 21 else level)
            await delay(half // 3 if bad == "short" and i == 0 else half)
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
    for gap, half, reply, bad in (
        (7, 19_000, 0x54, None), (22, 23_100, 0x81, None),
        (9, HALF, 0x3C, "stop"), (10, HALF, 0xF0, "short"),
        (5, HALF, 0xEF, "early"),
        (None, HALF, 0, "missing"), (12, HALF, 0xA7, None),
    ):
        # Watch concurrently even during the reply. An early TX falling edge
        # must be timestamped where it occurred, not mistaken for a later frame.
        following = cocotb.start_soon(gear.forward(0x01A0))
        if gap is not None:
            # Idle through both stop bits. Also watch RESULT until the gear
            # finishes the two backward stop bits, including the corrupt one.
            await delay(round(4 * TE))
            assert int(dut.uio_out.value) == 1 << TX_BIT
            offset = (floor if gap == 22 else ceil)((4 + gap) * TE)
            await delay(offset - round(4 * TE))
            assert cycle() - query_stop == offset
            await gear.reply(reply, half, bad, last)
            end = cycle()
        start, next_stop = await following
        if bad is None:
            assert start - end >= ceil(22 * TE), "short backward-to-forward settling time"
            dut._log.info("reply %02x, Te %d, gap %d Te: next forward %d cycles after stop",
                          reply, half, gap, start - end)
            last = reply
        else:
            # 4 Te of stop followed by >=22 Te of bus settling.
            assert start - query_stop >= ceil(26 * TE)
            if bad == "missing":
                dut._log.info("no reply: next start %d cycles after stop begins", start - query_stop)
                assert start - query_stop <= round(26 * TE) + 500, "missed timeout deadline"
        assert int(dut.uo_out.value) == last, f"{bad or 'valid'} reply: RESULT"
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
