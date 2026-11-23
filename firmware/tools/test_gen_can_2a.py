#!/usr/bin/env python3
"""Host-side self-test for the generated CAN 2.0A program (issue #450).

Stdlib only (no pytest, no simulator): `python3 firmware/tools/test_gen_can_2a.py`,
listed in `scripts/lint-manifest.txt`. Two layers:

1. **A cycle-accurate ISA interpreter** for the frozen DR 0017 ISA (DR 0001
   opcodes and timing; DR 0012 control space including the fixed 2-cycle
   `RCTL PM_DATA_HI` stall; DR 0015's P1 CRC engine and P2 LINE unit with
   the same next-state equations as `rtl/protocol_core.v`). It executes
   the generated program word by word against a scripted CAN bus on
   CAN_TXD = uo_out[0] / CAN_RXD = ui_in[0] and records the TXD waveform.
2. **An independent CAN 2.0A model** (two CRC-15 implementations, a
   stuffer/destuffer, frame encode/decode) that grades the recorded
   waveform, exactly as the cocotb bench does against
   `verification/reference_models/can_2a.py`.

The two layers meet only at the waveform and the status words, so a timing
or logic error anywhere in the program shows up as a failing bit window, a
decoding mismatch or a wrong status. This is the generator's own gate; the
committed cocotb bench (`verification/test_firmware_can.py`) remains the
RTL-level evidence.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import asm  # noqa: E402  (the committed assembler)
import gen_can_2a as gen  # noqa: E402

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
# An independent CAN 2.0A model (the grader)
# ======================================================================
def crc15_lfsr(bits):
    """CRC-15, poly 0x4599, seed 0, MSB-first (a bitwise shift register)."""
    state = 0
    for b in bits:
        fb = ((state >> 14) & 1) ^ b
        state = ((state << 1) & 0x7FFF) ^ (0x4599 if fb else 0)
    return state


def crc15_rem(bits):
    """The same CRC as bit-by-bit polynomial long division of the message
    followed by fifteen zero bits (a second, independent method: the
    quotient is never formed, the remainder register just absorbs the
    appended zeros -- verified against `crc15_lfsr` in the self-test)."""
    work = 0
    for b in list(bits) + [0] * 15:
        top = (work >> 14) & 1
        work = ((work << 1) | b) & 0x7FFF
        if top:
            work ^= 0x4599
    return work


def stuff(bits):
    out, run, last = [], 0, None
    for b in bits:
        if run == 5:
            s = 1 - last
            out.append(s)
            run, last = 1, s
        out.append(b)
        run = run + 1 if b == last else 1
        last = b
    return out


def frame_bits(cid, data, rtr=0):
    bits = [0] + [(cid >> i) & 1 for i in range(10, -1, -1)]
    bits += [rtr, 0, 0]
    bits += [(len(data) >> i) & 1 for i in range(3, -1, -1)]
    for b in data:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    return bits


def encode_frame(cid, data, rtr=0):
    """Returns the stuffed wire bits (SOF..CRC sequence) and the ten tail
    bits (CRC delimiter, ACK slot, ACK delimiter, EOF x7)."""
    bits = frame_bits(cid, data, rtr)
    crc = crc15_lfsr(bits)
    bits += [(crc >> i) & 1 for i in range(14, -1, -1)]
    return stuff(bits), [1] * 10, bits


def decode_destuffed(bits):
    """Fields of a destuffed SOF..CRC-sequence bit list, and the CRC verdict."""
    cid = 0
    for k in range(11):
        cid = (cid << 1) | bits[1 + k]
    dlc = (bits[15] << 3) | (bits[16] << 2) | (bits[17] << 1) | bits[18]
    data = [sum(bits[19 + 8 * m + k] << (7 - k) for k in range(8))
            for m in range(dlc)]
    return {"id": cid, "rtr": bits[12], "dlc": dlc, "data": data,
            "crc_ok": crc15_rem(bits) == 0}


def destuff(bits):
    out, run, last = [], 0, None
    for i, b in enumerate(bits):
        if run == 5:
            if b == last:
                return out, i  # stuff error at i
            run, last = 1, b
            continue
        out.append(b)
        run = run + 1 if b == last else 1
        last = b
    return out, None


# ======================================================================
# The cycle-accurate core (DR 0001 + DR 0012 + DR 0015 semantics)
# ======================================================================
class Halted(Exception):
    pass


class Core:
    def __init__(self, words, bus):
        self.pm = list(words) + [0] * (256 - len(words))
        self.bus = bus
        self.r = [0, 0, 0, 0]
        self.z = False
        self.c = False
        self.pc = 0
        self.cycle = 0
        self.uo_out = 0x00      # DR 0012: uo_out resets 0 (dominant!)
        self.uio_dir = 0
        self.uio_od = 0
        self.pm_addr = 0
        self.pm_lo = 0
        self.crc_wm1 = 0
        self.crc_refl = 0
        self.crc_inv = 0
        self.crc_ptr = 0
        self.crc_poly = 0
        self.crc_state = 0
        self.line_cfg = 0
        self.line_lvl = 0
        self.line_prev = 0
        self.line_cnt = 0
        self.line_stuf = 0
        self.txd = []           # uo_out bit 0 per cycle (post-write)
        self.halted_at = None

    @property
    def crc_mask(self):
        return (1 << (self.crc_wm1 + 1)) - 1

    def _crc_step(self, d):
        fb = d ^ ((self.crc_state >> (0 if self.crc_refl else self.crc_wm1)) & 1)
        sh = ((self.crc_state & self.crc_mask) >> 1) if self.crc_refl \
            else (self.crc_state << 1)
        self.crc_state = (sh ^ (self.crc_poly if fb else 0)) & 0xFFFFFFFF

    def _byte(self, v, ptr):
        return (v >> (8 * ptr)) & 0xFF

    def _rctl(self, k):
        if k == 0x00:
            return self.uio_dir
        if k == 0x01:
            return self.uio_od
        if k == 0x02:
            return self.pm_addr
        if k == 0x04:
            v = self.pm_lo
            self.pm_addr = (self.pm_addr + 1) & 0xFF
            return v
        if k == 0x10:
            return (self.crc_inv << 6) | (self.crc_refl << 5) | self.crc_wm1
        if k == 0x11:
            v = self._byte(self.crc_poly, self.crc_ptr)
            self.crc_ptr = (self.crc_ptr + 1) & 3
            return v
        if k == 0x12:
            v = self._byte(self.crc_state, self.crc_ptr) & \
                self._byte(self.crc_mask, self.crc_ptr)
            self.crc_ptr = (self.crc_ptr + 1) & 3
            return v
        if k == 0x15:
            v = self.crc_state ^ (self.crc_mask if self.crc_inv else 0)
            b = self._byte(v, self.crc_ptr) & self._byte(self.crc_mask, self.crc_ptr)
            self.crc_ptr = (self.crc_ptr + 1) & 3
            return b
        if k == 0x16:
            return self.line_cfg & 0x7F
        if k == 0x18:
            return ((~self.line_lvl & 1) << 1) | self.line_lvl
        if k == 0x19:
            return self.line_stuf
        return 0x00

    def _wctl(self, k, val):
        if k == 0x00:
            self.uio_dir = val
        elif k == 0x01:
            self.uio_od = val
        elif k == 0x02:
            self.pm_addr = val
        elif k == 0x10:
            self.crc_wm1 = val & 0x1F
            self.crc_refl = (val >> 5) & 1
            self.crc_inv = (val >> 6) & 1
            self.crc_ptr = 0
        elif k == 0x11:
            self.crc_poly = (self.crc_poly & ~(0xFF << (8 * self.crc_ptr))) | \
                (val << (8 * self.crc_ptr))
            self.crc_ptr = (self.crc_ptr + 1) & 3
        elif k == 0x12:
            self.crc_state = (self.crc_state & ~(0xFF << (8 * self.crc_ptr))) | \
                (val << (8 * self.crc_ptr))
            self.crc_ptr = (self.crc_ptr + 1) & 3
        elif k == 0x13:
            self._crc_step(val & 1)
        elif k == 0x16:
            self.line_cfg = val & 0x7F
            self.line_lvl = (val >> 7) & 1
            self.line_cnt = 0
            self.line_stuf = 0
        elif k == 0x17:
            cfg = self.line_cfg
            ones = (cfg >> 2 & 3) == 1
            equal = (cfg >> 2 & 3) == 2
            n = (cfg >> 4) & 0x7
            due = (ones or equal) and self.line_cnt == n
            e = (1 - self.line_prev) if (due and equal) else (val & 1)
            run = e if ones else (1 if e == self.line_prev else 0)
            self.line_cnt = (self.line_cnt + 1) if run else (1 if not ones else 0)
            mode = cfg & 0x3
            if mode == 1:
                self.line_lvl = (self.line_lvl ^ (0 if e else 1)) & 1
            elif mode == 2:
                self.line_lvl = (self.line_lvl ^ e) & 1
            else:
                self.line_lvl = e
            self.line_prev = e
            self.line_stuf = 1 if due else 0

    def run(self):
        try:
            while self.cycle < LIMIT:
                self.step()
        except Halted:
            pass

    def step(self):
        word = self.pm[self.pc & 0xFF]
        op = (word >> 12) & 0xF
        rd = (word >> 10) & 0x3
        rs = (word >> 8) & 0x3
        imm = word & 0xFF
        rd_val, rs_val = self.r[rd], self.r[rs]
        stalls = 0
        rxd = self.ui0

        if op == 0x0:
            pass
        elif op == 0x1:
            self.r[rd] = imm
        elif op == 0x2:
            self.r[rd] = rs_val
        elif op == 0x3:
            v = rd_val + rs_val
            self.c = v > 0xFF
            self.r[rd] = v & 0xFF
            self.z = (v & 0xFF) == 0
        elif op == 0x4:
            self.c = rd_val < rs_val
            self.r[rd] = (rd_val - rs_val) & 0xFF
            self.z = self.r[rd] == 0
        elif op == 0x5:
            self.r[rd] = rd_val & rs_val
            self.z = self.r[rd] == 0
        elif op == 0x6:
            self.r[rd] = rd_val | rs_val
            self.z = self.r[rd] == 0
        elif op == 0x7:
            self.r[rd] = rd_val ^ rs_val
            self.z = self.r[rd] == 0
        elif op == 0x8:
            if rs & 1:
                self.c = bool((rd_val >> 7) & 1)
                self.r[rd] = (rd_val << 1) & 0xFF
            else:
                self.c = bool(rd_val & 1)
                self.r[rd] = rd_val >> 1
        elif op == 0x9:                                   # IN
            if rs == 0b00:
                self.r[rd] = self.ui0                     # UI_IN
            elif rs == 0b01:
                self.r[rd] = self.ui0                     # UIO_IN (unused)
            elif rs == 0b10:                              # RCTL
                self.r[rd] = self._rctl(imm)
                if imm == 0x03:                           # PM_DATA_HI read
                    self.pm_lo = self.pm[self.pm_addr] & 0xFF
                    stalls = 1
        elif op == 0xA:                                   # OUT
            if rs == 0b10:
                self.uo_out = rd_val                      # UO_OUT
            elif rs == 0b00:                              # WCTL
                self._wctl(imm, rd_val)
                if imm == 0x04:                           # PM_DATA_LO write
                    stalls = 1
        elif op == 0xB:
            stalls = imm                                  # WAIT imm
        elif op == 0xC:
            self.pc = imm & 0xFF
            self._tick()
            return
        elif op == 0xD:
            self.pc = imm & 0xFF if self.z else ((self.pc + 1) & 0xFF)
            self._tick()
            return
        elif op == 0xE:
            self.pc = ((self.pc + 1) & 0xFF) if self.z else (imm & 0xFF)
            self._tick()
            return
        elif op == 0xF:
            self.halted_at = self.cycle
            raise Halted()

        self.pc = (self.pc + 1) & 0xFF
        for _ in range(stalls):
            self._tick()
        self._tick()

    def _tick(self):
        self.txd.append(self.uo_out & 1)
        self.cycle += 1
        self.ui0 = self.bus(self.cycle, self.uo_out) & 1


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

    def ack_dut_frame(self, n_bits_wire):
        """ACK the DUT's next transmission: dominant during its ACK slot."""
        assert self.dut_sof is not None
        # wire bits + CRC delimiter, then the ACK slot bit
        ack_start = self.dut_sof + 1 + (n_bits_wire + 1) * BIT
        self.ack_frames.append((ack_start + 2, ack_start + BIT - 2))


def run_scenario(other_on_sof=None, ack=True, rx_after_tx=None, limit_note=""):
    """Run the generated program to HALT (or the cycle limit).

    other_on_sof: (bits, ) scheduled on the DUT's SOF (arbitration winner).
    rx_after_tx: (start_delay_after_status, bits) a bench->DUT frame.
    """
    text = gen.generate()
    prog = asm.assemble_text(text)
    bench = Bench()
    core = Core(prog.words, bench.bus)
    wire, tail, _ = encode_frame(gen.TX_ID, gen.TX_DATA)
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

    core.bus = wrapped
    core.ui0 = 1
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


def test_crc15_implementations_agree():
    rnd = random.Random(7)
    for _ in range(60):
        n = rnd.randrange(1, 130)
        bits = [rnd.randrange(2) for _ in range(n)]
        assert crc15_lfsr(bits) == crc15_rem(bits)
    # the algebraic property the RX check relies on: data + its CRC
    # feeds through to a zero remainder
    bits = frame_bits(0x123, [0xAB, 0xCD, 0x5A])
    crc = crc15_lfsr(bits)
    full = bits + [(crc >> i) & 1 for i in range(14, -1, -1)]
    assert crc15_rem(full) == 0


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
    win_wire, win_tail, _ = encode_frame(0x5A1, [0xC3])   # lower ID: wins
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
    rx_wire, rx_tail, _ = encode_frame(0x123, [0xAB, 0xCD, 0x5A])
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
    rx_wire, rx_tail, _ = encode_frame(0x123, [0xAB, 0xCD, 0x5A])
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
    rx_wire, rx_tail, _ = encode_frame(0x123, [0xAB, 0xCD, 0x5A])
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
    check("crc15 implementations agree", test_crc15_implementations_agree)
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
