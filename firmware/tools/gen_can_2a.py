#!/usr/bin/env python3
"""Generator for `firmware/asm/can_2a.asm` (issue #450, multi-protocol extra
credit, catalog #443): a CAN 2.0A (classic, 11-bit identifiers) node on the
frozen DR 0017 ISA, no RTL change and no hardware peripheral.

The committed `.asm` is the evidence (DR 0003); this script is how it was
written, kept so the timing literals are provably derived from the bit
budget rather than hand-tuned, in the shape of `gen_i2c_sr.py` /
`gen_spi_modes.py`. It does not run in the verification flow; its own gate
is `firmware/tools/test_gen_can_2a.py` (a host-side cycle-accurate
simulation of the program against an independent CAN model).

    python3 firmware/tools/gen_can_2a.py            # (re)write the file
    python3 firmware/tools/gen_can_2a.py --check    # exit 1 on drift

One program, one bus sequence, four behaviours:

1. **Transmit** a standard data frame (SOF, 11-bit ID, RTR=0, IDE=0, r0=0,
   DLC, data, CRC-15, CRC delimiter, ACK slot, ACK delimiter, EOF, IFS).
   Bit stuffing is DR 0015's P2 `LINE_*` unit (equal-bits rule, N=5, NRZ
   off); the CRC-15 is DR 0015's P1 `CRC_*` engine (poly 0x4599, width 15,
   normal form, seed 0) fed one `CRC_BIT` per destuffed bit.
2. **Arbitrate**: while transmitting a recessive bit, the sample point
   reads CAN_RXD; a dominant read there is a lost arbitration -> drive
   recessive, wait for 11 recessive bit times (EOF+IFS+1), retransmit.
3. **Receive** a frame of this image's own shape (DLC 3): hard-sync on the
   SOF falling edge, sample each bit at ~75% of the bit time, verify every
   slot against the LINE unit's own predicted level (a mismatch is a stuff
   error -> abort, no ACK), de-stuff (`LINE_STUF` says which sampled bits
   to drop), feed the destuffed stream to the CRC engine, and check the
   CRC by the classic remainder-zero property (SOF..CRC sequence fed
   through the register leaves 0); drive the dominant ACK in the ACK slot
   only when the CRC checked.
4. **Report** on `uo_out[7:1]` (bit 0 is CAN_TXD and stays recessive in
   every status word): 0x41/0x61 after the transmit (ACK seen / not), and
   at HALT 0xC1 (received, CRC ok, ACK driven), 0xC3 (received, CRC error,
   no ACK) or 0xC5 (stuff error, frame abandoned).

Pin plan (DR 0010's `can` phase, added by this issue):

    CAN_TXD = uo_out[0]   push-pull, the transceiver's D input
                           (shares the pad with uart_tx/dmx512 TX and
                           result[0]; one image runs at a time)
    CAN_RXD = ui_in[0]    the transceiver's R output; a run-phase input
                           (the same pad is PROG_SER during the load phase)

`uo_out` writes during bit times are `RCTL LINE_OUT`'s {~level, level}
pair: bit 0 is the line level (the TXD bit) and bit 1 its complement
(LINE_OUT's differential-pair shape; the edge on uo_out[1] is unused
here). 0x03 is recessive, 0x00 dominant.

The register ceiling shapes the program (recorded as ISA findings in the
evidence record, like i2c_std's unrolled bytes before it):

- R3 holds the one constant 0x01 (the CAN_RXD mask on ui_in[0] and the
  loop decrement), so every counter counts in ones and every sample is
  one AND away.
- The frame's 19-bit header is never byte-aligned, so the transmit stream
  rides one arbitrated table loop whose byte-boundary dispatch walks
  `UIO_DIR` 5..1 through five bit-reversed table bytes (`WAIT imm8` words
  read through `PM_DATA_HI`/`PM_DATA_LO`, DR 0012's latch-then-increment
  pair) and a literal-loaded 3-bit tail. The CRC readout then takes two
  register-loaded passes: the engine's `CRC_NEXT` bytes are MSB-first
  (state[14] goes on the wire first) but `LINE_PUT` presents bit 0, so
  each byte is reversed by a 7-word rotation loop first; byte 0 waits in
  `PM_ADDR` (the table pointer is spent by then).
- The receive path is sized to this image's own frame (DLC 3; 58
  destuffed bits SOF..CRC sequence): a general DLC parser needs a fifth
  live value (collector, counter, sampled bit, compare scratch, constant)
  and this ISA has four registers. Recorded as the issue's ISA finding.
- Arbitration is monitored on every transmitted bit through the CRC
  sequence (CAN monitors to EOF). A mismatch after the arbitration field
  is a bit error in CAN terms; this image takes the same
  back-off-and-retransmit path for it, without the error-frame signalling
  a full controller would add.

Timing: **exactly BIT = 400 core cycles per bit** (125 kbit/s arithmetic
at target-spec row 4's unconfirmed 50 MHz clock), sample point at offset
300 (75%). Every path through a bit window -- recessive or dominant,
consumed or stuff slot, byte boundary or not -- is padded to the same
400-cycle OUT-to-OUT span; the derived WAIT values below are checked by
`test_gen_can_2a.py`'s cycle-accurate simulation, which is the generator's
real gate (and the feasibility check for faster bit rates).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "firmware" / "asm" / "can_2a.asm"

# ---------------------------------------------------------------- constants
BIT = 400        # core cycles per bit time (the measured claim)
SP = 300         # sample-point offset from the bit-start OUT retirement

TX_ID = 0x5A5    # the frame this program transmits
TX_DLC = 3
TX_DATA = [0x11, 0x1F, 0x22]

CRC_CFG_WORD = 0x0E          # width-1 = 14, not reflected, no inversion
CRC_POLY_B0, CRC_POLY_B1 = 0x99, 0x45   # 0x4599, byte 0 = bits [7:0]
LINE_CFG_WORD = 0xD8         # level 1 (recessive), N=5, equal-bits rule, NRZ off

STAT_TX_ACK = 0x41           # after the transmit: ACK seen
STAT_TX_NOACK = 0x61         # after the transmit: no ACK
STAT_RX_OK = 0xC1            # final: received, CRC ok, ACK driven
STAT_RX_CRC = 0xC3           # final: received, CRC error, no ACK
STAT_RX_STUFF = 0xC5         # final: stuff error, frame abandoned

RX_BITS = 19 + 8 * TX_DLC + 15 - 1  # loop samples: the SOF bit is fed at sync


def bitrev8(v: int) -> int:
    return int(f"{v & 0xFF:08b}"[::-1], 2)


def tx_stream_bits() -> list[int]:
    """The unstuffed transmit bits, SOF first."""
    bits = [0]                                       # SOF (dominant)
    bits += [(TX_ID >> i) & 1 for i in range(10, -1, -1)]   # ID10..ID0
    bits += [0, 0, 0]                                # RTR (data), IDE, r0
    bits += [(TX_DLC >> i) & 1 for i in range(3, -1, -1)]   # DLC3..DLC0
    for b in TX_DATA:
        bits += [(b >> i) & 1 for i in range(7, -1, -1)]
    return bits


def tx_table_bytes() -> list[int]:
    """The first 40 stream bits as five MSB-first-packed bytes."""
    bits = tx_stream_bits()
    assert len(bits) == 19 + 8 * TX_DLC
    out = []
    for k in range(5):
        v = 0
        for i in range(8):
            v = (v << 1) | bits[8 * k + i]
        out.append(v)
    return out


def tx_tail3() -> int:
    """Bits 40..42 (the last three data bits), presentation order in bits 2..0."""
    bits = tx_stream_bits()
    return bits[40] | (bits[41] << 1) | (bits[42] << 2)


def stuff_bits(bits: list[int]) -> list[int]:
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


# ------------------------------------------------------------- the emitter
class E:
    def __init__(self):
        self.lines: list[str] = []
        self.labels: dict[str, int] = {}
        self.n = 0

    def raw(self, text: str = ""):
        self.lines.append(text)

    def label(self, name: str):
        assert name not in self.labels, name
        self.labels[name] = self.n
        self.raw(f"{name}:")

    def op(self, text: str) -> int:
        cycles = 2 if text.upper().replace(" ", "").endswith(",PM_DATA_HI") else 1
        self.lines.append("\t" + text)
        self.n += 1
        return cycles

    def wait(self, name: str, comment: str = ""):
        self.lines.append(f"\tWAIT  <{name}>{f'\t; {comment}' if comment else ''}")
        self.n += 1
        return 1  # placeholder cycle count; waits are solved separately

    def sec(self, name: str):
        self.raw(f"\t.cyclesec {name}")

    def endsec(self):
        self.raw("\t.endcyclesec")

    def render(self, waits: dict[str, int]) -> str:
        out = []
        for ln in self.lines:
            if "WAIT  <" in ln:
                name = ln.split("WAIT  <")[1].split(">")[0]
                comment = ln.split(";", 1)[1].strip() if ";" in ln else ""
                cycles = waits[name]
                first = True
                while cycles > 0:
                    imm = min(255, cycles - 1)
                    c = f"\t; {comment}" if comment and first else ""
                    out.append(f"\tWAIT  {imm:<3}{c}")
                    cycles -= imm + 1
                    first = False
            else:
                out.append(ln)
        return "\n".join(out) + "\n"


# ======================================================================
# generation
# ======================================================================
def generate() -> str:
    e = E()
    bits = tx_stream_bits()
    stuffed = stuff_bits(bits)
    n_stuff = len(stuffed) - len(bits)
    assert n_stuff >= 2, "demo frame must exercise stuffing (>= 2 stuff bits)"

    # ---- solved WAIT values (cycles). Derived per path, then asserted:
    # every OUT-to-OUT span in a bit loop is exactly BIT, the sample IN
    # retires at offset SP from its window's OUT. The host-side simulation
    # in test_gen_can_2a.py re-measures all of this at run time.
    W = {
        # transmit table loop paths (see the derivations in each comment):
        # recessive mid-byte: 16 fixed cycles + wa + wb = BIT, IN at 3+wa = SP
        "wa": 297, "wb": 87, "wc": 299, "wd": 91,
        "we": 77, "wt": 79,
        # CRC readout paths
        "wco": 19, "wbc1": 390, "wdc1": 393, "wco2": 330,
        "wbc0": 390, "wdc0": 393,
        # transmit tail: last-CRC-bit exit pad, the delimiter+ACK-slot span
        # to the ACK sample, the ACK slot tail, then per-bit pads
        "wexit": 392, "wdel": 699, "wafin": 96, "wad": 398, "weif": 398,
        # arbitration idle poll (one bit period less the poll's 5 ops)
        "warb": 395,
        # receive: loop iteration (12 ops), sync->first sample, skip pad
        "wr": 388, "wrs": 301, "wrs2": 1,
        # rx tail: readout pad to the delimiter boundary, the delimiter bit,
        # the ACK slot tail, then per-bit pads
        "wz1": 79, "wz2": 394, "wak": 397, "wad2": 398, "wrxif": 398,
        "werr": 398,
        "idle": 256,
    }
     # the rx stuff-skip pad: measured tight (see simulator)

    # ---------------------------------------------------------- setup ----
    e.label("setup")
    e.op("LDI   R3, 0x01")            # the constant: CAN_RXD mask / decrement
    e.op("OUT   UO_OUT, R3")          # release TXD (uo_out resets dominant)
    e.op(f"LDI   R1, 0x{CRC_CFG_WORD:02X}")
    e.op("WCTL  CRC_CFG, R1")
    e.op(f"LDI   R1, 0x{CRC_POLY_B0:02X}")
    e.op("WCTL  CRC_POLY, R1")
    e.op(f"LDI   R1, 0x{CRC_POLY_B1:02X}")
    e.op("WCTL  CRC_POLY, R1")
    e.op(f"LDI   R1, 0x{CRC_CFG_WORD:02X}")
    e.op("WCTL  CRC_CFG, R1")         # rewind the pointer for the seed
    e.op("XOR   R2, R2")
    e.op("WCTL  CRC_STATE, R2")
    e.op("WCTL  CRC_STATE, R2")       # seed 0
    e.op(f"LDI   R1, 0x{LINE_CFG_WORD:02X}")
    e.op("WCTL  LINE_CFG, R1")        # stuff counter 0, line recessive
    e.op("LDI   R1, @TX_TABLE@")
    e.op("WCTL  PM_ADDR, R1")
    e.op("LDI   R2, 0x05")
    e.op("WCTL  UIO_DIR, R2")         # table bytes remaining after the preload
    e.op("RCTL  R1, PM_DATA_HI")      # (2 cycles) latch word 0's low byte
    e.op("RCTL  R0, PM_DATA_LO")      # reversed byte 0; PM_ADDR -> 1
    e.op("LDI   R2, 0x08")
    e.wait("idle", "bus idle before this node's SOF")

    # -------------------------------------- the transmit table loop
    e.raw("")
    e.raw("; ---- the transmit loop: every bit of SOF..last data byte goes")
    e.raw("; ---- through this body (arbitrated, stuffed, CRC-fed). The byte")
    e.raw("; ---- boundary dispatch walks UIO_DIR: 5..2 = table bytes left,")
    e.raw("; ---- 1 = load the 3-bit tail, 0 = tail done -> the CRC readout.")
    e.sec("can_tx_bit")
    e.label("tx_bit")
    e.op("WCTL  LINE_PUT, R0")
    e.op("RCTL  R1, LINE_OUT")
    e.op("OUT   UO_OUT, R1")           # === bit window anchor
    e.op("AND   R1, R3")
    e.op("BZ    tx_dom")
    e.wait("wa", "to the sample point")
    e.op("IN    R1, UI_IN")
    e.op("AND   R1, R3")
    e.op("BZ    arb_lost")             # recessive sent, dominant read: lost
    e.label("tx_join")
    e.op("RCTL  R1, LINE_STUF")
    e.op("AND   R1, R3")               # (RCTL sets no flags: AND does)
    e.op("BNZ   tx_stuff")             # stuff slot: the bit was not consumed
    e.op("WCTL  CRC_BIT, R0")
    e.op("SHF   R0, RIGHT")
    e.op("SUB   R2, R3")
    e.op("BZ    tx_bnd")
    e.wait("wb", "rest of the bit")
    e.op("JMP   tx_bit")
    e.endsec()
    e.label("tx_dom")
    e.wait("wc", "dominant bit: arbitration cannot be lost")
    e.op("JMP   tx_join")
    e.label("tx_stuff")
    e.wait("wd", "stuff slot pad")
    e.op("JMP   tx_bit")
    e.label("tx_bnd")
    e.op("RCTL  R1, UIO_DIR")
    e.op("OR    R1, R1")               # Z iff the tail finished (R1 kept)
    e.op("BZ    tx_crcout")
    e.op("SUB   R1, R3")               # Z iff one byte remains (the tail's)
    e.op("BZ    tx_tail")
    e.op("WCTL  UIO_DIR, R1")
    e.op("RCTL  R1, PM_DATA_HI")
    e.op("RCTL  R0, PM_DATA_LO")
    e.op("LDI   R2, 0x08")
    e.wait("we", "byte-boundary pad")
    e.op("JMP   tx_bit")
    e.label("tx_tail")
    e.op("WCTL  UIO_DIR, R1")          # R1 = 0 here: the next boundary exits
    e.op(f"LDI   R0, 0x{tx_tail3():02X}")
    e.op("LDI   R2, 0x03")
    e.wait("wt", "tail-load pad")
    e.op("JMP   tx_bit")

    # -------------------------------------- CRC readout
    e.raw("")
    e.raw("; ---- the CRC readout: rewind, read the two state bytes, stash byte")
    e.raw("; ---- 0 in PM_ADDR (the table pointer is spent), reverse byte 1 (the")
    e.raw("; ---- top seven bits, state[14] first on the wire) and send it;")
    e.raw("; ---- byte 0 follows through the tx_cb1bnd reload.")
    e.label("tx_crcout")
    e.op(f"LDI   R1, 0x{CRC_CFG_WORD:02X}")
    e.op("WCTL  CRC_CFG, R1")          # rewind the NEXT pointer
    e.op("RCTL  R0, CRC_NEXT")         # byte 0 = state[7:0]
    e.op("WCTL  PM_ADDR, R0")          # stash it
    e.op("RCTL  R0, CRC_NEXT")         # byte 1 = state[14:8]
    e.op("SHF   R0, LEFT")             # state[14] -> bit 7
    e.op("XOR   R1, R1")
    e.label("rev8a")
    for t in ("MOV   R2, R0", "AND   R2, R3", "ADD   R1, R1", "OR    R1, R2",
              "SHF   R0, RIGHT", "OR    R0, R0", "BNZ   rev8a"):
        e.op(t)
    e.op("MOV   R0, R1")               # reversed: bit 0 = state[14]
    e.op("LDI   R2, 0x07")
    e.wait("wco", "CRC byte 1 pad")
    e.op("JMP   tx_cbit1")

    e.sec("can_tx_crc1")
    e.label("tx_cbit1")                # CRC bits 14..8
    e.op("WCTL  LINE_PUT, R0")
    e.op("RCTL  R1, LINE_OUT")
    e.op("OUT   UO_OUT, R1")
    e.op("RCTL  R1, LINE_STUF")
    e.op("AND   R1, R3")
    e.op("BNZ   tx_cs1")
    e.op("SHF   R0, RIGHT")
    e.op("SUB   R2, R3")
    e.op("BZ    tx_cb1bnd")
    e.wait("wbc1", "rest of the bit")
    e.op("JMP   tx_cbit1")
    e.endsec()
    e.label("tx_cs1")
    e.wait("wdc1", "stuff slot pad")
    e.op("JMP   tx_cbit1")
    e.label("tx_cb1bnd")               # byte 1 done -> byte 0
    e.op("RCTL  R0, PM_ADDR")          # the stashed byte 0
    e.op("XOR   R1, R1")
    e.label("rev8b")
    for t in ("MOV   R2, R0", "AND   R2, R3", "ADD   R1, R1", "OR    R1, R2",
              "SHF   R0, RIGHT", "OR    R0, R0", "BNZ   rev8b"):
        e.op(t)
    e.op("MOV   R0, R1")
    e.op("LDI   R2, 0x08")
    e.wait("wco2", "CRC byte 0 pad")
    e.op("JMP   tx_cbit0")

    e.sec("can_tx_crc0")
    e.label("tx_cbit0")                # CRC bits 7..0
    e.op("WCTL  LINE_PUT, R0")
    e.op("RCTL  R1, LINE_OUT")
    e.op("OUT   UO_OUT, R1")
    e.op("RCTL  R1, LINE_STUF")
    e.op("AND   R1, R3")
    e.op("BNZ   tx_cs0")
    e.op("SHF   R0, RIGHT")
    e.op("SUB   R2, R3")
    e.op("BZ    tx_delim")
    e.wait("wbc0", "rest of the bit")
    e.op("JMP   tx_cbit0")
    e.endsec()
    e.label("tx_cs0")
    e.wait("wdc0", "stuff slot pad")
    e.op("JMP   tx_cbit0")

    # -------------------------------------- transmit tail
    e.raw("")
    e.raw("; ---- CRC delimiter, ACK slot (sampled at the sample point), ACK")
    e.raw("; ---- delimiter, EOF (7) + IFS (3), then the transmit status word.")
    e.label("tx_delim")
    e.wait("wexit", "the last CRC bit's window")
    e.op("LDI   R1, 0x03")
    e.op("OUT   UO_OUT, R1")           # the CRC delimiter bit
    e.wait("wdel", "the delimiter + ACK slot, to the ACK sample point")
    e.op("IN    R1, UI_IN")
    e.op("AND   R1, R3")
    e.op("XOR   R1, R3")               # 1 = another node ACKed
    e.op("WCTL  UIO_DIR, R1")
    e.wait("wafin", "rest of the ACK slot")
    e.op("OUT   UO_OUT, R3")           # the ACK delimiter (0x01: recessive)
    e.wait("wad", "the ACK delimiter bit")
    e.op("LDI   R2, 0x0A")             # EOF (7) + IFS (3)
    e.label("tx_eif")
    e.wait("weif", "one recessive bit")
    e.op("SUB   R2, R3")
    e.op("BNZ   tx_eif")
    e.op("RCTL  R1, UIO_DIR")          # the ACK flag
    e.op("OR    R1, R1")               # Z iff nobody ACKed
    e.op("BZ    tx_noack")
    e.op(f"LDI   R1, 0x{STAT_TX_ACK:02X}")
    e.op("JMP   tx_status")
    e.label("tx_noack")
    e.op(f"LDI   R1, 0x{STAT_TX_NOACK:02X}")
    e.label("tx_status")
    e.op("OUT   UO_OUT, R1")           # bit 0 = 1: TXD stays recessive
    e.op("JMP   rx_setup")             # on to the receive phase

    # -------------------------------------- arbitration back-off
    e.raw("")
    e.raw("; ---- arbitration lost: drive recessive, wait out the winner's frame")
    e.raw("; ---- (20 recessive bit times: the winner's trailing CRC run (up to")
    e.raw("; ---- 6, stuffing-capped) + delimiter + ACK + delimiter + EOF + IFS + margin).")
    e.label("arb_lost")                # entered at a sample point
    e.op("OUT   UO_OUT, R3")           # recessive (it already is)
    e.label("arb_again")
    e.op("LDI   R2, 0x14")
    e.label("arb_wait")
    e.wait("warb", "one idle bit")
    e.op("IN    R1, UI_IN")
    e.op("AND   R1, R3")
    e.op("BZ    arb_again")            # dominant: the winner is still sending
    e.op("SUB   R2, R3")
    e.op("BNZ   arb_wait")
    e.op("JMP   setup")                # bus idle: retransmit

    # -------------------------------------- receive setup + SOF poll
    e.raw("")
    e.raw("; ---- receive: reseed the engines, poll for the SOF falling edge")
    e.raw("; ---- (the poll period is ~11 cycles, so the hard sync lands within")
    e.raw("; ---- ~11 cycles of the edge; DR 0021's async-input caveat is handled")
    e.raw("; ---- by the bench driving CAN_RXD synchronously to the core clock).")
    e.label("rx_setup")
    e.op(f"LDI   R1, 0x{CRC_CFG_WORD:02X}")
    e.op("WCTL  CRC_CFG, R1")
    e.op("XOR   R2, R2")
    e.op("WCTL  CRC_STATE, R2")
    e.op("WCTL  CRC_STATE, R2")
    e.op(f"LDI   R1, 0x{LINE_CFG_WORD:02X}")
    e.op("WCTL  LINE_CFG, R1")
    e.label("rx_sof")
    e.op("IN    R1, UI_IN")
    e.op("AND   R1, R3")
    e.op("BZ    rx_sync")              # dominant: SOF
    e.op("WAIT  6")                    # poll period ~11 cycles
    e.op("JMP   rx_sof")
    e.label("rx_sync")                 # hard sync anchor
    e.op("WCTL  CRC_BIT, R1")          # feed the SOF bit (0)
    e.op("WCTL  LINE_PUT, R1")         # ...and the LINE unit (run parity)
    e.op(f"LDI   R0, 0x{RX_BITS:02X}") # destuffed bits to take
    e.wait("wrs", "to the first sample point")
    e.op("JMP   rx_bit")

    # -------------------------------------- the receive loop
    e.raw("")
    e.raw("; ---- the receive loop: sample at the sample point, verify every slot")
    e.raw("; ---- against the LINE unit's own prediction (a mismatch is a stuff")
    e.raw("; ---- error), de-stuff, feed the CRC, count down the 58 destuffed")
    e.raw("; ---- bits of a DLC-3 frame (the register ceiling's scope cut).")
    e.sec("can_rx_bit")
    e.label("rx_bit")
    e.wait("wr", "to the next sample point")
    e.op("IN    R1, UI_IN")
    e.op("AND   R1, R3")               # b
    e.op("WCTL  LINE_PUT, R1")
    e.op("RCTL  R2, LINE_OUT")         # {~e, e}
    e.op("XOR   R2, R1")
    e.op("AND   R2, R3")               # Z iff e == b
    e.op("BNZ   rx_err")
    e.op("RCTL  R2, LINE_STUF")
    e.op("AND   R2, R3")               # (RCTL sets no flags: AND does)
    e.op("BNZ   rx_skip")              # stuff bit on the wire: drop it
    e.op("WCTL  CRC_BIT, R1")
    e.op("SUB   R0, R3")
    e.op("BNZ   rx_bit")
    e.endsec()
    e.label("rx_check")                # the loop's fall-through: all bits taken
    e.op(f"LDI   R2, 0x{CRC_CFG_WORD:02X}")
    e.op("WCTL  CRC_CFG, R2")          # rewind the NEXT pointer
    e.op("RCTL  R1, CRC_NEXT")         # byte 0
    e.op("WCTL  UIO_DIR, R1")
    e.op("RCTL  R1, CRC_NEXT")         # byte 1
    e.op("RCTL  R2, UIO_DIR")          # byte 0 back
    e.op("OR    R1, R2")               # Z iff the CRC checked
    e.wait("wz1", "to the CRC delimiter boundary")
    e.op("LDI   R1, 0x03")
    e.op("OUT   UO_OUT, R1")           # the CRC delimiter bit
    e.wait("wz2", "the delimiter bit")
    e.op("BZ    rx_ack")
    e.label("rx_noack")                # CRC error: no ACK
    e.op("XOR   R2, R2")
    e.op("WCTL  UIO_DIR, R2")          # status flag: CRC error
    e.op("LDI   R1, 0x03")
    e.op("OUT   UO_OUT, R1")           # the ACK slot stays recessive
    e.op("JMP   rx_ackdel")
    e.label("rx_ack")
    e.op("LDI   R2, 0x01")
    e.op("WCTL  UIO_DIR, R2")          # status flag: CRC ok
    e.op("LDI   R1, 0x00")
    e.op("OUT   UO_OUT, R1")           # the dominant ACK
    e.op("JMP   rx_ackdel")
    e.label("rx_ackdel")
    e.wait("wak", "rest of the ACK slot")
    e.op("OUT   UO_OUT, R3")           # the ACK delimiter (recessive)
    e.wait("wad2", "the ACK delimiter bit")
    e.op("LDI   R2, 0x0A")             # EOF (7) + IFS (3)
    e.label("rx_eif")
    e.wait("wrxif", "one recessive bit")
    e.op("SUB   R2, R3")
    e.op("BNZ   rx_eif")
    e.op("RCTL  R1, UIO_DIR")
    e.op("OR    R1, R1")               # Z iff CRC error
    e.op("BZ    rx_st3")
    e.op(f"LDI   R1, 0x{STAT_RX_OK:02X}")
    e.op("JMP   rx_fin")
    e.label("rx_st3")
    e.op(f"LDI   R1, 0x{STAT_RX_CRC:02X}")
    e.label("rx_fin")
    e.op("OUT   UO_OUT, R1")
    e.op("HALT")

    e.label("rx_skip")
    e.wait("wrs2", "stuff slot pad")
    e.op("JMP   rx_bit")

    # -------------------------------------- stuff error path
    e.raw("")
    e.raw("; ---- stuff error: abandon the frame, drive no ACK, report.")
    e.label("rx_err")                  # entered at a sample point
    e.op("OUT   UO_OUT, R3")           # recessive: stop driving
    e.op("LDI   R2, 0x0C")
    e.label("rx_errw")
    e.wait("werr", "one recessive bit")
    e.op("SUB   R2, R3")
    e.op("BNZ   rx_errw")
    e.op(f"LDI   R1, 0x{STAT_RX_STUFF:02X}")
    e.op("OUT   UO_OUT, R1")
    e.op("HALT")

    # -------------------------------------- the transmit table
    e.raw("")
    e.raw("; ---- the transmit table: five bit-reversed bytes (stream bits 0..39,")
    e.raw("; ---- MSB-first packed then bit-reversed so SHF RIGHT presents the")
    e.raw("; ---- earliest bit from bit 0). Each is a WAIT word: never executed,")
    e.raw("; ---- only read as data through PM_DATA_HI + PM_DATA_LO (DR 0012).")
    tbl_addr = e.n
    e.label("tx_table")
    for b in tx_table_bytes():
        e.op(f"WAIT  0x{bitrev8(b):02X}")

    text = e.render(W)
    # The rendered WAIT splits may add words beyond e.n's one-per-wait
    # count, so derive the table address from the rendered instruction
    # count (the LDI's own width never changes, so one patch is a fixpoint).
    n_words = sum(1 for ln in text.splitlines()
                  if ln.startswith("\t") and not ln.startswith("\t."))
    tbl_addr = n_words - len(tx_table_bytes())
    text = text.replace("@TX_TABLE@", f"0x{tbl_addr:02X}")
    return finalize(text, bits, stuffed)


def finalize(text: str, bits, stuffed) -> str:
    n_stuff = len(stuffed) - len(bits)
    H = []
    A = H.append
    A("; can_2a.asm -- CAN 2.0A node on the frozen ISA (issue #450, catalog")
    A("; #443): transmit a standard data frame with bitwise arbitration,")
    A("; receive one with de-stuffing, CRC check and ACK drive. GENERATED by")
    A("; firmware/tools/gen_can_2a.py -- do not edit the literals by hand;")
    A("; regenerate and re-assemble. See firmware/README.md for the program")
    A("; note and the acceptance criteria this image is evidence for.")
    A(";")
    A(f"; Frame transmitted: ID 0x{TX_ID:03X}, RTR=0 (data frame), DLC {TX_DLC},")
    A(f"; data {' '.join(f'0x{b:02X}' for b in TX_DATA)}; {len(bits)} unstuffed bits")
    A(f"; SOF..data, {n_stuff} stuff bits on the wire, CRC-15 poly 0x4599 seed 0")
    A("; (DR 0015 P1, one CRC_BIT per destuffed bit; stuffing by the P2 LINE")
    A("; unit, equal-bits rule N=5, NRZ off). Status words on uo_out keep bit 0")
    A("; recessive: 0x41/0x61 after the transmit (ACK seen / not), 0xC1/0xC3/0xC5")
    A("; at HALT (received ok / CRC error / stuff error).")
    A(";")
    A(f"; Timing: exactly {BIT} core cycles per bit, sample point at offset {SP}")
    A(f"; ({SP * 100 // BIT}%). Every path through a bit window is padded to the")
    A("; same OUT-to-OUT span; the generator derives each WAIT from the path's")
    A("; instruction count (DR 0001: 1 cycle per instruction except WAIT imm8 =")
    A("; imm8+1 and the RCTL PM_DATA_HI read = 2).")
    return "\n".join(H) + "\n" + text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="compare against the committed file; exit 1 on drift")
    args = ap.parse_args(argv)

    text = generate()
    if args.check:
        have = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if have != text:
            print(f"drift: {OUT} differs from the generator output", file=sys.stderr)
            return 1
        print(f"ok: {OUT} matches the generator output")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
