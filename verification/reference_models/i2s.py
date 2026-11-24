"""Independent I2S (Philips) receiver model, written from the I2S bus
specification (Philips, "I2S bus specification", 1986, rev. 5 June 1996) and
nothing in this repository's firmware (issue #451, multi-protocol extra
credit; catalog #443).

What the model is: a *receiver*. It is given three recorded signals (BCLK,
WS, SD, each a `waveform.Signal` in nanoseconds) and does what an I2S DAC
does with them:

- the data and word-select lines are sampled on the **rising** edge of BCLK;
- a change of WS is seen at the rising edge after it; that rising edge still
  carries the last bit of the previous word, and the **next** rising edge
  carries the new word's MSB (the "one BCLK delay": the transmitter changes
  WS one clock before the MSB);
- WS low selects the left channel, high the right;
- the bits of a word run MSB first; a slot longer than the word is padded and
  the model reads the first `data_bits` bits as the sample and requires the
  rest (`slot_bits - data_bits`) to be zero.

What it checks, with the bus specification's figures:

- BCLK: every period within `PERIOD_TOL` of the median; each phase (high and
  low) at least 0.35 T (the specification's t_HC, t_LC minimum for a
  transmitter);
- every SD / WS transition falls after a rising edge (hold >= 0) and at
  least 0.2 T before the next one (receiver set-up t_sr = 0.2 T; the
  specification's transmitter delay t_dtr <= 0.8 T is the same figure seen
  from the falling edge);
- every slot is exactly `slot_bits` BCLK periods between WS changes;
- the pad bits are zero.

It does not know the firmware's table or encoding. The bench compares what
this model decodes with the samples the bench loaded.
"""

from dataclasses import dataclass, field
from statistics import median

# Bus-specification figures.
HIGH_LOW_MIN = 0.35   # t_HC / t_LC minimum, fraction of the clock period T
SETUP_MIN = 0.20      # receiver set-up t_sr minimum, fraction of T
HOLD_MIN_NS = 0.0     # receiver hold t_hr minimum
# Not a bus-specification figure: how steady a *receiver's PLL* can assume
# BCLK is. A real DAC derives its sample clock from BCLK, so a period that
# wanders more than this is a rate error the DAC would pass on.
PERIOD_TOL = 0.01

LEFT, RIGHT = "L", "R"


@dataclass
class Violation:
    kind: str
    detail: str

    def __str__(self):
        return f"{self.kind}: {self.detail}"


@dataclass
class Word:
    channel: str          # "L" or "R"
    bits: list            # the sampled bits of the whole slot, MSB first
    first_edge: int       # index of the rising edge sampling bits[0]

    def value(self, data_bits):
        v = 0
        for b in self.bits[:data_bits]:
            v = (v << 1) | b
        return v

    def signed(self, data_bits):
        v = self.value(data_bits)
        return v - (1 << data_bits) if v >> (data_bits - 1) else v


@dataclass
class I2sResult:
    data_bits: int
    slot_bits: int
    rising: list = field(default_factory=list)
    period_ns: float = 0.0
    words: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    setup_min_ns: float = float("inf")
    hold_min_ns: float = float("inf")

    def samples(self):
        """Signed samples in arrival order as (channel, value) pairs."""
        return [(w.channel, w.signed(self.data_bits)) for w in self.words]

    def frames(self):
        """(left, right) signed pairs: each left word followed by a right."""
        out, i = [], 0
        w = self.words
        while i + 1 < len(w):
            if w[i].channel == LEFT and w[i + 1].channel == RIGHT:
                out.append((w[i].signed(self.data_bits), w[i + 1].signed(self.data_bits)))
                i += 2
            else:
                i += 1
        return out


class I2sReceiver:
    def __init__(self, data_bits=16, slot_bits=32):
        assert 0 < data_bits <= slot_bits
        self.data_bits = data_bits
        self.slot_bits = slot_bits

    def decode(self, bclk, ws, sd, t0, t1):
        """Decode the window [t0, t1] (ns) of three `Signal`s."""
        res = I2sResult(self.data_bits, self.slot_bits)
        rising = [t for t, v in bclk.transitions if v == 1 and t0 <= t <= t1]
        falling = [t for t, v in bclk.transitions if v == 0 and t0 <= t <= t1]
        res.rising = rising
        if len(rising) < 3:
            res.violations.append(Violation("no-clock", f"{len(rising)} rising edge(s) in the window"))
            return res

        periods = [b - a for a, b in zip(rising, rising[1:])]
        T = median(periods)
        res.period_ns = T
        for i, p in enumerate(periods):
            if abs(p - T) > PERIOD_TOL * T:
                res.violations.append(Violation("period", f"period {i} is {p:.3f} ns, median {T:.3f} ns"))
        # duty: each high lasts from a rising edge to the next falling edge
        for r in rising:
            f = next((x for x in falling if x > r), None)
            if f is not None and f - r < HIGH_LOW_MIN * T:
                res.violations.append(Violation("duty", f"BCLK high {f - r:.3f} ns < 0.35 T at {r:.1f} ns"))
            nxt = next((x for x in rising if x > r), None)
            if f is not None and nxt is not None and nxt - f < HIGH_LOW_MIN * T:
                res.violations.append(Violation("duty", f"BCLK low {nxt - f:.3f} ns < 0.35 T at {f:.1f} ns"))

        # set-up / hold of every SD and WS change against the rising edges
        for name, sig in (("WS", ws), ("SD", sd)):
            for t, _v in sig.transitions:
                if not (rising[0] <= t <= rising[-1]):
                    continue
                prev = max(r for r in rising if r <= t)
                nxt = min(r for r in rising if r > t) if t < rising[-1] else None
                hold = t - prev
                res.hold_min_ns = min(res.hold_min_ns, hold)
                if hold < HOLD_MIN_NS or (hold == 0.0):
                    res.violations.append(Violation("hold", f"{name} changes {hold:.3f} ns after a rising edge at {t:.1f} ns"))
                if nxt is not None:
                    setup = nxt - t
                    res.setup_min_ns = min(res.setup_min_ns, setup)
                    if setup < SETUP_MIN * T:
                        res.violations.append(Violation("setup", f"{name} changes {setup:.3f} ns before a rising edge at {t:.1f} ns (< 0.2 T)"))

        # sample on every rising edge; a transition exactly at the edge reads
        # as the old level (the receiver's flop has not seen it yet)
        eps = 1e-6
        ws_s = [ws.value_at(r - eps) for r in rising]
        sd_s = [sd.value_at(r - eps) for r in rising]

        # words: a WS change at edge i ends the previous word with this edge's
        # sample (its last bit) and starts the new word at edge i + 1
        changes = [i for i in range(1, len(rising)) if ws_s[i] != ws_s[i - 1]]
        for a, b in zip(changes, changes[1:]):
            start, end = a + 1, b  # bits at edges start .. end inclusive
            bits = [sd_s[i] for i in range(start, end + 1)]
            channel = LEFT if ws_s[a] == 0 else RIGHT
            if len(bits) != self.slot_bits:
                res.violations.append(Violation(
                    "slot-length", f"{channel} slot at edge {a} is {len(bits)} BCLK, expected {self.slot_bits}"))
                continue
            word = Word(channel, bits, start)
            if any(bits[self.data_bits:]):
                res.violations.append(Violation("pad", f"{channel} slot at edge {a} has nonzero pad bits {bits[self.data_bits:]}"))
            res.words.append(word)
        return res


# ---------------------------------------------------------------- encoder
def encode_ideal(bclk, ws, sd, t_start, period_ns, frames, data_bits=16, slot_bits=32,
                 ws_delay=True, ws_lead_ns=0.0):
    """Append an ideal I2S transmission of `frames` ((left, right) signed or
    unsigned ints) to three Signals. BCLK is 50 % duty, WS and SD change on
    the falling edge. `ws_delay=False` is the classic mistake: the MSB goes
    out at the WS edge instead of one BCLK after it (left-justified framing).
    Used by the model's self-test only. Returns the end time."""
    t = t_start
    half = period_ns / 2.0
    clock_level = []
    # build per-BCLK-period (ws, sd) levels first
    periods = []
    for left, right in frames:
        for ch, word in ((0, left), (1, right)):
            w = word & ((1 << data_bits) - 1)
            bits = [(w >> (data_bits - 1 - i)) & 1 for i in range(data_bits)] + [0] * (slot_bits - data_bits)
            slot = [(ch, b) for b in bits]
            periods.append(slot)
    flat = [x for slot in periods for x in slot]
    # with the delay, WS leads its slot's data by one period: shift WS earlier
    n = len(flat)
    ws_lv = [flat[i][0] for i in range(n)]
    sd_lv = [flat[i][1] for i in range(n)]
    if ws_delay:
        ws_lv = ws_lv[1:] + [ws_lv[-1]]
    for i in range(n):
        bclk.add(t, 0)
        ws.add(t + ws_lead_ns, ws_lv[i])
        sd.add(t, sd_lv[i])
        bclk.add(t + half, 1)
        t += period_ns
    bclk.add(t, 0)
    return t
