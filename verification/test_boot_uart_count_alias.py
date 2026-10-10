"""cocotb regression for DR 0013 finding F8 (judge counterexample, PR #210):
the UART load's count byte is not covered by the CRC.

The valid two-word image [0xF000, 0x13C1] is framed
`a5 01 f0 00 13 c1 00 00`, because 0x13C1 is the CRC-16/XMODEM of `f0 00`:
the second word is the first word's own CRC. Flipping bit 0 of the count
gives `a5 00 f0 00 13 c1 00 00`. The loader then takes ONE word (0xF000),
reads `13 c1` as the trailer, and the CRC matches.

This bench runs both frames on the RTL of the submitted top and PINS what the
chip does, so the claim "a bad length never reaches RUN" cannot be read
stronger than it is. The result of the simulation is the evidence: see
`verification/records/boot-uart/` (record 20261010-163858-080ef15). It is a separate module from
`test_boot_uart.py` so that the gate-level records that hash that file stay
live; it reuses that bench's session and host plumbing.

White-box (RTL): the core's fetch source and program memory words.
"""

import binascii

import cocotb
from cocotb.clock import Clock

import uart_boot_host as host
from test_boot_uart import (CLK_NS, Session, flip_bit, load_and_check, read_memory)

IMAGE = [0xF000, 0x13C1]


@cocotb.test()
async def test_count_corruption_aliasing_residue(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    good = host.frame(IMAGE)
    assert good.hex() == "a501f00013c10000", good.hex()
    assert binascii.crc_hqx(bytes((0xF0, 0x00)), 0) == 0x13C1
    bad = flip_bit(good, 1, 0)
    assert bad.hex() == "a500f00013c10000", bad.hex()

    # Control: the uncorrupted frame is accepted whole.
    session = Session(dut)
    r = await load_and_check(dut, session, IMAGE, "two-word image, count 01")
    got, _ = session.reply(r["t_before"])
    session.stop()
    assert got == host.expected_reply(IMAGE), got
    assert r["left_rom"] in (True, None)
    mem = read_memory(dut, 2)
    if mem is not None:
        assert mem == IMAGE, mem

    # The finding: count 01 -> 00 is accepted as a one-word image and run.
    # The loader answers after the trailer, i.e. while the host is still
    # sending the frame's last two bytes (it ignores them while it transmits),
    # so the reply is read from before the frame, not from its end.
    session = Session(dut)
    r = await load_and_check(dut, session, None, "count 01->00", data=bad)
    got, _ = session.reply(r["t_before"])
    session.stop()
    dut._log.info(f"count 01->00: reply {got!r}, left_rom {r['left_rom']}")
    assert got == host.expected_reply([IMAGE[0]]), got            # 06 13 c1: ACK
    assert r["left_rom"] in (True, None), "expected the truncated image to be run (F8)"
    mem = read_memory(dut, 1)
    if mem is not None:
        assert mem == [IMAGE[0]], mem
