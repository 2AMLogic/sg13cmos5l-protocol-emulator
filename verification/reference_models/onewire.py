"""Independent 1-Wire DS18B20 slave model and bus-master grader (issue #447).

Written from two Maxim documents, and from nothing else:

* the DS18B20 datasheet's 1-Wire standard-speed timing table (Maxim
  Integrated, "DS18B20 Programmable Resolution 1-Wire Digital Thermometer",
  document 19-7487): reset low >= 480 us, presence delay 15..60 us after
  the reset release, presence low 60..240 us, write-1 low 1..15 us,
  write-0 low 60..120 us, slot >= 60 us with >= 1 us recovery, read-slot
  low >= 1 us with the slave's data valid within 15 us of the slot's
  falling edge;
* Maxim application note AN27 ("Understanding and Using Cyclic Redundancy
  Checks with Dallas Semiconductor iButton and 1-Wire Products") for the
  ROM CRC-8: x^8 + x^5 + x^4 + 1, reflected polynomial 0x8C, init 0, bits
  consumed LSB first. `crc8` reproduces AN27's worked example (family
  0x02, serial 1C B8 01 00 00 00 -> CRC 0xA2) and the published
  CRC-8/1-Wire check value for the string "123456789" (0xA1);
  `test_onewire_model.py` asserts both, byte-wise and bit-by-bit.

Nothing here imports from `rtl/`, `firmware/` or any bench, and nothing
knows what the firmware does: the model sees one line (DQ) and whether the
**master's** pad is pulling it low. Every other low level is the slave's
own doing, which the model knows because it is the slave.

What it is
----------
An event-driven DS18B20 plus a passive grader over the same log. The bench
feeds every `Snap` (the resolved DQ level and the master's open-drain
enable at one instant) to `Ds18b20.observe`, applies the slave's `drive`
intent to the pad model, and wakes again at `deadline`. `check()` returns
everything the bench asserts on:

* `violations` -- the master's timing, every pulse measured in ns against
  the datasheet numbers above: reset low width, reset high (release to the
  next falling edge, which is the window the master must let the presence
  pulse finish in), each slot's low width classified by protocol state
  (write-1 / write-0 / read), fall-to-fall slot length, release-to-fall
  recovery;
* `events` -- the decoded protocol: resets, presence answered, the command
  bytes (Read ROM 0x33, Skip ROM 0xCC, Convert T 0x44, Read Scratchpad
  0xBE), each ROM / scratchpad byte served and when, and how many read
  slots the conversion poll took;
* `margins` / `measured` -- the smallest distance to each limit, and the
  smallest / largest measured value of each graded quantity.

Single-drop only, like the program it grades: one device on the bus, so
Skip ROM addresses it and Read ROM returns its 8 bytes. Search ROM,
multi-drop, overdrive speed, parasitic power and the alarm search are out
of scope. The real part's 750 ms conversion is not simulated:
`busy_slots` configures how many read slots answer 0 before the 1 that
says done; the datasheet's t_CONVMAX is a property of silicon this model
does not model.

Corruption hooks (the bench's error paths): `corrupt_rom_byte` /
`corrupt_scr_byte` flip bit 0 of one served data byte while leaving the
CRC byte alone -- the signature of a bit corrupted in transit, which the
master's CRC check must catch. `present=False` is the empty bus: no
presence pulse is ever answered.

Time is nanoseconds throughout, so a bench can pass simulation time as is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

US = 1000.0

#: Datasheet numbers, 1-Wire standard speed (ns; cycles at 20 ns in parens).
RESET_LOW_MIN_NS = 480 * US          # >= 24,000 cycles
RESET_HIGH_MIN_NS = 480 * US         # includes the presence window
RESET_LOW_GUESS_NS = 300 * US        # >= this but short: meant as a reset
PRESENCE_DELAY_MIN_NS = 15 * US      # slave: release -> pulling low
PRESENCE_DELAY_MAX_NS = 60 * US
PRESENCE_LOW_MIN_NS = 60 * US        # slave: how long it holds the pulse
PRESENCE_LOW_MAX_NS = 240 * US
WRITE1_LOW_MIN_NS = 1 * US           # master's write-1 low
WRITE1_LOW_MAX_NS = 15 * US
WRITE0_LOW_MIN_NS = 60 * US          # master's write-0 low
WRITE0_LOW_MAX_NS = 120 * US
READ_LOW_MIN_NS = 1 * US             # master's read-slot low
READ_LOW_MAX_NS = 15 * US
SLOT_MIN_NS = 60 * US                # fall -> fall
RECOVERY_MIN_NS = 1 * US             # release -> next fall
DATA_VALID_MAX_NS = 15 * US          # slave: falling edge -> data valid

READ_ROM, SKIP_ROM, CONVERT_T, READ_SCRATCHPAD = 0x33, 0xCC, 0x44, 0xBE


def crc8(data, crc: int = 0) -> int:
    """Dallas/Maxim CRC-8 (AN27): reflected poly 0x8C, init 0, LSB first.

    Byte-wise bitwise form; accepts any iterable of ints. The CRC of a
    byte stream with its own CRC byte appended is 0 -- the property the
    master's final check relies on.
    """
    for byte in data:
        for i in range(8):
            fb = (crc & 1) ^ ((byte >> i) & 1)
            crc >>= 1
            if fb:
                crc ^= 0x8C
    return crc


@dataclass(frozen=True)
class Snap:
    """DQ at time `t` (ns): the resolved level, and whether the master's
    open-drain pad is enabled (pulling low -- a master never drives high)."""

    t: float
    dq: int
    m_oe: int  # 1 = the master's pad is on (pulling low), 0 = released


@dataclass
class Violation:
    t: float
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.t:.0f} ns: {self.kind}: {self.detail}"


@dataclass
class Result:
    events: List[Tuple] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)
    #: smallest distance (ns) from a measured quantity to the limit it is
    #: held to, by name
    margins: dict = field(default_factory=dict)
    #: smallest and largest measured value (ns) of each graded quantity
    measured: dict = field(default_factory=dict)

    def kinds(self) -> List[str]:
        return sorted({v.kind for v in self.violations})

    def commands(self) -> List[int]:
        return [e[1] for e in self.events if e[0] == "cmd"]


def _bits_of(byte_list) -> List[int]:
    """A byte stream as 1-Wire sends it: LSB first, per byte."""
    out: List[int] = []
    for byte in byte_list:
        out += [(byte >> i) & 1 for i in range(8)]
    return out


class Ds18b20:
    """One DS18B20 on the bus, plus the master grader over the same log.

    Construct with the 8-byte `rom` (last byte = CRC of the first seven)
    and the 9-byte `scratchpad` (last byte = CRC of the first eight); the
    self-test holds both to that with `crc8`.
    """

    def __init__(self, rom: Tuple[int, ...], scratchpad: Tuple[int, ...],
                 busy_slots: int = 5, present: bool = True,
                 corrupt_rom_byte: Optional[int] = None,
                 corrupt_scr_byte: Optional[int] = None):
        assert len(rom) == 8 and crc8(rom[:7]) == rom[7]
        assert len(scratchpad) == 9 and crc8(scratchpad[:8]) == scratchpad[8]
        self.rom = tuple(rom)
        self.scratchpad = tuple(scratchpad)
        self.busy_slots = busy_slots
        self.present = present
        # what the bus actually carries (corruption hooks flip one bit)
        self._rom_out = list(rom)
        self._scr_out = list(scratchpad)
        if corrupt_rom_byte is not None:
            self._rom_out[corrupt_rom_byte] ^= 0x01
        if corrupt_scr_byte is not None:
            self._scr_out[corrupt_scr_byte] ^= 0x01
        # --- grader state
        self.events: List[Tuple] = []
        self.violations: List[Violation] = []
        self._margins: dict = {}
        self._values: dict = {}
        # --- slave drive state
        self._pull = False
        self._pull_at: Optional[float] = None    # start pulling DQ at t
        self._release_at: Optional[float] = None  # stop pulling DQ at t
        # --- protocol state
        self._last_t: Optional[float] = None
        self._was_oe: Optional[int] = None
        self._master_low_since: Optional[float] = None
        self._reset_release: Optional[float] = None
        self._slot_fall: Optional[float] = None
        self._slot_release: Optional[float] = None
        self._saw_presence = False
        # FSM: "idle" (nothing answered) -> "command" (8 write bits) ->
        # "second" (8 more after Skip ROM) -> "read_rom" (64 bits) /
        # "poll" (read slots until a 1) / "read_scr" (72 bits) -> "idle".
        self._mode = "idle"
        self._byte: List[int] = []
        self._read_plan: List[int] = []
        self._read_name = ""            # "rom" | "scratchpad"
        self._poll_busy_left = busy_slots

    # -------------------------------------------------------------- drive
    @property
    def pull(self) -> bool:
        """Whether the slave wants DQ low right now."""
        return self._pull

    @property
    def deadline(self) -> Optional[float]:
        """The next time the slave changes its drive, or None."""
        t = self._last_t or 0.0
        nexts = [x for x in (self._pull_at, self._release_at)
                 if x is not None and x > t]
        return min(nexts) if nexts else None

    def _set_pull(self, on: bool) -> None:
        self._pull = on
        self._pull_at = None
        self._release_at = None

    def _schedule_pull(self, at: float, until: float) -> None:
        """Pull DQ low from `at` to `until` (both absolute times)."""
        self._pull = False
        self._pull_at = at
        self._release_at = until

    # ------------------------------------------------------------ observe
    def observe(self, s: Snap) -> None:
        """Feed one snapshot. The bench calls this at every change of DQ or
        of the master's enable, in time order."""
        if self._last_t is not None and s.t < self._last_t:
            return  # ignore an out-of-order replay
        t0, t1 = self._last_t, s.t
        self._last_t = s.t
        # fire scheduled slave transitions inside (t0, t1]
        if t0 is not None:
            for fire_at in sorted(x for x in (self._pull_at, self._release_at)
                                  if x is not None and t0 < x <= t1):
                if fire_at == self._pull_at:
                    self._pull = True
                else:
                    self._pull, self._release_at = False, None
        if self._was_oe is None:
            self._was_oe = s.m_oe
            return
        if s.m_oe and not self._was_oe:            # falling edge
            self._on_master_fall(t1)
        elif not s.m_oe and self._was_oe:          # release
            self._on_master_release(t1)
        self._was_oe = s.m_oe

    # ------------------------------------------------------------- grader
    def _v(self, t, kind, detail):
        self.violations.append(Violation(t, kind, detail))

    def _m(self, key, value, lo=None, hi=None):
        pair = self._values.setdefault(key, [value, value])
        pair[0], pair[1] = min(pair[0], value), max(pair[1], value)
        if lo is None and hi is None:
            return
        edges = [d for d in ((value - lo) if lo is not None else None,
                             (hi - value) if hi is not None else None)
                 if d is not None]
        m = min(edges)
        if key not in self._margins or m < self._margins[key]:
            self._margins[key] = m

    def _on_master_fall(self, t: float) -> None:
        if self._master_low_since is not None:
            return  # already low: not a new edge
        if self._slot_release is not None:
            self._m("recovery", t - self._slot_release, lo=RECOVERY_MIN_NS)
            if t - self._slot_release < RECOVERY_MIN_NS:
                self._v(t, "recovery-short",
                        f"only {t - self._slot_release:.0f} ns of recovery "
                        f"(< {RECOVERY_MIN_NS:.0f})")
        if self._slot_fall is not None:
            self._m("slot", t - self._slot_fall, lo=SLOT_MIN_NS)
            if t - self._slot_fall < SLOT_MIN_NS:
                self._v(t, "slot-too-short",
                        f"fall-to-fall {t - self._slot_fall:.0f} ns "
                        f"< {SLOT_MIN_NS:.0f}")
        if self._reset_release is not None:
            self._m("reset-high", t - self._reset_release, lo=RESET_HIGH_MIN_NS)
            if t - self._reset_release < RESET_HIGH_MIN_NS:
                self._v(t, "reset-high-short",
                        f"reset high {t - self._reset_release:.0f} ns < "
                        f"{RESET_HIGH_MIN_NS:.0f} (the presence window was "
                        "not waited out)")
            self._reset_release = None
        self._slot_fall = t
        self._master_low_since = t
        # the master owns the line from here: end any 0-bit drive
        if self._pull:
            self._set_pull(False)

    def _on_master_release(self, t: float) -> None:
        start = self._master_low_since
        self._master_low_since = None
        low = t - start if start is not None else 0.0
        self._slot_release = t
        if low >= RESET_LOW_MIN_NS:
            self._m("reset-low", low, lo=RESET_LOW_MIN_NS)
            self.events.append(("reset", t))
            self._saw_presence = False
            self._byte = []
            self._read_plan = []
            self._mode = "idle"
            self._reset_release = t
            # close the just-finished slot bookkeeping: a reset is not a slot
            self._slot_fall = None
            self._slot_release = None
            if self.present:
                delay = 30 * US   # inside presence-delay 15..60 us
                hold = 120 * US   # inside presence-low 60..240 us
                self._schedule_pull(t + delay, t + delay + hold)
                self._saw_presence = True
                self.events.append(("presence", t))
                self._mode = "command"
            return
        if low >= RESET_LOW_GUESS_NS:
            # long enough that it was meant as a reset, too short to be one
            self._m("reset-low", low, lo=RESET_LOW_MIN_NS)
            self._v(t, "reset-low-short",
                    f"reset low {low:.0f} ns < {RESET_LOW_MIN_NS:.0f}; no "
                    "presence is answered and none was expected")
            self._slot_fall = None
            self._slot_release = None
            return
        if self._slot_fall is None:
            return
        if self._mode in ("read_rom", "poll", "read_scr"):
            self._m("read-low", low, lo=READ_LOW_MIN_NS, hi=READ_LOW_MAX_NS)
            if not READ_LOW_MIN_NS <= low <= READ_LOW_MAX_NS:
                self._v(t, "read-low-width",
                        f"read-slot low {low:.0f} ns outside "
                        f"{READ_LOW_MIN_NS:.0f}..{READ_LOW_MAX_NS:.0f}")
            self._serve_read_bit(t)
        elif self._mode in ("command", "second"):
            if low <= WRITE1_LOW_MAX_NS:
                self._m("write1-low", low, lo=WRITE1_LOW_MIN_NS, hi=WRITE1_LOW_MAX_NS)
                if low < WRITE1_LOW_MIN_NS:
                    self._v(t, "write1-low-width",
                            f"write-1 low {low:.0f} ns < {WRITE1_LOW_MIN_NS:.0f}")
                self._take_bit(1, t)
            elif low >= WRITE0_LOW_MIN_NS:
                self._m("write0-low", low, lo=WRITE0_LOW_MIN_NS, hi=WRITE0_LOW_MAX_NS)
                if low > WRITE0_LOW_MAX_NS:
                    self._v(t, "write0-low-width",
                            f"write-0 low {low:.0f} ns > {WRITE0_LOW_MAX_NS:.0f}")
                self._take_bit(0, t)
            else:
                self._m("slot-low", low)
                self._v(t, "slot-low-width",
                        f"write-slot low {low:.0f} ns is neither a write-1 "
                        f"(<= {WRITE1_LOW_MAX_NS:.0f}) nor a write-0 "
                        f"(>= {WRITE0_LOW_MIN_NS:.0f})")
        else:
            self._v(t, "stray-slot", f"a slot while idle (no presence "
                                     f"exchange): low {low:.0f} ns")

    def _take_bit(self, bit: int, t: float) -> None:
        self._byte.append(bit)
        if len(self._byte) < 8:
            return
        value = sum(b << i for i, b in enumerate(self._byte))  # LSB first
        self._byte = []
        if self._mode == "command":
            self.events.append(("cmd", value, t))
            if value == READ_ROM:
                self._read_plan = _bits_of(self._rom_out)
                self._read_name = "rom"
                self._mode = "read_rom"
            elif value == SKIP_ROM:
                self._mode = "second"
            else:
                self._v(t, "unknown-command", f"command 0x{value:02X}")
                self._mode = "idle"
            return
        # the second command byte after Skip ROM
        self.events.append(("cmd", value, t))
        if value == CONVERT_T:
            self._poll_busy_left = self.busy_slots
            self._mode = "poll"
        elif value == READ_SCRATCHPAD:
            self._read_plan = _bits_of(self._scr_out)
            self._read_name = "scratchpad"
            self._mode = "read_scr"
        else:
            self._v(t, "unknown-command", f"command 0x{value:02X}")
            self._mode = "idle"

    def _serve_read_bit(self, t: float) -> None:
        bit: int
        if self._mode == "poll":
            bit = 0 if self._poll_busy_left > 0 else 1
            if bit:
                self.events.append(("conversion-done", t))
                self._mode = "idle"   # the master resets before the next byte
            else:
                self._poll_busy_left -= 1
                self.events.append(("poll-busy", t))
        elif self._mode in ("read_rom", "read_scr"):
            if not self._read_plan:
                self._v(t, "stray-read-slot", "more read slots than bytes")
                return
            bit = self._read_plan.pop(0)
            if len(self._read_plan) % 8 == 0:    # a whole byte just finished
                served = getattr(self, "_rom_out" if self._read_name == "rom"
                                 else "_scr_out")
                done = len(served) - len(self._read_plan) // 8
                self.events.append((f"{self._read_name}-byte", served[done - 1], t))
                if not self._read_plan:
                    self._mode = "idle"
        else:
            self._v(t, "stray-read-slot", f"a read slot during {self._mode!r}")
            return
        if bit == 0:
            # pull DQ low from now until ~45 us past the slot's falling
            # edge: past the master's 15 us sample window, gone before its
            # next slot (a real part releases inside the time slot, so a
            # transaction that simply stops cannot leave the bus held)
            fall = self._slot_fall if self._slot_fall is not None else t
            self._pull = True
            self._pull_at = None                       # already pulling
            self._release_at = max(fall + 45 * US, t)
        else:
            self._set_pull(False)

    # ------------------------------------------------------------- report
    def check(self) -> Result:
        return Result(events=list(self.events), violations=list(self.violations),
                      margins=dict(self._margins), measured=dict(self._values))
