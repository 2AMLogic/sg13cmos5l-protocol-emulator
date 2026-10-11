"""cocotb regression for DR 0013 finding F8 (judge counterexample, PR #210),
closed by issue #211: a corrupted count byte is rejected before any word is
committed.

History. Before #211 the frame was `0xA5`, `N-1`, payload, CRC-16, and the
count was not covered by anything. The valid two-word image
[0xF000, 0x13C1] (0x13C1 is the CRC-16/XMODEM of `f0 00`: the second word is
the first word's own CRC) was framed `a5 01 f0 00 13 c1 00 00`, and with bit
0 of the count flipped the loader took ONE word, read `13 c1` as the trailer,
found the CRC matching, answered `06 13 c1` and ran the truncated image. This
module pinned that acceptance (record
`verification/records/boot-uart/records/20261010-164351-57c5c8c.md`, which
stays as the evidence of the old behaviour).

Now (operator ruling on #211, option 1). The frame is `0xA5`, `N-1`,
`~(N-1)`, payload, CRC-16. The loader checks the complement before it commits
a payload word and answers a mismatch `15 00 00` (NAK, then PM_CRC with
nothing committed) and never runs. This module asserts:

- the valid frame `a5 01 fe f0 00 13 c1 00 00` is accepted (reply `06 00 00`:
  the CRC of the two committed words, a message followed by its own CRC) and
  run;
- the F8 frame, count 01 -> 00 with the complement left at `fe`, is REJECTED:
  reply `15 00 00`, the core never leaves the boot ROM, no word committed;
- every single-bit flip of the count byte (8) and of the complement byte (8)
  is rejected the same way;
- the loader is not wedged by a rejected header: in the same session as a
  rejected F8 frame, with no reset, the valid frame sent afterwards loads and
  runs (this image's bytes hold no `0xA5`, so the tail of the rejected frame
  cannot start a false frame).

Each rejected frame is sent whole, as a host would. The reply comes while the
host is still sending the payload (the loader answers as soon as the third
byte is in), so it is read from the start of the frame. A flip of the count
upward does not make the loader wait for bytes that never come: the header is
rejected first.

White-box (RTL): the core's fetch source and program memory words. At gate
level (`GATES=yes`) only the pins are checked.
"""

import binascii

import cocotb
from cocotb.clock import Clock

import uart_boot_host as host
from test_boot_uart import (CLK_NS, REPLY_WINDOW, RomWatch, Session, assert_pins_quiet,
                            check_reply_timing, flip_bit, load_and_check, read_memory)

IMAGE = [0xF000, 0x13C1]
NAK_HEADER = bytes((host.NAK, 0x00, 0x00))


async def expect_accepted(dut, label):
    session = Session(dut)
    r = await load_and_check(dut, session, IMAGE, label)
    got, reports = session.reply(r["t_before"])
    session.stop()
    assert got == host.expected_reply(IMAGE), f"{label}: reply {got!r}"
    check_reply_timing(reports, label)
    assert r["left_rom"] in (True, None), f"{label}: the valid image did not run"
    mem = read_memory(dut, 2)
    if mem is not None:
        assert mem == IMAGE, f"{label}: memory {mem}"


async def expect_rejected(dut, data, label, keep=False):
    session = Session(dut)
    await session.reset()
    watch = RomWatch(dut)
    t0 = session.t_of(session.cycle)
    await session.play(data)
    await session.idle(REPLY_WINDOW)
    got, reports = session.reply(t0)
    assert got == NAK_HEADER, f"{label}: reply {got!r}, want {NAK_HEADER.hex()}"
    check_reply_timing(reports, label)
    assert watch.left_rom() in (False, None), f"{label}: the core left the boot ROM"
    assert_pins_quiet(session, session.t_release, float("inf"), label)
    if keep:
        return session, watch
    session.stop()
    return None


@cocotb.test()
async def test_count_corruption_is_rejected(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    good = host.frame(IMAGE)
    assert good.hex() == "a501fef00013c10000", good.hex()
    assert binascii.crc_hqx(bytes((0xF0, 0x00)), 0) == 0x13C1

    # Control: the uncorrupted frame is accepted whole and run.
    await expect_accepted(dut, "two-word image, count 01, complement fe")

    # The F8 counterexample: count 01 -> 00. Before #211 this was `06 13 c1`
    # and RUN; the complement now rejects it before a word is committed.
    f8 = flip_bit(good, 1, 0)
    assert f8.hex() == "a500fef00013c10000", f8.hex()
    await expect_rejected(dut, f8, "F8: count 01->00")
    dut._log.info("F8 frame a500fe...: rejected 15 00 00, not run")

    # Every single-bit flip of the count byte and of the complement byte.
    rejected = 0
    for index, name in ((1, "count"), (2, "complement")):
        for bit in range(8):
            data = flip_bit(good, index, bit)
            if index == 1 and bit == 0:
                continue                      # the F8 frame, done above
            await expect_rejected(dut, data, f"{name} bit {bit} flipped ({data[1]:02x} {data[2]:02x})")
            rejected += 1
    assert rejected == 15
    dut._log.info("all 16 single-bit flips of the count and complement bytes rejected, none run")

    # Not wedged: the F8 frame is rejected, then (no reset) the valid frame runs.
    session, watch = await expect_rejected(dut, f8, "F8 again, then a retry", keep=True)
    t_retry = session.t_of(session.cycle)
    await session.play(good)
    await session.idle(REPLY_WINDOW)
    got, reports = session.reply(t_retry)
    assert got == host.expected_reply(IMAGE), f"retry after a rejected header: reply {got!r}"
    check_reply_timing(reports, "retry")
    await session.idle(400)
    session.stop()
    assert watch.left_rom() in (True, None), "the retry after a rejected header did not run"
    mem = read_memory(dut, 2)
    if mem is not None:
        assert mem == IMAGE, f"retry: memory {mem}"
    dut._log.info("valid frame after a rejected header, no reset: accepted and run")
