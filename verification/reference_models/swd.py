"""Independent SWD target model (multi-protocol extra credit, issue #452; the
protocol choice is the dated note of 2026-11-19 in DR 0018, fourth revision).

Written from one source: the Arm Debug Interface v5 architecture specification
(ARM IHI 0031, section B4, "SWD"), with the connection shape -- first line
reset, 0xE79E switch, second line reset, idle clocks -- taken from pyOCD's
SWJ mode selection (`pyocd/probe/swj.py`), the observable reference for what
a working probe sends. **No copy of IHI 0031 was fetched into this
repository**, so the constants here carry DR 0015's "confirm" mark, exactly as
DR 0018's note records for the same constants: a fetched copy must be checked
against them before this model is used to certify silicon behaviour. Nothing
here imports from `rtl/`, `firmware/` or any bench, and nothing here knows
what the firmware does: the model sees only the two lines (SWCLK, SWDIO),
whether the probe is driving SWDIO, and the time.

What it is
----------
An *interactive* target, not a passive monitor: SWD turns the data line around
mid-transaction, so the model must drive SWDIO while the bench runs. The
bench calls `on_pad(t_ns, swclk, swdio, host_oe)` on every settled change of
the resolved lines or of the probe's SWDIO output-enable, then applies
`self.drive` (None = released, else the level to drive) to the pad model. The
reaction is zero-delay (same time step), which is the aggressive-but-legal
corner IHI 0031 section B4.3.1 allows: a target may change or release SWDIO
on any rising SWCLK edge. A probe that samples after the rise instead of in
the low phase before it -- the defect DR 0018's fourth revision corrected --
mis-decodes against exactly this model.

Protocol implemented, and what is graded
----------------------------------------
* **Line reset**: at least 50 SWCLK cycles with SWDIO high, before the switch
  and again after it (pyOCD sends both). A short run is `line-reset-short`,
  and the target stays dormant: it never takes the line, so a probe that
  skipped the reset reads the pull-up through every response phase.
* **JTAG-to-SWD switch**: the 16 rise-sampled bits, LSB first, must equal
  0xE79E, else `switch-sequence` and no connection.
* **Idle**: at least two SWCLK clocks with SWDIO low before the first request
  (`idle-after-switch`).
* **Request frame**: 8 bits sampled at SWCLK rising edges, LSB first:
  start(1), APnDP, RnW, A2, A3, parity, stop(0), park(1). The parity bit is
  the even parity over APnDP/RnW/A2/A3 (an odd number of ones there -> parity
  1), the bit CMSIS-DAP's request generator produces; a frame with a wrong
  start, stop, park or parity is reported for its own field (`request-parity`
  and friends) and gets **no response**: the target never takes the line and
  the probe reads the pull-up (all 1s) through the response phase.
* **Turnaround**: after the request's park bit the probe must release SWDIO
  (its output-enable low) while SWCLK is low; the target takes the line on
  the next rising edge. A probe still driving there is `no-release`, and the
  bench's pad model reports the contention of the two drivers. After the
  final response bit both sides release SWDIO for one return turnaround
  cycle. The probe then takes the line while SWCLK is low.
* **Response**: the three-bit ACK is sent LSB first. OK (numeric 1) is
  1,0,0 on the wire, WAIT (2) is 0,1,0, and FAULT (4) is 0,0,1.
  After OK the target sends 32 data bits LSB first, then even parity
  (0x4BA00477 has 13 set bits, so its parity bit is 1). With
  CTRL/STAT.ORUNDETECT = 0, WAIT and FAULT go directly from the last ACK
  bit to the return turnaround.
* **Trailing idle**: after the last transfer, at least eight SWCLK clocks
  with SWDIO low (driven low by the probe) before SWCLK stops, else
  `trailing-idle-short` (graded at `finish()`).
* **Host-write stability**: while the probe drives SWDIO, SWDIO may change
  only while SWCLK is low, and must be stable across every rising edge
  (`swdio-change-while-high`).
* **Measured, not limited**: SWCLK high/low widths are recorded (min/max per
  phase, ns and cycles at 20 ns/cycle, target-spec row 4's unconfirmed 50
  MHz). ADIv5 sets no numeric width minimum for a host-generated clock, so
  none is invented here; the recorded figures are the evidence, held against
  DR 0018's table by the bench.

Time is nanoseconds throughout; `on_pad` times need only be monotonic.

Memory-access-port mode (issue #500)
------------------------------------
Constructed with `ap=MemAp(...)`, the target answers by *decoding* each
request instead of replaying a script, and it accepts write requests. What it
models, from ADIv5 (IHI 0031 chapter B2, "DP registers", and the MEM-AP
register map of chapter C2) alone -- every register address and field
below carries the same "confirm" mark as the constants above, since no copy
of IHI 0031 is in this repository:

* DP reads at A[3:2] = 0b00 (DPIDR, the IDCODE) and 0b11 (RDBUFF); DP writes
  at 0b10 (SELECT). Any other DP register is `unmodeled-register`.
* **SELECT has no reset value** (IHI 0031 marks it UNKNOWN after reset), so
  an AP access before a SELECT write is `ap-not-selected`: a probe cannot
  skip the write. Only APSEL = 0 and APBANKSEL = 0 name this MEM-AP's TAR /
  DRW window; DPBANKSEL is ignored (DP register 0x4 is not modeled).
* The MEM-AP's **word-access starting state**: CSW is *not written* by the
  probe, so the model starts with CSW.Size = 0b010 (32-bit word) and
  CSW.AddrInc = 0b00 (no auto-increment) -- the state a DRW access at a
  word-aligned TAR needs. CSW (AP 0x00) reads back that start value; a real
  part may reset CSW differently (implementation-defined: the model records
  the assumption, it does not prove it for silicon).
* **TAR has no reset value either**: a DRW access before a TAR write is
  `tar-unset`; a TAR that is not word aligned is `tar-unaligned`.
* **A DRW read is posted** (IHI 0031 B2.2.7 / C2): the read returns the
  *previous* read-buffer value and starts the access at TAR; the addressed
  word is only available from the read buffer, through a DP RDBUFF read (or
  the next AP read). The read buffer starts at `posted_initial`, deliberately
  different from every fixture word, so a probe that reports the DRW read as
  the result is told apart from one that reads RDBUFF.
* **Write data**: 32 bits LSB first plus even parity, driven by the probe
  from the cycle after the return turnaround. A wrong parity bit is
  `write-parity` and the write is discarded (AP / DP state unchanged); a write
  answered WAIT or FAULT has no data phase and never changes state.
* `acks={n: ACK_*}` makes the nth well-formed request (1-based) answer WAIT or
  FAULT, so a rejected write can be exercised.
* **A protocol error** (`ACK_NONE`: no answer, the line reads 1,1,1; `ACK_BAD`:
  1,0,1): the probe must not take SWDIO for the possible 32 + 1 data bits that
  follow the turnaround (`driven-after-bad-ack` otherwise: a probe that treats
  1,1,1 as OK drives its write data into a line nobody acknowledged). The
  target never expects a data phase and the probe issues no further request;
  a longer release is allowed (Arm's CMSIS-DAP backs off 33 clocks too).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#: DR 0018's recorded ADIv5 / pyOCD constants (all "confirm": no IHI 0031 in-repo).
RESET_MIN_CYCLES = 50          # line reset: >= 50 SWCLK cycles with SWDIO high
SWITCH_CODE = 0xE79E           # JTAG-to-SWD switch code, sent LSB first
SWITCH_BITS = 16
IDLE_AFTER_SWITCH_MIN = 2      # idle clocks, SWDIO low, before the first request
TRAILING_IDLE_MIN = 8          # idle clocks, SWDIO low, before SWCLK stops
REQUEST_BITS = 8               # start, APnDP, RnW, A2, A3, parity, stop, park
RESPONSE_BITS = 36             # ACK 3 + read data 32 + parity 1
#: One core cycle at target-spec row 4's target 50 MHz clock (unconfirmed).
NS_PER_CYCLE = 20.0

WRITE_BITS = 33                # write data: 32 bits + parity

#: ADIv5 register addresses as (A[3:2]) decoded values (all "confirm").
DP_DPIDR_READ = 0b00           # DP address 0x0, read: DPIDR
DP_SELECT_WRITE = 0b10         # DP address 0x8, write: SELECT
DP_RDBUFF_READ = 0b11          # DP address 0xC, read: RDBUFF
AP_CSW = 0b00                  # AP address 0x0 (bank 0): CSW
AP_TAR = 0b01                  # AP address 0x4 (bank 0): TAR
AP_DRW = 0b11                  # AP address 0xC (bank 0): DRW
#: CSW word-access starting state: Size = 0b010 (32-bit), AddrInc = 0b00.
CSW_START = 0x00000002

ACK_OK = "OK"
ACK_WAIT = "WAIT"
ACK_FAULT = "FAULT"
#: Not ACK codes: a target that does not answer (SWDIO released, the pull-up
#: reads 1,1,1) and one that drives 1,0,1 (two ones: neither OK nor WAIT nor
#: FAULT). Only the 1,0,0 wire pattern is OK.
ACK_NONE = "NONE"
ACK_BAD = "BAD"
#: ACK in time order on the wire (first bit sent first). ADIv5 numeric codes
#: are OK=0b001, WAIT=0b010, FAULT=0b100, sent LSB first (IHI 0031 B4.1.5),
#: so the wire carries OK = 1,0,0; WAIT = 0,1,0; FAULT = 0,0,1.
ACK_WIRE = {ACK_OK: (1, 0, 0), ACK_WAIT: (0, 1, 0), ACK_FAULT: (0, 0, 1),
            ACK_NONE: (None, None, None), ACK_BAD: (1, 0, 1)}


def request_parity(apn_dp: int, rn_w: int, a2: int, a3: int) -> int:
    """The request parity bit: even parity over APnDP/RnW/A2/A3 -- 1 when the
    four bits hold an odd number of ones (CMSIS-DAP's generator)."""
    return (apn_dp + rn_w + a2 + a3) & 1


def read_value_parity(value: int) -> int:
    """The read parity bit: even parity over the 32 data bits plus the parity
    bit itself -- 1 when the data holds an odd number of ones."""
    return bin(value).count("1") & 1


@dataclass
class Violation:
    t: float
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.t:.0f} ns: {self.kind}: {self.detail}"


@dataclass
class Request:
    """One request frame the model decoded."""

    t_start: float
    bits: List[int] = field(default_factory=list)  # wire order, bit 0 first
    ok: bool = False
    start: Optional[int] = None
    apn_dp: Optional[int] = None
    rn_w: Optional[int] = None
    a2: Optional[int] = None
    a3: Optional[int] = None
    parity: Optional[int] = None
    stop: Optional[int] = None
    park: Optional[int] = None

    @property
    def byte(self) -> Optional[int]:
        if len(self.bits) != REQUEST_BITS:
            return None
        return sum(b << i for i, b in enumerate(self.bits))

    def field_decode(self) -> str:
        return (f"start={self.start} APnDP={self.apn_dp} RnW={self.rn_w} "
                f"A2={self.a2} A3={self.a3} parity={self.parity} "
                f"stop={self.stop} park={self.park}")


@dataclass
class MemAp:
    """The DP and the single MEM-AP behind the target (see the module
    docstring for the semantics); holds the state a probe's transactions
    change and the log the bench grades."""

    idcode: int = 0x4BA00477
    mem: Dict[int, int] = field(default_factory=dict)
    #: the AP read buffer after reset: what the first DRW read returns
    posted_initial: int = 0xA5A5C3C3
    select: Optional[int] = None
    tar: Optional[int] = None
    csw: int = CSW_START
    rdbuff: int = 0
    #: ("write"|"read", register name, value) in transaction order
    log: List[Tuple[str, str, int]] = field(default_factory=list)

    def __post_init__(self):
        self.rdbuff = self.posted_initial & 0xFFFFFFFF


class SwdTarget:
    """The scripted SWD target and, in the same pass, the grader of what the
    probe did to the lines.

    `reads` configures the response to the Nth well-formed read request as
    `(ack_name, 32-bit value)`. The default answers OK twice: the IDCODE-style
    value 0x4BA00477 first, then 0x12345678, the pair DR 0018's measurement
    used. `idcode` is a keyword alias for the first read's value.

    State machine (all transitions on SWCLK rising edges unless said):
    reset1 -> switch -> reset2 -> idle -> [connected] request ->
    await-turnaround -> response -> post-response -> request ... with
    post-response ending in the trailing idle clocks the probe owes ADIv5
    before it stops SWCLK.
    """

    def __init__(self, reads: Optional[List[Tuple[str, int]]] = None,
                 idcode: int = 0x4BA00477, ap: Optional[MemAp] = None,
                 acks: Optional[Dict[int, str]] = None):
        self.ap = ap
        self.ack_overrides: Dict[int, str] = dict(acks or {})
        #: pending write: the request and its collected data bits
        self._wreq: Optional[Request] = None
        self._wbits: List[int] = []
        self.ack_log: List[str] = []
        first = (ACK_OK, idcode & 0xFFFFFFFF)
        self.reads: List[Tuple[str, int]] = list(reads) if reads else [first, (ACK_OK, 0x12345678)]
        self.violations: List[Violation] = []
        #: what the target applies to SWDIO after the last on_pad call
        self.drive: Optional[int] = None
        self.connected = False
        self.requests: List[Request] = []
        #: (phase, SWDIO) at every SWCLK rising edge, wire order
        self.wire: List[Tuple[str, int]] = []
        self.rise_count = 0
        #: SWCLK phase widths (ns): phase -> [min, max], high and low apart
        self.widths: dict[str, List[float]] = {}
        self.low_widths: dict[str, List[float]] = {}
        # observation memory
        self._last_clk: Optional[int] = None
        self._last_dio: Optional[int] = None
        self._last_host_oe: Optional[bool] = None
        self._rise_t: Optional[float] = None
        self._fall_t: Optional[float] = None
        # state
        self._state = "reset1"
        self._high_run = 0
        self._switch_bits: List[int] = []
        self._idle_lows = 0
        self._frame: Optional[Request] = None
        self._resp_bits: List[int] = []
        self._resp_index = 0
        self._taken = False
        self._await_takeover = False
        self._read_no = 0
        self._tail_lows = 0
        self._flagged_not_driven = False
        self._return_turnaround = False
        self._flagged_released = False
        self._protocol_error = False
        self._backoff = 0
        self._flagged_backoff = False

    # ------------------------------------------------------------ helpers
    def _v(self, t, kind, detail):
        self.violations.append(Violation(t, kind, detail))

    def _width(self, value: float, high: bool):
        table = self.widths if high else self.low_widths
        entry = table.setdefault(self._state, [value, value])
        entry[0], entry[1] = min(entry[0], value), max(entry[0], value)

    def _launch_response(self, t: float = 0.0, f: Optional["Request"] = None) -> None:
        self._read_no += 1
        n = self._read_no
        if self.ap is not None and f is not None:
            self._launch_ap_response(t, f, n)
            return
        ack, value = (self.reads[n - 1]
                      if n - 1 < len(self.reads) else (ACK_OK, 0))
        self.ack_log.append(ack)
        bits = list(ACK_WIRE[ack])
        # WAIT / FAULT end after the ACK (CTRL/STAT.ORUNDETECT = 0, the
        # power-up setting): no data phase, so no data or parity bits follow.
        if ack == ACK_OK:
            bits += [(value >> i) & 1 for i in range(32)] + [read_value_parity(value)]
        self._resp_bits = bits
        self._resp_index = 0

    def _launch_ap_response(self, t: float, f: "Request", n: int) -> None:
        """Decode the request against the DP / MEM-AP and build the response:
        an ACK for a write (its data phase follows from the probe), an ACK and
        the register value for a read."""
        ap = self.ap
        ack = self.ack_overrides.get(n, ACK_OK)
        self.ack_log.append(ack)
        reg = (f.a3 << 1) | f.a2
        bits = list(ACK_WIRE[ack])
        if ack in (ACK_NONE, ACK_BAD):
            self._protocol_error = True
            self._resp_bits = bits
            self._resp_index = 0
            return
        if f.rn_w == 0:
            if ack == ACK_OK:
                self._wreq = f
                self._wbits = []
            self._resp_bits = bits
            self._resp_index = 0
            return
        value = 0
        if ack == ACK_OK:
            value = self._ap_read(t, f, reg)
            bits += [(value >> i) & 1 for i in range(32)] + [read_value_parity(value)]
        self._resp_bits = bits
        self._resp_index = 0

    def _ap_selected(self, t: float, what: str) -> bool:
        ap = self.ap
        if ap.select is None:
            self._v(t, "ap-not-selected",
                    f"{what} before any SELECT write: SELECT has no reset "
                    "value, so no AP is selected")
            return False
        if (ap.select >> 24) != 0 or ((ap.select >> 4) & 0xF) != 0:
            self._v(t, "ap-not-selected",
                    f"{what} with SELECT {ap.select:#010x}: this MEM-AP answers "
                    "APSEL 0, APBANKSEL 0 only")
            return False
        return True

    def _ap_read(self, t: float, f: "Request", reg: int) -> int:
        ap = self.ap
        if f.apn_dp == 0:
            if reg == DP_DPIDR_READ:
                ap.log.append(("read", "DPIDR", ap.idcode))
                return ap.idcode
            if reg == DP_RDBUFF_READ:
                ap.log.append(("read", "RDBUFF", ap.rdbuff))
                return ap.rdbuff
            self._v(t, "unmodeled-register",
                    f"DP read at A[3:2]={reg:#04b} is not modeled")
            return 0
        if reg == AP_DRW:
            returned = ap.rdbuff
            if self._ap_selected(t, "an AP DRW read"):
                if ap.tar is None:
                    self._v(t, "tar-unset",
                            "a DRW access before any TAR write: TAR has no reset value")
                    ap.rdbuff = 0
                elif ap.tar & 3:
                    self._v(t, "tar-unaligned",
                            f"TAR {ap.tar:#010x} is not word aligned (CSW.Size = word)")
                    ap.rdbuff = 0
                else:
                    ap.rdbuff = ap.mem.get(ap.tar, 0) & 0xFFFFFFFF
            else:
                ap.rdbuff = 0
            ap.log.append(("read", "DRW", returned))
            return returned
        if reg == AP_CSW:
            # An AP register read is posted like DRW: it returns the pending
            # read-buffer value and queues CSW for the next read.
            returned = ap.rdbuff
            if self._ap_selected(t, "an AP CSW read"):
                ap.rdbuff = ap.csw
            else:
                ap.rdbuff = 0
            ap.log.append(("read", "CSW", returned))
            return returned
        self._v(t, "unmodeled-register",
                f"AP read at A[3:2]={reg:#04b} is not modeled")
        return 0

    def _ap_write(self, t: float, f: "Request", value: int) -> None:
        ap = self.ap
        reg = (f.a3 << 1) | f.a2
        if f.apn_dp == 0 and reg == DP_SELECT_WRITE:
            ap.select = value
            ap.log.append(("write", "SELECT", value))
        elif f.apn_dp == 1 and reg == AP_TAR:
            if self._ap_selected(t, "an AP TAR write"):
                ap.tar = value
                ap.log.append(("write", "TAR", value))
        else:
            self._v(t, "unmodeled-register",
                    f"a write at APnDP={f.apn_dp} A[3:2]={reg:#04b} is not modeled")

    # ---------------------------------------------------------- main loop
    def on_pad(self, t: float, swclk: int, swdio: int, host_oe: bool) -> None:
        """One settled observation: resolved `swclk` / `swdio` levels and
        whether the probe's pad is driving SWDIO (`host_oe`)."""
        if self._last_clk is not None:
            if swclk == 1 and self._last_clk == 0:
                if self._fall_t is not None:
                    self._width(t - self._fall_t, high=False)
                self._rise_t = t
                self._on_rise(t, swdio, host_oe)
            elif swclk == 0 and self._last_clk == 1:
                if self._rise_t is not None:
                    self._width(t - self._rise_t, high=True)
                self._fall_t = t
            elif swdio != self._last_dio or host_oe != self._last_host_oe:
                self._on_flat(t, swclk, swdio, host_oe)
        # the probe may move SWDIO only while SWCLK is low (host-write phases)
        if (self._last_dio is not None and swdio != self._last_dio
                and host_oe and self._last_host_oe and swclk == 1):
            self._v(t, "swdio-change-while-high",
                    "the probe changed SWDIO during an SWCLK high phase "
                    "(host data must be stable across the rising edge)")
        self._last_clk, self._last_dio, self._last_host_oe = swclk, swdio, host_oe

    def _on_flat(self, t: float, swclk: int, swdio: int, host_oe: bool) -> None:
        """SWDIO / output-enable changes between clock edges."""
        if host_oe and self._last_host_oe is False and swclk == 1 and self.connected:
            self._v(t, "redrive-while-high",
                    "the probe re-drove SWDIO during an SWCLK high phase "
                    "(it must re-drive while SWCLK is low)")

    def _on_rise(self, t: float, swdio: int, host_oe: bool) -> None:
        self.rise_count += 1
        self.wire.append((self._state, swdio))
        if self._await_takeover:
            self._takeover(t, host_oe)
            return
        if self._taken:
            self._response_rise()
            return
        if self._frame is not None:
            self._request_rise(t, swdio, host_oe)
            return
        state = self._state
        if state == "reset1":
            self._reset_rise(t, swdio, which="first")
        elif state == "switch":
            self._switch_rise(t, swdio)
        elif state == "reset2":
            self._reset_rise(t, swdio, which="second")
        elif state == "idle":
            self._idle_rise(t, swdio, host_oe)
        elif state == "write-data":
            self._wdata_rise(t, swdio, host_oe)
        elif state == "ack-backoff":
            self._backoff_rise(t, host_oe)
        elif state in ("post-response", "no-response"):
            self._between_rise(t, swdio, host_oe)

    # -- connection -------------------------------------------------------
    def _reset_rise(self, t: float, swdio: int, which: str) -> None:
        if swdio == 1:
            self._high_run += 1
            return
        # a low bit ends the run
        if which == "first":
            if self._high_run >= RESET_MIN_CYCLES:
                self._switch_bits = [0]
                self._state = "switch"
                self.wire[-1] = ("switch", swdio)  # this rise begins the switch
            else:
                if self._high_run:
                    self._v(t, "line-reset-short",
                            f"the {'first' if which == 'first' else which} line reset "
                            f"held SWDIO high for {self._high_run} SWCLK cycles, "
                            f"fewer than the {RESET_MIN_CYCLES} required (the target "
                            "stays dormant and never takes the line)")
                self._high_run = 0
        else:
            if self._high_run < RESET_MIN_CYCLES:
                self._v(t, "line-reset-short",
                        f"the second line reset held SWDIO high for "
                        f"{self._high_run} SWCLK cycles, fewer than the "
                        f"{RESET_MIN_CYCLES} the connection shape requires "
                        "(pyOCD sends a full reset after the switch)")
            self._high_run = 0
            self._idle_lows = 1
            self._state = "idle"

    def _switch_rise(self, t: float, swdio: int) -> None:
        self._switch_bits.append(swdio)
        if len(self._switch_bits) < SWITCH_BITS:
            return
        code = sum(b << i for i, b in enumerate(self._switch_bits))
        self._switch_bits = []
        if code != SWITCH_CODE:
            self._v(t, "switch-sequence",
                    f"the 16 switch bits decoded to {code:#06x}, not "
                    f"{SWITCH_CODE:#06x} (the JTAG-to-SWD switch is LSB "
                    "first; the target stays dormant)")
            self._high_run = 0
            self._state = "reset1"
            return
        self._high_run = 0
        self._state = "reset2"

    def _idle_rise(self, t: float, swdio: int, host_oe: bool) -> None:
        if swdio == 0:
            self._idle_lows += 1
            return
        if self._idle_lows < IDLE_AFTER_SWITCH_MIN:
            self._v(t, "idle-after-switch",
                    f"only {self._idle_lows} idle SWCLK cycle(s) with SWDIO "
                    f"low before the first request; the connection shape "
                    f"pyOCD sends waits at least {IDLE_AFTER_SWITCH_MIN}")
        self.connected = True
        self._start_frame(t)

    # -- requests ---------------------------------------------------------
    def _start_frame(self, t: float) -> None:
        self._frame = Request(t_start=t, bits=[1])  # the start bit was just risen
        self._state = "request"
        self._tail_lows = 0
        self.wire[-1] = ("request", 1)  # this rise begins the request

    def _request_rise(self, t: float, swdio: int, host_oe: bool) -> None:
        assert self._frame is not None
        if not host_oe and not self._flagged_not_driven:
            self._flagged_not_driven = True
            self._v(t, "request-not-driven",
                    "a request bit rose while the probe was not driving SWDIO")
        if len(self._frame.bits) < REQUEST_BITS:
            self._frame.bits.append(swdio)
            if len(self._frame.bits) < REQUEST_BITS:
                return
        f = self._frame
        self._frame = None
        (f.start, f.apn_dp, f.rn_w, f.a2, f.a3, f.parity, f.stop, f.park) = f.bits
        bad = None
        if f.start != 1:
            bad = "request-start"
        elif f.stop != 0:
            bad = "request-stop"
        elif f.park != 1:
            bad = "request-park"
        elif f.parity != request_parity(f.apn_dp, f.rn_w, f.a2, f.a3):
            bad = "request-parity"
        f.ok = bad is None
        self.requests.append(f)
        if bad is not None:
            self._v(t, bad, f"a request frame ({f.field_decode()}, byte "
                            f"{f.byte:#04x}) failed its {bad.split('-', 1)[1]} "
                            "field; the target sends no response and the probe "
                            "reads the pull-up through the response phase")
            self._state = "no-response"
            return
        if f.rn_w != 1 and self.ap is None:
            self._v(t, "write-request",
                    "a write request (RnW 0) was sent; this scripted target "
                    "answers reads only (DR 0018: probe-driven writes do not "
                    "fit the unrolled schedule)")
            self._state = "no-response"
            return
        self._launch_response(t, f)
        self._await_takeover = True
        self._state = "await-turnaround"

    # -- the response ------------------------------------------------------
    def _takeover(self, t: float, host_oe: bool) -> None:
        self._await_takeover = False
        if host_oe:
            self._v(t, "no-release",
                    "the probe still drove SWDIO on the turnaround cycle "
                    "after the request's park bit (it must release the line "
                    "while SWCLK is low); the pad model reports the two "
                    "drivers' contention besides")
        self._taken = True
        self.drive = self._resp_bits[0]
        self._resp_index = 1
        self._state = "response"

    def _response_rise(self) -> None:
        if self._resp_index < len(self._resp_bits):
            self.drive = self._resp_bits[self._resp_index]
            self._resp_index += 1
            return
        # The probe samples the final bit (read parity or the last error ACK
        # bit) before this rise. Release SWDIO for the return turnaround.
        self.drive = None
        self._taken = False
        self._state = "post-response"
        self._return_turnaround = True

    # -- between transactions ---------------------------------------------
    def _between_rise(self, t: float, swdio: int, host_oe: bool) -> None:
        if self._return_turnaround:
            # the cycle after the last response bit is the target-to-host
            # turnaround (IHI 0031 B4.1.3): the probe must still have SWDIO
            # released, and takes the line only after it
            self._return_turnaround = False
            if host_oe:
                self._v(t, "return-turnaround-driven",
                        "the probe drove SWDIO on the turnaround cycle after "
                        "the last response bit (it must leave the line "
                        "released for that cycle and re-drive after it)")
            if self._protocol_error:
                self._state = "ack-backoff"
                self._backoff = WRITE_BITS
            elif self._wreq is not None:
                self._state = "write-data"
            return
        if self._state == "post-response" and not host_oe:
            if self._protocol_error:
                return  # a longer release after a bad ACK is allowed
            if not self._flagged_released:
                self._flagged_released = True
                self._v(t, "line-released-after-transfer",
                        "SWDIO was released (pulled high) after the "
                        "transfer ended; the probe must drive it low for "
                        "the idle cycles that follow")
            return
        if host_oe and swdio == 1:
            # the next request's start bit
            self._start_frame(t)
        elif host_oe and swdio == 0:
            self._tail_lows += 1

    def _backoff_rise(self, t: float, host_oe: bool) -> None:
        """The 33 cycles after a bad ACK's turnaround, where a data phase could
        be: the probe must leave SWDIO released."""
        if host_oe and not self._flagged_backoff:
            self._flagged_backoff = True
            self._v(t, "driven-after-bad-ack",
                    "the probe drove SWDIO in the possible data phase after an "
                    "ACK that was not 1,0,0 (it must back off, released)")
        self._backoff -= 1
        if self._backoff <= 0:
            self._state = "post-response"

    def _wdata_rise(self, t: float, swdio: int, host_oe: bool) -> None:
        """One write-data bit: 32 data bits LSB first, then even parity, all
        driven by the probe."""
        if not host_oe:
            self._v(t, "write-data-not-driven",
                    "a write-data bit rose while the probe was not driving SWDIO")
        self._wbits.append(swdio)
        if len(self._wbits) < WRITE_BITS:
            return
        f, bits = self._wreq, self._wbits
        self._wreq, self._wbits = None, []
        value = sum(b << i for i, b in enumerate(bits[:32]))
        self._state = "post-response"
        if bits[32] != read_value_parity(value):
            self._v(t, "write-parity",
                    f"write data {value:#010x} carried parity {bits[32]}, "
                    f"expected {read_value_parity(value)}; the write is discarded")
            return
        self._ap_write(t, f, value)

    def finish(self, t_end: float) -> None:
        """Grade what only the end of a run shows: the trailing idle."""
        if not self.connected:
            return
        if self._tail_lows < TRAILING_IDLE_MIN:
            self._v(t_end, "trailing-idle-short",
                    f"only {self._tail_lows} SWCLK cycle(s) with SWDIO low "
                    f"(probe driving) after the last transfer before SWCLK "
                    f"stopped; ADIv5 requires at least {TRAILING_IDLE_MIN}")

    # ---------------------------------------------------------- reporting
    @property
    def acks(self) -> List[str]:
        """The ACK name the model answered each well-formed request with."""
        if self.ap is not None:
            return list(self.ack_log)
        names = []
        for i, f in enumerate(f for f in self.requests if f.ok):
            ack = (self.reads[i] if i < len(self.reads) else (ACK_OK, 0))[0]
            names.append(ack)
        return names

    def report(self) -> dict:
        def cyc(table):
            return {k: (round(lo / NS_PER_CYCLE, 1), round(hi / NS_PER_CYCLE, 1))
                    for k, (lo, hi) in sorted(table.items())}
        hi_ns = {k: (round(lo, 1), round(hi, 1)) for k, (lo, hi) in sorted(self.widths.items())}
        lo_ns = {k: (round(lo, 1), round(hi, 1)) for k, (lo, hi) in sorted(self.low_widths.items())}
        return {
            "connected": self.connected,
            "rises": self.rise_count,
            "requests": [(f.ok, f.byte, f.field_decode()) for f in self.requests],
            "acks": self.acks,
            "swclk_high_ns": hi_ns,
            "swclk_low_ns": lo_ns,
            "swclk_high_cycles": cyc(self.widths),
            "swclk_low_cycles": cyc(self.low_widths),
            "trailing_idle_low": self._tail_lows,
            "ap_log": list(self.ap.log) if self.ap is not None else None,
            "violations": [str(v) for v in self.violations],
        }
