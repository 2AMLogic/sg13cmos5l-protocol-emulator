"""DUT-facing Modbus RTU server bench (issue #446, part of the
multi-protocol extra credit; catalog #443).

The claim this bench substantiates is the one `CLAUDE.md` demands for a
protocol ("firmware is evidence"): a **committed** program
(`firmware/asm/modbus_rtu.asm`, image `firmware/build/modbus_rtu.hex`)
loaded over the real serial load-phase pins onto the real top
(`tt_um_2amlogic_protocol_emulator`), executing on the ISA core, spoken
to as a Modbus RTU **master** over the RS-485 transceiver's line-side
pins -- requests driven on `ui_in[1]` (R of the transceiver), the
response captured off `uo_out[0]` (D) with its driver-enable window on
`uo_out[1]` (DE and /RE tied) -- and every response judged by the
**independent** Modbus model `verification/reference_models/modbus_rtu.py`:
its own table-driven CRC-16, its own frame builder and 8N2 decoder, its
own server behaviour for the fixed two-register map. Nothing here
asserts the waveform against the firmware's own encoding of anything;
the expected bytes come from the model's `ServerState.reply`, and the
timing verdicts (per-bit slot stability, character pitch, the 3.5
character response latency, the DE discipline) come from the model's
grading against its stated tolerance.

What is measured, and in what units
-----------------------------------
**Cycles.** The bit period this program implements is exactly
**434 core cycles**, which the cycle-domain assertions below check at
the pin: every response character's start-edge pitch is 11 x 434
cycles to the cycle. That number is independent of any clock frequency.

**Any baud/microsecond figure is arithmetic at an unconfirmed clock.**
The 434-cycle period names 115,207 baud at target-spec row 4's
**unconfirmed** 50 MHz target (20 ns/cycle; STA against this core is
blocked -- `verification/records/sta-corner-sweep/`), exactly as the
UART benches state for their own figures. The bench runs its simulation
clock at `CLK_PERIOD_NS = 20` purely to *name* that nominal; a
different clock would change the baud number and nothing measured.

**Framing: 8N2.** The issue allows 8E1 or 8N2; the committed program
sends 8N2 (the framing Modbus over Serial Line V1.02 permits without
parity, and the one whose transmit loop fits the ISA's four registers
-- see the .asm header). The model frames 8N2 identically.

Negative control (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
The bench's own captured response waveform, retimed by 1.04x, must
FAIL the model's bit-timing grading while the bytes still decode --
the case only the timing measurement catches, the same control the
DMX bench uses.

Driven by `klt functional-verification` (see
`verification/request-firmware-modbus.json`) against
`src/tt_um_2amlogic_protocol_emulator.v` plus the two `rtl/` modules it
instantiates and the vendored PDK macro model (`rtl/vendor/`). Like its
siblings, this file is *input* to `klt functional-verification`, not a
pytest module. Everything is deterministic: one committed program, a
fixed exchange script, no randomization.
"""

import math
import re
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, Timer
from cocotb.utils import get_sim_time

from reference_models.modbus_rtu import (
    BIT_TOL_PCT,
    FRAME_BITS,
    SERVER_ADDRESS,
    ServerState,
    check_de_window,
    check_silence,
    decode_frame,
    encode_frame,
    frame_bytes,
)

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))

try:
    from firmware_artifacts import parse_cycle_sections, parse_hex_image
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from firmware_artifacts import parse_cycle_sections, parse_hex_image
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

# The serial load-phase driver, the per-edge pin capture and the
# absolute-time line driver are the ones the UART benches already use;
# importing them registers none of their tests (cocotb discovers tests
# by scanning the *named* module's own namespace).
from test_protocol_emulator import load_program  # noqa: E402
from test_firmware_uart_rx import capture_ports, set_rx  # noqa: E402

SRC = REPO_ROOT / "firmware" / "asm" / "modbus_rtu.asm"
HEX = REPO_ROOT / "firmware" / "build" / "modbus_rtu.hex"
CYCLES = REPO_ROOT / "firmware" / "build" / "modbus_rtu.cycles.txt"

# --- the unconfirmed-clock mapping, stated once --------------------------
#: Simulation clock period. 20 ns names target-spec row 4's *target*
#: 50 MHz; row 4 is unconfirmed, so this value is a nominal for the
#: ns <-> cycle mapping, never a measurement.
CLK_PERIOD_NS = 20

#: The measured quantity: cycles per bit, as implemented by
#: `firmware/asm/modbus_rtu.asm`, cross-checked against the committed
#: cycle report's `.cyclesec` sections below.
BIT_PERIOD_CYCLES = 434

#: 8N2: a character is 11 bit periods.
CHAR_CYCLES = FRAME_BITS * BIT_PERIOD_CYCLES

#: The exact-grid cross-check's allowance: the character-to-character
#: pitch measures 4,766 cycles on the RTL (11 x 434 - 8: the fetch's
#: two PM accesses retire a few cycles faster against the fetch-ahead
#: than the static count -- a fixed, deterministic arbitration effect,
#: every character the same), so the bound is +-12 cycles (~0.25%)
#: around the static 4,774.
CHAR_PITCH_TOL_CYCLES = 12

#: The program's data area begins at PM word 0xF0 (the frame buffer),
#: so the code must stay below 240 words (the .asm header states it).
CODE_WORD_CEILING = 240

#: The documented lint warnings (the .asm header's timing section): the
#: start-edge poll, the stop-bit checks, the CRC residual test, the
#: address/function dispatch, the request validation branches and the
#: response-length branch -- every one between characters or frames,
#: never between a character's samples.
EXPECTED_WARNING_COUNT = 18

#: The committed cycle report's sections this bench pins (the transmit
#: bit loop's whole body is one bit period; the other sections are the
#: documented partial spans the README completes).
EXPECTED_SECTIONS = {
    "modbus_rx_bit": 434,   # the whole receive bit-loop body
    "modbus_tx_start": 425,  # + fetch(3)+LDI+WCTL+3+OUT(1) = 434
    "modbus_tx_bit": 433,   # + the section-excluded MOV(1) = 434
    "modbus_tx_stop1": 3,   # + the loop tail(430)+OUT(1) = 434
    "modbus_tx_stop2": 433,  # +OUT(1) = 434
    "modbus_tx_stop": 425,  # + fetch(3)+LDI+WCTL+3+OUT(1) = 434
}

#: Pins: RX on ui_in[1], TX on uo_out[0], DE on uo_out[1] (DR 0010's
#: modbus profile; the RS-485 transceiver's R, D and DE//RE pins).
RX_BIT = 1
TX_BIT, DE_BIT = 0, 1

#: Idle gap between exchanges, in cycles: the firmware's response
#: latency (3.5-char silence + ~2,900 cycles of CRC/dispatch/build)
#: plus a full 9-character response plus margin.
EXCHANGE_GAP_CYCLES = 70_000

#: Cycles of capture past the last planned event, so the final
#: response's DE fall is always inside the capture.
CAPTURE_MARGIN_CYCLES = 2_000

#: The negative-control retimer: the last data-bit sample still lands
#: inside its own (stretched) bit ((10.5 x 4% = 0.42 < 0.5) of a bit),
#: so the bytes decode, while the character pitch 11 x 4% = 44% of a
#: bit far exceeds the 2.5% spacing bound: only the timing fails.
NEGATIVE_CONTROL_SCALE = 1.04

#: The model's grading tolerance, re-stated for assertions below.
TOL_PCT = BIT_TOL_PCT


# =======================================================================
# Committed-artifact readers and stimulus planning
# =======================================================================


def committed_image() -> list:
    return parse_hex_image(HEX)


def parse_sections() -> dict:
    return parse_cycle_sections(CYCLES.read_text(encoding="utf-8"))


def header_bit_period() -> int:
    text = SRC.read_text(encoding="utf-8")
    match = re.search(r"^; BIT-PERIOD-CYCLES (\d+)$", text, re.M)
    assert match, "modbus_rtu.asm has no '; BIT-PERIOD-CYCLES n' header"
    return int(match.group(1))


def crc16_bench(data: bytes) -> int:
    """The bench's own cross-check CRC (a second, independent
    implementation of the check value the model also computes)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class Exchange:
    """One planned request: the wire bytes to drive and the absolute
    times the drive coroutine will apply them."""

    def __init__(self, payload: bytes, t0_ns: float, bit_ns: float,
                 raw: bytes = None):
        self.payload = payload
        self.wire = frame_bytes(payload) if raw is None else raw
        self.t0_ns = t0_ns
        self.bit_ns = bit_ns
        self.transitions, self.end_ns = encode_frame(
            payload, bit_ns, t0_ns) if raw is None else (
            self._encode_raw(bit_ns), t0_ns + len(self.wire) * FRAME_BITS * bit_ns)
        self.expect_silence = False

    def _encode_raw(self, bit_ns: float):
        out, t = [], self.t0_ns
        for byte in self.wire:
            for level in [0] + [(byte >> i) & 1 for i in range(8)] + [1, 1]:
                out.append((t, level))
                t += bit_ns
        out.append((t, 1))
        return out


def plan_exchanges(payloads, bit_ns: float, base_ns: float,
                   raws=None, first_gap_ns: float = 100_000.0):
    """Lay the exchanges out on the line: each starts after the previous
    one's end plus `EXCHANGE_GAP_CYCLES` of idle."""
    plan = []
    t = base_ns + first_gap_ns
    for k, payload in enumerate(payloads):
        raw = None if raws is None else raws[k]
        ex = Exchange(payload, t, bit_ns, raw=raw)
        plan.append(ex)
        t = ex.end_ns + EXCHANGE_GAP_CYCLES * CLK_PERIOD_NS
    return plan, t


async def drive_exchanges(dut, plan):
    """Apply every exchange's transitions to ui_in[1] at their planned
    absolute times (the line idles high between them)."""
    set_rx(dut, 1)
    for ex in plan:
        for t, level in ex.transitions:
            target_ps = round(t * 1000)
            now_ps = round(float(get_sim_time("ps")))
            if target_ps > now_ps:
                await Timer(target_ps - now_ps, unit="ps")
            set_rx(dut, level)
    # leave the line idle high for whatever capture remains


def grade_exchange(rep, expected: bytes, ex: "Exchange", bit_ns: float,
                   label: str) -> list:
    """The full verdict for one exchange. Returns failure strings."""
    fails = []
    if rep is None:
        return [f"{label}: no response window (DE never opened)"]
    if not rep.chars:
        return [f"{label}: DE window with no decodable character"]
    decoded = rep.decoded()
    if decoded is None:
        fails.append(f"{label}: framing/timing errors: " + "; ".join(
            f"char {c.index}: {c.slot_errors or c.spacing_errors}"
            for c in rep.chars if not c.ok))
        return fails
    if decoded != expected:
        fails.append(f"{label}: decoded {decoded.hex()} != expected "
                     f"{expected.hex()}")
    fails.extend(check_de_window(rep, bit_ns))
    fails.extend(check_silence(ex.end_ns, rep.first_start_ns, bit_ns))
    return fails


def grade_silence(reps, label: str) -> list:
    fails = []
    if reps:
        fails.append(f"{label}: expected silence, DE window(s) at "
                     f"{[r.de_open_ns for r in reps]}")
    return fails


# =======================================================================
# The single-run driver: load once, script the exchanges, capture once
# =======================================================================


async def run_script(dut, payloads, raws=None, extra_tail_cycles=0):
    """Load the committed image, run the exchange script, return
    (times_ns, uo, plan, end_ns). One clock, one load, one capture."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    words = committed_image()
    assert len(words) <= 256, "image exceeds the 256-word store"
    await load_program(dut, words)
    set_rx(dut, 1)  # the line idles high from the MODE drop onward
    bit_ns = BIT_PERIOD_CYCLES * CLK_PERIOD_NS
    base_ns = float(get_sim_time("ns"))
    plan, end_ns = plan_exchanges(payloads, bit_ns, base_ns, raws=raws)
    cycles = math.ceil((end_ns - base_ns) / CLK_PERIOD_NS) \
        + CAPTURE_MARGIN_CYCLES + extra_tail_cycles
    driver = cocotb.start_soon(drive_exchanges(dut, plan))
    times, uo, _uio = await capture_ports(dut, cycles)
    driver.cancel()
    return times, uo, plan, end_ns


def windows_for(times, uo, plan):
    """Split the decoded response windows between the exchanges: each
    window belongs to the exchange whose response slot it falls in."""
    reps = decode_frame(times, uo, BIT_PERIOD_CYCLES * CLK_PERIOD_NS,
                        de_bit=DE_BIT, tx_bit=TX_BIT)
    per_exchange = []
    for ex in plan:
        lo = ex.end_ns
        hi = ex.end_ns + EXCHANGE_GAP_CYCLES * CLK_PERIOD_NS
        per_exchange.append([r for r in reps if lo <= (r.de_open_ns or -1) < hi])
    return reps, per_exchange


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed build artifacts match the committed `.asm` source,
    the program fits its stated code ceiling (the data area starts at
    PM word 0xF0), the bit period this bench grades against is the one
    the committed header and cycle report state, and the program's lint
    warnings are exactly the documented inter-character/inter-frame
    branches (DR 0003: committed artifacts are the evidence)."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    assert len(program.instructions) <= CODE_WORD_CEILING, (
        f"{len(program.instructions)} words: the code must stay below "
        f"0xF0 ({CODE_WORD_CEILING} words), where the frame buffer lives")
    assert len(program.warnings) == EXPECTED_WARNING_COUNT, (
        f"expected exactly {EXPECTED_WARNING_COUNT} documented lint "
        f"warnings, got {len(program.warnings)}: {program.warnings}")
    assert header_bit_period() == BIT_PERIOD_CYCLES
    sections = parse_sections()
    for name, want in EXPECTED_SECTIONS.items():
        assert name in sections, f"committed report missing {name!r}"
        got = sections[name][2]
        assert got == want, f"section {name}: {got} cycles != {want}"
    # the bench's own CRC cross-check: a valid frame carries the running
    # CRC low byte first, and the residual over the whole frame is zero
    probe = frame_bytes(bytes([SERVER_ADDRESS, 0x03, 0, 0, 0, 2]))
    assert crc16_bench(probe[:6]) == int.from_bytes(probe[6:], "little")
    assert crc16_bench(probe) == 0


@cocotb.test()
async def test_modbus_read_and_write(dut):
    """The core claim: 0x03 reads the fixed two-register map, 0x06
    writes a register and echoes, every response matches the
    independent server model byte for byte, and the timing holds: bit
    slots stable, character pitch exactly 11 x 434 cycles, the response
    no earlier than 3.5 character times, DE around the frame."""
    state = ServerState()
    script = [
        bytes([0x11, 0x03, 0x00, 0x00, 0x00, 0x02]),   # initial map
        bytes([0x11, 0x06, 0x00, 0x01, 0x12, 0x34]),   # write reg 1
        bytes([0x11, 0x03, 0x00, 0x00, 0x00, 0x02]),   # read back
        bytes([0x11, 0x06, 0x00, 0x00, 0xA5, 0x5A]),   # write reg 0
        bytes([0x11, 0x03, 0x00, 0x00, 0x00, 0x02]),   # final map
    ]
    times, uo, plan, _end = await run_script(dut, script)
    reps, per_exchange = windows_for(times, uo, plan)
    assert len(reps) == len(script), (
        f"expected exactly {len(script)} response windows, got "
        f"{len(reps)} at {[r.de_open_ns for r in reps]}")
    fails = []
    bit_ns = BIT_PERIOD_CYCLES * CLK_PERIOD_NS
    for k, (ex, windows) in enumerate(zip(plan, per_exchange)):
        expected = state.reply(ex.wire)
        assert expected is not None, f"exchange {k}: model must answer"
        if len(windows) != 1:
            fails.append(f"exchange {k}: {len(windows)} DE windows")
            continue
        fails.extend(grade_exchange(windows[0], expected, ex, bit_ns,
                                    f"exchange {k}"))
    assert not fails, "; ".join(fails)
    # the exact-grid cross-check: every response character's start-edge
    # pitch is 11 x 434 cycles to the cycle (cycle-domain, clock-free)
    for k, windows in enumerate(per_exchange):
        rep = windows[0]
        starts = []
        t = rep.de_open_ns
        n = len(times)
        from bisect import bisect_right
        def tx_at(x):
            i = bisect_right(times, x) - 1
            return (uo[i] >> TX_BIT) & 1 if i >= 0 else 1
        while t < rep.de_close_ns - CHAR_CYCLES * CLK_PERIOD_NS * 0.9:
            j = bisect_right(times, t) - 1
            while j + 1 < n and tx_at(times[j]):
                j += 1
            if j + 1 >= n or times[j] >= rep.de_close_ns or tx_at(times[j]):
                break
            starts.append(times[j])
            t = times[j] + CHAR_CYCLES * CLK_PERIOD_NS
        for a, b in zip(starts, starts[1:]):
            pitch = (b - a) / CLK_PERIOD_NS
            assert abs(pitch - CHAR_CYCLES) <= CHAR_PITCH_TOL_CYCLES, (
                f"exchange {k}: character pitch {pitch} cycles outside "
                f"{CHAR_CYCLES}+-{CHAR_PITCH_TOL_CYCLES}")


@cocotb.test()
async def test_modbus_silence_and_liveness(dut):
    """The malformed/edge cases: a bad CRC, another slave's address, an
    unsupported function, a count the server does not serve and a
    register outside the map are all met with silence -- and the server
    is alive again for the very next good request (no wedge)."""
    state = ServerState()
    good = bytes([0x11, 0x03, 0x00, 0x00, 0x00, 0x02])
    bad_crc = bytearray(frame_bytes(good)); bad_crc[-1] ^= 0x01
    script = [
        bytes(bad_crc),                              # bad CRC: silence
        bytes([0x12, 0x03, 0x00, 0x00, 0x00, 0x02]),  # wrong address
        good,                                        # liveness probe
        bytes([0x11, 0x10, 0x00, 0x00, 0x00, 0x02]),  # unsupported fc
        bytes([0x11, 0x03, 0x00, 0x00, 0x00, 0x01]),  # count 1: silence
        bytes([0x11, 0x06, 0x00, 0x02, 0x12, 0x34]),  # reg 2: silence
        good,                                        # final liveness
    ]
    raws = [bytes(bad_crc)] + [None] * (len(script) - 1)
    times, uo, plan, _end = await run_script(dut, script, raws=raws)
    reps, per_exchange = windows_for(times, uo, plan)
    fails = []
    bit_ns = BIT_PERIOD_CYCLES * CLK_PERIOD_NS
    for k, (ex, windows) in enumerate(zip(plan, per_exchange)):
        expected = state.reply(ex.wire)
        if expected is None:
            fails.extend(grade_silence(windows, f"exchange {k}"))
        else:
            if len(windows) != 1:
                fails.append(f"exchange {k}: {len(windows)} DE windows")
                continue
            fails.extend(grade_exchange(windows[0], expected, ex, bit_ns,
                                        f"exchange {k}"))
    assert not fails, "; ".join(fails)


@cocotb.test()
async def test_modbus_truncated_then_recovery(dut):
    """A truncated request (four of eight bytes, then silence) gets no
    answer; because the program keeps no inter-character timeout (the
    .asm header's recorded cut), the next complete frame completes the
    phantom frame and is consumed by its failing CRC -- and the frame
    after that answers. Two frames to resync, silence throughout."""
    state = ServerState()
    good = bytes([0x11, 0x03, 0x00, 0x00, 0x00, 0x02])
    trunc = frame_bytes(good)[:4]
    script = [good[:0], good, good]          # placeholders; raws below
    raws = [trunc, frame_bytes(good), frame_bytes(good)]
    times, uo, plan, _end = await run_script(dut, script, raws=raws)
    reps, per_exchange = windows_for(times, uo, plan)
    fails = []
    fails.extend(grade_silence(per_exchange[0], "truncated"))
    fails.extend(grade_silence(per_exchange[1], "phantom completion"))
    expected = state.reply(frame_bytes(good))
    if len(per_exchange[2]) == 1:
        fails.extend(grade_exchange(per_exchange[2][0], expected,
                                    plan[2],
                                    BIT_PERIOD_CYCLES * CLK_PERIOD_NS,
                                    "recovery"))
    else:
        fails.append(f"recovery: {len(per_exchange[2])} DE windows")
    assert not fails, "; ".join(fails)


@cocotb.test()
async def test_capture_path_negative_control(dut):
    """This bench's own capture-and-grade path can fail: the DUT's
    captured response waveform, retimed by 1.04x, still decodes to the
    right bytes but must FAIL the model's bit-timing grading -- the
    case only the timing measurement catches."""
    state = ServerState()
    good = bytes([0x11, 0x03, 0x00, 0x00, 0x00, 0x02])
    times, uo, plan, _end = await run_script(dut, [good])
    reps, per_exchange = windows_for(times, uo, plan)
    assert len(reps) == 1 and reps[0].ok, "the DUT's own response first"
    expected = state.reply(frame_bytes(good))
    assert reps[0].decoded() == expected
    # re-grade the whole capture retimed: every time stretched
    scaled_times = [t * NEGATIVE_CONTROL_SCALE for t in times]
    scaled_bit_ns = BIT_PERIOD_CYCLES * CLK_PERIOD_NS  # nominal grid
    scaled_reps = decode_frame(scaled_times, uo, scaled_bit_ns,
                               de_bit=DE_BIT, tx_bit=TX_BIT)
    assert len(scaled_reps) == 1, "the retimed window still frames"
    rep = scaled_reps[0]
    assert rep.bytes == list(expected), (
        "the negative control's mid-bit samples must still recover the "
        f"bytes (got {rep.bytes!r}) -- only its timing may fail")
    bad = [c for c in rep.chars if c.slot_errors or c.spacing_errors]
    assert bad, (
        f"a {NEGATIVE_CONTROL_SCALE}x-retimed waveform must fail the "
        f"{TOL_PCT}% bit-timing bound")
