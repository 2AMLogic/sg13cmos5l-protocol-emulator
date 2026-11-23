"""Independent CAN 2.0A (classic, 11-bit identifier) model (issue #450,
multi-protocol extra credit, catalog #443).

Written from the ISO 11898-1 / CiA framing description alone: a standard
data frame is SOF (dominant), an 11-bit identifier MSB first, RTR
(dominant for a data frame), IDE (dominant, standard), r0 (dominant), a
4-bit DLC, zero to eight data bytes MSB first within each byte, a 15-bit
CRC sequence (polynomial 0x4599, seed 0, computed over the destuffed bits
SOF..last data bit, transmitted MSB first), a recessive CRC delimiter, a
recessive ACK slot (any receiver that passes the CRC drives it dominant),
a recessive ACK delimiter, seven recessive EOF bits and three recessive
intermission bits. Bit stuffing runs from the SOF through the CRC
sequence: after five consecutive equal bits on the wire the transmitter
inserts one complement bit, and the run count restarts at the stuff bit.
It imports nothing from `rtl/`, `src/`, `firmware/` or any bench, and
knows nothing about this design's ISA, clock or cycle counts. Its input is
a `waveform.Signal` in nanoseconds; its output is the frames a CAN
receiver would accept plus every violation it saw.

Two CRC-15 implementations, one verdict
---------------------------------------
`crc15_shift` is the driven shift register (feedback = data XOR the top
state bit, state = state<<1 XOR poly-on-feedback) and `crc15_divide` is
bit-by-bit polynomial long division of the message followed by fifteen
zero bits. They agree on every input (the model's self-test checks this
on random messages), and the classic algebraic property -- feeding a
message *and its CRC sequence* through the register leaves zero -- is what
a receiver checks on the wire. No published CAN test vector is quoted from
memory; the two independent constructions plus the zero property are the
oracle, in the same spirit as `dmx512.py`'s derived drift bound.

What the timing measurement can and cannot see
----------------------------------------------
Classic CAN receivers resynchronise on every recessive-to-domininant edge
and sample once per bit at the nominal sample point (75% here, the
mid-range of the 50-90% a real node's clock-segment setup produces). This
model does the same: the phase resets at every falling edge, and each bit
is sampled at 75% of the nominal period after its start. A bit whose
measured period deviates from nominal by more than ``MAX_BIT_DEV_PCT`` is
flagged even when its sample still reads back correctly -- ISO 11898-1
states oscillator-tolerance bounds only in terms of a node's time quantum
setup (SJW and segment lengths), which a whole-bit firmware node does not
have, so the bound here is derived from the sampling alone: with a 75%
sample point the receiving window is (0, 100%) of the period and a
one-sided drift past 25% would slide the sample into a neighbour bit;
15% is stated as the model's grading choice, tight enough that a 20%
stretch fails while any conformant transmitter passes. Cumulative drift
cannot build past one bit period because every falling edge resets the
phase -- exactly the hard-sync-plus-resync behaviour the DUT's receiver
half implements in firmware, at whole-bit granularity.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .waveform import Signal

#: The sample point, as a percentage of the bit time.
SAMPLE_PCT = 75.0

#: The model's stated per-bit period tolerance (see the module docstring).
MAX_BIT_DEV_PCT = 15.0

#: The CRC-15 polynomial without its x^15 term (CAN's 0x4599).
CRC15_POLY = 0x4599

#: Frame shape constants (bits).
ID_BITS = 11
DLC_BITS = 4
CRC_BITS = 15
EOF_BITS = 7
IFS_BITS = 3


# ---------------------------------------------------------------- the CRC
def crc15_shift(bits: List[int]) -> int:
    """CRC-15 by the driven shift register (the transmitter's form)."""
    state = 0
    for b in bits:
        fb = ((state >> 14) & 1) ^ b
        state = ((state << 1) & 0x7FFF) ^ (CRC15_POLY if fb else 0)
    return state


def crc15_divide(bits: List[int]) -> int:
    """CRC-15 by long division of the message followed by 15 zero bits."""
    work = 0
    for b in list(bits) + [0] * CRC_BITS:
        top = (work >> 14) & 1
        work = ((work << 1) | b) & 0x7FFF
        if top:
            work ^= CRC15_POLY
    return work


def crc15_check(bits_with_crc: List[int]) -> bool:
    """The receiver-side verdict: the register ends at zero."""
    return crc15_shift(bits_with_crc) == 0


# ------------------------------------------------------------- stuffing
def stuff_bits(bits: List[int]) -> List[int]:
    """Insert the stuff bit after every run of five equal bits."""
    out, run, last = [], 0, None
    for b in bits:
        if run == 5:
            s = 1 - last
            out.append(s)
            run, last = 1, s
        out.append(b)
        run = run + 1 if b == last else 1
        last = b
    return out


def destuff_bits(bits: List[int]) -> Tuple[List[int], Optional[int]]:
    """Remove stuff bits; returns (destuffed, error_index).

    ``error_index`` is the wire position of a sixth equal bit (a stuff
    error) if one is present, else None.
    """
    out, run, last = [], 0, None
    for i, b in enumerate(bits):
        if run == 5:
            if b == last:
                return out, i
            run, last = 1, b
            continue
        out.append(b)
        run = run + 1 if b == last else 1
        last = b
    return out, None


# ------------------------------------------------------------- encoding
def frame_bits(can_id: int, data: bytes, rtr: int = 0) -> List[int]:
    """The unstuffed bits SOF..last data bit, in transmission order."""
    assert 0 <= can_id < 0x800 and 0 <= len(data) <= 8
    bits = [0]
    bits += [(can_id >> i) & 1 for i in range(ID_BITS - 1, -1, -1)]
    bits += [rtr, 0, 0]
    bits += [(len(data) >> i) & 1 for i in range(DLC_BITS - 1, -1, -1)]
    for byte in data:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    return bits


def crc_sequence(bits: List[int]) -> List[int]:
    crc = crc15_shift(bits)
    return [(crc >> i) & 1 for i in range(CRC_BITS - 1, -1, -1)]


def encode_frame(can_id: int, data: bytes, rtr: int = 0):
    """A standard frame as (stuffed wire bits SOF..CRC sequence, tail bits).

    The tail is the ten fixed bits after the CRC sequence -- CRC
    delimiter, ACK slot, ACK delimiter and the seven EOF bits -- all
    recessive from a transmitter's point of view, with the intermission
    left to the caller's idle time.
    """
    bits = frame_bits(can_id, data, rtr)
    return stuff_bits(bits + crc_sequence(bits)), [1] * 10


# ------------------------------------------------------------- decoding
@dataclass
class CanFrame:
    t_start: float
    t_end: float
    can_id: int = 0
    rtr: int = 0
    dlc: int = 0
    data: List[int] = field(default_factory=list)
    crc_ok: Optional[bool] = None
    ack_slot_level: Optional[int] = None
    stuff_error_at: Optional[int] = None   # wire bit index


@dataclass
class Violation:
    kind: str    # "bit-timing" | "stuff" | "crc" | "form"
    detail: str
    t_ns: float


@dataclass
class DecodeResult:
    frames: List[CanFrame] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)


class CanReceiver:
    """Sample a TXD/RXD-shaped signal on a nominal bit grid.

    The receiver hard-syncs on the first falling edge out of idle,
    resynchronises its phase at every recessive-to-dominant edge, samples
    each bit at ``SAMPLE_PCT`` of the nominal period, and grades each
    sampled bit's period against the nominal by ``MAX_BIT_DEV_PCT``.
    """

    def __init__(self, period_ns: float, sample_pct: float = SAMPLE_PCT,
                 max_dev_pct: float = MAX_BIT_DEV_PCT):
        self.period = float(period_ns)
        self.sample_pct = sample_pct
        self.max_dev_pct = max_dev_pct

    # -- sampling ------------------------------------------------------
    def _sample_bits(self, sig: Signal, t0: float, t_end: float):
        """Sample the signal at the sample points of consecutive nominal
        bits from ``t0``; returns [(sample_time, level, bit_start)]."""
        out = []
        t = t0
        while t < t_end:
            out.append((t + self.period * self.sample_pct / 100.0,
                        sig.value_at(t + self.period * self.sample_pct / 100.0),
                        t))
            # resync: the phase resets at a falling edge inside the bit
            nxt = t + self.period
            for (et, ev) in sig.transitions:
                if t < et < nxt and ev == 0:
                    nxt = et + self.period
            t = nxt
        return out

    def decode(self, sig: Signal, t_start: float, t_end: float) -> DecodeResult:
        res = DecodeResult()
        t = t_start
        while t < t_end:
            # wait for a falling edge (SOF) out of a recessive idle
            edge = None
            for (et, ev) in sig.transitions:
                if et >= t and ev == 0:
                    edge = et
                    break
            if edge is None or edge >= t_end:
                break
            self._decode_frame(sig, edge, t_end, res)
            if res.frames and res.frames[-1].t_end > t:
                t = res.frames[-1].t_end
            else:
                t = edge + self.period
        return res

    def _decode_frame(self, sig: Signal, sof: float, t_end: float,
                      res: DecodeResult) -> None:
        # cap the capture at a DLC-8 frame's worst case (stuffed) + tail
        n_max = (1 + ID_BITS + 3 + DLC_BITS + 8 * 8 + CRC_BITS) * 6 // 5 + 10 + 4
        bits = self._sample_bits(sig, sof, min(sof + n_max * self.period, t_end))
        if len(bits) < 19:
            return
        levels = [b[1] for b in bits]
        # per-bit timing: consecutive bit starts vs the nominal period
        prev_start = None
        for (_st, _lvl, bs) in bits:
            if prev_start is not None:
                dev = abs((bs - prev_start) - self.period) / self.period * 100.0
                if dev > self.max_dev_pct:
                    res.violations.append(Violation(
                        "bit-timing",
                        f"bit period {(bs - prev_start) / self.period:.3f} x nominal",
                        prev_start))
            prev_start = bs
        # walk the wire destuffing until the frame's destuffed length (per
        # its own DLC) is collected; the rest is the unstuffed tail
        frame = CanFrame(t_start=sof, t_end=sof)
        destuff, run, last, need, tail_start, err_at = [], 0, None, 19, None, None
        for i, b in enumerate(levels):
            if len(destuff) == 19 and need == 19:
                dlc = (destuff[15] << 3) | (destuff[16] << 2) | (destuff[17] << 1) | destuff[18]
                need = 19 + 8 * dlc + CRC_BITS
            if len(destuff) == need:
                tail_start = i
                break
            if run == 5:
                if b == last:
                    err_at = i
                    break
                run, last = 1, b
                continue
            destuff.append(b)
            run = run + 1 if b == last else 1
            last = b
        if err_at is not None:
            frame.stuff_error_at = err_at
            res.violations.append(Violation(
                "stuff", f"six equal bits at wire bit {err_at}",
                bits[err_at][0]))
            frame.t_end = bits[min(err_at + 1, len(bits) - 1)][2] + self.period
            res.frames.append(frame)
            return
        if tail_start is None or len(destuff) < need:
            return
        body = destuff
        frame.crc_ok = crc15_check(body)
        if not frame.crc_ok:
            res.violations.append(Violation("crc", "nonzero CRC remainder", sof))
        frame.can_id = 0
        for k in range(ID_BITS):
            frame.can_id = (frame.can_id << 1) | body[1 + k]
        frame.rtr = body[12]
        frame.dlc = (body[15] << 3) | (body[16] << 2) | (body[17] << 1) | body[18]
        frame.data = [sum(body[19 + 8 * m + k] << (7 - k) for k in range(8))
                      for m in range(frame.dlc)]
        if tail_start + 10 <= len(levels):
            tail = levels[tail_start:tail_start + 10]
            frame.ack_slot_level = tail[1]
            for i, b in enumerate(tail):
                if i != 1 and b != 1:
                    res.violations.append(Violation(
                        "form", f"tail bit {i} is dominant (must be recessive)",
                        bits[tail_start + i][0]))
                    break
            frame.t_end = bits[tail_start + 9][2] + self.period
        else:
            frame.t_end = bits[-1][2] + self.period
        res.frames.append(frame)
