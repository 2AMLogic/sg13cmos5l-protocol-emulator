"""Independent Modbus RTU model (issue #446, multi-protocol extra
credit, catalog #443).

Written from the Modbus over Serial Line V1.02 description alone (the
copy `docs/protocols.md` #443 cites for the row): RTU framing over a
UART-style line -- characters of 1 start bit, 8 data bits LSB-first and
2 stop bits (8N2, the framing the spec allows when there is no parity),
frames delimited by a silent interval of at least 3.5 character times,
and a CRC-16 transmitted low byte first: polynomial 0xA001 reflected,
init 0xFFFF, no final XOR. It imports nothing from `rtl/`, `src/`,
`firmware/` or any bench, and knows nothing about this design's ISA,
clock or cycle counts. Its inputs are nanosecond waveforms -- exactly
what the bench can observe on the pins -- and its outputs are the
frames a Modbus master would recover, plus every timing violation it
saw.

What is graded
--------------
**Frame bytes.** A response frame is decoded start-edge by start-edge:
the model samples each bit at the centre of the nominal grid anchored
on the start edge (a receiver's own resynchronisation), reassembles the
byte LSB-first, and requires both stop bits high. The expected response
bytes come from `server_reply`, this model's own server behaviour for
the request -- a fixed two-register map, function 0x03 answered only
for start 0 count 2, function 0x06 echoed -- never from the firmware's
encoding of anything.

**Bit timing, in the units the bench counts.** Each character's eleven
nominal bit slots are graded against the transmitter's stated tolerance
(`BIT_TOL_PCT`): every sampled bit must sit inside its slot, and every
measured start-edge-to-start-edge spacing within a frame must stay
inside the accumulated bound. Modbus over Serial Line publishes no
numeric transmitter tolerance; +-2.5% is this model's stated grading
choice, the classic async-receiver discrimination budget (a receiver
re-anchors every start edge, so per-character drift below half a bit
in ~10 slots is free; 2.5% keeps a 5x margin under that and, as the
bench's retimed negative control shows, a 5% mistiming fails).

**Silence discipline.** A response's first start edge must leave the
pad no earlier than 3.5 character times after the request's last stop
bit (the framing the DUT owes before answering), and the driver-enable
window must open before and close after the frame it drives.
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --- the protocol's numbers ------------------------------------------------

#: The DUT's committed bit period is 434 core cycles; the bench names the
#: unconfirmed 50 MHz row-4 clock to convert. The model itself works in
#: nanoseconds and takes the nominal bit period as a parameter.
BIT_TOL_PCT = 2.5
#: RTU inter-frame silent interval, in character times (11 bits).
SILENCE_CHARS = 3.5
#: Characters are 8N2: start, 8 data LSB-first, two stops.
FRAME_BITS = 11
DATA_BITS = 8
STOP_BITS = 2
#: The server's identity this model grades against (the bench states it
#: as the DUT's committed configuration).
SERVER_ADDRESS = 0x11
#: The fixed map: two 16-bit holding registers, high byte first.
INITIAL_MAP: Tuple[Tuple[int, int], ...] = ((0xDE, 0xAD), (0xBE, 0xEF))

FC_READ_HOLDING = 0x03
FC_WRITE_SINGLE = 0x06


def crc16_modbus(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/MODBUS via the classic 256-entry table (poly 0xA001
    reflected, init 0xFFFF, no final XOR) -- deliberately a different
    computation than any bitwise loop the firmware might use."""
    table = []
    for byte in range(256):
        entry = byte
        for _ in range(8):
            entry = (entry >> 1) ^ 0xA001 if entry & 1 else entry >> 1
        table.append(entry)
    for byte in data:
        crc = (crc >> 8) ^ table[(crc ^ byte) & 0xFF]
    return crc


def frame_bytes(payload: bytes) -> bytes:
    """A request/response wire frame: payload plus its CRC, low first."""
    crc = crc16_modbus(payload)
    return bytes(payload) + bytes((crc & 0xFF, crc >> 8))


def char_value_bits(byte: int) -> List[int]:
    """The eleven line levels of one 8N2 character, LSB first."""
    return [0] + [(byte >> i) & 1 for i in range(DATA_BITS)] + [1, 1]


# --- the server this model grades against ---------------------------------

@dataclass
class ServerState:
    """The bench-side server: the map 0x06 changes and 0x03 returns."""
    map: Dict[int, Tuple[int, int]] = field(default_factory=dict)

    def __post_init__(self):
        if not self.map:
            self.map = dict(enumerate(INITIAL_MAP))

    def reply(self, wire: bytes) -> Optional[bytes]:
        """The response frame for a request wire frame, or None for
        silence (bad CRC, another slave's address, or a request this
        server does not serve)."""
        if len(wire) != 8:
            return None
        if crc16_modbus(wire) != 0:      # residual: valid frame -> 0
            return None
        addr, fc = wire[0], wire[1]
        if addr != SERVER_ADDRESS:
            return None
        if fc == FC_READ_HOLDING:
            if wire[2] | wire[3]:
                return None              # start outside the map
            if (wire[4], wire[5]) != (0, 2):
                return None              # a count this server does not serve
            data = [b for pair in self.map.values() for b in pair]
            return frame_bytes(bytes([addr, fc, 4] + data))
        if fc == FC_WRITE_SINGLE:
            if wire[2] | (wire[3] & 0xFE):
                return None              # register outside 0..1
            self.map[wire[3]] = (wire[4], wire[5])
            return wire                  # the echo
        return None                      # any other function


# --- stimulus ---------------------------------------------------------------

def encode_frame(payload: bytes, bit_ns: float, t0: float,
                 scale: float = 1.0) -> Tuple[List[Tuple[float, int]], float]:
    """One request frame as (time, level) transitions of the RX line,
    idle high, starting at `t0`; returns (transitions, end_time).
    `scale` multiplies every bit period (the negative-control retimer)."""
    transitions: List[Tuple[float, int]] = []
    t = t0
    b = bit_ns * scale
    for byte in frame_bytes(payload):
        for level in char_value_bits(byte):
            transitions.append((t, level))
            t += b
    transitions.append((t, 1))           # the line idles high after the frame
    return transitions, t


def concat(frames: List[List[Tuple[float, int]]]) -> List[Tuple[float, int]]:
    out: List[Tuple[float, int]] = []
    for frame in frames:
        out.extend(frame)
    return out


# --- capture analysis -------------------------------------------------------

@dataclass
class CharReport:
    index: int
    byte: Optional[int] = None
    slot_errors: List[str] = field(default_factory=list)
    spacing_errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.byte is not None and not self.slot_errors and not self.spacing_errors


@dataclass
class FrameReport:
    chars: List[CharReport] = field(default_factory=list)
    bytes: List[int] = field(default_factory=list)
    de_open_ns: Optional[float] = None
    de_close_ns: Optional[float] = None
    first_start_ns: Optional[float] = None

    def decoded(self) -> Optional[bytes]:
        if all(c.ok for c in self.chars) and self.chars:
            return bytes(self.bytes)
        return None

    @property
    def ok(self) -> bool:
        return self.decoded() is not None


class Waveform:
    """A captured (time, value) pin trace with nearest-sample reads."""

    def __init__(self, times: List[float], values: List[int], bit_pin: int):
        self.times = times
        self.values = values
        self.bit_pin = bit_pin

    def at(self, t: float) -> int:
        i = bisect_right(self.times, t) - 1
        return (self.values[i] >> self.bit_pin) & 1 if i >= 0 else 0


def decode_frame(times: List[float], uo: List[int], bit_ns: float,
                 de_bit: int = 1, tx_bit: int = 0) -> List[FrameReport]:
    """Decode every response frame in a capture: the DE (driver-enable)
    windows, and within each the 8N2 characters a Modbus master would
    recover, with per-bit slot and spacing grading against `bit_ns`."""
    de = Waveform(times, uo, de_bit)
    tx = Waveform(times, uo, tx_bit)
    reports: List[FrameReport] = []
    n = len(times)
    i = 1
    while i < n:
        if de.at(times[i]) and not de.at(times[i - 1]):
            # a DE window opens
            rep = FrameReport(de_open_ns=times[i])
            j = i
            while j < n and de.at(times[j]):
                j += 1
            rep.de_close_ns = times[j] if j < n else times[-1]
            # decode characters while TX is inside the window; each
            # hunt for the next start edge begins half a bit before the
            # nominal boundary so a slightly fast transmitter (a fixed
            # arbitration effect of a few cycles) is still caught -- the
            # stop bits idle high, so the early hunt cannot misfire
            t = rep.de_open_ns
            while t < rep.de_close_ns - FRAME_BITS * bit_ns * 0.9:
                # hunt the start edge: the first falling TX edge
                k = bisect_right(times, t) - 1
                while k + 1 < n and tx.at(times[k]) :
                    k += 1
                if k + 1 >= n or times[k] >= rep.de_close_ns:
                    break
                if tx.at(times[k]):   # line idles high to the window's end
                    break
                s0 = times[k]
                if rep.first_start_ns is None:
                    rep.first_start_ns = s0
                char = CharReport(index=len(rep.chars))
                bits: List[int] = []
                for slot in range(FRAME_BITS):
                    centre = s0 + (slot + 0.5) * bit_ns
                    bit = tx.at(centre)
                    bits.append(bit)
                    lo = s0 + slot * bit_ns
                    hi = s0 + (slot + 1) * bit_ns
                    tol = bit_ns * BIT_TOL_PCT / 100.0
                    if bit != tx.at(lo + tol) or bit != tx.at(hi - tol):
                        char.slot_errors.append(
                            f"bit {slot} not stable across its slot")
                if bits[0] != 0:
                    char.slot_errors.append("start bit not low")
                if bits[9] != 1 or bits[10] != 1:
                    char.slot_errors.append("stop bits not both high")
                # the mid-bit samples always reassemble a byte: timing
                # violations are diagnostics, not decode guesses
                char.byte = sum(bits[1 + k] << k for k in range(DATA_BITS))
                rep.bytes.append(char.byte)
                rep.chars.append(char)
                t = s0 + (FRAME_BITS - 0.5) * bit_ns
            reports.append(rep)
            i = j
        else:
            i += 1
    # spacing grading: start-edge pitch within each frame
    for rep in reports:
        starts = []
        t = rep.de_open_ns
        while t < (rep.de_close_ns or t) - FRAME_BITS * bit_ns * 0.9:
            k = bisect_right(times, t) - 1
            while k + 1 < n and tx.at(times[k]):
                k += 1
            if k + 1 >= n or times[k] >= (rep.de_close_ns or times[-1]):
                break
            if tx.at(times[k]):
                break
            starts.append(times[k])
            t = times[k] + (FRAME_BITS - 0.5) * bit_ns
        pitch_nom = FRAME_BITS * bit_ns
        for a, bnd in zip(starts, starts[1:]):
            pitch = bnd - a
            if abs(pitch - pitch_nom) > pitch_nom * BIT_TOL_PCT / 100.0:
                for char in rep.chars:
                    char.spacing_errors.append(
                        f"character pitch {pitch:.1f} ns != nominal "
                        f"{pitch_nom:.1f} ns")
                break
    return reports


def check_de_window(rep: FrameReport, bit_ns: float) -> List[str]:
    """The driver-enable discipline: open before the first start bit,
    close after the last stop bit ends. The floor is a quarter bit on
    each side -- a commodity RS-485 transceiver's enable/disable times
    are tens of nanoseconds, so a quarter of an 8.68-us bit is already
    a generous margin for the line to settle before the frame and for
    the last stop bit to finish after it."""
    errors: List[str] = []
    if rep.first_start_ns is None:
        return ["no start edge inside the DE window"]
    setup = rep.first_start_ns - (rep.de_open_ns or 0.0)
    if setup < 0.25 * bit_ns:
        errors.append(f"DE setup {setup:.1f} ns < a quarter bit")
    last_char_end = rep.first_start_ns + len(rep.chars) * FRAME_BITS * bit_ns
    hold = (rep.de_close_ns or 0.0) - last_char_end
    if hold < 0.25 * bit_ns:
        errors.append(f"DE hold {hold:.1f} ns < a quarter bit after the frame")
    return errors


def check_silence(request_end_ns: float, first_start_ns: float,
                  bit_ns: float) -> List[str]:
    """RTU framing: the response waits out the 3.5-character interval."""
    char_ns = FRAME_BITS * bit_ns
    latency = first_start_ns - request_end_ns
    if latency < SILENCE_CHARS * char_ns:
        return [f"response latency {latency:.1f} ns < 3.5 character times "
                f"({SILENCE_CHARS * char_ns:.1f} ns)"]
    return []
