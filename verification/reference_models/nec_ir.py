"""Independent NEC infrared remote-control receiver model (issue #448,
multi-protocol extra credit, catalog #443).

Written from the NEC protocol description alone (the SB Projects knowledge
page `docs/protocols.md` #443 cites for the row: leader 9 ms mark + 4.5 ms
space, 562.5-us marks, 562.5-us / 1,687.5-us spaces, 32 bits address /
inverted address / command / inverted command MSB-first, a 9 ms + 2.25 ms +
562.5-us repeat code, all on a 38 kHz carrier). It imports nothing from
`rtl/`, `src/`, `firmware/` or any bench, and knows nothing about this
design's ISA, clock or cycle counts. Its input is a `waveform.Signal` in
nanoseconds -- the TRANSMITTER'S OWN PIN, carrier and all, because that is
what the bench can observe; its output is the frames (and repeat codes) a
demodulating receiver module plus an NEC decoder would recover, plus every
timing violation it saw.

The two-stage shape
-------------------
A real receiving end is a 38 kHz demodulating module (its output is the
envelope: high while carrier bursts arrive, idle high between frames is a
property of the module's output stage, modelled here as low = no carrier)
followed by NEC pulse-distance decoding. The model does both:

1. **Demodulate.** The envelope rises at a rising edge of the pin and
   falls at a falling edge that is *not* followed by another rise within
   the demodulator's hold-off -- a low of at least 0.9 nominal carrier
   periods ends the mark (a commodity module's hold-off is one period
   class; the in-burst low of a 1/3-duty carrier is 2/3 of a period, and
   the first low of any space is a whole bit space). Every *complete*
   carrier period inside a mark (rise to next rise, both within the mark)
   is graded against the carrier window. Two kinds of period are not
   graded: a mark's final burst, whose low becomes the envelope edge (the
   period that would span a mark's end does not exist), and a *burst
   junction* -- a low shorter than a quarter of the nominal period, which
   is a transmitter restarting its burst counter mid-mark (below any
   hold-off; the mark continues through it). A mark with no complete
   carrier period at all is an unmodulated pulse and a violation.

2. **Decode NEC.** Marks and spaces of the envelope are classified by
   width and checked:

   | piece            | nominal      | window (the model's stated tolerance) |
   |------------------|--------------|---------------------------------------|
   | leader mark      | 9,000 ns x1e3| +-10%                                 |
   | leader space     | 4,500 ns x1e3| +-10%                                 |
   | repeat space     | 2,250 ns x1e3| +-10%                                 |
   | bit / final mark | 562.5 ns x1e3| +-10%                                 |
   | space of a 0     | 562.5 ns x1e3| +-10%                                 |
   | space of a 1     | 1,687.5 x1e3 | +-10%                                 |
   | carrier period   | 1/38 kHz     | +-5% (a demodulator's passband)       |

   NEC publishes no numeric transmitter tolerances; +-10% is this model's
   stated grading choice, wide enough for any receiver (a 0-space and a
   1-space differ 3:1, so +-10% keeps a 2.7:1 discrimination margin) and
   narrow enough that a 15% mistiming fails, as the bench's stretched
   negative control shows. The carrier window is the passband a commodity
   38 kHz module quotes.

A frame is 32 bits, MSB first: address, inverted address, command,
inverted command. Both complement pairs are checked -- a bad inverted byte
is a violation, not a decode guess. A repeat code (leader-class mark +
2.25-ms-class space + one bit-class mark) is reported as a repeat, not a
frame. A frame whose 33rd mark arrives early, or whose capture ends
mid-frame, is a violation; a frame needs the final mark plus a trailing
silence of at least the leader-space window's floor to count as complete
(`latched`), the analogue of ws2812's reset latch.

The windows are closed intervals: a width exactly on a window edge passes.
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .waveform import Signal

# --- the protocol's numbers, in ns ---------------------------------------
CARRIER_HZ = 38_000.0
CARRIER_TOL_PCT = 5.0
LEADER_MARK_NS = 9_000_000.0
LEADER_SPACE_NS = 4_500_000.0
REPEAT_SPACE_NS = 2_250_000.0
BIT_MARK_NS = 562_500.0
SPACE0_NS = 562_500.0
SPACE1_NS = 1_687_500.0
TIMING_TOL_PCT = 10.0
FRAME_BITS = 32
#: A frame's trailing silence must be at least the leader-space floor for
#: the frame to count as complete (a receiver needs the gap to commit it).
FRAME_SILENCE_MIN_NS = LEADER_SPACE_NS * (1.0 - TIMING_TOL_PCT / 100.0)

CARRIER_PERIOD_NS = 1e9 / CARRIER_HZ
#: A low this long (with no further rise) ends a mark: 0.9 carrier periods.
DEMOD_GAP_NS = 0.9 * CARRIER_PERIOD_NS
#: A low shorter than this inside a mark is a burst junction (the mark
#: continues; the period across it is not graded): a quarter period.
BURST_JUNCTION_NS = 0.25 * CARRIER_PERIOD_NS


def window(nominal: float, tol_pct: float) -> Tuple[float, float]:
    return (nominal * (1.0 - tol_pct / 100.0), nominal * (1.0 + tol_pct / 100.0))


LEADER_MARK_WIN = window(LEADER_MARK_NS, TIMING_TOL_PCT)
LEADER_SPACE_WIN = window(LEADER_SPACE_NS, TIMING_TOL_PCT)
REPEAT_SPACE_WIN = window(REPEAT_SPACE_NS, TIMING_TOL_PCT)
BIT_MARK_WIN = window(BIT_MARK_NS, TIMING_TOL_PCT)
SPACE0_WIN = window(SPACE0_NS, TIMING_TOL_PCT)
SPACE1_WIN = window(SPACE1_NS, TIMING_TOL_PCT)
CARRIER_WIN = window(CARRIER_PERIOD_NS, CARRIER_TOL_PCT)


def _inside(value: float, bounds: Tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


@dataclass
class Violation:
    t: float
    kind: str   # carrier / mark / leader-space / repeat-space / space /
                # bit-count / complement / gap / no-carrier
    detail: str


@dataclass
class Frame:
    t_leader: float
    bits: List[int] = field(default_factory=list)
    complete: bool = False
    latched: bool = False

    @property
    def addr(self) -> Optional[int]:
        if len(self.bits) < 8:
            return None
        return int("".join(str(b) for b in self.bits[0:8]), 2)

    @property
    def inv_addr(self) -> Optional[int]:
        if len(self.bits) < 16:
            return None
        return int("".join(str(b) for b in self.bits[8:16]), 2)

    @property
    def cmd(self) -> Optional[int]:
        if len(self.bits) < 24:
            return None
        return int("".join(str(b) for b in self.bits[16:24]), 2)

    @property
    def inv_cmd(self) -> Optional[int]:
        if len(self.bits) < 32:
            return None
        return int("".join(str(b) for b in self.bits[24:32]), 2)


@dataclass
class Decode:
    frames: List[Frame]
    repeats: List[float]
    violations: List[Violation]
    pulse_widths: dict          # kind -> [measured ns], for the record
    carrier_periods: List[float]

    @property
    def latched_frames(self) -> List[Frame]:
        return [f for f in self.frames if f.latched]


class NecIrDecoder:
    """Decode and grade a transmitter pin carrying NEC infrared."""

    def decode(self, sig: Signal, t_start: float, t_end: float) -> Decode:
        edges = [(t, v) for (t, v) in sig.transitions if t_start <= t <= t_end]
        violations: List[Violation] = []
        if sig.value_at(t_start) != 0:
            violations.append(Violation(t_start, "mark",
                                        "the pin is not idle low at the start"))
        rises = [t for (t, v) in edges if v == 1]
        falls = [t for (t, v) in edges if v == 0]

        # ---- stage 1: demodulate the envelope off the carrier ----
        marks: List[Tuple[float, float]] = []       # (rise, fall) per mark
        carrier: List[float] = []
        i = 0
        while i < len(rises):
            rise = rises[i]
            last_rise = rise
            j = i
            while True:
                idx = bisect_right(falls, last_rise)
                fall = falls[idx] if idx < len(falls) else None
                nxt = rises[j + 1] if j + 1 < len(rises) else None
                if fall is None:
                    violations.append(Violation(
                        last_rise, "mark", "the pin is still high when the waveform ends"))
                    marks.append((rise, t_end))
                    j += 1
                    break
                if nxt is not None and nxt - fall < DEMOD_GAP_NS:
                    if nxt - fall >= BURST_JUNCTION_NS:
                        carrier.append(nxt - last_rise)
                    last_rise = nxt
                    j += 1
                    continue
                marks.append((rise, fall))
                j += 1
                break
            i = j
        for p in carrier:
            if not _inside(p, CARRIER_WIN):
                violations.append(Violation(
                    0.0, "carrier",
                    f"carrier period {p:.0f} ns outside {CARRIER_WIN}"))
        for (rise, fall) in marks:
            inner = [r for r in rises if rise < r < fall]
            if not inner:
                violations.append(Violation(
                    rise, "no-carrier",
                    "a mark with no complete carrier period (an unmodulated pulse)"))
        widths = {"leader_mark": [], "leader_space": [], "repeat_space": [],
                  "bit_mark": [], "space0": [], "space1": [], "silence": []}

        # ---- stage 2: the NEC protocol, over the envelope ----
        frames: List[Frame] = []
        repeats: List[float] = []
        k = 0
        while k < len(marks):
            rise, fall = marks[k]
            width = fall - rise
            # the next mark (None inside the trailing silence)
            n_rise = marks[k + 1][0] if k + 1 < len(marks) else None
            if _inside(width, LEADER_MARK_WIN):
                widths["leader_mark"].append(width)
                if k + 1 >= len(marks):
                    break  # the capture ends inside the leader's space: a
                           # capture boundary, not a transmitter defect
                space = marks[k + 1][0] - fall
                if _inside(space, LEADER_SPACE_WIN):
                    widths["leader_space"].append(space)
                    k = self._decode_frame(marks, k, t_end, widths, violations, frames)
                    continue
                if _inside(space, REPEAT_SPACE_WIN):
                    widths["repeat_space"].append(space)
                    # one bit-class mark completes the repeat code
                    if n_rise is not None and _inside(marks[k + 1][1] - n_rise, BIT_MARK_WIN):
                        widths["bit_mark"].append(marks[k + 1][1] - n_rise)
                        repeats.append(rise)
                        k += 2
                        continue
                    violations.append(Violation(
                        fall, "mark", "a repeat-code space not followed by its mark"))
                    k += 1
                    continue
                violations.append(Violation(
                    fall, "leader-space",
                    f"space {space:.0f} ns after the leader is in neither the "
                    f"frame window {LEADER_SPACE_WIN} nor the repeat window {REPEAT_SPACE_WIN}"))
                k += 1
                continue
            if _inside(width, BIT_MARK_WIN):
                violations.append(Violation(
                    rise, "bit-count", "a bit mark before any leader"))
                k += 1
                continue
            violations.append(Violation(
                rise, "mark",
                f"mark {width:.0f} ns is neither a leader ({LEADER_MARK_WIN}) "
                f"nor a bit ({BIT_MARK_WIN})"))
            k += 1
        return Decode(frames, repeats, violations, widths, carrier)

    def _decode_frame(self, marks, k, t_end, widths, violations, frames) -> int:
        """Decode one data frame starting at leader mark `k`; returns the
        index of the first unconsumed mark."""
        frame = Frame(t_leader=marks[k][0])
        k += 1
        while len(frame.bits) < FRAME_BITS:
            if k >= len(marks):
                frame.complete = False
                self._partial(frame, violations)
                frames.append(frame)
                return k
            rise, fall = marks[k]
            width = fall - rise
            if not _inside(width, BIT_MARK_WIN):
                if _inside(width, LEADER_MARK_WIN):
                    # the next frame started before this one had 32 bits
                    self._partial(frame, violations)
                    frames.append(frame)
                    return k
                violations.append(Violation(
                    rise, "mark", f"bit mark {width:.0f} ns outside {BIT_MARK_WIN}"))
                frame.complete = False
                frames.append(frame)
                return k + 1
            widths["bit_mark"].append(width)
            n_rise = marks[k + 1][0] if k + 1 < len(marks) else None
            if n_rise is None:
                # the capture ends inside this bit's space: the frame is
                # truncated by the waveform, not mistimed by the sender
                self._partial(frame, violations)
                frames.append(frame)
                return k + 1
            space = n_rise - fall
            if _inside(space, SPACE0_WIN):
                widths["space0"].append(space)
                frame.bits.append(0)
            elif _inside(space, SPACE1_WIN):
                widths["space1"].append(space)
                frame.bits.append(1)
            else:
                violations.append(Violation(
                    fall, "space",
                    f"bit space {space:.0f} ns in neither {SPACE0_WIN} nor {SPACE1_WIN}"))
                frame.complete = False
                frames.append(frame)
                return k + 1
            # the 32nd bit's space is followed by the frame's final mark
            if len(frame.bits) == FRAME_BITS:
                if k + 1 >= len(marks) or not _inside(marks[k + 1][1] - marks[k + 1][0],
                                                      BIT_MARK_WIN):
                    violations.append(Violation(
                        fall, "bit-count", "no final mark after the 32nd bit"))
                    frame.complete = False
                    frames.append(frame)
                    return min(k + 1, len(marks))
                final_rise, final_fall = marks[k + 1]
                widths["bit_mark"].append(final_fall - final_rise)
                after = (marks[k + 2][0] if k + 2 < len(marks) else t_end) - final_fall
                frame.complete = True
                frame.latched = after >= FRAME_SILENCE_MIN_NS
                widths["silence"].append(min(after, t_end - final_fall))
                self._complement(frame, violations)
                frames.append(frame)
                return k + 2
            k += 1
        return k

    @staticmethod
    def _partial(frame: Frame, violations: List[Violation]) -> None:
        violations.append(Violation(
            frame.t_leader, "bit-count",
            f"frame carries {len(frame.bits)} of {FRAME_BITS} bits"))

    @staticmethod
    def _complement(frame: Frame, violations: List[Violation]) -> None:
        if frame.addr is None or frame.inv_addr is None:
            return
        if (frame.addr ^ frame.inv_addr) != 0xFF:
            violations.append(Violation(
                frame.t_leader, "complement",
                f"address 0x{frame.addr:02X} with inverted byte 0x{frame.inv_addr:02X}"))
        if (frame.cmd ^ frame.inv_cmd) != 0xFF:
            violations.append(Violation(
                frame.t_leader, "complement",
                f"command 0x{frame.cmd:02X} with inverted byte 0x{frame.inv_cmd:02X}"))


# --- an encoder, for the model's own self-checks and negative controls ---


def _burst(sig: Signal, t: float, n: int, period: float, hi: float) -> float:
    """n carrier periods starting at `t`; returns the time of the last
    falling edge (the mark a demodulator recovers ends there)."""
    for _ in range(n - 1):
        sig.add(t, 1)
        sig.add(t + hi, 0)
        t += period
    sig.add(t, 1)
    t += hi
    sig.add(t, 0)
    return t


def _periods_for(mark_ns: float, period: float, hi: float) -> int:
    return max(1, round((mark_ns - hi) / period) + 1)


def encode_frame(sig: Signal, addr: int, cmd: int, t0: float = 0.0, *,
                 lead_ns: float = 20_000_000.0,
                 carrier_period_ns: float = CARRIER_PERIOD_NS,
                 duty: float = 1.0 / 3.0,
                 leader_mark_ns: float = LEADER_MARK_NS,
                 leader_space_ns: float = LEADER_SPACE_NS,
                 bit_mark_ns: float = BIT_MARK_NS,
                 space0_ns: float = SPACE0_NS,
                 space1_ns: float = SPACE1_NS,
                 inv_addr: Optional[int] = None,
                 inv_cmd: Optional[int] = None,
                 stop_after_bits: Optional[int] = None) -> float:
    """Append one NEC frame to `sig` starting after `lead_ns` of silence
    (the line must be low at `t0`). Returns the end time. Marks are whole
    carrier periods nearest their nominal width; spaces are exact. The
    keyword arguments let a caller build a mistimed or damaged frame on
    purpose (bad inverted bytes, a truncated bit count, off-nominal
    widths, a wrong carrier)."""
    hi = carrier_period_ns * duty
    t = t0 + lead_ns
    t = _burst(sig, t, _periods_for(leader_mark_ns, carrier_period_ns, hi), carrier_period_ns, hi)
    t += leader_space_ns
    bits = []
    for byte in (addr, 0xFF - addr if inv_addr is None else inv_addr,
                 cmd, 0xFF - cmd if inv_cmd is None else inv_cmd):
        bits.extend((byte >> i) & 1 for i in range(7, -1, -1))
    n = 0
    for b in bits:
        if stop_after_bits is not None and n >= stop_after_bits:
            return t
        n += 1
        t = _burst(sig, t, _periods_for(bit_mark_ns, carrier_period_ns, hi),
                   carrier_period_ns, hi)
        t += space1_ns if b else space0_ns
    # the final mark
    t = _burst(sig, t, _periods_for(bit_mark_ns, carrier_period_ns, hi),
               carrier_period_ns, hi)
    return t


def encode_repeat(sig: Signal, t0: float = 0.0, *,
                  carrier_period_ns: float = CARRIER_PERIOD_NS,
                  duty: float = 1.0 / 3.0,
                  leader_mark_ns: float = LEADER_MARK_NS,
                  repeat_space_ns: float = REPEAT_SPACE_NS,
                  bit_mark_ns: float = BIT_MARK_NS) -> float:
    """Append one NEC repeat code (leader + 2.25 ms + one mark)."""
    hi = carrier_period_ns * duty
    t = t0
    t = _burst(sig, t, _periods_for(leader_mark_ns, carrier_period_ns, hi), carrier_period_ns, hi)
    t += repeat_space_ns
    return _burst(sig, t, _periods_for(bit_mark_ns, carrier_period_ns, hi),
                  carrier_period_ns, hi)
