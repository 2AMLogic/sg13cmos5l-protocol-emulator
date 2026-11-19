"""DUT-facing DMX512 firmware bench (issue #445, multi-protocol extra
credit, catalog #443).

The claim: the committed program `firmware/asm/dmx512_tx.asm` (image
`firmware/build/dmx512_tx.hex`), loaded over the real serial load-phase
pins onto the real top (`tt_um_2amlogic_protocol_emulator`) and executed
by the ISA core, drives an endless stream of DMX512 packets on TX =
`uo_out[0]` -- BREAK, mark-after-break, the 0x00 start code, then 512
channel slots at 250 kbaud 8N2 -- that the **independent** DMX512
receiver model (`verification/reference_models/dmx512.py`, written from
the protocol conventions alone) decodes byte for byte, with every slot's
two stop bits sampled high and every packet boundary intact.

What is measured, and in what units
-----------------------------------
**Cycles.** The bit period this program implements is exactly **200 core
cycles**; the slot pitch is exactly **2,200**, the BREAK exactly
**4,609** and the mark-after-break exactly **605**. Those are what the
cycle-domain assertions below measure at the pin as spacing between
consecutive TX edges, in rising edges of the core clock -- independent
of any clock frequency.

**Any baud/microsecond figure is arithmetic at an unconfirmed clock.**
200 cycles x 20 ns is the 4 us of 250 kbaud only at target-spec row 4's
**target** 50 MHz, which is unconfirmed on this program's own flow (STA
against this core is blocked, `verification/records/sta-corner-sweep/`),
the same stance as `test_firmware_uart.py`. The bench runs its simulation
clock at `CLK_PERIOD_NS = 20` ns purely to *name* that nominal, and the
model's 4000 ns period is derived from the same arithmetic. The graded
claims are the cycle counts.

The channel pattern
-------------------
The universe is not stored (four registers, no data memory): slot n
carries level ``(5 x (n-1)) mod 256`` -- a fixed walk whose adjacent
values always differ, whose natural 0x00 slots (1 and 257) send nine
consecutive low periods, and whose period (256) is traversed twice per
universe. The bench computes the expected 512 levels from that formula
alone; the model recovers the bytes independently; the two never meet
except here.

The 512th slot and the packet boundary
--------------------------------------
The issue's wrap concern (an 8-bit slot counter ending the universe
after 256 slots) is caught structurally: this bench decodes **all 513**
slots of universe 1 (start code + 512 channels), asserts slot 512's
level, and asserts the next BREAK's falling edge lands exactly 2,200
cycles after slot 512's start -- one full slot later, stop 2 complete --
then that universe 2 opens with its own BREAK, mark and start code
(successive BREAKs).

Negative controls (a suite that cannot fail cannot cite its passes)
-------------------------------------------------------------------
Two, both graded by the model:

1. **One-stop-bit boundary** (the issue's control): a copy of the DUT's
   own captured waveform with the channel-2 slot and everything after it
   shifted one bit early. Slot 1 must still decode 0x05 while the model
   flags the boundary (stop sampled 0, short pitch) -- proving this
   bench's capture-and-grade path can fail on exactly the malformed
   framing the protocol forbids.
2. **Mistimed capture**: the DUT's own captured waveform time-stretched
   by 1.051x. The per-slot cumulative drift becomes ~5.1% of a bit
   period, past `MAX_SLOT_DRIFT_PCT` (5%), while every byte still samples
   correctly -- the timing-only failure mode. The scale is boxed above
   the drift bound and below the half-sample slip that would corrupt the
   stop-bit samples instead.

Driven by `klt functional-verification` (see
`verification/request-firmware-dmx512.json`) against
`src/tt_um_2amlogic_protocol_emulator.v` plus the two `rtl/` modules it
instantiates and the vendored PDK macro model (`rtl/vendor/`). Like its
siblings, this file is *input* to `klt functional-verification`, not a
pytest module.

Everything is deterministic: one committed program, no randomization
anywhere, so every run is byte-reproducible.
"""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock

from reference_models.dmx512 import (
    BREAK_MIN_NS,
    MAB_MIN_NS,
    MAX_SLOT_DRIFT_PCT,
    Dmx512Receiver,
)
from reference_models.waveform import Signal

# --- the unconfirmed-clock mapping, stated once -------------------------
#: Simulation clock period. 20 ns names target-spec row 4's **target**
#: 50 MHz; row 4 is unconfirmed (see the module docstring), so this value
#: is a nominal for the ns<->cycle mapping, never a measurement.
CLK_PERIOD_NS = 20

#: The measured quantity: cycles per DMX512 bit (250 kbaud 8N2), as
#: implemented by `firmware/asm/dmx512_tx.asm` and stated by its
#: committed `.cyclesec` sections, which this bench cross-checks below.
BIT_PERIOD_CYCLES = 200

#: The model's nominal grid, from the same arithmetic: 200 x 20 ns.
MODEL_PERIOD_NS = BIT_PERIOD_CYCLES * CLK_PERIOD_NS

#: TX pin: bit 0 of the dedicated output port (`uo_out`), DR 0010's
#: dmx512 role.
TX_PIN, TX_BIT = "uo_out", 0

# --- the committed program's static timing (cross-checked below) --------
#: BREAK: 18 x `WAIT 255` (4,608) + the OUT that ends the low.
BREAK_CYCLES = 4609
#: Mark-after-break: 3 x `WAIT 200` (603) + LDI + the START OUT.
MAB_CYCLES = 605
#: One slot: 11 bit periods (start + 8 data + 2 stop), back to back.
SLOT_CYCLES = 11 * BIT_PERIOD_CYCLES
#: Slots per packet: the start code plus 512 channels.
PACKET_SLOTS = 513
#: One universe: BREAK + MAB + all slots.
UNIVERSE_CYCLES = BREAK_CYCLES + MAB_CYCLES + PACKET_SLOTS * SLOT_CYCLES
#: Statically: the BREAK fall retires 2 (fetch-ahead) + 3 setup
#: instructions + `WAIT 255` + XOR + OUT after the MODE drop.
FIRST_BREAK_FALL_CYCLE = 2 + 3 + 256 + 1 + 1

#: The pattern: slot n (1-based) carries (5 x (n-1)) mod 256.
def expected_level(slot_1based: int) -> int:
    return (5 * (slot_1based - 1)) & 0xFF

#: Slot 512's level, and the wrap/zero landmarks the README documents.
SLOT_512_LEVEL = expected_level(512)
assert SLOT_512_LEVEL == 251

#: Capture length past the first universe's BREAK fall, in cycles: the
#: second packet's BREAK (4,609) and mark (605), then three slots
#: (3 x 2,200: the start code and two channels) less 200 cycles -- which
#: lands inside the third slot's stop-bit mark, so the capture ends on a
#: sampled RISE inside a stop bit and the model's trailing check sees a
#: clean end, not a low it cannot measure.
CAPTURE_MARGIN_CYCLES = BREAK_CYCLES + MAB_CYCLES + 3 * SLOT_CYCLES - 200

#: Capture-path negative-control stretch: boxed by
#:   10 x (scale - 1) > 5%      (the drift bound must catch it)
#:   9 x (scale - 1) < 0.5 bit  (the stop-bit samples must stay legal)
#:   8 x (scale - 1) < 0.5 bit  (so must the last data-bit sample)
NEGATIVE_CONTROL_SCALE = 1.051

try:
    from repo_root import find_repo_root
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from repo_root import find_repo_root

REPO_ROOT = find_repo_root(globals().get("__file__"))

try:
    from firmware_artifacts import parse_cycle_sections as _parse_sections, parse_hex_image, total_cycles
except ImportError:  # module run without verification/ on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from firmware_artifacts import parse_cycle_sections as _parse_sections, parse_hex_image, total_cycles
sys.path.insert(0, str(REPO_ROOT / "firmware" / "tools"))
import asm  # noqa: E402  (path-shimmed import of the committed assembler)

# The serial load-phase driver and the per-edge pin capture are the ones
# the UART bench already uses; importing functions does not register
# their tests (cocotb discovers tests by scanning the *named* module's
# own namespace).
from test_protocol_emulator import load_program  # noqa: E402
from test_firmware_uart import capture_pin_bits  # noqa: E402

SRC = REPO_ROOT / "firmware" / "asm" / "dmx512_tx.asm"
HEX = REPO_ROOT / "firmware" / "build" / "dmx512_tx.hex"
CYCLES = REPO_ROOT / "firmware" / "build" / "dmx512_tx.cycles.txt"

#: The committed program's two lint warnings (see the .asm header: the
#: half-loop BNZ after the PM_ADDR stash round-trip; no IN exists).
EXPECTED_WARNING_COUNT = 2


def committed_image() -> list:
    return parse_hex_image(HEX)


def parse_cycle_sections() -> dict:
    return _parse_sections(CYCLES.read_text(encoding="utf-8"))


def committed_total_cycles() -> int:
    return total_cycles(CYCLES.read_text(encoding="utf-8"))


def universe_run_cycles() -> int:
    """Capture length in cycles: static offset + one full universe +
    the second packet's BREAK, mark and start code + margin."""
    return (FIRST_BREAK_FALL_CYCLE + UNIVERSE_CYCLES
            + CAPTURE_MARGIN_CYCLES)


def time_scaled(signal: Signal, factor: float) -> Signal:
    """A copy of the captured waveform with every transition time
    stretched by `factor` -- the negative control that re-grades this
    bench's own captured waveform as a mistimed transmitter."""
    clone = Signal(signal.initial, name=f"{signal.name}*{factor}")
    clone.transitions = [(t * factor, v) for (t, v) in signal.transitions]
    return clone


def shift_slot_early(signal: Signal, boundary_ns: float, period_ns: float) -> Signal:
    """A copy of the captured waveform with every transition at or after
    `boundary_ns` pulled one bit period earlier -- the malformed boundary:
    the slot that used to begin at `boundary_ns` now begins one stop bit
    sooner, and the slot before it keeps only one stop bit."""
    clone = Signal(signal.initial, name=f"{signal.name}-1bit")
    clone.transitions = [
        ((t - period_ns) if t >= boundary_ns else t, v)
        for (t, v) in signal.transitions
    ]
    return clone


# =======================================================================
# Tests
# =======================================================================


@cocotb.test()
async def test_committed_image_is_fresh(dut):
    """The committed build artifacts match the committed `.asm` source,
    the per-bit cycle budget this bench grades against is the one the
    committed cycle report states, and the program's only lint warnings
    are the two documented PM_ADDR-stash ones (DR 0003: committed
    artifacts are the evidence, not regenerated ad hoc)."""
    program = asm.assemble_file(SRC)
    drift = asm.check_against(program, HEX.parent)
    assert not drift, f"committed firmware/build/ artifacts drifted: {drift}"
    assert len(program.warnings) == EXPECTED_WARNING_COUNT, (
        f"expected exactly {EXPECTED_WARNING_COUNT} documented lint "
        f"warnings (the PM_ADDR stash round-trip), got "
        f"{len(program.warnings)}: {program.warnings}"
    )
    assert len(program.instructions) <= 256, (
        "program exceeds DR 0001's 256-word memory")

    sections = parse_cycle_sections()
    for name, want in (
        ("dmx512_sc_bit", BIT_PERIOD_CYCLES),
        ("dmx512_bit_a", BIT_PERIOD_CYCLES),
        ("dmx512_bit_b", BIT_PERIOD_CYCLES),
    ):
        assert name in sections, f"committed report is missing section {name!r}"
        _start, _end, section_cycles, branches = sections[name]
        assert section_cycles == want, (
            f"section {name} claims {section_cycles} cycles/bit, this bench "
            f"grades {want}"
        )
        assert branches == "true", (
            f"section {name} should contain the constant-trip-count BNZ loop"
        )
    for name in ("dmx512_slot_tail_a", "dmx512_slot_tail_b"):
        assert name in sections, f"committed report is missing section {name!r}"
        _start, _end, cycles, branches = sections[name]
        assert branches == "true", f"section {name} must keep its branch"

    dut._log.info(
        f"committed program: {len(program.instructions)} words, "
        f"{committed_total_cycles()} fall-through cycles; universe is "
        f"{UNIVERSE_CYCLES} cycles ({BREAK_CYCLES} BREAK + {MAB_CYCLES} "
        f"MAB + {PACKET_SLOTS} x {SLOT_CYCLES})"
    )


@cocotb.test()
async def test_dmx512_universe_passes_independent_reference_model(dut):
    """The claim: the committed DMX512 program, loaded over the real
    load-phase pins and executed by the core, drives packets that the
    independent `Dmx512Receiver` decodes byte for byte -- start code 0x00,
    all 512 channel levels of the documented pattern including slot 512,
    both stop bits high in every slot -- with the BREAK, mark, slot pitch
    and universe boundary measuring exactly their static cycle counts at
    the pin. The negative controls run on this same captured waveform at
    the end, so a capture path that could only ever pass fails here."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    words = committed_image()
    assert len(words) <= 256, "program exceeds DR 0001's 256-word memory"

    await load_program(dut, words)
    run_cycles = universe_run_cycles()
    dut._log.info(
        f"capturing {TX_PIN}[{TX_BIT}] for {run_cycles} cycles "
        f"(~{run_cycles * CLK_PERIOD_NS / 1e6:.2f} ms simulated)"
    )
    caps = await capture_pin_bits(dut, {"tx": (TX_PIN, TX_BIT)}, run_cycles)
    tx = caps["tx"]

    # ---- the independent model does the decoding and the grading ------
    receiver = Dmx512Receiver(period_ns=MODEL_PERIOD_NS)
    decode = receiver.decode(tx.signal)
    assert decode.ends_clean, (
        "the capture must end inside a stop-bit mark (a sampled high), "
        "not inside a low the model cannot measure"
    )
    assert decode.violations == [], (
        f"the receiver model flagged the DUT's own waveform: "
        f"{decode.violations}"
    )
    assert len(decode.packets) >= 2, (
        f"the model found {len(decode.packets)} packet(s); the program "
        f"sends successive BREAKs and this capture spans the boundary: "
        f"{decode.packets}"
    )
    pkt = decode.packets[0]
    assert pkt.break_ns >= BREAK_MIN_NS, (
        f"BREAK {pkt.break_ns:.0f} ns is below the receiver limit "
        f"{BREAK_MIN_NS:.0f} ns"
    )
    assert pkt.mab_ns >= MAB_MIN_NS, (
        f"mark-after-break {pkt.mab_ns:.0f} ns is below the receiver "
        f"limit {MAB_MIN_NS:.0f} ns"
    )
    assert len(pkt.slots) == PACKET_SLOTS, (
        f"universe 1 carries {len(pkt.slots)} slots, expected "
        f"{PACKET_SLOTS} (start code + 512 channels) -- an 8-bit slot "
        f"counter wrapping early would show here"
    )
    assert pkt.slots[0].data == 0x00, (
        f"start code is 0x{pkt.slots[0].data:02x}, expected 0x00"
    )
    mismatched = [
        (slot.index, slot.data, expected_level(slot.index))
        for slot in pkt.slots[1:]
        if slot.data != expected_level(slot.index)
    ]
    assert not mismatched, (
        f"channel levels off the documented pattern (5 x (n-1) mod 256): "
        f"{mismatched[:8]}{'...' if len(mismatched) > 8 else ''}"
    )
    assert pkt.slots[512].data == SLOT_512_LEVEL, (
        f"slot 512 is 0x{pkt.slots[512].data:02x}, the pattern says "
        f"0x{SLOT_512_LEVEL:02x}"
    )
    for slot in pkt.slots:
        assert slot.stop_samples == (1, 1), (
            f"slot {slot.index}: stop bits sampled {slot.stop_samples}"
        )
        assert Dmx512Receiver.check_slot(slot, MAX_SLOT_DRIFT_PCT), (
            f"slot {slot.index} out of bounds: {slot}"
        )
    # universe 2 opens with its own BREAK, mark and start code
    pkt2 = decode.packets[1]
    assert pkt2.break_ns >= BREAK_MIN_NS and pkt2.slots, (
        "the second BREAK did not open a packet with slots"
    )
    assert pkt2.slots[0].data == 0x00, (
        "universe 2's start code is not 0x00"
    )

    # ---- the measurement, in cycles (clock-rate-independent) ----------
    # Map the model's findings onto the captured transition cycle indices
    # and grade the widths against the committed program's static numbers.
    t_of = {t: c for t, c in zip(
        [t for (t, _v) in tx.signal.transitions], tx.transition_cycles)}
    def cycle_of(t_ns: float) -> int:
        got = t_of.get(t_ns)
        assert got is not None, f"no captured transition at {t_ns} ns"
        return got

    break_falls = [cycle_of(p.t_break_fall) for p in decode.packets[:2]]
    break_rises = [cycle_of(p.t_break_rise) for p in decode.packets[:2]]
    for n, (fall, rise) in enumerate(zip(break_falls, break_rises)):
        measured = rise - fall
        assert measured == BREAK_CYCLES, (
            f"BREAK {n + 1} measured {measured} cycles, the committed "
            f"program's static accounting says {BREAK_CYCLES}"
        )
    mab1 = cycle_of(pkt.slots[0].t_start) - break_rises[0]
    assert mab1 == MAB_CYCLES, (
        f"mark-after-break measured {mab1} cycles, static accounting "
        f"says {MAB_CYCLES}"
    )
    slot_falls = [cycle_of(s.t_start) for s in pkt.slots]
    pitches = {b - a for a, b in zip(slot_falls, slot_falls[1:])}
    assert pitches == {SLOT_CYCLES}, (
        f"slot pitches measured {sorted(pitches)} cycles, expected only "
        f"the {SLOT_CYCLES}-cycle slot pitch"
    )
    boundary = break_falls[1] - slot_falls[512]
    assert boundary == SLOT_CYCLES, (
        f"the next BREAK's fall lands {boundary} cycles after slot 512's "
        f"start; stop 2 must complete first ({SLOT_CYCLES})"
    )
    # every intra-slot edge sits on the 200-cycle grid
    first_edge, last_edge = slot_falls[0], slot_falls[512] + SLOT_CYCLES
    window = [c for c in tx.transition_cycles
              if first_edge <= c <= last_edge]
    offsets = [(c - first_edge) % BIT_PERIOD_CYCLES for c in window]
    assert set(offsets) == {0}, (
        f"intra-universe edges fall off the {BIT_PERIOD_CYCLES}-cycle grid"
    )
    dut._log.info(
        f"universe 1: BREAK {BREAK_CYCLES} cycles, MAB {MAB_CYCLES}, "
        f"{len(pkt.slots)} slots at {SLOT_CYCLES}-cycle pitch, boundary "
        f"{boundary} cycles; captured {len(tx.transition_cycles)} edges"
    )

    # ---- negative control 1: the one-stop-bit boundary -----------------
    # shift the whole stream from channel slot 1's start edge one bit
    # early: the start-code slot that precedes it keeps only its first
    # stop bit, exactly the malformed boundary the issue names
    boundary_ns = pkt.slots[1].t_start  # channel slot 1's start edge
    early = shift_slot_early(tx.signal, boundary_ns, MODEL_PERIOD_NS)
    early_decode = receiver.decode(early)
    kinds = {v.kind for v in early_decode.violations}
    assert "stop" in kinds or "short-pitch" in kinds, (
        "NEGATIVE CONTROL FAILED TO FAIL: shifting channel slot 1 one "
        f"bit early produced no boundary violation: {early_decode.violations}"
    )
    early_pkt = early_decode.packets[0]
    assert early_pkt.slots[0].data == 0x00, (
        "the negative control must leave the preceding byte decodable "
        f"(the start code read 0x{early_pkt.slots[0].data:02x})"
    )
    assert not Dmx512Receiver.check_slot(early_pkt.slots[0]), (
        "NEGATIVE CONTROL FAILED TO FAIL: the one-stop-bit slot passed "
        f"check_slot: {early_pkt.slots[0]}"
    )
    assert Dmx512Receiver.check_slot(early_pkt.slots[1]), (
        "the slot after the early boundary keeps both stop bits and "
        f"must still pass: {early_pkt.slots[1]}"
    )
    dut._log.info(
        "negative control (one-stop-bit boundary): the start code still "
        f"decodes 0x00, model flags {sorted(kinds)}"
    )

    # ---- negative control 2: the mistimed capture ----------------------
    stretched = time_scaled(tx.signal, NEGATIVE_CONTROL_SCALE)
    stretched_decode = receiver.decode(stretched)
    stretched_pkt = stretched_decode.packets[0]
    assert [s.data for s in stretched_pkt.slots] == \
        [s.data for s in pkt.slots], (
        "the mistimed capture must still decode to the same bytes -- its "
        "whole point is a failure only the timing measurement catches"
    )
    graded = [Dmx512Receiver.check_slot(s, MAX_SLOT_DRIFT_PCT)
              for s in stretched_pkt.slots]
    assert not all(graded), (
        f"NEGATIVE CONTROL FAILED TO FAIL: a {NEGATIVE_CONTROL_SCALE}x "
        f"mistimed copy of the DUT's own waveform still passed "
        f"check_slot at {MAX_SLOT_DRIFT_PCT}% drift -- this bench cannot "
        "be trusted to detect a timing error"
    )
    worst = max((s.drift_pct for s in stretched_pkt.slots
                 if s.drift_pct is not None), default=0.0)
    dut._log.info(
        f"negative control (captured x{NEGATIVE_CONTROL_SCALE}): "
        f"{sum(1 for g in graded if not g)}/{len(graded)} slots fail "
        f"check_slot, worst drift {worst:.2f}% > {MAX_SLOT_DRIFT_PCT}%"
    )
