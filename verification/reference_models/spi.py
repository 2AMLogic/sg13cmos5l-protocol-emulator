"""Independent SPI reference model (issue #25, verification-plan.md
section 4; target-spec rows 1 and 11).

Independence, per the plan: this model shares no code with this repo's RTL
or firmware and encodes only the de facto Motorola/Freescale/NXP "SPI
Block Guide" (V03.06) mode and clock-edge conventions that ratified
target-spec row 11 names as the reference -- four modes from
(CPOL, CPHA), data MSB-first, sampling on the leading clock edge for
CPHA=0 and on the trailing edge for CPHA=1, SCLK idling at CPOL.  Nothing
here is derived from this repo's DR 0001 cycle-budget arithmetic.

The model has two halves:

* ``encode_burst`` -- a controller-side transmitter: appends a chip-select
  assertion, full-duplex clocked bits, and the chip-select release to
  ``Signal`` objects, at an SCLK period the caller chooses.
* ``check_burst`` -- an independent checker: re-derives both data streams
  from the waveform by sampling on the mode-correct edges, verifies the
  mode's idle level and the chip-select envelope, and enforces row 11's
  SCLK <= f_clk/4 ceiling (given the core clock the caller names).
"""

from .waveform import Signal


class SpiMode:
    """One of the four (CPOL, CPHA) combinations, Motorola numbering."""

    def __init__(self, cpol, cpha):
        if cpol not in (0, 1) or cpha not in (0, 1):
            raise ValueError(f"bad (CPOL, CPHA): {(cpol, cpha)!r}")
        self.cpol = cpol
        self.cpha = cpha
        self.number = 2 * cpol + cpha
        self.idle = cpol
        self.active = 1 - cpol

    def __repr__(self):
        return f"SpiMode(CPOL={self.cpol}, CPHA={self.cpha}, mode {self.number})"

    def sample_edge_is_rising(self):
        """True when this mode's sampling edge is a rising SCLK edge.

        CPHA=0 samples on the leading edge (idle -> active), CPHA=1 on the
        trailing edge (active -> idle); the leading edge is rising exactly
        when CPOL=0.
        """
        return (self.cpol == 0) == (self.cpha == 0)


MODES = [SpiMode(cpol, cpha) for cpol in (0, 1) for cpha in (0, 1)]


class SpiReport:
    """What ``check_burst`` found on the wires."""

    def __init__(self, mosi_bytes, miso_bytes, violations, sclk_period_ns):
        self.mosi_bytes = mosi_bytes
        self.miso_bytes = miso_bytes
        self.violations = violations
        self.sclk_period_ns = sclk_period_ns

    @property
    def ok(self):
        return not self.violations

    def __repr__(self):
        return (
            f"SpiReport(mosi={[f'0x{b:02x}' for b in self.mosi_bytes]}, "
            f"miso={[f'0x{b:02x}' for b in self.miso_bytes]}, "
            f"sclk_period={self.sclk_period_ns:.3f}ns, "
            f"violations={self.violations!r})"
        )


def encode_burst(mosi_bytes, miso_bytes, mode, sclk_period_ns, sclk, mosi, miso, cs,
                 t0=0.0, cs_setup_ns=None, cs_hold_ns=None):
    """Append one controller-mode full-duplex burst; return its end time.

    ``miso_bytes`` must be the same length as ``mosi_bytes`` (the peripheral
    the checker will re-derive drove those bits on MISO).  ``cs_setup_ns`` /
    ``cs_hold_ns`` default to half an SCLK period around the clock burst.
    """
    if len(mosi_bytes) != len(miso_bytes):
        raise ValueError("full-duplex burst needs equal MOSI/MISO lengths")
    if sclk_period_ns <= 0:
        raise ValueError("SCLK period must be positive")
    if cs_setup_ns is None:
        cs_setup_ns = sclk_period_ns / 2.0
    if cs_hold_ns is None:
        cs_hold_ns = sclk_period_ns / 2.0

    half = sclk_period_ns / 2.0
    n_bits = 8 * len(mosi_bytes)
    cs_fall = float(t0)
    first_leading = cs_fall + cs_setup_ns

    cs.add(cs_fall, 0)
    sclk.add(first_leading, mode.idle)

    for i in range(n_bits):
        leading = first_leading + i * sclk_period_ns
        trailing = leading + half
        byte = i // 8
        bit = 7 - (i % 8)
        if mode.cpha == 0:
            # Sample on `leading`; data shifts out on the trailing edge, so
            # bit i appears at the previous cycle's trailing edge (bit 0 at
            # CS fall, before any clock edge).
            when = cs_fall if i == 0 else leading - half
        else:
            # Shift on `leading`, sample on `trailing`.
            when = leading
        mosi.add(when, (mosi_bytes[byte] >> bit) & 1)
        miso.add(when, (miso_bytes[byte] >> bit) & 1)
        sclk.add(leading, mode.active)
        sclk.add(trailing, mode.idle)

    last_trailing = first_leading + (n_bits - 1) * sclk_period_ns + half
    cs_rise = last_trailing + cs_hold_ns
    cs.add(cs_rise, 1)
    return cs_rise


def check_burst(sclk, mosi, miso, cs, mode, f_clk_hz, t0=0.0, t1=float("inf")):
    """Independently re-derive and judge the burst in ``[t0, t1]``.

    Samples MOSI/MISO on the mode-correct edges, checks CPOL idle levels,
    the CS envelope, that SCLK returns to idle, and row 11's SCLK <= f_clk/4
    ceiling at the caller's named core clock.  Returns an ``SpiReport``
    whose ``violations`` list names every rule the waveform broke (an empty
    list is conforming traffic).
    """
    edges = [(t, v) for (t, v) in sclk.transitions if t0 <= t <= t1]
    if len(edges) < 2:
        raise ValueError("no SCLK activity in window")
    burst_start = edges[0][0]
    burst_end = edges[-1][0]
    violations = []

    if sclk.value_at(burst_start - 1e-9) != mode.idle:
        violations.append(f"SCLK not idle at CPOL={mode.cpol} before burst")
    if sclk.value_at(burst_end + 1e-9) != mode.idle:
        violations.append("SCLK did not return to CPOL idle after burst")

    rising = [t for (t, v) in edges if v == 1]
    falling = [t for (t, v) in edges if v == 0]
    full_periods = [b - a for a, b in zip(rising, rising[1:])]
    full_periods += [b - a for a, b in zip(falling, falling[1:])]
    if not full_periods:
        raise ValueError("fewer than two SCLK periods in window")
    sclk_period = min(full_periods)
    min_period_ns = 4e9 / float(f_clk_hz)
    if sclk_period < min_period_ns - 1e-9:
        violations.append(
            f"SCLK period {sclk_period:.3f}ns below f_clk/4 ceiling "
            f"({min_period_ns:.3f}ns at f_clk={f_clk_hz:.6g}Hz)"
        )

    if cs.value_at(burst_start) != 0 or cs.value_at(burst_end) != 0:
        violations.append("CS not asserted across the clock burst")

    sample_edges = rising if mode.sample_edge_is_rising() else falling
    if len(sample_edges) % 8 != 0:
        violations.append(
            f"sample-edge count {len(sample_edges)} is not a whole number of bytes"
        )

    def sample_stream(stream):
        out = []
        for byte_i in range(len(sample_edges) // 8):
            value = 0
            for bit_i in range(8):
                value = (value << 1) | stream.value_at(sample_edges[byte_i * 8 + bit_i])
            out.append(value)
        return out

    mosi_decoded = sample_stream(mosi)
    miso_decoded = sample_stream(miso)
    return SpiReport(mosi_decoded, miso_decoded, violations, sclk_period)
