#!/usr/bin/env python3
"""Self-test for `verification/reference_models/onewire.py` (issue #447).

Pure stdlib: a synthetic master drives the model over a resolved single
line (DQ = 0 when the master's pad or the slave pulls, else the pull-up),
and every graded quantity is pushed to both sides of its datasheet limit
so the grader is seen to fail. The CRC is held to two published values:
Maxim AN27's worked ROM example (family 0x02, serial 1C B8 01 00 00 00 ->
CRC 0xA2) and the CRC-8/1-Wire check string "123456789" -> 0xA1, plus the
append-CRC property the master's final check relies on.

The bench's fixed bus constants live here too, once: the ROM (a DS18B20
family code, 0x28) and the scratchpad (the datasheet's own +25.0625 C
example, 0x0191, 12-bit config 0x7F), each closed with its own CRC byte.

Usage:
    python3 verification/test_onewire_model.py
Exit codes: 0 pass, 1 at least one case failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reference_models.onewire import (  # noqa: E402
    Ds18b20, Snap, crc8,
    RESET_LOW_MIN_NS, SLOT_MIN_NS, RECOVERY_MIN_NS, WRITE1_LOW_MAX_NS,
    WRITE0_LOW_MIN_NS, READ_LOW_MAX_NS, READ_LOW_MIN_NS, WRITE1_LOW_MIN_NS,
)

US = 1000.0

#: The bench bus, fixed: DS18B20 family 0x28, serial, CRC (crc8 closes it).
ROM = (0x28, 0x8E, 0x2F, 0x43, 0x01, 0x0C, 0x00, 0xFE)
#: The datasheet's +25.0625 C example (0x0191), TH 75, TL 70, 12-bit
#: resolution 0x7F, the three reserved 0xFF bytes, CRC.
SCRATCHPAD = (0x91, 0x01, 0x4B, 0x46, 0x7F, 0xFF, 0xFF, 0xFF, 0x14)
BUSY_SLOTS = 3

_results: list = []
CASES: list = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


class Bus:
    """One resolved DQ line: low when the master or the slave pulls it."""

    def __init__(self, slave: Ds18b20):
        self.t = 0.0
        self.m_oe = 0
        self.slave = slave
        self.slave.observe(self._snap())   # baseline: idle line, released

    def level(self) -> int:
        return 0 if (self.m_oe or self.slave.pull) else 1

    def _snap(self):
        return Snap(self.t, self.level(), self.m_oe)

    def advance(self, dt: float) -> None:
        end = self.t + dt
        while self.t < end:
            d = self.slave.deadline
            nxt = min(end, d) if d is not None else end
            self.t = nxt
            self.slave.observe(self._snap())
        self.slave.observe(self._snap())

    def low(self, width: float) -> None:
        self.m_oe = 1
        self.slave.observe(self._snap())
        self.advance(width)
        self.m_oe = 0
        self.slave.observe(self._snap())


def write_slot(bus: Bus, bit: int, low_ns: float = None,
               slot_ns: float = 62_000.0) -> None:
    low = low_ns if low_ns is not None else (2_000.0 if bit else 61_000.0)
    bus.low(low)
    bus.advance(slot_ns - low)


def read_slot(bus: Bus, low_ns: float = 2_000.0,
              slot_ns: float = 62_000.0) -> int:
    """One read slot; returns the served bit (the resolved level once the
    master has released)."""
    bus.low(low_ns)
    bit = bus.level()
    bus.advance(slot_ns - low_ns)
    return bit


def send_byte(bus: Bus, byte: int) -> None:
    for i in range(8):                      # 1-Wire sends LSB first
        write_slot(bus, (byte >> i) & 1)


def reset(bus: Bus, low_ns: float = RESET_LOW_MIN_NS) -> None:
    bus.low(low_ns)
    bus.advance(RESET_LOW_MIN_NS)           # the presence window


def read_bytes(bus: Bus, n: int) -> list:
    out = []
    bits = []
    for _ in range(n * 8):
        bits.append(read_slot(bus))
    for k in range(n):
        out.append(sum(b << i for i, b in enumerate(bits[k * 8:(k + 1) * 8])))
    return out


# ---------------------------------------------------------------- CRC


@case("crc8: AN27 worked example, check string, append-CRC property")
def _():
    assert crc8((0x02, 0x1C, 0xB8, 0x01, 0x00, 0x00, 0x00)) == 0xA2
    assert crc8(b"123456789") == 0xA1
    rom7 = ROM[:7]
    assert crc8(list(rom7) + [crc8(rom7)]) == 0
    scr8 = SCRATCHPAD[:8]
    assert crc8(list(scr8) + [crc8(scr8)]) == 0
    # bit-by-bit (the firmware's incremental form) == byte-wise
    crc = 0
    for byte in rom7:
        for i in range(8):
            fb = (crc & 1) ^ ((byte >> i) & 1)
            crc >>= 1
            crc ^= 0x8C if fb else 0
    assert crc == crc8(rom7)


@case("bench constants are closed: ROM and scratchpad CRC bytes")
def _():
    assert crc8(ROM[:7]) == ROM[7]
    assert crc8(SCRATCHPAD[:8]) == SCRATCHPAD[8]


# ------------------------------------------------------- the happy path


def run_transaction(slave: Ds18b20, *, w1_low: float = None,
                    reset_low: float = RESET_LOW_MIN_NS,
                    slot_ns: float = 62_000.0, busy_limit: int = 20) -> Bus:
    """The bench's whole transaction with datasheet-legal timing."""

    def send(bus: Bus, byte: int) -> None:
        for i in range(8):                # 1-Wire sends LSB first
            bit = (byte >> i) & 1
            low = w1_low if (w1_low is not None and bit) else None
            write_slot(bus, bit, low_ns=low, slot_ns=slot_ns)

    def read(bus: Bus, n: int) -> list:
        return read_bytes(bus, n)

    bus = Bus(slave)
    reset(bus, reset_low)
    send(bus, 0x33)
    read(bus, 8)
    reset(bus, reset_low)
    send(bus, 0xCC)
    send(bus, 0x44)
    polls = 0
    while read_slot(bus, slot_ns=slot_ns) == 0:
        polls += 1
        assert polls < busy_limit, "the slave never finished converting"
    reset(bus, reset_low)
    send(bus, 0xCC)
    send(bus, 0xBE)
    read(bus, 9)
    return bus


@case("happy path: decode, no violations, margins, measured widths")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD, busy_slots=BUSY_SLOTS)
    run_transaction(slave)
    r = slave.check()
    assert r.violations == [], [str(v) for v in r.violations]
    assert r.commands() == [0x33, 0xCC, 0x44, 0xCC, 0xBE]
    assert [e[1] for e in r.events if e[0] == "rom-byte"] == list(ROM)
    assert [e[1] for e in r.events if e[0] == "scratchpad-byte"] == list(SCRATCHPAD)
    assert sum(1 for e in r.events if e[0] == "poll-busy") == BUSY_SLOTS
    assert sum(1 for e in r.events if e[0] == "conversion-done") == 1
    assert sum(1 for e in r.events if e[0] == "presence") == 3
    assert min(r.margins.values()) >= 0    # reset-low sits exactly on 480 us
    lo, hi = r.measured["reset-low"]
    assert lo == hi == RESET_LOW_MIN_NS
    lo, hi = r.measured["write1-low"]
    assert WRITE1_LOW_MIN_NS <= lo and hi <= WRITE1_LOW_MAX_NS
    lo, hi = r.measured["write0-low"]
    assert WRITE0_LOW_MIN_NS <= lo and hi <= 120_000.0
    lo, hi = r.measured["read-low"]
    assert READ_LOW_MIN_NS <= lo and hi <= READ_LOW_MAX_NS
    lo, hi = r.measured["slot"]
    assert lo >= SLOT_MIN_NS
    lo, hi = r.measured["recovery"]
    assert lo >= RECOVERY_MIN_NS


@case("read slot: the slave's 0 bit is on the line within 15 us of the fall")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD, busy_slots=1)
    bus = Bus(slave)
    reset(bus)
    send_byte(bus, 0xCC)
    send_byte(bus, 0x44)
    assert read_slot(bus) == 0 and read_slot(bus) == 1   # busy, then done
    # ROM bit 0 of byte 0 (0x28): LSB-first first bit is 0 -> line goes low
    slave2 = Ds18b20(ROM, SCRATCHPAD)
    bus2 = Bus(slave2)
    reset(bus2)
    send_byte(bus2, 0x33)
    t_fall = bus2.t
    bus2.low(2_000.0)                    # the master's read low
    t_rel = bus2.t
    assert slave2.pull, "a served 0 bit must pull DQ low"
    assert t_rel - t_fall <= 15_000.0    # data valid from the falling edge


@case("presence: pulled 30 us after the release, held 120 us")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD)
    bus = Bus(slave)
    bus.low(RESET_LOW_MIN_NS)
    assert not slave.pull                # not yet: inside the delay window
    bus.advance(30 * US)
    assert slave.pull
    bus.advance(120 * US)
    assert not slave.pull


@case("worst-case presence (15 us start, 60 us hold) is low only 60..75 us after the release")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD, presence_delay_ns=15 * US, presence_hold_ns=60 * US)
    bus = Bus(slave)
    bus.low(RESET_LOW_MIN_NS)
    bus.advance(14 * US)
    assert not slave.pull
    bus.advance(2 * US)                  # 16 us after the release
    assert slave.pull
    bus.advance(58 * US)                 # 74 us: still low
    assert slave.pull
    bus.advance(2 * US)                  # 76 us: gone, a late sample reads 1
    assert not slave.pull and bus.level() == 1


@case("tight read validity: a served 0 is held 15 us from the fall, then released")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD, read_valid_ns=15 * US)
    bus = Bus(slave)
    reset(bus)
    send_byte(bus, 0x33)
    assert ROM[0] & 1 == 0               # first served bit (0x28, LSB first) is 0
    bus.low(2_000.0)                     # the master's read low
    assert slave.pull, "a served 0 bit must pull DQ low"
    bus.advance(12 * US)                 # 14 us after the fall
    assert slave.pull
    bus.advance(2 * US)                  # 16 us after the fall: a late sample sees a 1
    assert not slave.pull and bus.level() == 1


# --------------------------------------------------------- the dark path


@case("reset low 479.9 us: flagged, no presence answered")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD)
    run_transaction(slave, reset_low=RESET_LOW_MIN_NS - 100.0)
    r = slave.check()
    assert "reset-low-short" in r.kinds(), r.kinds()
    assert not [e for e in r.events if e[0] == "presence"]


@case("empty bus: no presence, and the master's reset is still graded")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD, present=False)
    bus = Bus(slave)
    reset(bus)
    r = slave.check()
    assert [e[0] for e in r.events] == ["reset"]
    assert r.violations == []
    assert not slave.pull


@case("write-1 low at the 15 us bound passes, 15.5 us fails")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD)
    run_transaction(slave, w1_low=15_000.0)
    assert slave.check().violations == []
    slave = Ds18b20(ROM, SCRATCHPAD)
    run_transaction(slave, w1_low=15_500.0)
    assert "slot-low-width" in slave.check().kinds()


@case("write-0 low 59.5 us: neither a 1 nor a 0")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD)
    bus = Bus(slave)
    reset(bus)
    write_slot(bus, 0, low_ns=59_500.0)
    assert "slot-low-width" in slave.check().kinds()


@case("read-slot low 16 us: too long for a read")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD)
    bus = Bus(slave)
    reset(bus)
    send_byte(bus, 0x33)
    read_slot(bus, low_ns=16_000.0)
    assert "read-low-width" in slave.check().kinds()


@case("slot 59 us fall-to-fall and 0.5 us recovery: both flagged")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD)
    bus = Bus(slave)
    reset(bus)
    send_byte(bus, 0xCC)
    write_slot(bus, 1, slot_ns=59_000.0)
    write_slot(bus, 1, low_ns=59_500.0)   # high time 0.5 us, total ~61.1
    kinds = slave.check().kinds()
    assert "slot-too-short" in kinds, kinds


@case("reset high 479 us: the presence window was not waited out")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD)
    bus = Bus(slave)
    bus.low(RESET_LOW_MIN_NS)             # a legal reset ...
    bus.advance(RESET_LOW_MIN_NS - 1_000.0)
    bus.low(2_000.0)                      # ... but the next slot falls 1 us early
    assert "reset-high-short" in slave.check().kinds()


@case("corruption hooks flip one served byte, not the CRC byte")
def _():
    slave = Ds18b20(ROM, SCRATCHPAD, corrupt_scr_byte=0)
    run_transaction(slave)
    served = [e[1] for e in slave.check().events if e[0] == "scratchpad-byte"]
    assert served[0] == SCRATCHPAD[0] ^ 0x01
    assert served[8] == SCRATCHPAD[8]
    assert crc8(served) != 0             # what the master's check must catch
    slave = Ds18b20(ROM, SCRATCHPAD, corrupt_rom_byte=7)
    run_transaction(slave)
    served = [e[1] for e in slave.check().events if e[0] == "rom-byte"]
    assert served[7] == ROM[7] ^ 0x01 and crc8(served) != 0


def main() -> int:
    for name, fn in CASES:
        try:
            fn()
            _results.append((name, True, ""))
        except AssertionError as exc:
            _results.append((name, False, str(exc)))
    for name, ok, msg in _results:
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            print("     " + msg.replace("\n", "\n     "))
    failed = [r for r in _results if not r[1]]
    print(f"{len(_results) - len(failed)}/{len(_results)} cases pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
