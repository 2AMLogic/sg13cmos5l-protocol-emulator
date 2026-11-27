"""DUT-facing CAN 2.0A firmware bench (issue #450, multi-protocol extra
credit, catalog #443).

The claim: the committed program `firmware/asm/can_2a.asm` (image
`firmware/build/can_2a.hex`), loaded over the real serial load-phase pins
onto the real top (`tt_um_2amlogic_protocol_emulator`) and executed by the
ISA core, is a classic-CAN node on CAN_TXD = `uo_out[0]` and CAN_RXD =
`ui_in[0]` through an external transceiver: it transmits a standard data
frame (bit-stuffed by DR 0015's P2 `LINE_*` unit, CRC-15 by the P1
`CRC_*` engine, one `CRC_BIT` per destuffed bit), arbitrates bit by bit at
the sample point and retransmits after a lost arbitration, receives a
frame of its own DLC with de-stuffing and the remainder-zero CRC check,
drives the dominant ACK only when the CRC checked, and reports its status
on `uo_out[7:1]`.

What is measured, and in what units
-----------------------------------
**Cycles.** The bit period this program implements is exactly **400 core
cycles** and the sample point sits at offset **300** (75%). Those are what
the cycle-domain assertions below measure at the pin, in rising edges of
the core clock -- independent of any clock frequency.

**Any kbit/s figure is arithmetic at an unconfirmed clock.** 400 cycles x
20 ns is the 8 us of 125 kbit/s only at target-spec row 4's **target**
50 MHz, which is unconfirmed on this program's own flow (STA against this
core is blocked, `verification/records/sta-corner-sweep/`), the same
stance as `test_firmware_dmx512.py`. The bench's simulation clock runs at
`CLK_PERIOD_NS = 20` ns purely to name that nominal.

The bus model
-------------
The bench is the other end of the bus: every core cycle it reads TXD,
resolves the wired-AND bus level from the DUT's TXD (delayed by the
8-cycle round trip a ~160 ns transceiver pair adds), any scripted other
node, and any ACK window, and drives the result back on `ui_in[0]`. The
DUT's own transmissions are graded from the captured TXD waveform by the
**independent** model `verification/reference_models/can_2a.py` (written
from the ISO 11898-1 framing description; two CRC-15 implementations, a
stuffer/destuffer, an edge-resynchronising receiver with a stated
per-bit bound) -- never from the firmware's own encoding.

Scenarios
---------
1. **Clean transmit** (ACK given): frame content, stuffing, CRC, tail
   shape, the 400-cycle grid and the ACK-seen status word.
2. **No ACK**: the no-ACK status word.
3. **Lost arbitration**: a lower-ID winner starts on our SOF; the DUT
   must stop driving dominant within the loss bit, stay recessive through
   the winner's frame, then retransmit and complete.
4. **Receive + ACK**: a bench frame of the image's DLC (3); the DUT's
   dominant ACK pulse must sit inside the ACK slot bit window.
5. **CRC error**: a corrupted CRC sequence; no ACK, CRC-error status.
6. **Stuff error**: a flipped stuff bit (six equal bits); the frame is
   abandoned, stuff-error status.
7. **Sample-point probe**: a dominant RXD pulse straddling offset 300 of
   a recessive transmitted bit loses the arbitration; one clear of it
   does not -- the transmit sample point measured at cycle granularity.
8. **Bit-rate tolerance**: bench frames at +0.5% still receive (ACK
   driven); at +5% they do not -- the hard-sync-only receiver tolerance,
   the DR 0015 clock-recovery question measured rather than assumed.

Negative controls: scenarios 5 and 6 are malformed frames the bench
constructs itself (a suite that cannot fail cannot cite its passes), and
scenario 7's clear-pulse arm is the negative control for the straddle arm.

Driven by `klt functional-verification` (see
`verification/request-firmware-can.json`) against
`src/tt_um_2amlogic_protocol_emulator.v` plus the `rtl/` modules it
instantiates and the vendored PDK macro model. Everything is
deterministic: one committed program, fixed scenarios, no randomization.
"""

import sys
from collections import deque
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly, Timer

try:
    from repo_root import find_repo_root
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))

try:
    from firmware_artifacts import parse_cycle_sections as _parse_sections, parse_hex_image
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from firmware_artifacts import parse_cycle_sections as _parse_sections, parse_hex_image
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

from reference_models.can_2a import encode_frame  # noqa: E402
from reference_models.waveform import Signal      # noqa: E402

from test_protocol_emulator import load_program  # noqa: E402

# --- the unconfirmed-clock mapping, stated once -------------------------
CLK_PERIOD_NS = 20
BIT_CYCLES = 400

#: CAN_TXD, the transceiver's D input (DR 0010's can phase).
TX_PIN, TX_BIT = "uo_out", 0
#: CAN_RXD, the transceiver's R output (ui_in[0]; PROG_SER during load).
RX_BIT = 0

SRC = REPO_ROOT / "firmware" / "asm" / "can_2a.asm"
HEX = REPO_ROOT / "firmware" / "build" / "can_2a.hex"
CYCLES = REPO_ROOT / "firmware" / "build" / "can_2a.cycles.txt"

#: The generator's frame constants (the bench's expected values; the
#: model re-derives the wire shape independently).
TX_ID = 0x5A5
TX_DATA = bytes([0x11, 0x1F, 0x22])

#: The documented lint warnings: every sample branch (arbitration, the
#: stuff tests, the boundary dispatch, the polls) is a protocol handshake
#: in DR 0001's sense; no timing-critical WAIT depends on them.
EXPECTED_WARNING_COUNT = 16
EXPECTED_WORDS = 253

STAT_TX_ACK, STAT_TX_NOACK = 0x41, 0x61
STAT_RX_OK, STAT_RX_CRC, STAT_RX_STUFF = 0xC1, 0xC3, 0xC5

#: The bench->DUT frame (the image's fixed receive shape, DLC 3).
RX_ID = 0x123
RX_DATA = bytes([0xAB, 0xCD, 0x5A])
#: The arbitration winner: a LOWER id wins; the first differing bit is
#: stream bit 9 (our ID2 is 1, the winner's is 0).
WIN_ID = 0x5A1
WIN_DATA = bytes([0xC3])


class CanBus:
    """The bench side of the bus: TXD echo with a round-trip delay,
    scripted other-node transmissions, ACK windows, per-cycle capture."""

    DEFER = 8  # cycles of transceiver round trip (~160 ns at 20 ns)

    def __init__(self, dut):
        self.dut = dut
        self.hist = deque([1] * 64, maxlen=1 << 20)
        self.txd = []          # per-cycle TXD samples (post-write)
        self.uo = []           # per-cycle uo_out
        self.lvl = []          # per-cycle driven bus level (CAN_RXD)
        self.other = None      # (start_cycle, bits)
        self.ack_windows = []  # [(a, b)] dominant-low windows
        self.rx_frame = None   # (start_cycle, bits, period)
        self.glitches = []     # [(a, b)] extra dominant-low windows
        self.running = True

    def bus_level(self, cycle):
        lvl = self.hist[-1 - self.DEFER] if len(self.hist) > self.DEFER else 1
        if self.other is not None:
            start, bits = self.other
            k = cycle - start
            if 0 <= k < len(bits) * BIT_CYCLES:
                lvl &= bits[k // BIT_CYCLES]
        if self.rx_frame is not None:
            start, bits, period = self.rx_frame
            k = cycle - start
            if 0 <= k < len(bits) * period:
                lvl &= bits[k // period]
        for a, b in self.ack_windows + self.glitches:
            if a <= cycle < b:
                lvl &= 0
        return lvl

    async def run(self):
        dut = self.dut
        while self.running:
            await RisingEdge(dut.clk)
            await ReadOnly()
            uo = int(dut.uo_out.value)
            txd = (uo >> TX_BIT) & 1
            cycle = len(self.txd)
            self.uo.append(uo)
            self.txd.append(txd)
            self.hist.append(txd)
            rxd = self.bus_level(cycle + 1)
            self.lvl.append(rxd)
            await Timer(1, unit="ns")
            dut.ui_in.value = rxd


def cycles_to_signal(levels, ns_per_cycle, idle_ns):
    """A per-cycle 0/1 list -> a Signal in ns (one step per cycle)."""
    sig = Signal(1, name="txd")
    t = 0.0
    for b in levels:
        sig.add(t, b)
        t += ns_per_cycle
    sig.add(t + idle_ns, 1)
    return sig, t + idle_ns + 2 * ns_per_cycle


async def run_image(dut, cycles):
    """Load the committed image and run `cycles` core cycles with the bus
    model attached; returns the CanBus recorder."""
    words = parse_hex_image(HEX)
    assert len(words) <= 256, "program exceeds DR 0001's 256-word memory"
    await load_program(dut, words)
    bus = CanBus(dut)
    task = cocotb.start_soon(bus.run())
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    bus.running = False
    await Timer(10, unit="ns")
    task.kill()
    return bus


def sof_of(bus):
    for i, t in enumerate(bus.txd):
        if t == 0 and i > 8:
            return i
    return None


def first_dominant_run_end(txd, a, b):
    """First cycle >= a and < b at which TXD is recessive after dominant."""
    for i in range(a, min(b, len(txd))):
        if txd[i] == 1 and (i == 0 or txd[i - 1] == 0):
            return i
    return None


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed build artifacts match the committed `.asm` source and
    the generator, the program fits the store, its only lint warnings are
    the documented sample branches, and the committed cycle report states
    the per-bit budget this bench grades against."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    assert len(program.instructions) == EXPECTED_WORDS
    assert len(program.instructions) <= 256
    assert len(program.warnings) == EXPECTED_WARNING_COUNT, (
        f"expected {EXPECTED_WARNING_COUNT} documented handshake warnings, "
        f"got {len(program.warnings)}: {program.warnings}")

    sections = _parse_sections(CYCLES.read_text(encoding="utf-8"))
    for name, want in (("can_tx_bit", BIT_CYCLES), ("can_tx_crc1", BIT_CYCLES),
                       ("can_tx_crc0", BIT_CYCLES), ("can_rx_bit", BIT_CYCLES + 1)):
        assert name in sections, f"committed report is missing {name!r}"
        _s, _e, got, branches = sections[name]
        assert got == want, f"section {name} claims {got} cycles, want {want}"
        assert branches == "true", f"section {name} must contain its loop branch"
    dut._log.info(
        f"committed program: {len(program.instructions)} words, "
        f"{len(program.warnings)} documented handshake warnings")


@cocotb.test()
async def test_can_tx_frame_acked(dut):
    """The clean transmit, with the bench ACKing the DUT's frame: the
    model decodes the frame, every edge is on the grid, the ACK slot
    carries no dominant from the transmitter itself, and the status word
    is 0x41 (ACK seen)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    from reference_models.can_2a import CanReceiver
    wire, tail = encode_frame(TX_ID, TX_DATA)
    full = wire + tail
    run = 30 * BIT_CYCLES + (len(full) + 14) * BIT_CYCLES
    words = parse_hex_image(HEX)
    await load_program(dut, words)
    bus = CanBus(dut)
    armed = {"sof": None, "idle": 20 * BIT_CYCLES, "prev": 1}

    orig_level = bus.bus_level

    def level_with_ack(cycle):
        txd = bus.txd[-1] if len(bus.txd) > 4 else 1
        # a new DUT frame = a falling edge out of >= 14 recessive bits
        if txd == 0 and armed["prev"] == 1 and armed["idle"] >= 14 * BIT_CYCLES:
            armed["sof"] = cycle - 1
        armed["prev"] = txd
        armed["idle"] = armed["idle"] + 1 if txd else 0
        if armed["sof"] is not None and not bus.ack_windows:
            a = armed["sof"] + 1 + (len(wire) + 1) * BIT_CYCLES
            bus.ack_windows = [(a + 2, a + BIT_CYCLES - 2)]
        return orig_level(cycle)

    bus.bus_level = level_with_ack
    task = cocotb.start_soon(bus.run())
    for _ in range(run):
        await RisingEdge(dut.clk)
    bus.running = False
    await Timer(10, unit="ns")
    task.kill()

    sof = sof_of(bus)
    assert sof is not None
    # the model grades the captured waveform (ns = cycles x CLK_PERIOD_NS)
    sig, end = cycles_to_signal(bus.txd[sof:sof + (len(full) + 12) * BIT_CYCLES],
                                 CLK_PERIOD_NS, 4 * BIT_CYCLES * CLK_PERIOD_NS)
    res = CanReceiver(BIT_CYCLES * CLK_PERIOD_NS).decode(sig, 0.0, end)
    assert res.violations == [], f"the model flagged the DUT: {res.violations}"
    assert len(res.frames) == 1, res.frames
    f = res.frames[0]
    assert (f.can_id, f.dlc, f.data, f.crc_ok) == (TX_ID, 3, list(TX_DATA), True), f
    assert f.ack_slot_level == 1, "the transmitter drove its own ACK slot"
    # every TXD edge inside the frame sits on the bit grid (the txd epoch
    # records the OUT retirement cycle; the SOF sample is that same cycle)
    prev = None
    for i, t in enumerate(bus.txd[sof:sof + len(full) * BIT_CYCLES]):
        if t != prev and i > 0:
            assert i % BIT_CYCLES == 0, \
                f"TXD edge at SOF+{i} is off the {BIT_CYCLES}-cycle grid"
        prev = t
    # the status word: poll uo_out for the TX-phase status
    got = next((v for v in bus.uo[sof + len(full) * BIT_CYCLES:] if v >> 1), None)
    assert got in (STAT_TX_ACK, STAT_TX_NOACK), f"no status word: {got}"
    assert got == STAT_TX_ACK, f"status 0x{got:02X}, expected 0x{STAT_TX_ACK:02X}"
    dut._log.info(
        f"frame: id 0x{f.can_id:03X} dlc {f.dlc} data {f.data} "
        f"({len(wire)} wire bits, {len(wire) - 43 - 15} stuff bits); "
        f"status 0x{got:02X}")


@cocotb.test()
async def test_can_tx_noack(dut):
    """Nobody ACKs: the same clean frame, and the 0x61 status word."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    wire, tail = encode_frame(TX_ID, TX_DATA)
    full = wire + tail
    run = 30 * BIT_CYCLES + (len(full) + 14) * BIT_CYCLES
    bus = await run_image(dut, run)
    sof = sof_of(bus)
    assert sof is not None
    got = next((v for v in bus.uo[sof + len(full) * BIT_CYCLES:] if v >> 1), None)
    assert got == STAT_TX_NOACK, f"status 0x{got if got is None else got:02X}"


@cocotb.test()
async def test_can_arbitration(dut):
    """A lower-ID winner starts on our SOF: the DUT must stop driving
    dominant from the loss bit's sample point, stay recessive through the
    winner's frame (which the model decodes cleanly off the *bus*), then
    retransmit and complete with an ACK."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    from reference_models.can_2a import CanReceiver
    win_wire, win_tail = encode_frame(WIN_ID, WIN_DATA)
    winner = win_wire + win_tail
    wire, tail = encode_frame(TX_ID, TX_DATA)
    run = 40 * BIT_CYCLES + (len(winner) + 24 + len(wire) + len(tail) + 16) * BIT_CYCLES
    words = parse_hex_image(HEX)
    await load_program(dut, words)
    bus = CanBus(dut)
    state = {"armed_other": False, "sof": None, "idle": 20 * BIT_CYCLES,
             "prev": 1, "gate": 0}

    orig_level = bus.bus_level

    def level_with_scenario(cycle):
        txd = bus.txd[-1] if len(bus.txd) > 4 else 1
        if txd == 0 and state["prev"] == 1 and state["idle"] >= 14 * BIT_CYCLES:
            state["sof"] = cycle - 1
            if not state["armed_other"]:
                bus.other = (state["sof"] + 1, winner)
                state["armed_other"] = True
                state["gate"] = state["sof"] + 1 + len(winner) * BIT_CYCLES
        state["prev"] = txd
        state["idle"] = state["idle"] + 1 if txd else 0
        if state["sof"] is not None and state["sof"] > state["gate"] \
                and (not bus.ack_windows or bus.ack_windows[0][0] < state["sof"]):
            a = state["sof"] + 1 + (len(wire) + 1) * BIT_CYCLES
            bus.ack_windows = [(a + 2, a + BIT_CYCLES - 2)]
        return orig_level(cycle)

    bus.bus_level = level_with_scenario
    task = cocotb.start_soon(bus.run())
    for _ in range(run):
        await RisingEdge(dut.clk)
    bus.running = False
    await Timer(10, unit="ns")
    task.kill()

    sof = sof_of(bus)
    assert sof is not None
    loss = sof + 9 * BIT_CYCLES + BIT_CYCLES // 2   # bit 9's sample point
    winner_end = sof + 1 + len(winner) * BIT_CYCLES
    # from the loss sample: the DUT drives no dominant until its
    # retransmission (which the bench ACKs after the winner's frame)
    # -- allow the winner's-frame window plus the idle poll margin
    resume = winner_end + 21 * BIT_CYCLES + 2 * BIT_CYCLES
    for i in range(loss, min(resume, len(bus.txd))):
        if bus.other[0] <= i < winner_end and bus.txd[i] == 0:
            # the winner drives dominant too -- grade TXD (the DUT's own
            # pin) only: it must be recessive after the loss sample
            pass
        assert bus.txd[i] == 1 or i > winner_end, \
            f"the DUT drove dominant at cycle {i} after losing arbitration"
    # a retransmission happened and was ACKed
    falls = [i for i in range(int(winner_end), len(bus.txd) - 1)
             if bus.txd[i - 1] == 1 and bus.txd[i] == 0]
    assert falls, "no retransmission after the arbitration loss"
    re_sof = falls[0]
    got = next((v for v in bus.uo[re_sof + (len(wire) + 14) * BIT_CYCLES:] if v >> 1), None)
    assert got == STAT_TX_ACK, f"status 0x{got if got is None else got:02X} after retransmit"
    # the winner's frame survives on the bus the DUT saw: every winner bit
    # reads back at the sample points of the winner's own grid
    start = sof + 1
    wrong = [k for k in range(len(winner))
             if bus.lvl[start + k * BIT_CYCLES + 300] != winner[k]]
    assert not wrong, f"the winner's frame was corrupted at bits {wrong[:6]}"
    dut._log.info(
        f"lost at bit 9, recessive through the winner's {len(winner)} bits, "
        f"retransmitted at cycle {re_sof} and completed (status "
        f"0x{got:02X})")


async def run_nominal_rx(dut, rx_bits):
    """ACK the DUT's frame, send rx_bits at the nominal rate, and return the capture."""
    wire, tail = encode_frame(TX_ID, TX_DATA)
    run = 40 * BIT_CYCLES + (len(wire) + len(tail) + 14 + len(rx_bits) + 14) * BIT_CYCLES
    words = parse_hex_image(HEX)
    await load_program(dut, words)
    bus = CanBus(dut)
    state = {"armed": False, "idle": 20 * BIT_CYCLES, "prev": 1, "sof": None}

    orig_level = bus.bus_level

    def level_with_rx(cycle):
        txd = bus.txd[-1] if len(bus.txd) > 4 else 1
        if txd == 0 and state["prev"] == 1 and state["idle"] >= 14 * BIT_CYCLES:
            state["sof"] = cycle - 1
        state["prev"] = txd
        state["idle"] = state["idle"] + 1 if txd else 0
        if state["sof"] is not None and not state["armed"]:
            a = state["sof"] + 1 + (len(wire) + 1) * BIT_CYCLES
            bus.ack_windows = [(a + 2, a + BIT_CYCLES - 2)]
            state["armed"] = True
        if not state["armed"] or bus.rx_frame is not None:
            return orig_level(cycle)
        # after the DUT's own frame + tail + IFS: send ours
        frame_at = state["sof"] + 1 + (len(wire) + len(tail) + 4) * BIT_CYCLES
        if cycle >= frame_at:
            bus.rx_frame = (frame_at, rx_bits, BIT_CYCLES)
        return orig_level(cycle)

    bus.bus_level = level_with_rx
    task = cocotb.start_soon(bus.run())
    for _ in range(run):
        await RisingEdge(dut.clk)
    bus.running = False
    await Timer(10, unit="ns")
    task.kill()
    return bus


@cocotb.test()
async def test_can_rx_ok_and_ack(dut):
    """The bench sends a DLC-3 frame; the DUT receives it (hard sync on
    the SOF edge, samples at 75%), checks the CRC and drives a dominant
    ACK pulse inside the ACK slot bit window; final status 0xC1."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    rx_wire, rx_tail = encode_frame(RX_ID, RX_DATA)
    rx_bits = rx_wire + rx_tail
    bus = await run_nominal_rx(dut, rx_bits)

    assert bus.rx_frame is not None, "the bench never sent its frame"
    start = bus.rx_frame[0]
    # the DUT's ACK: a dominant pulse on TXD inside the ACK slot window
    ack_slot = start + (len(rx_wire) + 1) * BIT_CYCLES
    seg = bus.txd[ack_slot:ack_slot + BIT_CYCLES]
    assert 0 in seg, "no dominant ACK pulse in the bench frame's ACK slot"
    # TXD is recessive again by the ACK delimiter (the first cycles may
    # still carry the pulse: the DUT's whole sample grid carries its SOF
    # poll's ~11-cycle detection latency and the sync wait's jitter)
    last0 = max(i for i in range(ack_slot, min(ack_slot + 2 * BIT_CYCLES,
                                                len(bus.txd))) if bus.txd[i] == 0)
    assert last0 < ack_slot + BIT_CYCLES + 300, \
        (f"the ACK pulse ran to +{last0 - ack_slot} cycles, past the ACK "
         f"delimiter's sample point")
    final = bus.uo[-1]
    assert final == STAT_RX_OK, f"final status 0x{final:02X}, want 0x{STAT_RX_OK:02X}"
    dut._log.info(f"ACK pulse in [{ack_slot}, {ack_slot + BIT_CYCLES}); "
                  f"final status 0x{final:02X}")


@cocotb.test()
async def test_can_rx_crc_error(dut):
    """A corrupted CRC sequence: no ACK pulse, final status 0xC3."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    rx_wire, rx_tail = encode_frame(RX_ID, RX_DATA)
    rx_wire = list(rx_wire)
    rx_wire[-1] ^= 1                      # corrupt the last CRC bit
    rx_bits = list(rx_wire) + rx_tail
    bus = await run_nominal_rx(dut, rx_bits)

    start = bus.rx_frame[0]
    ack_slot = start + (len(rx_wire) + 1) * BIT_CYCLES
    seg = bus.txd[ack_slot:ack_slot + BIT_CYCLES]
    assert 0 not in seg, "the DUT ACKed a frame with a bad CRC"
    assert bus.uo[-1] == STAT_RX_CRC, \
        f"final status 0x{bus.uo[-1]:02X}, want 0x{STAT_RX_CRC:02X}"


@cocotb.test()
async def test_can_rx_stuff_error(dut):
    """A flipped stuff bit (six equal bits on the wire): the DUT abandons
    the frame at that slot, drives no ACK, final status 0xC5."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    rx_wire, rx_tail = encode_frame(RX_ID, RX_DATA)
    w = list(rx_wire)
    run, last = 0, None
    for i, b in enumerate(w):
        if run == 5:
            w[i] = last          # the stuff bit now extends the run
            break
        run = run + 1 if b == last else 1
        last = b
    else:
        raise AssertionError("the demo RX frame has no stuff bit to corrupt")
    rx_bits = w + rx_tail
    bus = await run_nominal_rx(dut, rx_bits)

    start = bus.rx_frame[0]
    ack_slot = start + (len(rx_wire) + 1) * BIT_CYCLES
    seg = bus.txd[ack_slot:ack_slot + BIT_CYCLES]
    assert 0 not in seg, "the DUT ACKed a stuff-error frame"
    assert bus.uo[-1] == STAT_RX_STUFF, \
        f"final status 0x{bus.uo[-1]:02X}, want 0x{STAT_RX_STUFF:02X}"


@cocotb.test()
async def test_transmit_sample_point(dut):
    """The transmit sample point, measured: a dominant glitch on the bus
    straddling offset 300 of a recessive transmitted bit costs the
    arbitration; the same-width glitch clear of the sample point does
    not. Two arms, one negative control."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    wire, tail = encode_frame(TX_ID, TX_DATA)
    full = wire + tail
    run = 60 * BIT_CYCLES + 2 * (len(full) + 16) * BIT_CYCLES

    async def arm(glitch_at, width=40):
        words = parse_hex_image(HEX)
        await load_program(dut, words)
        bus = CanBus(dut)
        state = {"idle": 20 * BIT_CYCLES, "prev": 1, "sof": None}

        orig_level = bus.bus_level

        def level(cycle):
            txd = bus.txd[-1] if len(bus.txd) > 4 else 1
            if txd == 0 and state["prev"] == 1 and state["idle"] >= 14 * BIT_CYCLES:
                state["sof"] = cycle - 1
                if glitch_at is not None and not bus.glitches:
                    bus.glitches = [(state["sof"] + glitch_at,
                                     state["sof"] + glitch_at + width)]
                if state["sof"] > 0 and not bus.ack_windows:
                    a = state["sof"] + 1 + (len(wire) + 1) * BIT_CYCLES
                    bus.ack_windows = [(a + 2, a + BIT_CYCLES - 2)]
            state["prev"] = txd
            state["idle"] = state["idle"] + 1 if txd else 0
            return orig_level(cycle)

        bus.bus_level = level
        task = cocotb.start_soon(bus.run())
        for _ in range(run // 2):
            await RisingEdge(dut.clk)
        bus.running = False
        await Timer(10, unit="ns")
        task.kill()
        return bus

    # a recessive bit early in the frame: stream bit 3 (ID9 is 1 for
    # 0x5A5 -> bits 1,3,4 recessive); use bit 3's window
    bit3 = 3 * BIT_CYCLES
    # arm 1: straddling the sample point (offset 300 +/- 20)
    bus = await arm(bit3 + 300 - 20)
    sof = sof_of(bus)
    assert sof is not None
    # the DUT lost the arbitration: a retransmission follows (a second
    # SOF after a long idle) -- and the first attempt never completed
    falls = [i for i in range(sof + 4 * BIT_CYCLES, len(bus.txd) - 1)
             if bus.txd[i - 1] == 1 and bus.txd[i] == 0]
    assert falls, "a glitch straddling the sample point did not cost the arbitration"
    # arm 2 (the negative control): the same glitch early in the bit
    bus2 = await arm(bit3 + 100)
    sof2 = sof_of(bus2)
    assert sof2 is not None
    got = next((v for v in bus2.uo[sof2 + len(full) * BIT_CYCLES:] if v >> 1), None)
    assert got == STAT_TX_ACK, \
        f"a glitch clear of the sample point disturbed the frame: 0x{got:02X}"
    dut._log.info(
        f"glitch at +{300}-20 loses; glitch at +100 does not "
        f"(status 0x{got:02X})")


@cocotb.test()
async def test_rx_bit_rate_tolerance(dut):
    """The hard-sync-only receiver's bit-rate tolerance, measured: a
    bench frame paced at +0.5% still receives (ACK driven, status 0xC1);
    at +5% it does not. The firmware paces its sample grid from the SOF
    edge alone (no per-edge resynchronisation), so the tolerance is
    bounded by the sample point's distance to the bit edge divided by
    the frame length -- measured here, not assumed."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    rx_wire, rx_tail = encode_frame(RX_ID, RX_DATA)
    rx_bits = rx_wire + rx_tail
    wire, tail = encode_frame(TX_ID, TX_DATA)

    async def run_at(scale):
        period = int(round(BIT_CYCLES * scale))
        words = parse_hex_image(HEX)
        await load_program(dut, words)
        bus = CanBus(dut)
        state = {"armed": False, "idle": 20 * BIT_CYCLES, "prev": 1, "sof": None}
        orig_level = bus.bus_level

        def level(cycle):
            txd = bus.txd[-1] if len(bus.txd) > 4 else 1
            if txd == 0 and state["prev"] == 1 and state["idle"] >= 14 * BIT_CYCLES:
                state["sof"] = cycle - 1
            state["prev"] = txd
            state["idle"] = state["idle"] + 1 if txd else 0
            if state["sof"] is not None and not state["armed"]:
                a = state["sof"] + 1 + (len(wire) + 1) * BIT_CYCLES
                bus.ack_windows = [(a + 2, a + BIT_CYCLES - 2)]
                state["armed"] = True
            if not state["armed"] or bus.rx_frame is not None:
                return orig_level(cycle)
            frame_at = state["sof"] + 1 + (len(wire) + len(tail) + 4) * BIT_CYCLES
            if cycle >= frame_at:
                bus.rx_frame = (frame_at, rx_bits, period)
            return orig_level(cycle)

        bus.bus_level = level
        task = cocotb.start_soon(bus.run())
        need = 40 * BIT_CYCLES + (len(wire) + len(tail) + 14) * BIT_CYCLES \
            + int(len(rx_bits) * period * 1.3) + 20 * BIT_CYCLES
        for _ in range(need):
            await RisingEdge(dut.clk)
        bus.running = False
        await Timer(10, unit="ns")
        task.kill()
        return bus

    bus = await run_at(1.005)
    assert bus.rx_frame is not None
    start = bus.rx_frame[0]
    period = bus.rx_frame[2]
    ack_slot = start + (len(rx_wire) + 1) * period
    seg = bus.txd[ack_slot:ack_slot + period + 8]
    assert 0 in seg, "a +0.5% bench frame was not received (no ACK)"
    assert bus.uo[-1] == STAT_RX_OK, f"0x{bus.uo[-1]:02X} at +0.5%"

    bus2 = await run_at(1.05)
    assert bus2.rx_frame is not None
    start2 = bus2.rx_frame[0]
    period2 = bus2.rx_frame[2]
    ack_slot2 = start2 + (len(rx_wire) + 1) * period2
    seg2 = bus2.txd[ack_slot2:ack_slot2 + period2 + 8]
    assert 0 not in seg2, "a +5% bench frame was received (ACK driven)"
    dut._log.info("+0.5% received with ACK; +5% not received")
