"""An independent UART host for DR 0013 layer 2's UART load (issue #139).

This is the "host" side of the boot protocol: it frames an image, turns the
frame into the line levels a USB-UART bridge would put on `ui_in[1]`, and
says what a correct reply looks like. It is written from DR 0013's frame
description and the generic 8N1 convention only. It imports nothing from
`firmware/` -- not the assembler, not `loadseq`, not the boot program -- so
a mistake in the firmware's idea of the frame cannot be repeated here. The
bench asserts that this module and `firmware/tools/loadseq.py` build the
same bytes, which is a check between two independent implementations.

Everything here is pure Python and takes no simulator: `edges()` returns
`(cycle, level)` pairs and the bench plays them into the DUT.

Timing model of the line. A bridge's clock is not the chip's: its bit period
is `nominal * (1 + rate_error)` core cycles, a real number. Bit `k` of a byte
that starts at core cycle `s` begins at `s + round(k * period)`, so the
fractional part is spread across the frame rather than rounded away, and a
2 % error is a 2 % error at every bit. `gap_bits` adds idle bits between
bytes (0 = back to back, the hardest case for a receiver). `jitter` moves each
edge by a whole number of cycles drawn from a seeded generator.
"""

import random

#: DR 0013: 8N1, "a fixed divisor of 434 core cycles per bit".
NOMINAL_CYCLES_PER_BIT = 434

MAGIC = 0xA5
ACK = 0x06
NAK = 0x15


def _crc_table():
    table = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        table.append(crc)
    return table


_TABLE = _crc_table()


def crc16_xmodem(data, crc=0x0000):
    """CRC-16/XMODEM by table, one byte at a time (poly 0x1021, init 0, no
    reflection, no final XOR). A different algorithm from `loadseq`'s
    bitwise loop; the bench checks both against `binascii.crc_hqx`."""
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _TABLE[((crc >> 8) ^ byte) & 0xFF]
    return crc


def image_bytes(words):
    """The image as the chip receives it: each word high byte first."""
    out = bytearray()
    for word in words:
        assert 0 <= word <= 0xFFFF
        out += bytes((word >> 8, word & 0xFF))
    return bytes(out)


def frame(words):
    """`0xA5`, `N-1`, `2N` bytes, CRC-16 high byte first."""
    assert 1 <= len(words) <= 256, len(words)
    body = image_bytes(words)
    crc = crc16_xmodem(body)
    return bytes((MAGIC, len(words) - 1)) + body + bytes((crc >> 8, crc & 0xFF))


def expected_reply(words, accepted=True):
    """What the chip answers for an image it wrote: the verdict byte, then
    the CRC of the words actually written, high byte first."""
    crc = crc16_xmodem(image_bytes(words))
    return bytes((ACK if accepted else NAK, crc >> 8, crc & 0xFF))


def byte_levels(value):
    """Start bit, eight data bits least significant first, stop bit."""
    return [0] + [(value >> bit) & 1 for bit in range(8)] + [1]


def edges(data, start, rate_error=0.0, gap_bits=0, jitter=0, seed=0,
          nominal=NOMINAL_CYCLES_PER_BIT):
    """Line transitions for `data`, as `(cycle, level)` in cycle order.

    `start` is the core cycle of the first start bit. The line is assumed
    idle high before `start`, and the returned list ends with the line high.
    A level is listed only when it changes."""
    period = nominal * (1.0 + rate_error)
    rng = random.Random(seed)
    level, out, last_cycle = 1, [], -1
    byte_start = float(start)
    for value in data:
        for k, bit in enumerate(byte_levels(value)):
            if bit != level:
                cycle = int(round(byte_start + k * period))
                if jitter:
                    cycle += rng.randint(-jitter, jitter)
                cycle = max(cycle, last_cycle + 1)
                out.append((cycle, bit))
                last_cycle, level = cycle, bit
        byte_start += (10 + gap_bits) * period
    if level != 1:  # a frame always ends on its stop bit, but be explicit
        out.append((int(round(byte_start)), 1))
    return out


def end_cycle(data, start, rate_error=0.0, gap_bits=0, nominal=NOMINAL_CYCLES_PER_BIT):
    """The cycle at which the last byte's stop bit has been on the line for
    one full bit period."""
    period = nominal * (1.0 + rate_error)
    return int(round(start + (len(data) * (10 + gap_bits) - gap_bits) * period))


def noise_edges(start, stop, rng, bits=(0, 2, 3, 4), mean_gap=300):
    """Toggles of unrelated `ui_in` bits over `[start, stop)`: `(cycle, bit)`
    pairs meaning "bit `bit` of `ui_in` flips at `cycle`". The chip must only
    look at its RX pin (and the straps it already sampled)."""
    out, cycle = [], start
    while True:
        cycle += rng.randint(1, 2 * mean_gap)
        if cycle >= stop:
            return out
        out.append((cycle, rng.choice(bits)))
