#!/usr/bin/env python3
"""Unit tests for `reference_models/spi_flash.py` (issue #140), no simulator.

A flash model that cannot fail cannot be cited, so this drives it with a
small mode-0 master written here and checks (1) that a conforming master
reads exactly the bytes of the image, whatever the image and address, and
(2) that every rule the model claims to check is flagged when a master
breaks it. Run as `python3 verification/test_spi_flash_model.py` (part of
`npm run lint`).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.spi_flash import SpiFlashModel  # noqa: E402

PERIOD = 10.0  # ns per master step, the benches' core clock


class Master:
    """A mode-0 master that moves one line per `PERIOD` and reads back what
    the model drives on MISO one period after each rising edge."""

    def __init__(self, flash, t0=1000.0):
        self.flash = flash
        self.t = t0
        self.cs, self.sck, self.mosi = 1, 0, 0
        self.flash.step(self.t, self.cs, self.sck, self.mosi)

    def _push(self):
        self.t += PERIOD
        self.flash.step(self.t, self.cs, self.sck, self.mosi)

    def set(self, **lines):
        for name, value in lines.items():
            setattr(self, name, value)
        self._push()

    def idle(self, n=1):
        for _ in range(n):
            self._push()

    def clock_bit(self, mosi, *, stretch=0):
        """One bit: put MOSI on the line, rise, sample MISO, fall. Returns the
        sampled MISO. MOSI is set on its own step, a period before the rise."""
        self.set(mosi=mosi)
        self.set(sck=1)
        sampled = self.flash.miso(self.t + PERIOD)  # what the pin shows a step later
        self.idle(stretch)
        self.set(sck=0)
        return sampled

    def command(self, opcode=0x03, address=0, nbytes=0, *, cs_setup=1):
        self.set(cs=0)
        self.idle(cs_setup)
        for bit in range(7, -1, -1):
            self.clock_bit((opcode >> bit) & 1)
        for bit in range(23, -1, -1):
            self.clock_bit((address >> bit) & 1)
        out = []
        for _ in range(nbytes):
            value = 0
            for _ in range(8):
                bit = self.clock_bit(0)
                value = (value << 1) | (0 if bit is None else bit)
            out.append(value)
        self.idle(1)
        return bytes(out)

    def end(self):
        self.set(cs=1)
        self.idle(2)


def image(n=64):
    return bytes((i * 37 + 11) & 0xFF for i in range(n))


def expect_clean(name, flash):
    assert flash.violations == [], f"{name}: {flash.violations}"


def test_reads_the_image():
    data = image(300)
    flash = SpiFlashModel(data)
    m = Master(flash)
    got = m.command(address=0, nbytes=300)
    m.end()
    expect_clean("read", flash)
    assert got == data, "model returned different bytes than the image"
    tx = flash.transactions[0]
    assert (tx["opcode"], tx["address"], tx["bytes_read"], tx["data_bits"]) == (0x03, 0, 300, 2400)


def test_address_and_wrap():
    data = image(16)
    flash = SpiFlashModel(data)
    m = Master(flash)
    got = m.command(address=5, nbytes=20)  # runs past the end and wraps
    m.end()
    expect_clean("wrap", flash)
    assert got == (data[5:] + data)[:20]
    assert flash.transactions[0]["address"] == 5


def test_partial_byte_and_two_transactions():
    data = image(8)
    flash = SpiFlashModel(data)
    m = Master(flash)
    m.command(address=0, nbytes=1)
    for _ in range(3):  # three more bits of the next byte, then CS rises
        m.clock_bit(0)
    m.end()
    m.idle(3)
    got = m.command(address=2, nbytes=2)
    m.end()
    expect_clean("two transactions", flash)
    assert [t["bytes_read"] for t in flash.transactions] == [1, 2]
    assert flash.transactions[0]["data_bits"] == 11
    assert got == data[2:4]


def test_nothing_driven_outside_data_phase():
    flash = SpiFlashModel(image(8))
    m = Master(flash)
    m.set(cs=0)
    m.idle(1)
    for _ in range(8 + 24):
        m.clock_bit(0)
        assert flash.miso(m.t + PERIOD) is None, "MISO driven before the address was complete"
    m.end()
    assert flash.miso(m.t) is None


def violated(name, build, needle):
    flash = SpiFlashModel(image(16))
    build(flash)
    text = " | ".join(flash.violations)
    assert needle in text, f"{name}: expected a violation mentioning {needle!r}, got {flash.violations}"


def test_wrong_opcode():
    def build(flash):
        m = Master(flash)
        m.command(opcode=0x0B, address=0, nbytes=2)
        m.end()
    violated("opcode", build, "only READ (0x03)")
    flash = SpiFlashModel(image(16))
    m = Master(flash)
    got = m.command(opcode=0x0B, nbytes=2)
    assert got == b"\x00\x00", "an unsupported command must drive nothing"


def test_mode_3_clocking_is_flagged():
    def build(flash):
        m = Master(flash)
        m.sck = 1  # SCK idles high: CPOL = 1
        m.idle(1)
        m.command(nbytes=1)
        m.end()
    violated("mode 3", build, "SCK moved while CS is high")


def test_sck_high_at_cs_fall_and_rise():
    def fall(flash):
        m = Master(flash)
        m.set(sck=1)
        m.set(cs=0)
    violated("cs fall", fall, "SCK is high when CS falls")

    def rise(flash):
        m = Master(flash)
        m.set(cs=0)
        m.idle(1)
        m.set(sck=1)
        m.idle(1)
        m.set(cs=1)
    violated("cs rise", rise, "SCK is high when CS rises")


def test_clock_while_cs_high():
    def build(flash):
        m = Master(flash)
        m.set(sck=1)
        m.set(sck=0)
    violated("cs high", build, "SCK moved while CS is high")


def test_cs_setup_and_hold():
    def setup(flash):
        m = Master(flash)
        m.set(cs=0)
        m.set(mosi=0)  # CS fell one step ago; the rise is the next step: 10 ns
        flash.t_css_ns = 25.0
        m.set(sck=1)
    violated("cs setup", setup, "after CS fell")

    def hold(flash):
        m = Master(flash)
        m.set(cs=0)
        m.idle(2)
        m.set(sck=1)
        m.set(sck=0)
        flash.t_csh_ns = 30.0
        m.set(cs=1)
    violated("cs hold", hold, "after the last rising SCK edge")


def test_cs_high_time():
    def build(flash):
        m = Master(flash)
        m.command(nbytes=1)
        flash.t_shsl_ns = 50.0
        m.set(cs=1)
        m.set(cs=0)
    violated("cs high", build, "between transactions")


def test_mosi_setup_and_hold():
    def setup(flash):
        m = Master(flash)
        m.set(cs=0)
        m.idle(1)
        m.mosi = 1
        m.sck = 1
        m._push()  # MOSI and SCK rise on the same step: no setup
    violated("mosi setup", setup, "before a rising SCK edge")

    def hold(flash):
        m = Master(flash)
        m.set(cs=0)
        m.idle(1)
        m.set(sck=1)
        m.set(mosi=1)  # changes 10 ns after the rise: hold is 3 ns, so legal
        m.set(sck=0)
    flash = SpiFlashModel(image(16))
    hold(flash)
    assert not [v for v in flash.violations if "hold" in v], flash.violations

    def early(flash):
        m = Master(flash)
        m.set(cs=0)
        m.idle(1)
        flash.t_h_ns = 15.0
        m.set(sck=1)
        m.set(mosi=1)
    violated("mosi hold", early, "after a rising SCK edge")


def test_pulse_widths_and_frequency():
    def short_high(flash):
        m = Master(flash)
        m.set(cs=0)
        m.idle(2)
        flash.t_clh_ns = 15.0
        m.set(sck=1)
        m.set(sck=0)
    violated("sck high", short_high, "SCK high for")

    def short_low(flash):
        m = Master(flash)
        m.set(cs=0)
        m.idle(2)
        m.set(sck=1)
        m.set(sck=0)
        flash.t_cll_ns = 15.0
        m.set(sck=1)
    violated("sck low", short_low, "SCK low for")

    def too_fast(flash):
        flash.f_max_hz = 20e6  # 50 ns period
        m = Master(flash)
        m.set(cs=0)
        m.idle(2)
        for _ in range(3):
            m.set(sck=1)
            m.set(sck=0)  # 20 ns period
    violated("frequency", too_fast, "MHz")


def test_miso_not_yet_valid():
    def build(flash):
        flash.t_clqv_ns = 25.0  # slower part: the 20 ns low phase is not enough
        m = Master(flash)
        m.command(nbytes=3)
        m.end()
    violated("clqv", build, "valid only after")


def test_unresolved_line():
    flash = SpiFlashModel(image(4))
    flash.step(0.0, 1, 0, 0)
    flash.step(10.0, None, 0, 0)
    assert any("not a logic level" in v for v in flash.violations)


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
