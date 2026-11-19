"""DALI bus levels and timing from Microchip AN1465, figures 7–10 (bus side).

Times are core cycles at the proposed 50 MHz. Transitions on consecutive
equal levels are unobservable: grade their combined duration on the wire.
"""
from fractions import Fraction

TE = Fraction(50_000_000, 2 * 1200)
TE_MIN, TE_MAX = TE / Fraction(11, 10), TE / Fraction(9, 10)


def cells(word, width):
    """Start and MSB-first Manchester data followed by two idle stop bits."""
    bits = [1, *((word >> n) & 1 for n in reversed(range(width)))]
    return [level for bit in bits for level in (1 - bit, bit)] + [1] * 4


def forward_run(duration):
    """Number of half-bits represented by a measured constant-level run."""
    for count in (1, 2):
        if count * TE_MIN <= duration <= count * TE_MAX:
            return count
    raise ValueError(f"Manchester interval {duration} cycles outside timing tolerance")


def decode_forward(symbols):
    if len(symbols) != 34 or symbols[:2] != [0, 1]:
        raise ValueError("invalid forward frame length or start bit")
    word = 0
    for first, second in zip(symbols[2::2], symbols[3::2]):
        if first == second:
            raise ValueError("missing Manchester mid-bit transition")
        word = (word << 1) | second
    return word
