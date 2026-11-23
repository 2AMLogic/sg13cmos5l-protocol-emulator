"""Independent DMX512 receiver model (issue #445, multi-protocol extra
credit, catalog #443).

Written from the USITT DMX512-A protocol conventions alone (the 1986
spec's framing as carried forward by ANSI E1.11, and the transmitter
timing guidance ETC publishes for controllers). It imports nothing from
`rtl/`, `src/`, `firmware/` or any bench, and knows nothing about this
design's ISA, clock or cycle counts. Its input is a `waveform.Signal` in
nanoseconds; its output is the packets a DMX512 receiver would accept --
BREAK width, mark-after-break width, the start code, and one report per
channel slot -- plus every timing or framing violation it saw.

The protocol's numbers, in ns
-----------------------------
* Bit period 4000 ns: 250 kbaud, the DMX512 rate. Each slot is one low
  start bit, eight data bits LSB first, and TWO high stop bits (11 bits).
* BREAK: the line low. The 1986 spec's 88 us is what a *receiver* must
  recognise; a controller is directed to drive longer (the issue sets
  >= 92 us / >= 12 us for this transmitter), so the model grades against
  the receiver limit and the bench grades its own stricter controller
  target on top.
* Mark-after-break: the line high between the BREAK and the first slot,
  at least 8000 ns by the same reading.
* Universe: the BREAK, the mark, one start-code slot, then up to 512
  channel slots. The start code is slot 0 and is 0x00 for a dimmer
  universe; the model reports it and lets the caller compare.

What the timing measurement can and cannot see
----------------------------------------------
E1.11 publishes no numeric bit-rate tolerance for a transmitter, so the
model adopts the bound its sampling implies: a DMX receiver resynchronises
on every slot's start edge (as a UART receiver does per frame), samples
each of the 11 bits at its nominal centre, and needs the cumulative drift
across a slot's 10 bit periods to stay under half a bit or the last sample
lands in the wrong bit. Half a bit over 10 periods is 5%, so a slot whose
edges drift past ``MAX_SLOT_DRIFT_PCT`` of the bit period is flagged even
when every sampled bit still reads back correctly -- the same shape as
target-spec row 10's UART drift bound, derived rather than cited.

The one thing the mark between slots cannot be checked against is a
maximum: idle time between slots is legal, so a LATE next start is
accepted like UART idle; an EARLY one (the next start edge before the
current slot's second stop bit has been sampled) shortens a stop bit and
is the malformed boundary the bench exercises.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from .waveform import Signal

#: DMX512's 250 kbaud bit period.
BIT_PERIOD_NS = 4000.0

#: Bits per slot: one start, eight data, two stop (8N2).
SLOT_BITS = 11
DATA_BITS = 8
STOP_BITS = 2

#: The BREAK a receiver must recognise (the 1986 spec's figure); the
#: model grades every measured BREAK against this.
BREAK_MIN_NS = 88_000.0

#: The mark-after-break a receiver requires.
MAB_MIN_NS = 8_000.0

#: Slots per full universe: the start code plus 512 channels.
UNIVERSE_SLOTS = 513

#: Slots a receiver must tolerate before treating a packet as over-long
#: is not modelled: E1.11 permits any count up to 512 channels and the
#: caller compares the count it expects.

#: Per-slot cumulative drift bound (% of the bit period), derived above:
#: half a bit of slip over the 10 bit periods a receiver samples across.
MAX_SLOT_DRIFT_PCT = 5.0


@dataclass
class SlotReport:
    """One decoded slot: its recovered byte and its timing measurement."""

    #: Index within the packet's slot stream: 0 is the start code.
    index: int
    #: The recovered data byte.
    data: int
    #: Time of the slot's start edge (the falling edge), ns.
    t_start: float
    #: The two stop-bit samples (each 1 when the line was high).
    stop_samples: tuple
    #: Cumulative actual-vs-nominal drift of the slot's last in-slot edge,
    #: as % of the bit period (None when the slot has no measurable edge).
    drift_pct: Optional[float]
    #: Start-to-start distance to the following slot, in bit periods
    #: (None when no following slot exists before the next BREAK).
    pitch_periods: Optional[float]

    def __repr__(self):
        stops = ",".join(str(s) for s in self.stop_samples)
        drift = "n/a" if self.drift_pct is None else f"{self.drift_pct:.3f}%"
        pitch = "n/a" if self.pitch_periods is None else f"{self.pitch_periods:.3f}"
        return (
            f"SlotReport(index={self.index}, data=0x{self.data:02x}, "
            f"t_start={self.t_start:.0f}ns, stops=({stops}), "
            f"drift={drift}, pitch={pitch})"
        )


@dataclass
class Packet:
    """One DMX512 packet: a BREAK, its mark, the start code, the slots."""

    break_ns: float
    mab_ns: Optional[float]
    t_break_fall: float
    t_break_rise: float
    slots: List[SlotReport] = field(default_factory=list)


@dataclass
class Violation:
    """One protocol violation the receiver saw, with its time and kind."""

    t: float
    kind: str      # "mab", "stop", "short-pitch", "trailing"
    detail: str

    def __repr__(self):
        return f"Violation(t={self.t:.0f}ns, kind={self.kind!r}, {self.detail})"


@dataclass
class Decode:
    """Everything the receiver saw: packets, violations, trailing state."""

    packets: List[Packet]
    violations: List[Violation]
    #: True when the capture ends cleanly (inside idle or a stop-bit mark),
    #: False when it ends mid-slot or mid-BREAK.
    ends_clean: bool


class Dmx512Receiver:
    """A nominal-rate DMX512 receiver measuring per-slot drift.

    The period may be left at the protocol's 4000 ns or set from the
    caller's own cycle arithmetic; every measured width and drift is in
    nanoseconds against this nominal grid, exactly like `UartDecoder`.
    """

    def __init__(self, period_ns: float = BIT_PERIOD_NS,
                 break_min_ns: float = BREAK_MIN_NS,
                 mab_min_ns: float = MAB_MIN_NS):
        self.period = float(period_ns)
        self.break_min = float(break_min_ns)
        self.mab_min = float(mab_min_ns)

    # ------------------------------------------------------------ decoding
    def decode(self, line: Signal) -> Decode:
        """Decode every packet in the waveform."""
        edges = line.transitions
        violations: List[Violation] = []
        packets: List[Packet] = []

        falls = [t for (t, v) in edges if v == 0]
        rises = [t for (t, v) in edges if v == 1]

        def next_rise_after(t):
            for r in rises:
                if r > t:
                    return r
            return None

        def next_fall_from(t):
            for f in falls:
                if f > t:
                    return f
            return None

        ends_clean = True
        i = 0
        while i < len(falls):
            f = falls[i]
            r = next_rise_after(f)
            if r is None:
                # capture ends inside a low: unmeasurable, not graded
                violations.append(Violation(
                    f, "trailing",
                    "the capture ends inside a low whose width cannot be measured"))
                ends_clean = False
                break
            low = r - f
            if low >= self.break_min:
                # a BREAK: open a packet and find the mark's end
                packet = Packet(break_ns=low, mab_ns=None,
                                t_break_fall=f, t_break_rise=r)
                packets.append(packet)
                f_slot = next_fall_from(r)
                if f_slot is None:
                    violations.append(Violation(
                        r, "trailing",
                        "the capture ends inside the mark after a BREAK"))
                    ends_clean = False
                    break
                packet.mab_ns = f_slot - r
                if packet.mab_ns < self.mab_min:
                    violations.append(Violation(
                        r, "mab",
                        f"mark-after-break {packet.mab_ns:.0f} ns is below "
                        f"the {self.mab_min:.0f} ns receiver limit"))
                i = falls.index(f_slot)
                continue
            if not packets:
                # a short low before any BREAK: pre-history (e.g. the pin's
                # reset value before the controller's first idle), skipped.
                # A LOW CANNOT BE TOLD FROM A SLOT START below the BREAK
                # limit: a 0x00 slot's start-plus-data low runs nine
                # periods, so any shorter low is decoded as a slot and let
                # the stop-bit sampling flag it, exactly as a receiver
                # resynchronising per start edge would.
                i += 1
                continue
            # a slot start edge within the current packet
            packet = packets[-1]
            index = len(packet.slots)
            # resynchronise on the next falling edge after stop bit 1's
            # sample: a legal transmitter's next edge is the next slot's
            # start (or a BREAK); a short one is the malformed boundary
            # and is decoded as a slot so its pitch can be graded
            resume = f + (1 + DATA_BITS + 0.5) * self.period
            nxt = next((t2 for t2 in falls if t2 >= resume), None)
            report, slot_violations = self._decode_slot(
                line, packet, index, f, r, next_fall_from_after=nxt)
            packet.slots.append(report)
            violations.extend(slot_violations)
            i = next((j for j, t2 in enumerate(falls) if t2 >= resume),
                     len(falls))

        return Decode(packets=packets, violations=violations, ends_clean=ends_clean)

    # ------------------------------------------------------------ one slot
    def _decode_slot(self, line, packet, index, f, r, next_fall_from_after):
        violations: List[Violation] = []
        period = self.period
        # Sample each bit at its nominal centre from the start edge. This is
        # the receiver resynchronising per slot: no cumulation across slots.
        samples = [line.value_at(f + (k + 0.5) * period) for k in range(SLOT_BITS)]
        if samples[0] != 0:
            violations.append(Violation(
                f, "stop",
                "slot start edge is not a low level at the start-bit centre"))
        data = 0
        for k in range(DATA_BITS):
            data |= samples[1 + k] << k
        stops = (samples[1 + DATA_BITS], samples[1 + DATA_BITS + STOP_BITS - 1])
        if samples[1 + DATA_BITS] != 1:
            violations.append(Violation(
                f + (1 + DATA_BITS + 0.5) * period, "stop",
                f"slot {index}: stop bit 1 sampled 0 (the next start edge came "
                f"before this slot's stop-bit sample)"))
        if samples[1 + DATA_BITS + STOP_BITS - 1] != 1:
            violations.append(Violation(
                f + (SLOT_BITS - 0.5) * period, "stop",
                f"slot {index}: stop bit 2 sampled 0"))

        # drift: the slot's last in-slot edge against its nominal position
        drift_pct = self._measure_drift(line, f)

        # pitch to the following slot, graded only when short (late is legal
        # idle): a next start edge before this slot's second stop-bit sample
        # has shortened a stop bit even if it also decoded fine
        pitch_periods = None
        nxt = next_fall_from_after
        if nxt is not None and nxt < f + (SLOT_BITS - 0.5) * period:
            pitch_periods = (nxt - f) / period
            violations.append(Violation(
                nxt, "short-pitch",
                f"slot {index + 1} starts after {pitch_periods:.2f} bit "
                f"periods, before slot {index}'s second stop-bit sample "
                f"(pitch below {SLOT_BITS - 0.5})"))
        elif nxt is not None:
            pitch_periods = (nxt - f) / period

        return SlotReport(index=index, data=data, t_start=f,
                          stop_samples=stops, drift_pct=drift_pct,
                          pitch_periods=pitch_periods), violations

    def _measure_drift(self, line, t_start):
        """The slot's last in-slot edge vs its nominal position, in % of a
        bit period. The last edge is the transmitter's final level change
        inside the 11-bit window -- the data-to-stop rise when the last
        data bit is 0, or the last data edge otherwise. None when no edge
        exists in the window."""
        last = None
        for (t, _v) in line.transitions:
            if t_start < t <= t_start + (SLOT_BITS - 1) * self.period:
                last = t
            elif t > t_start:
                break
        if last is None:
            return None
        k = round((last - t_start) / self.period)
        drift = last - (t_start + k * self.period)
        return 100.0 * abs(drift) / self.period

    # ------------------------------------------------------------- grading
    @staticmethod
    def check_slot(report: SlotReport,
                   max_slot_drift_pct: float = MAX_SLOT_DRIFT_PCT) -> bool:
        """True when a slot's framing and timing are inside the bounds:
        both stop bits sampled high and cumulative drift within
        ``max_slot_drift_pct`` of the bit period."""
        if any(s != 1 for s in report.stop_samples):
            return False
        if report.drift_pct is not None and report.drift_pct > max_slot_drift_pct:
            return False
        return True


# ------------------------------------------------------------- transmitter
def encode_packet(start_code, channel_levels, period_ns=BIT_PERIOD_NS,
                  break_ns=88_000.0, mab_ns=8_000.0, line=None, t0=0.0):
    """Append one packet's transitions to ``line`` at a nominal bit period:
    the BREAK low, the mark high, then one 8N2 slot per byte (start code
    first). Returns the time the mark after the last slot ends. This is the
    model-side transmitter used for round-trip and negative-control tests.
    """
    period = float(period_ns)
    t = float(t0)
    line.add(t, 0)
    t += break_ns
    line.add(t, 1)
    t += mab_ns
    for data in [start_code] + list(channel_levels):
        line.add(t, 0)                       # start bit
        t += period
        for k in range(DATA_BITS):
            line.add(t, (data >> k) & 1)     # data, LSB first
            t += period
        line.add(t, 1)                        # stop 1 begins (rise if D7 was 0)
        t += 2 * period                       # stop 1 + stop 2
    return t


def encode_one_stop_slot(levels, period_ns=BIT_PERIOD_NS,
                         line=None, t0=0.0):
    """Append a malformed stream to ``line``. ``t0`` is the instant the
    preceding mark ends (the previous packet's stop 2 end). Each slot in
    ``levels`` starts ONE BIT EARLY -- the previous slot keeps its first
    stop bit and loses its second to this slot's start edge -- except the
    final slot, which keeps both. This is the malformed boundary of issue
    #445's test plan: the preceding byte still decodes, its second
    stop-bit sample lands inside the next slot's start bit. Returns the
    time the final stop 2 ends."""
    period = float(period_ns)
    t = float(t0) - period          # the first start cuts the preceding mark
    for i, data in enumerate(levels):
        line.add(t, 0)               # start bit
        t += period
        for k in range(DATA_BITS):
            line.add(t, (data >> k) & 1)
            t += period
        line.add(t, 1)               # stop 1 begins
        t += period                  # stop 2 is cut by the next early start
    return t + period                # the final slot keeps its second stop
