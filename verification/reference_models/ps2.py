"""Independent PS/2 host-side bus monitor (target-spec row 13, stretch column,
issue #235; the protocol is the dated note of 2026-10-11 in DR 0018).

Written from one source: Adam Chapweske, "The PS/2 Mouse/Keyboard Protocol"
(1999), as read at https://www.burtonsys.com/ps2_chapweske.htm (sha256
0010e2a50bb08b8b0d59207f582d08ec459f301d4d217ab9b110b0f4eac9a284). That page
says it describes the interface from the author's experience and that IBM's
manual was not available to him. Nothing here imports from `rtl/`,
`firmware/` or any bench, and nothing here knows what the firmware does: the
monitor sees only the two bus lines and what the *host* is doing to them.

What it is
----------
A passive checker over a log of bus snapshots. Each `Snap` is the state of
the two open-drain lines at one instant (`clk`, `data`: the resolved level,
0 or 1) and whether the host is pulling each line low (`hclk`, `hdata`).
The host is the bench's own driver, so it knows what it pulls; the monitor
attributes every other low level to the device. It decodes both directions,
times every edge and returns `violations` for the device and
`host_violations` for the host driver (a bench that breaks the protocol
itself would otherwise grade the device against an illegal host).

Limits checked (all from the page above; a quantity not on the page is not
checked):

* CLK high and CLK low, device generated: 30 to 50 us each.
* Device to host: a frame is start (0), 8 data bits LSB first, odd parity,
  stop (1), 11 clocks; the host reads on the falling edge. A data change
  comes at least 5 us after a CLK rising edge and between 5 and 25 us before
  the next falling edge; data never changes while CLK is low.
* The device may begin a frame only after CLK has been continuously high for
  at least 50 us, with DATA released.
* The host inhibits with CLK held low for at least 100 us. A device frame
  inhibited before its 11th clock is abandoned: DATA is released by the time
  the host lets go of CLK, no device clock edge follows until a new frame
  has passed the 50 us rule, and the same frame is sent again.
* Host to device: the host holds CLK low for at least 100 us, pulls DATA low,
  and releases CLK (request to send). The device must start clocking within
  15 ms. The host changes DATA only while CLK is low; the device reads it
  while CLK is high (the model samples at the rising edge). Eight data bits
  LSB first, odd parity, stop (1), then the device pulls DATA low while CLK
  is high (the ACK) and gives one more clock pulse (the 11th); the ACK
  transition comes 5 to 25 us before that pulse's falling edge, as for
  device-to-host data. The device then releases DATA and CLK. The page gives
  no deadline for the release; the model asks for it within 50 us of the
  11th rising edge, which is the point where the device could next transmit.

At the start of a log the lines count as high since the first snapshot, so the
50 us rule is measured from there; a bench that starts its log at the moment
the program starts is conservative about a device that powers up on an idle bus.

Not checked, because the page gives no value: what the device does if the
host never releases DATA after the ACK; electrical rise time; a deadline for
the device's DATA release after an inhibit (the model asks for it by the time
the host releases CLK, which is at least 100 us after the inhibit began).

Time is nanoseconds throughout, so a bench can pass simulation time as is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

US = 1000.0

CLK_HALF_MIN_NS = 30 * US
CLK_HALF_MAX_NS = 50 * US
DATA_AFTER_RISE_MIN_NS = 5 * US
DATA_BEFORE_FALL_MIN_NS = 5 * US
DATA_BEFORE_FALL_MAX_NS = 25 * US
IDLE_MIN_NS = 50 * US
INHIBIT_MIN_NS = 100 * US
RTS_RESPONSE_MAX_NS = 15_000 * US
RELEASE_AFTER_FRAME_MAX_NS = 50 * US
FRAME_CLOCKS = 11


@dataclass(frozen=True)
class Snap:
    """The two lines at time `t` (ns): resolved levels and whether the host
    is pulling each one low."""

    t: float
    clk: int
    data: int
    hclk: bool = False
    hdata: bool = False


@dataclass
class Violation:
    t: float
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.t:.0f} ns: {self.kind}: {self.detail}"


@dataclass
class Frame:
    """One byte on the wire. `direction` is "dev->host" or "host->dev"."""

    direction: str
    t_start: float
    bits: List[int] = field(default_factory=list)  # start, 8 data, parity, stop (host->dev: no start)
    complete: bool = False
    aborted: bool = False

    @property
    def data_bits(self) -> List[int]:
        return self.bits[1:9] if self.direction == "dev->host" else self.bits[0:8]

    @property
    def byte(self) -> Optional[int]:
        d = self.data_bits
        if len(d) != 8:
            return None
        return sum(b << i for i, b in enumerate(d))

    @property
    def parity_ok(self) -> bool:
        off = 1 if self.direction == "dev->host" else 0
        if len(self.bits) < off + 10:
            return False
        return (sum(self.bits[off:off + 9]) % 2) == 1

    @property
    def stop_ok(self) -> bool:
        off = 1 if self.direction == "dev->host" else 0
        return len(self.bits) >= off + 10 and self.bits[off + 9] == 1


@dataclass
class Result:
    frames: List[Frame]
    violations: List[Violation]
    host_violations: List[Violation]
    #: smallest distance (ns) from a measured quantity to the limit it is
    #: held to, by name; None entries are absent
    margins: dict
    #: ns from request-to-send release to the device's first clock fall
    rts_response_ns: List[float]
    #: ns of continuous CLK-high before each device frame started
    hold_off_ns: List[float]
    #: smallest and largest measured value (ns) of each graded quantity
    measured: dict = field(default_factory=dict)

    def complete(self, direction: Optional[str] = None) -> List[Frame]:
        return [f for f in self.frames if f.complete and (direction in (None, f.direction))]


class Ps2Monitor:
    def __init__(self):
        self.frames: List[Frame] = []
        self.violations: List[Violation] = []
        self.host_violations: List[Violation] = []
        self._margins: dict = {}
        self._values: dict = {}
        self.rts_response_ns: List[float] = []
        self.hold_off_ns: List[float] = []
        self.mode = "bus"  # bus | tx | rx_wait | rx
        self.frame: Optional[Frame] = None
        self.clk_high_since: Optional[float] = None
        self.host_clk_low_since: Optional[float] = None
        self.last_rise: Optional[float] = None
        self.last_fall: Optional[float] = None
        self.last_dc: Optional[float] = None  # last device data change in this cell
        self.falls = 0
        self.rts_t: Optional[float] = None
        self.release_deadline: Optional[float] = None
        self.ack_t: Optional[float] = None

    # ------------------------------------------------------------ helpers
    def _v(self, t, kind, detail):
        self.violations.append(Violation(t, kind, detail))

    def _hv(self, t, kind, detail):
        self.host_violations.append(Violation(t, kind, detail))

    def _margin(self, key, lo=None, hi=None, value=None):
        v = self._values.setdefault(key, [value, value])
        v[0], v[1] = min(v[0], value), max(v[1], value)
        m = min(x for x in ((value - lo) if lo is not None else None,
                            (hi - value) if hi is not None else None) if x is not None)
        if key not in self._margins or m < self._margins[key]:
            self._margins[key] = m

    def _end_frame(self, aborted=False):
        if self.frame is not None:
            self.frame.aborted = aborted
            self.frames.append(self.frame)
        self.frame = None
        self.mode = "bus"
        self.falls = 0
        self.last_dc = None
        self.ack_t = None

    # ---------------------------------------------------------- main loop
    def run(self, snaps: List[Snap], t_end: Optional[float] = None) -> Result:
        if not snaps:
            raise ValueError("no snapshots")
        first = snaps[0]
        self.clk_high_since = first.t if first.clk == 1 else None
        if first.hclk:
            self.host_clk_low_since = first.t
        prev = first
        for cur in snaps[1:]:
            if cur.t < prev.t:
                raise ValueError("snapshots must be in time order")
            self._step(prev, cur)
            prev = cur
        end = t_end if t_end is not None else prev.t
        self._finish(prev, end)
        return Result(self.frames, self.violations, self.host_violations, dict(self._margins),
                      self.rts_response_ns, self.hold_off_ns,
                      {k: (v[0], v[1]) for k, v in self._values.items()})

    def _step(self, p: Snap, c: Snap):
        t = c.t
        # a pending DATA release after an ACK
        if self.release_deadline is not None:
            # the previous snapshot's level holds until this one, so an
            # overdue release edge still means DATA was low through the deadline
            held_low = (p.data == 0 and not p.hdata) or (c.data == 0 and not c.hdata)
            if t > self.release_deadline and held_low:
                self._v(self.release_deadline, "ack-release", "DATA still held low more than 50 us after the 11th clock")
                self.release_deadline = None
            elif c.data == 1:
                self.release_deadline = None
        # ---- host side
        if c.hdata != p.hdata and self.mode == "rx" and c.clk == 1 and not c.hclk:
            self._hv(t, "host-data-while-clk-high", "host changed DATA while CLK was high")
        if c.hclk and not p.hclk:
            self._host_clk_down(t, c)
        if p.hclk and not c.hclk:
            self._host_clk_up(t, c)
        # ---- line edges
        if c.clk != p.clk and not (p.hclk or c.hclk):
            # an edge with the host holding or just releasing the line is the
            # host's (handled above); every other edge is the device's
            if c.clk == 0:
                self._dev_clk_fall(t, p, c)
            else:
                self._dev_clk_rise(t, p, c)
        if c.data != p.data and not (p.hdata or c.hdata):
            self._dev_data_edge(t, p, c)

    # ------------------------------------------------------------- host
    def _host_clk_down(self, t, c):
        self.host_clk_low_since = t
        if self.mode in ("tx", "rx"):
            if self.falls >= FRAME_CLOCKS:
                self._complete(t, c)  # all 11 clocks were already out
            else:
                self.frame.aborted = True  # recorded when the host lets go
        elif self.mode == "rx_wait":
            pass  # a second request before the device answered: ignore

    def _host_clk_up(self, t, c):
        since = self.host_clk_low_since if self.host_clk_low_since is not None else t
        held = t - since
        # ---- request to send: DATA pulled low by the host when CLK is let go
        if c.hdata:
            if held < INHIBIT_MIN_NS:
                self._hv(t, "host-rts", f"CLK held low only {held:.0f} ns before the request to send (>= 100 us)")
            else:
                self._margin("host inhibit", lo=INHIBIT_MIN_NS, value=held)
            if self.mode in ("tx", "rx"):
                self._end_frame(aborted=True)
            self.mode = "rx_wait"
            self.rts_t = t
            self.clk_high_since = t
            self.frame = Frame("host->dev", t)
            self.falls = 0
            return
        # ---- plain inhibit released
        if held < INHIBIT_MIN_NS:
            self._hv(t, "host-inhibit", f"CLK held low only {held:.0f} ns (>= 100 us)")
        else:
            self._margin("host inhibit", lo=INHIBIT_MIN_NS, value=held)
        if self.mode in ("tx", "rx") and self.frame is not None and self.frame.aborted:
            if c.data == 0 and not c.hdata:
                self._v(t, "inhibit-release", "device still holds DATA low when the host releases CLK")
            self._end_frame(aborted=True)
        elif self.mode == "rx_wait":
            pass
        self.clk_high_since = t if c.clk == 1 else None

    # ------------------------------------------------------------ device
    def _dev_clk_fall(self, t, p, c):
        if self.mode == "rx_wait":
            resp = t - self.rts_t
            self.rts_response_ns.append(resp)
            if resp > RTS_RESPONSE_MAX_NS:
                self._v(t, "rts-response", f"device began clocking {resp:.0f} ns after the request (<= 15 ms)")
            self.mode = "rx"
            self.falls = 0
            self.last_rise = None
        elif self.mode not in ("tx", "rx"):
            self._v(t, "stray-clock", "device pulled CLK low outside a frame")
            return
        self.falls += 1
        k = self.falls
        if self.last_rise is not None:
            high = t - self.last_rise
            self._margin("CLK high", CLK_HALF_MIN_NS, CLK_HALF_MAX_NS, high)
            if not CLK_HALF_MIN_NS <= high <= CLK_HALF_MAX_NS:
                self._v(t, "clk-high", f"CLK high {high:.0f} ns before fall {k} (30..50 us)")
        if self.mode == "tx":
            self.frame.bits.append(p.data)
            if k == 1:
                setup = t - self.frame.t_start
                key = "start bit setup"
            else:
                setup = (t - self.last_dc) if self.last_dc is not None else None
                key = "data setup"
            if setup is not None:
                self._margin(key, DATA_BEFORE_FALL_MIN_NS, DATA_BEFORE_FALL_MAX_NS, setup)
                if not DATA_BEFORE_FALL_MIN_NS <= setup <= DATA_BEFORE_FALL_MAX_NS:
                    self._v(t, "data-setup", f"DATA changed {setup:.0f} ns before fall {k} (5..25 us)")
        else:  # rx
            if k == FRAME_CLOCKS:
                if c.hdata:
                    # the host is still pulling DATA (a 0 stop bit held through
                    # the pulse): the ACK cannot be told from the host's low
                    pass
                elif c.data != 0:
                    self._v(t, "no-ack", "DATA is not pulled low by the device at the 11th clock")
                if c.data == 0 and not c.hdata and self.ack_t is not None:
                    setup = t - self.ack_t
                    self._margin("ack setup", DATA_BEFORE_FALL_MIN_NS, DATA_BEFORE_FALL_MAX_NS, setup)
                    if not DATA_BEFORE_FALL_MIN_NS <= setup <= DATA_BEFORE_FALL_MAX_NS:
                        self._v(t, "ack-setup", f"ACK came {setup:.0f} ns before the 11th fall (5..25 us)")
        self.last_fall = t
        self.last_dc = None if self.mode == "tx" else self.last_dc

    def _dev_clk_rise(self, t, p, c):
        if self.mode not in ("tx", "rx") or self.last_fall is None:
            return
        low = t - self.last_fall
        self._margin("CLK low", CLK_HALF_MIN_NS, CLK_HALF_MAX_NS, low)
        if not CLK_HALF_MIN_NS <= low <= CLK_HALF_MAX_NS:
            self._v(t, "clk-low", f"CLK low {low:.0f} ns in pulse {self.falls} (30..50 us)")
        self.last_rise = t
        self.last_fall = None
        if self.mode == "rx" and self.falls <= 10:
            self.frame.bits.append(p.data)  # the device reads DATA on this edge
        if self.falls >= FRAME_CLOCKS:
            self._complete(t, c)
            self.clk_high_since = t

    def _complete(self, t, c):
        fr = self.frame
        fr.complete = True
        if self.mode == "tx":
            if fr.bits[0] != 0:
                self._v(t, "start-bit", "start bit is not 0")
            if not fr.parity_ok:
                self._v(t, "parity", f"frame {fr.bits} is not odd parity")
            if not fr.stop_ok:
                self._v(t, "stop-bit", "stop bit is not 1")
        elif c.data == 0 and not c.hdata:
            self.release_deadline = t + RELEASE_AFTER_FRAME_MAX_NS
        self._end_frame()

    def _dev_data_edge(self, t, p, c):
        if self.mode == "bus":
            if c.data == 0:
                if c.clk == 1 and not c.hclk:
                    idle = (t - self.clk_high_since) if self.clk_high_since is not None else 0.0
                    self.hold_off_ns.append(idle)
                    self._margin("hold-off", lo=IDLE_MIN_NS, value=idle)
                    if idle < IDLE_MIN_NS:
                        self._v(t, "hold-off", f"device began a frame after CLK was high only {idle:.0f} ns (>= 50 us)")
                    self.mode = "tx"
                    self.frame = Frame("dev->host", t)
                    self.falls = 0
                    self.last_rise = None
                    self.last_fall = None
                    self.last_dc = t
                else:
                    self._v(t, "data-while-inhibited", "device pulled DATA low while CLK was held low")
            return
        if self.mode == "tx":
            if c.clk == 0 and not c.hclk:
                self._v(t, "data-while-clk-low", "device changed DATA while it was holding CLK low")
            elif self.last_rise is not None:
                after = t - self.last_rise
                self._margin("data after rise", lo=DATA_AFTER_RISE_MIN_NS, value=after)
                if after < DATA_AFTER_RISE_MIN_NS:
                    self._v(t, "data-after-rise", f"DATA changed {after:.0f} ns after a CLK rise (>= 5 us)")
            self.last_dc = t
            return
        if self.mode == "rx_wait":
            if c.data == 0:
                self._v(t, "data-before-clock", "device pulled DATA low before it began clocking")
            return
        if self.mode == "rx":
            if c.data == 0 and self.falls == FRAME_CLOCKS - 1 and c.clk == 1:
                self.ack_t = t
            elif c.data == 0:
                self._v(t, "rx-data-drive", f"device pulled DATA low in pulse {self.falls}, outside the ACK")

    # --------------------------------------------------------------- end
    def _finish(self, last: Snap, t_end: float):
        if self.mode == "rx_wait" and self.rts_t is not None and t_end - self.rts_t > RTS_RESPONSE_MAX_NS:
            self._v(t_end, "rts-response", "device never began clocking after the request to send")
        if self.release_deadline is not None and last.data == 0 and not last.hdata and t_end > self.release_deadline:
            self._v(self.release_deadline, "ack-release", "DATA still held low more than 50 us after the 11th clock")
        if self.frame is not None and self.mode in ("tx", "rx"):
            self.frames.append(self.frame)
            self.frame = None


def check(snaps: List[Snap], t_end: Optional[float] = None) -> Result:
    """Grade one bus log."""
    return Ps2Monitor().run(snaps, t_end)


def retransmission_violations(result: Result) -> List[Violation]:
    """Every device frame abandoned by an inhibit must be followed, before
    the next host frame, by a complete frame with the same byte value."""
    out: List[Violation] = []
    frames = result.frames
    for i, f in enumerate(frames):
        if f.direction != "dev->host" or not f.aborted:
            continue
        nxt = next((g for g in frames[i + 1:] if g.direction == "dev->host" and g.complete), None)
        between = [g for g in frames[i + 1:] if nxt is None or g.t_start < nxt.t_start]
        host_in_between = any(g.direction == "host->dev" for g in between)
        if nxt is None:
            if not host_in_between:
                out.append(Violation(f.t_start, "no-retransmit", "an inhibited frame was never sent again"))
            continue
        if host_in_between:
            continue  # the host spoke first; the page lets the device's buffer be replaced
        sent = f.bits
        if nxt.bits[: len(sent)] != sent:
            out.append(Violation(nxt.t_start, "retransmit-mismatch",
                                 f"abandoned frame bits {sent} are not the prefix of the next frame {nxt.bits}"))
    return out
