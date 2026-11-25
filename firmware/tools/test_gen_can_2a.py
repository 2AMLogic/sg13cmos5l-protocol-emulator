#!/usr/bin/env python3
"""Host-side self-test for the generated CAN 2.0A program (issue #450).

Stdlib only (no pytest, no simulator): `python3 firmware/tools/test_gen_can_2a.py`,
listed in `scripts/lint-manifest.txt`. Two layers:

1. **The frozen ISA** (DR 0001 opcodes and timing; DR 0012 control space
   including the fixed 2-cycle `RCTL PM_DATA_HI` stall; DR 0015's P1 CRC
   engine and P2 LINE unit) executed by the independent model
   `verification/reference_models/isa.py` -- the `Machine` that
   `verification/test_isa_lockstep.py` compares cycle by cycle against
   the RTL. A thin runner steps it one clock edge per cycle against a
   scripted CAN bus on CAN_TXD = uo_out[0] / CAN_RXD = ui_in[0] and
   records the TXD waveform.
2. **An independent CAN 2.0A model** (two CRC-15 implementations, a
   stuffer/destuffer, frame encode/decode), imported read-only from
   `verification/reference_models/can_2a.py`, that grades the recorded
   waveform, exactly as the cocotb bench does.

The two layers meet only at the waveform and the status words, so a timing
or logic error anywhere in the program shows up as a failing bit window, a
decoding mismatch or a wrong status. This is the generator's own gate; the
committed cocotb bench (`verification/test_firmware_can.py`) remains the
RTL-level evidence.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "verification"))

import asm  # noqa: E402  (the committed assembler)
import gen_can_2a as gen  # noqa: E402
from reference_models.can_2a import encode_frame  # noqa: E402
from reference_models.isa import Machine  # noqa: E402

BIT = gen.BIT
SP = gen.SP
LIMIT = 400_000

FAILURES: list[str] = []


def check(name, fn):
    try:
        fn()
    except AssertionError as err:
        FAILURES.append(name)
        print(f"FAIL {name}: {err}")
    else:
        print(f"ok   {name}")


# ======================================================================
# The cycle-accurate runner: the lockstep-verified Machine on the bus
# ======================================================================
class MachineRunner:
    """`Machine` (one clock edge per `step()`) driving the scripted bus.

    `Machine` primes its fetch on the first edge after run-phase entry
    (the DR 0005 amendment quoted in DR 0001's note) and commits each
    instruction's architectural effects at the end of its last edge, so
    with the priming edge skipped, machine edge k+1 is waveform cycle k:
    each cycle appends one TXD sample of the post-edge `uo_out`, then
    consults the bus once as `bus(cycle, uo_out)` -- the level it returns
    is the `ui_in` the next retiring `IN` samples, the same edge-sampling
    contract the RTL implements.
    """

    def __init__(self, words, bus):
        self.m = Machine(words)
        self.bus = bus
        self.txd = []           # uo_out bit 0 per cycle
        self.uo_out = 0x00      # DR 0012: uo_out resets 0 (dominant!)
        self.halted_at = None

    def run(self):
        """Run the program to HALT (or the cycle limit)."""
        self.m.step(ui_in=1)                # run-phase entry: prime the fetch
        lvl = 1
        while not self.m.halted and len(self.txd) < LIMIT:
            row = self.m.step(ui_in=lvl)
            self.uo_out = row.uo_out
            if self.m.halted:               # HALT retires: no cycle follows it
                self.halted_at = len(self.txd)
                break
            self.txd.append(row.uo_out & 1)
            lvl = self.bus(len(self.txd), row.uo_out) & 1


# ======================================================================
# Bus scenarios
# ======================================================================
class Bench:
    """The bench side of the bus: an 8-cycle transceiver round trip (RXD
    follows TXD delayed), plus scripted other-node transmissions, plus an
    ACK driver for the DUT's own frames."""

    DEFER = 8

    def __init__(self):
        self.hist = [1] * 64
        self.other = None        # (start_cycle, bits list) the other node
        self.ack_frames = []     # list of (ack_slot_start, ack_slot_end)
        self.rx_frame = None     # (start_cycle, bits) a bench->DUT frame
        self.dut_sof = None

    def bus(self, cycle, uo_out):
        txd = uo_out & 1
        if len(self.hist) <= cycle:
            self.hist.append(txd)
        else:
            self.hist[cycle] = txd
        if self.dut_sof is None and txd == 0 and cycle > 8:
            self.dut_sof = cycle
        lvl = self.hist[max(0, cycle - self.DEFER)]
        if self.other is not None:
            start, bits = self.other
            k = cycle - start
            if 0 <= k < len(bits) * BIT:
                lvl &= bits[k // BIT]
        if self.rx_frame is not None:
            start, bits = self.rx_frame
            k = cycle - start
            if 0 <= k < len(bits) * BIT:
                lvl &= bits[k // BIT]
        for a, b in self.ack_frames:
            if a <= cycle < b:
                lvl &= 0
        return lvl


def run_scenario(other_on_sof=None, ack=True, rx_after_tx=None, limit_note=""):
    """Run the generated program to HALT (or the cycle limit).

    other_on_sof: (bits, ) scheduled on the DUT's SOF (arbitration winner).
    rx_after_tx: (start_delay_after_status, bits) a bench->DUT frame.
    """
    text = gen.generate()
    prog = asm.assemble_text(text)
    bench = Bench()
    wire, tail = encode_frame(gen.TX_ID, bytes(gen.TX_DATA))
    n_wire = len(wire)

    state = {"prev": 1, "frame_sof": None, "idle": 20 * BIT}

    # wrap the bus to script the scenario dynamically
    orig = bench.bus

    def wrapped(cycle, uo_out):
        lvl = orig(cycle, uo_out)
        if other_on_sof is not None and bench.other is None and bench.dut_sof:
            bench.other = (bench.dut_sof + 1, other_on_sof)
        # a new DUT frame = a falling TXD edge after >= 14 recessive bit
        # times (in-frame runs are stuffing-capped at 6; the frame tail is
        # 13: delimiter+ACK+delimiter+EOF+IFS -- only true idle is longer).
        # uo_out resets dominant and only goes recessive at the setup's
        # first OUT, so idle counting starts after that.
        txd = uo_out & 1 if cycle > 3 else 1
        was_idle = state["idle"] >= 14 * BIT
        state["idle"] = state["idle"] + 1 if txd else 0
        if txd == 0 and was_idle:
            state["frame_sof"] = cycle
        state["prev"] = txd
        if ack and state["frame_sof"] is not None:
            # during the arbitration scenario the first (lost) attempt gets
            # no ACK: gate arming on the winner's frame being over
            gate = 0
            if bench.other is not None:
                start, wbits = bench.other
                gate = start + len(wbits) * BIT
            if state["frame_sof"] > gate:
                ack_at = state["frame_sof"] + 1 + (n_wire + 1) * BIT
                if not bench.ack_frames or bench.ack_frames[0][0] < state["frame_sof"]:
                    bench.ack_frames = [(ack_at + 2, ack_at + BIT - 2)]
        if rx_after_tx is not None and bench.rx_frame is None and uo_out in \
                (gen.STAT_TX_ACK, gen.STAT_TX_NOACK):
            bench.rx_frame = (cycle + rx_after_tx[0], rx_after_tx[1])
        return lvl

    core = MachineRunner(prog.words, wrapped)
    core.run()
    return core, bench, wire, tail


# ======================================================================
# Tests
# ======================================================================
def test_assembles():
    text = gen.generate()
    prog = asm.assemble_text(text)
    assert len(prog.instructions) <= 256, \
        f"{len(prog.instructions)} words exceeds DR 0001's 256-word store"
    for sec in ("can_tx_bit", "can_tx_crc1", "can_tx_crc0", "can_rx_bit"):
        assert f".cyclesec {sec}" in text, f"missing .cyclesec {sec}"


def test_tx_waveform_and_windows():
    core, bench, wire, tail = run_scenario()
    sof = bench.dut_sof
    assert sof is not None, "no SOF found on TXD"
    txd = core.txd
    full = wire + tail
    for k, want in enumerate(full):
        c = sof + 1 + k * BIT + BIT // 2
        assert c < len(txd), f"waveform ended inside the frame (bit {k})"
        assert txd[c] == want, \
            f"TX bit {k}: sent {txd[c]}, model says {want} " \
            f"(wire={wire[:k + 1] if k < len(wire) else 'tail'})"
    # every TXD edge inside the frame sits on the bit grid
    prev = None
    for i, t in enumerate(txd):
        if t != prev and sof < i <= sof + len(full) * BIT:
            assert (i - sof + 1) % BIT == 0, \
                f"TXD edge at cycle {i} is off the {BIT}-cycle grid"
        prev = t
    assert core.uo_out == gen.STAT_TX_ACK, \
        f"status 0x{core.uo_out:02X}, expected 0x{gen.STAT_TX_ACK:02X} after an ACKed TX"


def test_tx_noack():
    core, bench, wire, tail = run_scenario(ack=False)
    assert core.uo_out == gen.STAT_TX_NOACK, \
        f"status 0x{core.uo_out:02X}, expected 0x{gen.STAT_TX_NOACK:02X}"


def test_arbitration_loss_and_retransmit():
    win_wire, win_tail = encode_frame(0x5A1, bytes([0xC3]))   # lower ID: wins
    winner = win_wire + win_tail
    core, bench, wire, tail = run_scenario(other_on_sof=winner, ack=True)
    sof = bench.dut_sof
    txd = core.txd
    # the DUT loses at wire bit 9 (its ID2 is 1, the winner's is 0): from
    # that bit's sample point it must stay recessive through the winner's
    # frame + EOF/IFS, then retransmit
    loss_bit = 9
    # no dominant from the DUT between its loss bit and the winner's end
    # (+11 recessive bits it waits) -- i.e. the DUT's dominants stop at the
    # loss bit and resume only at the retransmission
    winner_end = sof + 1 + len(winner) * BIT
    resume = winner_end + 21 * BIT + 5 * BIT   # the idle poll waits 20 recessive bits
    for i in range(sof + 1 + (loss_bit + 1) * BIT + SP, min(resume, len(txd))):
        assert txd[i] == 1 or i > sof + 1 + (loss_bit + 1) * BIT + SP, \
            f"DUT drove dominant at cycle {i} after losing arbitration"
    # a retransmission happened (a second falling edge after the resume
    # window begins) and completed with an ACK
    falls = [i for i in range(resume, len(txd) - 1)
             if txd[i] == 1 and txd[i + 1] == 0]
    assert falls, "no retransmission after the arbitration loss"
    assert core.uo_out == gen.STAT_TX_ACK, \
        f"final status 0x{core.uo_out:02X} after retransmit + ACK"


def test_rx_ok_and_ack():
    rx_wire, rx_tail = encode_frame(0x123, bytes([0xAB, 0xCD, 0x5A]))
    rx_bits = rx_wire + rx_tail
    core, bench, wire, tail = run_scenario(ack=True, rx_after_tx=(2 * BIT, rx_bits))
    assert core.halted_at is not None, "the DUT never HALTed after the RX frame"
    assert core.uo_out == gen.STAT_RX_OK, \
        f"final status 0x{core.uo_out:02X}, expected 0x{gen.STAT_RX_OK:02X}"
    # the DUT drove a dominant ACK inside the ACK slot of the bench frame
    start = bench.rx_frame[0]
    ack_slot = start + (len(rx_wire) + 1) * BIT
    seg = core.txd[ack_slot:ack_slot + BIT]
    assert 0 in seg, "no dominant ACK pulse in the bench frame's ACK slot"


def test_rx_crc_error():
    rx_wire, rx_tail = encode_frame(0x123, bytes([0xAB, 0xCD, 0x5A]))
    rx_wire[-1] ^= 1                      # corrupt the last CRC bit
    rx_bits = rx_wire + rx_tail
    core, bench, wire, tail = run_scenario(ack=True, rx_after_tx=(2 * BIT, rx_bits))
    assert core.halted_at is not None
    assert core.uo_out == gen.STAT_RX_CRC, \
        f"final status 0x{core.uo_out:02X}, expected 0x{gen.STAT_RX_CRC:02X}"
    start = bench.rx_frame[0]
    ack_slot = start + (len(rx_wire) + 1) * BIT
    seg = core.txd[ack_slot:ack_slot + BIT]
    assert 0 not in seg, "the DUT ACKed a frame with a bad CRC"


def test_rx_stuff_error():
    # six equal bits inside the data field: take a valid frame and flip a
    # stuff bit to extend a run -- find the first stuff bit and make it
    # equal to the run it breaks
    rx_wire, rx_tail = encode_frame(0x123, bytes([0xAB, 0xCD, 0x5A]))
    run, last, out = 0, None, list(rx_wire)
    done = False
    for i, b in enumerate(rx_wire):
        if run == 5 and not done:
            out[i] = last          # the stuff bit now extends the run: error
            done = True
            break
        run = run + 1 if b == last else 1
        last = b
    assert done, "the demo RX frame has no stuff bit to corrupt"
    rx_bits = out + rx_tail
    core, bench, wire, tail = run_scenario(ack=True, rx_after_tx=(2 * BIT, rx_bits))
    assert core.halted_at is not None
    assert core.uo_out == gen.STAT_RX_STUFF, \
        f"final status 0x{core.uo_out:02X}, expected 0x{gen.STAT_RX_STUFF:02X}"


def main() -> int:
    check("generator output assembles", test_assembles)
    check("tx waveform and bit windows", test_tx_waveform_and_windows)
    check("tx noack status", test_tx_noack)
    check("arbitration loss and retransmit", test_arbitration_loss_and_retransmit)
    check("rx ok and ack", test_rx_ok_and_ack)
    check("rx crc error", test_rx_crc_error)
    check("rx stuff error", test_rx_stuff_error)
    if FAILURES:
        print(f"{len(FAILURES)} failure(s)")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
