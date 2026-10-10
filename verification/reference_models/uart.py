"""Independent UART reference model (issue #25, verification-plan.md
section 4; target-spec rows 1 and 10).

Independence, per the plan: this model shares no code with this repo's RTL
or firmware and encodes only the generic asynchronous-serial conventions
the ratified spec cites -- 8N1 framing (1 start bit, 8 data bits LSB-first,
1 stop bit, idle-high line) and the receiver-resyncs-per-start-bit timing
practice of target-spec row 10 (cumulative per-frame drift kept under ~2%
of the bit period; the row cites NXP AN10406-style general practice, since
no formal standards body owns UART bit-rate tolerance).  Nothing here is
derived from this repo's DR 0001 cycle-budget arithmetic.

The model has two halves:

* ``encode_frame`` -- a transmitter: appends one 8N1 frame's transitions to
  a ``Signal`` at a nominal bit period.
* ``UartDecoder`` -- a receiver: finds start bits, samples the 10 nominal
  bit centers off each start edge, reassembles the byte, checks the stop
  bit, and *measures* the frame's actual-vs-nominal bit timing (row 10's
  "measures actual vs. nominal bit timing from the cocotb waveform"), so a
  transmitter whose cumulative drift exceeds the bound is flagged even when
  every sampled bit still happens to read back correctly.

What the timing measurement can and cannot see (issue #97)
-----------------------------------------------------------

Drift is only observable where the transmitter puts an edge.  The model
measures two things:

* **In-frame last edge** (``drift_pct``): the frame's last level change
  inside the 10-bit window, placed on the nominal grid.  A per-bit error
  ``e`` shows up as ``k*e`` at the last edge's bit index ``k``, so the
  sensitivity depends on the payload.  For 0xFF the only edge after the
  start fall is the rise at bit 1: a frame whose start and first data bit
  are nominal reports 0 drift whatever the later bits do.

* **Frame pitch** (``pitch_drift_pct``): the start-to-start spacing to the
  following frame against ``UART_FRAME_BITS`` nominal bits.  This sees the
  whole frame's length, the stop bit included, for any payload.  A
  following start that comes *early* (the stop bit is short) is a
  violation on any line.  A following start that comes *late* is a
  violation only when the caller declares a back-to-back stream
  (``UartDecoder(baud, back_to_back=True)``), because on a general line a
  late start cannot be told apart from a legal idle gap after the stop bit.

**Isolated-frame limitation.**  A frame with no following frame (or one
followed by idle on a line not declared back-to-back) has no observable
quantity past its last in-frame edge.  For such a frame the bound is only
as strong as the payload's last edge: callers that need the row-10 bound
to mean something must supply a payload with a late edge (e.g. 0x5A,
whose last edge is the bit-8-to-stop rise) or a back-to-back stream.
0xFF, 0x01 and similar payloads in an isolated frame have, by
construction, limited or no sensitivity; this is a property of the
waveform, not of the model.
"""

from .waveform import Signal

UART_DATA_BITS = 8
UART_FRAME_BITS = 10

#: Target-spec row 10's adopted bound: cumulative per-frame drift under
#: ~2% of the bit period (receiver resynchronizes on each start bit, so
#: per-frame -- not per-bit -- error is what the receiver tolerates).
MAX_FRAME_DRIFT_PCT = 2.0


def bit_period_ns(baud):
    return 1e9 / float(baud)


def encode_frame(data, baud, line, t0=0.0):
    """Append one 8N1 frame for ``data`` at ``baud`` to ``line`` starting at
    ``t0``; return the time the line goes idle-high at the end of the stop
    bit (the next frame may start there or later)."""
    if not 0 <= data <= 0xFF:
        raise ValueError(f"UART data byte out of range: {data!r}")
    period = bit_period_ns(baud)
    t = float(t0)
    line.add(t, 0)
    t += period
    for i in range(UART_DATA_BITS):
        line.add(t, (data >> i) & 1)
        t += period
    line.add(t, 1)
    return t + period


class UartFrameReport:
    """One decoded frame plus its timing measurement."""

    def __init__(self, data, t_start, stop_ok, drift_ns, drift_pct, baud,
                 pitch_ns=None, pitch_drift_pct=None):
        self.data = data
        self.t_start = t_start
        self.stop_ok = stop_ok
        self.drift_ns = drift_ns
        self.drift_pct = drift_pct
        self.baud = baud
        #: Start-to-start spacing to the following frame (ns), or None when
        #: no following frame exists.
        self.pitch_ns = pitch_ns
        #: The graded pitch error as % of a bit, or None when not measured
        #: (no following frame).  See ``UartDecoder._grade_pitch``.
        self.pitch_drift_pct = pitch_drift_pct

    def __repr__(self):
        pitch = (
            "pitch=n/a"
            if self.pitch_ns is None
            else f"pitch={self.pitch_ns:.3f}ns ({self.pitch_drift_pct:.3f}% of bit)"
        )
        return (
            f"UartFrameReport(data=0x{self.data:02x}, t_start={self.t_start:.3f}ns, "
            f"stop_ok={self.stop_ok}, drift={self.drift_ns:.3f}ns "
            f"({self.drift_pct:.3f}% of bit), {pitch})"
        )


class UartFrameError(ValueError):
    """A framing violation the receiver cannot recover from mid-frame."""


class UartDecoder:
    """A nominal-baud UART receiver measuring per-frame drift.

    ``back_to_back=True`` declares that the transmitter is meant to send a
    continuous stream (each start bit immediately after the previous stop
    bit), so a following start that arrives late is graded as drift rather
    than accepted as idle.  The default accepts any idle after a full stop
    bit and grades only a short (early) pitch.
    """

    def __init__(self, baud, back_to_back=False):
        self.baud = baud
        self.period = bit_period_ns(baud)
        self.back_to_back = back_to_back

    def decode(self, line, t_from=0.0, max_frames=None):
        """Decode frames whose start bits fall after ``t_from``.

        Returns a list of ``UartFrameReport``.  Raises ``UartFrameError``
        only for waveform the protocol defines as unrecoverable (a stop bit
        that reads 0); drift and data errors are *reported*, so a caller
        asserting on them is what turns them into failures.

        The search for the next start bit resumes just after this frame's
        stop-bit sample point (bit 9.5), not at the nominal frame end, so a
        following frame that starts early is decoded and its pitch graded
        rather than silently skipped.  A following start before the stop
        sample makes the stop bit read 0, which is a framing error.
        """
        reports = []
        t = float(t_from)
        while True:
            t_start = self._next_start(line, t)
            if t_start is None:
                break
            bits = []
            for k in range(UART_FRAME_BITS):
                bits.append(line.value_at(t_start + (k + 0.5) * self.period))
            data = 0
            for i in range(UART_DATA_BITS):
                data |= bits[1 + i] << i
            stop_ok = bits[9] == 1
            if not stop_ok:
                raise UartFrameError(
                    f"framing error at t={t_start:.3f}ns: stop bit sampled 0"
                )
            drift_ns = self._measure_drift(line, t_start)
            drift_pct = 100.0 * abs(drift_ns) / self.period
            t = t_start + (UART_FRAME_BITS - 0.5) * self.period
            t_next = self._next_start(line, t)
            pitch_ns = None if t_next is None else t_next - t_start
            pitch_drift_pct = self._grade_pitch(pitch_ns)
            reports.append(
                UartFrameReport(
                    data, t_start, stop_ok, drift_ns, drift_pct, self.baud,
                    pitch_ns=pitch_ns, pitch_drift_pct=pitch_drift_pct,
                )
            )
            if max_frames is not None and len(reports) >= max_frames:
                break
        return reports

    def _next_start(self, line, t_from):
        for tt, vv in line.transitions:
            if tt <= t_from:
                continue
            if vv == 0 and line.value_at(tt - 1e-9) == 1:
                return tt
        return None

    def _measure_drift(self, line, t_start):
        """Cumulative actual-vs-nominal drift of one frame, in ns.

        The measurable statement of "cumulative per-frame drift" on a real
        waveform: take the frame's last transition (the transmitter's final
        level change inside the frame window -- the data-to-stop edge when
        the last data bit is 0, or the last data edge otherwise), place it
        on the nominal grid ``t_start + k*period``, and return the residual.
        A transmitter whose bit periods run e/(1+e) fast or slow accumulates
        ``k*e*period`` of residual at bit ``k``; a clean transmitter
        accumulates zero; injected edge jitter lands within the jitter
        amplitude.
        """
        t_end = t_start + UART_FRAME_BITS * self.period
        frame_edges = [
            tt
            for (tt, vv) in line.transitions_between(t_start, t_end)
            if tt > t_start
        ]
        if not frame_edges:
            return 0.0
        last = frame_edges[-1]
        k = round((last - t_start) / self.period)
        return last - (t_start + k * self.period)

    def _grade_pitch(self, pitch_ns):
        """Frame-pitch error as % of a bit, or None with no following frame.

        The error is the start-to-start spacing minus ``UART_FRAME_BITS``
        nominal bits.  A short pitch always counts (the stop bit was cut
        short).  A long pitch counts only on a declared back-to-back
        stream; otherwise it is indistinguishable from idle and grades 0.
        """
        if pitch_ns is None:
            return None
        error_ns = pitch_ns - UART_FRAME_BITS * self.period
        if error_ns > 0 and not self.back_to_back:
            error_ns = 0.0
        return 100.0 * abs(error_ns) / self.period

    def check_frame(self, report, max_drift_pct=MAX_FRAME_DRIFT_PCT):
        """Row 10's bound: True when the frame is inside the drift budget.

        Both measurements are held to the same bound: the in-frame
        last-edge drift always, and the frame pitch when a following frame
        exists.  An isolated frame is graded on its last edge alone (see
        the module docstring's isolated-frame limitation).
        """
        if not report.stop_ok or report.drift_pct > max_drift_pct:
            return False
        if report.pitch_drift_pct is not None and report.pitch_drift_pct > max_drift_pct:
            return False
        return True


def encode_slow_frame(data, baud, line, t0=0.0, scale=1.025):
    """Negative-control transmitter: bit periods ``scale`` x nominal.

    Deterministic (no randomness): 2.5% slow bits push the frame's
    measurable cumulative drift past the row-10 2% bound while typically
    still decoding to the correct byte at the nominal sample points, which
    is exactly the case only the *timing* measurement catches.
    """
    if not 0 <= data <= 0xFF:
        raise ValueError(f"UART data byte out of range: {data!r}")
    period = bit_period_ns(baud) * scale
    t = float(t0)
    line.add(t, 0)
    t += period
    for i in range(UART_DATA_BITS):
        line.add(t, (data >> i) & 1)
        t += period
    line.add(t, 1)
    return t + period
