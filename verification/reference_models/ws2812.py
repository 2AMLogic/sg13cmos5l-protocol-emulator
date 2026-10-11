"""Independent WS2812B receiver model (target-spec row 13, issue #141 part 2;
the protocol choice is DR 0018).

Written from the Worldsemi WS2812B datasheet alone, the "Data transfer time"
table and the "Composition of 24bit data" note (the copy DR 0018 cites,
sha256 670517e4...7448). It imports nothing from `rtl/`, `src/`,
`firmware/` or any bench, and it knows nothing about this design's ISA,
clock or cycle counts. Its input is a `waveform.Signal` in nanoseconds; its
output is the frames of pixels a WS2812B chain would latch, plus every
timing violation it saw.

The datasheet's timing (all ±150 ns, except the bit period and the reset):

    T0H  0 code, high   0.40 us        T0L  0 code, low   0.85 us
    T1H  1 code, high   0.80 us        T1L  1 code, low   0.45 us
    TH + TL = 1.25 us ± 600 ns         RES  low, above 50 us

Data is 24 bits per pixel, G7..G0 R7..R0 B7..B0, high bit first. The first
pixel keeps the first 24 bits of a frame and forwards the rest, so the
frame's pixels arrive in order. A low longer than RES ends (latches) the
frame.

How a waveform is judged
------------------------
The line idles low. Every high pulse is one bit:

* its width must lie in the T0H window (a 0) or the T1H window (a 1). A
  width in neither is a violation, and the bit is unreadable;
* the low that follows must be either a reset (at least RES) or the low of
  that same code (T0L or T1L window), and the high plus the low must lie in
  the bit-period window. A low that is longer than the code's TL window but
  shorter than RES is a violation (a real part may or may not latch on it).

A low of at least RES after a bit ends the frame. The frame's TL is then not
graded, because the bit is followed by the reset, not by another bit. A frame
whose bit count is not a multiple of 24 is a violation (the last pixel would
be partly written). A frame still open when the waveform ends is reported
with `latched = False`: no reset has been seen, so no part would have shown
it.

The windows are closed intervals: a pulse exactly on a window edge is legal.
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# --- the datasheet's numbers, in ns -------------------------------------
T0H_NS = 400.0
T1H_NS = 800.0
T0L_NS = 850.0
T1L_NS = 450.0
PULSE_TOL_NS = 150.0
BIT_PERIOD_NS = 1250.0
BIT_PERIOD_TOL_NS = 600.0
RES_MIN_NS = 50_000.0
BITS_PER_PIXEL = 24


def window(nominal: float, tol: float) -> Tuple[float, float]:
    return (nominal - tol, nominal + tol)


T0H_WINDOW = window(T0H_NS, PULSE_TOL_NS)
T1H_WINDOW = window(T1H_NS, PULSE_TOL_NS)
T0L_WINDOW = window(T0L_NS, PULSE_TOL_NS)
T1L_WINDOW = window(T1L_NS, PULSE_TOL_NS)
PERIOD_WINDOW = window(BIT_PERIOD_NS, BIT_PERIOD_TOL_NS)


def _inside(value: float, bounds: Tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


@dataclass
class Bit:
    t_rise: float
    high_ns: float
    low_ns: Optional[float]  # None when the waveform ends during the low
    value: Optional[int]     # None when the high width fits neither code


@dataclass
class Violation:
    t: float
    kind: str      # "high", "low", "period", "gap", "partial-pixel", "leading-reset"
    detail: str


@dataclass
class Frame:
    bits: List[Bit] = field(default_factory=list)
    latched: bool = False

    def pixels(self) -> List[Tuple[int, int, int]]:
        """(G, R, B) per complete pixel, from the readable bits."""
        values = [b.value for b in self.bits]
        out = []
        for p in range(len(values) // BITS_PER_PIXEL):
            chunk = values[p * BITS_PER_PIXEL:(p + 1) * BITS_PER_PIXEL]
            if any(v is None for v in chunk):
                raise ValueError("pixel has an unreadable bit")
            word = 0
            for v in chunk:
                word = (word << 1) | v
            out.append(((word >> 16) & 0xFF, (word >> 8) & 0xFF, word & 0xFF))
        return out


@dataclass
class Decode:
    frames: List[Frame]
    violations: List[Violation]
    leading_low_ns: float
    pulse_widths: dict  # kind -> list of measured ns, for the record

    @property
    def latched_frames(self) -> List[Frame]:
        return [f for f in self.frames if f.latched]


class Ws2812Decoder:
    """Decode and grade a WS2812B data line.

    `require_leading_reset`: the low from the start of the waveform to the
    first rising edge must itself be a reset. A controller that starts
    driving a chain whose state it does not know should do this. The first
    frame would otherwise extend whatever the chain last received.
    """

    def __init__(self, *, require_leading_reset: bool = True):
        self.require_leading_reset = require_leading_reset

    def decode(self, sig, t_start: float, t_end: float) -> Decode:
        edges = [(t, v) for (t, v) in sig.transitions if t_start <= t <= t_end]
        level = sig.value_at(t_start)
        violations: List[Violation] = []
        widths = {"T0H": [], "T1H": [], "T0L": [], "T1L": [], "bit": [], "reset": []}
        if level != 0:
            violations.append(Violation(t_start, "gap", "the line is not idle low at the start"))
        rises = [t for (t, v) in edges if v == 1]
        falls = [t for (t, v) in edges if v == 0]
        leading = (rises[0] if rises else t_end) - t_start
        if rises and self.require_leading_reset and leading < RES_MIN_NS:
            violations.append(Violation(
                t_start, "leading-reset",
                f"first rise after {leading:.0f} ns of low, below RES {RES_MIN_NS:.0f} ns"))

        frames: List[Frame] = []
        current = Frame()
        for i, t_rise in enumerate(rises):
            j = bisect_right(falls, t_rise)
            fall = falls[j] if j < len(falls) else None
            if fall is None:
                violations.append(Violation(t_rise, "high", "the line is still high when the waveform ends"))
                break
            high = fall - t_rise
            if _inside(high, T0H_WINDOW):
                value, code = 0, "T0"
            elif _inside(high, T1H_WINDOW):
                value, code = 1, "T1"
            else:
                value, code = None, None
                violations.append(Violation(
                    t_rise, "high",
                    f"high {high:.0f} ns is in neither T0H {T0H_WINDOW} nor T1H {T1H_WINDOW}"))
            if code:
                widths[code + "H"].append(high)
            next_rise = rises[i + 1] if i + 1 < len(rises) else None
            low = (next_rise if next_rise is not None else t_end) - fall
            bit = Bit(t_rise, high, low if next_rise is not None else None, value)
            current.bits.append(bit)

            if low >= RES_MIN_NS:
                # reset: the frame ends with this bit and is latched
                widths["reset"].append(low)
                current.latched = True
                frames.append(current)
                current = Frame()
                continue
            if next_rise is None:
                # the waveform ends inside this bit's low, before a reset
                frames.append(current)
                current = None
                break
            lwin = T0L_WINDOW if value == 0 else T1L_WINDOW if value == 1 else None
            if lwin is not None:
                if _inside(low, lwin):
                    widths[code + "L"].append(low)
                else:
                    violations.append(Violation(
                        fall, "low",
                        f"{code}L low {low:.0f} ns outside {lwin} and below RES"))
            if not _inside(high + low, PERIOD_WINDOW):
                violations.append(Violation(
                    t_rise, "period",
                    f"bit period {high + low:.0f} ns outside {PERIOD_WINDOW}"))
            else:
                widths["bit"].append(high + low)
        if current is not None and current.bits:
            frames.append(current)

        for f in frames:
            if len(f.bits) % BITS_PER_PIXEL:
                violations.append(Violation(
                    f.bits[0].t_rise, "partial-pixel",
                    f"frame of {len(f.bits)} bits is not a whole number of 24-bit pixels"))
        return Decode(frames, violations, leading, widths)


# --- an encoder, for the model's own self-checks and negative controls ---


def encode_frame(sig, pixels, t0: float, *, t0h=T0H_NS, t1h=T1H_NS, t0l=T0L_NS,
                 t1l=T1L_NS, reset_ns=RES_MIN_NS + 10_000.0, drop_bit_at=None):
    """Append one frame (and its trailing reset) to `sig` starting at `t0`
    (the line must be low). Returns the time the reset ends. The keyword
    arguments let a caller build a mistimed or damaged frame on purpose."""
    t = t0
    n = 0
    for g, r, b in pixels:
        word = (g << 16) | (r << 8) | b
        for k in range(BITS_PER_PIXEL - 1, -1, -1):
            if drop_bit_at is not None and n == drop_bit_at:
                n += 1
                continue
            n += 1
            one = (word >> k) & 1
            high, low = (t1h, t1l) if one else (t0h, t0l)
            sig.add(t, 1)
            sig.add(t + high, 0)
            t += high + low
    # the last bit's low merges into the reset
    return t + reset_ns
