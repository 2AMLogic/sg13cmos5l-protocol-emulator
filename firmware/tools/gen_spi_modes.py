#!/usr/bin/env python3
"""Generator for the four `spi_mode{0..3}.asm` programs (issue #319).

The committed `.asm` files under `firmware/asm/` are the evidence (DR 0003);
this script is how they were written, kept so the four (CPOL, CPHA)
variants provably share one instruction stream and differ only in the SCLK
idle bit of the `LDI` images (CPOL) and in which half-period carries the data
edge (CPHA). It does not run in the verification flow.

    python3 firmware/tools/gen_spi_modes.py            # (re)write the four files
    python3 firmware/tools/gen_spi_modes.py --check    # exit 1 on drift

Pin map (uio): CS = bit 0, MOSI = bit 1, MISO = bit 2, SCLK = bit 3.
`spi_mode0_burst3.asm` has a different structure and is not generated here.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "firmware" / "asm"

CS, MOSI, SCLK = 0x01, 0x02, 0x08
CEIL_BYTE = 0xA5   # ceiling-burst MOSI byte
FUNC_BYTE = 0x3C   # functional-burst MOSI byte

HEAD = '''; (issue #72, the SPI third of #23; target-spec rows 1 and 11).
;
; Implements DR 0001's SPI cycle-budget sketch ("SPI (controller,
; mode 0, SCLK <= f_clk/4)") extended to all four (CPOL, CPHA)
; combinations. At the ceiling rate the SCLK period is exactly 4 core
; cycles (SCLK = f_clk/4), so each phase gets a 2-cycle budget, with
; zero added WAIT -- the same budget the sketch states. The sketch's
; literal 4-instruction loop is not writable in this ISA (its SHF
; comment presumes one shift both assembling the sampled MISO bit and
; advancing the MOSI bit through the port image; the real SHF shifts
; one register, fills with 0, and there is no immediate ALU form), so
; this program keeps the sketch's BUDGET with per-bit LDI immediates
; for the data-bearing phase write and a static register for the
; other phase's write; the IN (the MISO sample) is in the loop, as
; the sketch requires. See the evidence record for the dated ISA
; note this files per #72's acceptance criterion 5.
;
; Pin map: DR 0010's target plan, the standard Tiny Tapeout SPI Pmod
; (upper row), adopted by issue #155:
;   uio[0] = CS   (active low; driven by this program)
;   uio[1] = MOSI (driven)
;   uio[2] = MISO (peripheral-driven; sampled by IN on uio_in)
;   uio[3] = SCLK (the Pmod's SCK; idles at CPOL; driven)
; The three controller outputs are push-pull through DR 0012's pin-mode
; register: the setup writes the idle image to UIO_OUT and only THEN
; 0x0B (CS|MOSI|SCLK) to UIO_DIR. uio_out resets to 0x00, so enabling
; the drivers first would assert CS for a cycle. Until the WCTL retires
; every uio pin is an input (DR 0012's reset state). MISO stays an input.
; The received byte is still published on uo_out[7:0].
;
; Two bursts per program, both full-duplex (an IN samples MISO every
; bit), both graded by the independent model in
; verification/test_firmware_spi.py:
;   1. ceiling burst: exactly 4 cycles/bit (SCLK = f_clk/4), MOSI
;      byte 0xA5. The write on the sampling edge carries the data
;      bit; the other phase's write is static (MOSI low) -- the model
;      samples only on the mode-correct edges, so the sampled value is
;      the data bit with a half-period of setup.
;   2. functional burst: 10 cycles/bit, MOSI byte 0x3C, slower so
;      the loop can also EXTRACT and ASSEMBLE the received MISO bits
;      (IN + AND + 2 x SHF + SHF + OR per bit; that extraction cannot fit
;      in the 4-cycle ceiling budget). MISO sits on uio bit 2, so the
;      isolated bit takes two right shifts to reach bit 0 before it is
;      ORed into the accumulator. On the earlier plan (MISO on uio bit 0)
;      it took none and the burst ran at 8 cycles/bit; the two extra
;      instructions per bit do not fit in 8. After CS releases, the
;      assembled byte
;      0x5A-expected is echoed on uo_out[7:0] (bench-checked: the
;      echo window reuses uo_out as a readout bus once the burst is
;      over).
;
; Mode timing (Motorola numbering, per verification/reference_models/
; spi.py -- the model is the authority, not this comment):
'''

HDR_B = ''';
; Every trip count and delay here is an assemble-time literal; the
; program is straight-line (no branches at all), so the assembler's
; TOTAL-CYCLES is the exact execution length and nothing branches on
; pin data (DR 0001 "Timing model").

; ---------------------------------------------------------------- setup
'''

B1_INTRO = '''
; --------------------------------------------- burst 1: ceiling rate
; 4 cycles/bit: OUTs land 2 cycles apart (2-cycle half-periods), the
; IN (MISO sample) rides inside the loop at no timing cost.
'''

B2_BANNER = '''
; ------------------------------------------- burst 2: functional rate
; 10 cycles/bit (OUTs 5 cycles apart): the same full-duplex shape plus
; MISO extraction and assembly -- R0 accumulates the received byte,
; MSB first, and is echoed on uo_out after CS releases. MISO is uio
; bit 2, so the isolated bit is shifted right twice (one SHF in each
; half-period) before it is ORed in at bit 0.
'''

# CPHA=1 only: where the IN sits in the functional burst (issue #309).
NOTE = ''';
; IN placement (issue #309, DR 0021 open item 1): in a CPHA=1 mode the
; leading edge is where the peripheral LAUNCHES MISO and the trailing
; edge is where it is SAMPLED. The IN is therefore instruction 5 of the
; 10-instruction bit -- immediately before the trailing OUT (instruction
; 6), 4 core cycles after the launch edge -- not instruction 2, 1 cycle
; after it. The extraction (AND, SHF, SHF) follows the trailing edge and
; the previous bit's SHF R0 / OR fill the slots after the leading edge, so
; the accumulation lags the sample by one bit; bit 7's SHF R0 / OR run
; after the section, inside the CS-hold cycles. Every OUT is at its
; original cycle.
'''

EDGE = {
    0: ("CPHA=0 -> sampling edge is the leading edge.",
        ["This program drives data on the leading edge (the sampling edge for",
         "CPHA=0) and the static image on the trailing edge."]),
    1: ("CPHA=1 -> sampling edge is the trailing edge.",
        ["This program drives data on the trailing edge (the sampling edge for",
         "CPHA=1) and the static image on the leading edge."]),
}


def hx(v):
    return f"0x{v:02X}"


def bits(byte):
    return [(byte >> (7 - i)) & 1 for i in range(8)]


def build(cpol, cpha):
    n = cpol * 2 + cpha
    name = f"spi_mode{n}"
    idle = cpol * SCLK            # SCLK at its idle level, CS asserted
    active = (1 - cpol) * SCLK    # SCLK at its active level
    out = []

    def a(s=""):
        out.append(s)

    def raw(text):
        out.extend(text.rstrip("\n").split("\n"))

    a(f"; {name}.asm -- bit-banged SPI controller, mode {n} (CPOL={cpol}, CPHA={cpha})")
    raw(HEAD)
    edge, drive = EDGE[cpha]
    a(f";   CPOL={cpol} -> SCLK idles {cpol}; {edge}")
    for d in drive:
        a(f";   {d}")
    raw(HDR_B)
    a(f"        LDI   R2, {hx(idle | CS)}          ; CS released, SCLK at CPOL idle")
    a("        OUT   UIO_OUT, R2       ; the idle image, BEFORE the drivers are on")
    a("        LDI   R3, 0x0B          ; CS|MOSI|SCLK: the pins this program drives")
    a("        WCTL  UIO_DIR, R3       ; DR 0012: push-pull on uio[0], uio[1], uio[3]")
    a("        WAIT  13                 ; 16 cycles of driven idle before the burst")
    raw(B1_INTRO)
    a(f"        LDI   R2, {hx(idle)}          ; CS asserted, SCLK still idle")
    a("        OUT   UIO_OUT, R2          ; CS falls")
    a("        WAIT  3                  ; 4 cycles of CS setup (>= half period)")
    ceil = bits(CEIL_BYTE)
    if cpha == 0:
        a(f"        LDI   R1, {hx(idle)}          ; static image for the trailing phase")
        a(f".cyclesec {name}_ceil")
        for i, m in enumerate(ceil):
            a(f"        LDI   R2, {hx(active | m * MOSI)}          ; bit {i}: SCLK active + MOSI {m}")
            a("        OUT   UIO_OUT, R2          ; leading edge (sampling edge)")
            a(f"        IN    R3, UIO_IN         ; sample MISO (bit {i})")
            a("        OUT   UIO_OUT, R1         ; trailing edge (static image)")
    else:
        a(f"        LDI   R1, {hx(active)}          ; static image for the leading phase")
        a(f"        LDI   R2, {hx(idle | ceil[0] * MOSI)}          ; data image for bit 0 (preloaded)")
        a(f".cyclesec {name}_ceil")
        for i in range(8):
            a("        OUT   UIO_OUT, R1         ; leading edge (static image)")
            a(f"        IN    R3, UIO_IN         ; sample MISO (bit {i})")
            a("        OUT   UIO_OUT, R2         ; trailing edge (sampling edge)")
            if i < 7:
                a(f"        LDI   R2, {hx(idle | ceil[i + 1] * MOSI)}          ; bit {i + 1} data image (next)")
            else:
                a(f"        LDI   R2, {hx(idle)}          ; bit 7 data image (pad, never written)")
    a(".endcyclesec")
    a("        WAIT  3                  ; 4 cycles of CS hold (>= half period)")
    a(f"        LDI   R2, {hx(idle | CS)}          ; CS released, SCLK idle")
    a("        OUT   UIO_OUT, R2          ; CS rises")
    a("        WAIT  31                 ; 32 cycles between bursts")
    raw(B2_BANNER)
    if cpha == 1:
        raw(NOTE)
    a(f"        LDI   R2, {hx(idle)}          ; CS asserted, SCLK still idle")
    a("        OUT   UIO_OUT, R2          ; CS falls")
    a("        WAIT  3                  ; 4 cycles of CS setup")
    a("        LDI   R0, 0x00            ; RX accumulator, cleared")
    a("        LDI   R1, 0x04            ; MISO mask (uio_in bit 2)")
    func = bits(FUNC_BYTE)
    ext = ["        AND   R3, R1            ; isolate MISO bit (uio bit 2)",
           "        SHF   R3, RIGHT         ; MISO bit -> bit 1"]
    if cpha == 0:
        a(f"        LDI   R2, {hx(active | func[0] * MOSI)}          ; data image for bit 0 (preloaded)")
        a(f".cyclesec {name}_func")
        for i in range(8):
            a(f"        OUT   UIO_OUT, R2         ; leading edge (data bit {i})")
            a(f"        IN    R3, UIO_IN        ; sample MISO (bit {i})")
            out.extend(ext)
            a(f"        LDI   R2, {hx(idle)}          ; trailing static image")
            a("        OUT   UIO_OUT, R2         ; trailing edge")
            a("        SHF   R3, RIGHT         ; MISO bit -> bit 0")
            a("        SHF   R0, LEFT          ; RX accumulator <<= 1")
            a("        OR    R0, R3            ; RX accumulator |= MISO bit")
            if i < 7:
                a(f"        LDI   R2, {hx(active | func[i + 1] * MOSI)}          ; bit {i + 1} data image (next)")
            else:
                a(f"        LDI   R2, {hx(idle)}          ; bit 7 data image (pad, never written)")
        a(".endcyclesec")
        a("        WAIT  3                  ; 4 cycles of CS hold")
    else:
        a(f"        LDI   R2, {hx(active)}          ; static leading image (preloaded)")
        a(f".cyclesec {name}_func")
        a("        OUT   UIO_OUT, R2         ; leading edge (static image)")
        a("        LDI   R3, 0x00            ; nothing received yet: clear the MISO register")
        a("        NOP                       ; (slot of the previous bit's SHF R0 / OR)")
        for i in range(8):
            a(f"        LDI   R2, {hx(idle | func[i] * MOSI)}          ; trailing data image (bit {i})")
            a(f"        IN    R3, UIO_IN        ; sample MISO (bit {i}), 4 cycles after the leading edge")
            a("        OUT   UIO_OUT, R2         ; trailing edge (sampling edge)")
            out.extend(ext)
            a("        SHF   R3, RIGHT         ; MISO bit -> bit 0")
            if i < 7:
                a(f"        LDI   R2, {hx(active)}          ; leading static image (next)")
                a("        OUT   UIO_OUT, R2         ; leading edge (static image)")
                a(f"        SHF   R0, LEFT          ; RX accumulator <<= 1 (bit {i}'s turn)")
                a(f"        OR    R0, R3            ; RX accumulator |= MISO bit {i}")
            else:
                a(f"        LDI   R2, {hx(active)}          ; leading static image (pad, never written)")
        a(".endcyclesec")
        a("        SHF   R0, LEFT          ; bit 7's turn (completes the RX byte)")
        a("        OR    R0, R3            ; RX accumulator |= MISO bit 7")
        a("        WAIT  1                  ; 2 more cycles: 4 cycles of CS hold in all")
    a(f"        LDI   R2, {hx(idle | CS)}          ; CS released, SCLK idle")
    a("        OUT   UIO_OUT, R2          ; CS rises")
    a("        OUT   UO_OUT, R0          ; ECHO the assembled RX byte on uo_out[7:0]")
    a("        WAIT  4                  ; hold the echo past the bench window")
    a("        HALT                   ; freeze the core with the echo held")
    return name, "\n".join(out) + "\n"


def main(argv):
    check = "--check" in argv
    drift = False
    for cpol in (0, 1):
        for cpha in (0, 1):
            name, text = build(cpol, cpha)
            path = OUT_DIR / f"{name}.asm"
            if check:
                if not path.exists() or path.read_text() != text:
                    print(f"DRIFT {path}")
                    drift = True
            else:
                path.write_text(text)
                print(f"wrote {path}")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
