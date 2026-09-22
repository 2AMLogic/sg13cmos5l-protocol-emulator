"""Independent I2C reference model (issue #25, verification-plan.md
section 4; target-spec rows 1 and 12).

Independence, per the plan: this model checks timing against NXP UM10204
"I2C-bus specification and user manual" Rev. 6 (2014), Table 10
(Standard/Fast-mode AC characteristics) **directly** -- the minimums below
are the standard's own numbers, transcribed, not this repo's DR 0001
cycle-budget arithmetic.  That is the whole point of an independent
reference: it does not trust this repo's own math.

Protocol shape modeled (controller role, the role target-spec row 12
binds): open-drain SCL/SDA idling high; START (SDA falls while SCL high)
held t_HD;STA; 7-bit address + R/W bit; data bytes each followed by a
9th-clock ACK/NACK slot (SDA low = ACK, sampled on the SCL rising edge);
an optional repeated START (Sr) after any byte (held t_SU;STA before and
t_HD;STA after); optional peripheral clock-stretching (SCL held low past a
clock's falling edge -- legal per UM10204 section 3.1.9, so the checker
reports stretched clocks and never counts them as violations); and STOP
(SCL rises, held t_SU;STO, then SDA rises while SCL high).

``t_BUF`` (bus-free time between a STOP and the next START) is not bound
by target-spec row 12's list and needs a second transfer in the window to
be measurable; it is out of scope for this model until the DUT-facing
suite drives multi-transfer traffic.
"""

UM10204_TABLE_10_NS = {
    # parameter: (Standard-mode minimum, Fast-mode minimum), Table 10, Rev. 6
    "t_LOW": (4700.0, 1300.0),
    "t_HIGH": (4000.0, 600.0),
    "t_HD;STA": (4000.0, 600.0),
    "t_SU;STA": (4700.0, 600.0),
    "t_SU;STO": (4000.0, 600.0),
    "t_BUF": (4700.0, 1300.0),
}

#: Margin the encoder uses above each Table-10 minimum so generated legal
#: traffic is legal by construction, with the headroom a real bus needs.
ENCODER_MARGIN = 1.2

#: How far into an SCL low period the encoder moves SDA (ns).  Data must
#: change only while SCL is low; a fixed offset keeps every SDA change
#: clear of the SCL edges for the checker's while-high START/STOP tests.
DATA_SHIFT_NS = 50.0

#: A clock whose SCL low period is at least this multiple of the Table-10
#: t_LOW minimum is reported as stretched (the stimulus generator's
#: non-stretched low is ENCODER_MARGIN x, so this threshold separates the
#: two unambiguously).
STRETCH_DETECT_FACTOR = 2.0


def minimum_ns(parameter, fast_mode):
    return UM10204_TABLE_10_NS[parameter][1 if fast_mode else 0]


class I2cReport:
    """What ``check_transfer`` found on the wires."""

    def __init__(self, address, read_bit, data_bytes, acks, stretched_clocks,
                 measurements, violations):
        self.address = address
        self.read_bit = read_bit
        self.data_bytes = data_bytes
        self.acks = acks
        self.stretched_clocks = stretched_clocks
        self.measurements = measurements
        self.violations = violations

    @property
    def ok(self):
        return not self.violations

    def __repr__(self):
        return (
            f"I2cReport(addr=0x{self.address:02x}{'R' if self.read_bit else 'W'}, "
            f"data={[f'0x{b:02x}' for b in self.data_bytes]}, acks={self.acks}, "
            f"stretched={self.stretched_clocks}, violations={self.violations!r})"
        )


class _Encoder:
    def __init__(self, scl, sda, fast_mode, stop_setup_factor=ENCODER_MARGIN):
        self.scl = scl
        self.sda = sda
        self.fast_mode = fast_mode
        self.stop_setup_factor = stop_setup_factor
        self.t = 0.0

    def min_ns(self, parameter):
        return minimum_ns(parameter, self.fast_mode)

    def clock_pulse(self, sda_level):
        """One data/ACK clock: SCL low (SDA moves mid-low), rise, high,
        fall.  ``sda_level`` is the bit's level for this whole pulse."""
        t = self.t
        self.scl.add(t, 0)
        self.sda.add(t + DATA_SHIFT_NS, sda_level)
        t += ENCODER_MARGIN * self.min_ns("t_LOW")
        self.scl.add(t, 1)
        t += ENCODER_MARGIN * self.min_ns("t_HIGH")
        self.scl.add(t, 0)
        self.t = t

    def byte_and_ack(self, bits, ack_level):
        for bit in bits:
            self.clock_pulse(bit)
        self.clock_pulse(ack_level)

    def stretch(self, stretch_ns):
        self.t += stretch_ns

    def repeated_start(self):
        t = self.t
        # Release SDA high during the low period (an Sr needs a high->low SDA
        # move while SCL high, so SDA must be high first), then raise SCL,
        # hold t_SU;STA, then drop SDA for the repeated START.
        self.sda.add(t + DATA_SHIFT_NS, 1)
        t += ENCODER_MARGIN * self.min_ns("t_LOW")
        self.scl.add(t, 1)
        t += ENCODER_MARGIN * self.min_ns("t_SU;STA")
        self.sda.add(t, 0)
        t += ENCODER_MARGIN * self.min_ns("t_HD;STA")
        self.t = t

    def stop(self):
        t = self.t
        # Drive SDA low during the low period (a STOP needs a low->high SDA
        # move while SCL high, so SDA must be low first), then raise SCL,
        # hold t_SU;STO, then raise SDA for the STOP.
        self.sda.add(t + DATA_SHIFT_NS, 0)
        t += ENCODER_MARGIN * self.min_ns("t_LOW")
        self.scl.add(t, 1)
        t += self.stop_setup_factor * self.min_ns("t_SU;STO")
        self.sda.add(t, 1)
        self.t = t


def encode_transfer(address, read_bit, data_bytes, acks, fast_mode, scl, sda,
                    t0=0.0, stretch_ns=None, stretch_after_byte=None,
                    repeated_start_after_byte=None,
                    stop_setup_factor=ENCODER_MARGIN):
    """Append one controller-role transfer; return the time it ends.

    ``stretch_ns`` / ``stretch_after_byte`` insert a peripheral
    clock-stretch hold on SCL after that data byte's ACK clock.
    ``repeated_start_after_byte`` issues an Sr after that data byte instead
    of carrying straight on (the transfer then continues with one more
    address byte before any remaining data).  ``stop_setup_factor`` scales
    the final STOP's t_SU;STO; only the negative controls pass anything
    other than ``ENCODER_MARGIN``.
    """
    if not 0x08 <= address <= 0x77:
        raise ValueError(
            f"address 0x{address:02x} outside UM10204's valid static-address "
            "range 0x08-0x77"
        )
    if len(acks) != len(data_bytes):
        raise ValueError("one ACK/NACK per data byte")
    if repeated_start_after_byte is not None and repeated_start_after_byte >= len(
        data_bytes
    ) - 1:
        raise ValueError("Sr must be followed by at least one more byte")

    enc = _Encoder(scl, sda, fast_mode, stop_setup_factor)
    enc.t = float(t0)
    scl.add(enc.t, 1)
    sda.add(enc.t, 1)

    sda.add(enc.t, 0)
    enc.t += ENCODER_MARGIN * minimum_ns("t_HD;STA", fast_mode)

    address_bits = [(address >> (6 - i)) & 1 for i in range(7)] + [
        1 if read_bit else 0
    ]
    enc.byte_and_ack(address_bits, 0)

    for b_index, data in enumerate(data_bytes):
        bits = [(data >> (7 - i)) & 1 for i in range(8)]
        ack_level = 0 if acks[b_index] else 1
        enc.byte_and_ack(bits, ack_level)
        if stretch_ns is not None and stretch_after_byte == b_index:
            enc.stretch(stretch_ns)
        if repeated_start_after_byte == b_index:
            enc.repeated_start()
            enc.byte_and_ack(address_bits, 0)

    enc.stop()
    return enc.t


def encode_transfer_with_short_stop_setup(address, read_bit, data_bytes, acks,
                                          fast_mode, scl, sda, t0=0.0,
                                          factor=0.5):
    """Negative-control transmitter: the STOP's t_SU;STO at ``factor`` x
    the Table-10 minimum, everything else legal (deterministic -- the
    checker must flag exactly the t_SU;STO violation)."""
    return encode_transfer(
        address, read_bit, data_bytes, acks, fast_mode, scl, sda,
        t0=t0, stop_setup_factor=factor,
    )


def check_transfer(scl, sda, t0=0.0, t1=float("inf"), fast_mode=None):
    """Independently re-derive and judge the transfer in ``[t0, t1]``.

    ``fast_mode`` selects which Table-10 column the minimums come from; it
    is deliberately a caller argument (not inferred from the waveform) so
    the caller states which mode's contract the traffic claims to meet --
    the same statement the DUT-facing suite will one day extract from the
    firmware program under test.

    Returns an ``I2cReport``; ``violations`` names every Table-10 minimum
    the waveform broke (an empty list is conforming traffic).
    """
    if fast_mode is None:
        raise ValueError("fast_mode must be stated (True=Fast-mode, False=Standard)")

    scl_events = [(t, v) for (t, v) in scl.transitions if t0 <= t <= t1]
    sda_events = [(t, v) for (t, v) in sda.transitions if t0 <= t <= t1]
    starts = [t for (t, v) in sda_events if v == 0 and scl.value_at(t) == 1]
    if not starts:
        raise ValueError("no START in window")
    start_t = starts[0]
    stops = [
        t
        for (t, v) in sda_events
        if v == 1 and t > start_t and scl.value_at(t) == 1
    ]
    if not stops:
        raise ValueError("no STOP in window")
    stop_t = stops[0]
    repeated_starts = [t for t in starts if t > start_t]

    violations = []
    measurements = {}

    all_risings = [t for (t, v) in scl_events if v == 1 and start_t <= t <= stop_t]
    all_fallings = [t for (t, v) in scl_events if v == 0 and start_t <= t <= stop_t]

    def below(parameter, measured, limit):
        if measured < limit - 1e-9:
            violations.append(f"{parameter} {measured:.3f}ns < {limit:.3f}ns minimum")

    # Data clocks: SCL risings whose following high period carries no SDA
    # change while SCL is high.  A rise followed by SDA falling while SCL
    # is high is the repeated-START setup rise; the final rise followed by
    # SDA rising while high is the STOP setup rise.  Neither carries a bit.
    data_rises = []
    for r in all_risings:
        next_fall = next((f for f in all_fallings if f > r), None)
        window_end = stop_t if next_fall is None else min(next_fall, stop_t)
        sda_while_high = [
            t
            for (t, v) in sda_events
            if r < t <= window_end and scl.value_at(t) == 1
        ]
        if sda_while_high:
            continue
        if next_fall is None and r == all_risings[-1]:
            continue
        data_rises.append(r)

    # t_HD;STA for START and every repeated START: event to the next SCL fall.
    for event_t in [start_t] + repeated_starts:
        fall = next((f for f in all_fallings if f > event_t), None)
        if fall is not None:
            measured = fall - event_t
            measurements[f"t_HD;STA@{event_t:.0f}"] = measured
            below("t_HD;STA", measured, minimum_ns("t_HD;STA", fast_mode))

    # t_SU;STA for every repeated START: preceding SCL rise to the Sr.
    for sr_t in repeated_starts:
        rise = next((r for r in reversed(all_risings) if r < sr_t), None)
        if rise is not None:
            measured = sr_t - rise
            measurements[f"t_SU;STA@{sr_t:.0f}"] = measured
            below("t_SU;STA", measured, minimum_ns("t_SU;STA", fast_mode))

    # t_SU;STO: preceding SCL rise to the STOP.
    preceding_rise = next((r for r in reversed(all_risings) if r < stop_t), None)
    if preceding_rise is not None:
        measured = stop_t - preceding_rise
        measurements["t_SU;STO"] = measured
        below("t_SU;STO", measured, minimum_ns("t_SU;STO", fast_mode))

    # t_LOW / t_HIGH across every data clock.
    t_low_min_limit = minimum_ns("t_LOW", fast_mode)
    t_high_min_limit = minimum_ns("t_HIGH", fast_mode)
    min_low = None
    min_high = None
    stretched = 0
    for r in data_rises:
        prev_fall = next((f for f in reversed(all_fallings) if f < r), None)
        next_fall = next((f for f in all_fallings if f > r), None)
        if prev_fall is not None:
            low = r - prev_fall
            min_low = low if min_low is None else min(min_low, low)
            below("t_LOW", low, t_low_min_limit)
            if low >= STRETCH_DETECT_FACTOR * t_low_min_limit:
                stretched += 1
        if next_fall is not None:
            high = next_fall - r
            min_high = high if min_high is None else min(min_high, high)
            below("t_HIGH", high, t_high_min_limit)
    if min_low is not None:
        measurements["t_LOW(min)"] = min_low
    if min_high is not None:
        measurements["t_HIGH(min)"] = min_high

    # Address + R/W + data + ACK/NACK, sampled on each data clock's rise.
    bits = [sda.value_at(r) for r in data_rises]
    if len(bits) % 9 != 0:
        raise ValueError(
            f"{len(bits)} data clocks is not a whole number of 9-clock bytes"
        )
    address = 0
    for i in range(7):
        address = (address << 1) | bits[i]
    read_bit = bits[7]
    acks = [bits[8] == 0]
    data_bytes = []
    for b in range(1, len(bits) // 9):
        value = 0
        for i in range(8):
            value = (value << 1) | bits[b * 9 + i]
        data_bytes.append(value)
        acks.append(bits[b * 9 + 8] == 0)

    return I2cReport(address, read_bit, data_bytes, acks, stretched,
                     measurements, violations)
