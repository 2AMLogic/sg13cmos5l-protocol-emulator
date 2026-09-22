"""Shared piecewise-constant waveform abstraction for the protocol reference
models (`verification/reference_models/`, issue #25, verification-plan.md
section 4).

A `Signal` is an initial logic level plus a chronologically sorted list of
``(time_ns, value)`` transitions with ``value`` in ``{0, 1}``.  This is the
smallest common currency the three protocol models need: encoders append
transitions, checkers sample and measure.  It is deliberately *not* tied to
cocotb or any simulator type, so the same models run unchanged over a
recorded pin trace later (the DUT-facing suites, once the ISA core and
firmware land -- issues #18/#22/#23).

Time is float nanoseconds.  Float, not int, because a UART bit period at
9600 baud is 104166.666... ns; forcing integer times would itself be a
timing model.
"""


class Signal:
    """One logic signal as initial level + sorted transitions."""

    def __init__(self, initial, name=""):
        self.name = name
        self.initial = initial
        self.transitions = []

    def add(self, t, value):
        """Record a transition to ``value`` at time ``t`` (ns).

        Appending the level the line already carries is a no-op: transitions
        are *changes*, so encoders may compute levels on a nominal grid
        without manufacturing edges a decoder would misread as activity.
        Transitions must be appended in nondecreasing time order.
        """
        value = 1 if value else 0
        if self.current() == value:
            return
        if self.transitions and float(t) < self.transitions[-1][0]:
            raise ValueError(
                f"Signal({self.name!r}): transition at {t} precedes "
                f"previous transition at {self.transitions[-1][0]}"
            )
        self.transitions.append((float(t), value))

    def current(self):
        return self.transitions[-1][1] if self.transitions else self.initial

    def value_at(self, t):
        """Logic level at time ``t`` (a transition at exactly ``t`` reads as
        the post-transition level)."""
        value = self.initial
        for tt, vv in self.transitions:
            if tt <= t:
                value = vv
            else:
                break
        return value

    def transitions_between(self, t0, t1):
        """All ``(t, value)`` transitions with ``t0 <= t <= t1``, in order."""
        return [(t, v) for (t, v) in self.transitions if t0 <= t <= t1]


def apply_jitter(signal, rng, amplitude_ns, t0=0.0, t1=float("inf")):
    """Displace every transition in ``[t0, t1]`` by a uniform random offset
    in ``[-amplitude_ns, +amplitude_ns]`` (in place, order-preserving).

    This is the receive-side frame-timing jitter the verification plan's
    UART row names as a constrained-random dimension ("frame timing jitter
    injected on the receive side", verification-plan.md section 4).  The
    caller keeps ``amplitude_ns`` well under the receiver's resync margin so
    a legal waveform stays legal.
    """
    shifted = []
    for t, v in signal.transitions:
        if t0 <= t <= t1:
            t = t + rng.uniform(-amplitude_ns, amplitude_ns)
        shifted.append((t, v))
    shifted.sort(key=lambda tv: tv[0])
    if any(shifted[i][0] == shifted[i + 1][0] for i in range(len(shifted) - 1)):
        raise ValueError("jitter collapsed two transitions onto one instant")
    signal.transitions = shifted
