#!/usr/bin/env python3
"""Generator for the four nested-WAIT UART programs (issue #318).

`firmware/asm/uart_{rx,tx}_{115200,9600}.asm` are the same two programs at
two bit periods. The committed `.asm` files are the evidence (DR 0003); this
script is how they are written, kept so each pair provably shares one
instruction stream and differs only in delay literals, and so a period
change is one number rather than a dozen sites per file. It does not run in
the verification flow (the same arrangement as `gen_i2c_sr.py`).

    python3 firmware/tools/gen_uart_nested.py            # (re)write the four files
    python3 firmware/tools/gen_uart_nested.py --check    # exit 1 on drift

Every delay is "LDI R3 / WAIT 255 / SUB / BNZ" (258 cycles per outer pass)
plus one remainder WAIT. The generator takes a delay's total cycles
(including the LDI), picks the pass count and remainder, and renders the
`LDI` literal and every cycle comment from those numbers. The prose headers
are the evidence text and are carried verbatim per program.
`uart_rx.asm` / `uart_tx.asm` (the 50-cycle programs) are a different
structure and are not generated here.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = ROOT / "firmware" / "asm"

PASS = 258  # WAIT 255 (256) + SUB + BNZ

RX_HEADER = """; {name}.asm -- bit-banged 8N1 UART receiver, {period} core cycles per bit.
;
; Issue #91 (rows 1 and 10): the receive direction. The ISA is the product --
; no UART peripheral exists; the receiver is IN (pin read), WAIT (cycle
; count) and ordinary ALU ops.
;
; BIT-PERIOD-CYCLES {period}
;
{baud_note};
; Pins:
;   RX          UI_IN bit 1 (idle HIGH; DR 0010 target pin plan, USB-bridge
;               option B). UI_IN bit 0 is PROG_SER and plays no part here.
;               Held high by the bench from the MODE drop onward; the program also waits for a high line (`sync`)
;               before arming start detect, so a low line at boot is not a
;               start bit.
;   result      UO_OUT, all 8 bits: the received byte, written as soon as the
;               8th data bit has been sampled; holds until the next frame.
;   sample mark UIO_OUT bit 1: high for the cycles between each `IN` of the
;               line and the following clear. Observability aid so the bench
;               can read the firmware's real sample instants off the pins.
;   frame error UIO_OUT bit 2: set after the stop-bit sample when the stop bit
;               read 0; cleared by the next frame's first sample mark.
;
; Registers: R0 = shift accumulator (bits enter at bit 7, shift right, so
;            the first (LSB) bit lands in bit 0 after 8 shifts)
;            R1 = constant 2 (RX bit mask, XOR mask, sample-mark value and loop
;                 decrement; delay-loop counts below are doubled to match)
;            R2 = pin sample / scratch
;            R3 = constant 0 outside delay loops (strobe clear); the outer
;                 delay counter inside them, back to 0 on exit
;
; Timing, all in core cycles (DR 0001: every instruction 1 cycle, WAIT imm8 =
; imm8 + 1). The start edge is found by a 3-cycle poll (IN, AND, BNZ), so the
; edge is located to within 3 cycles; the first data sample is then placed at
; 1.5 bit periods after detection less the poll/instruction overhead
; (delay {d_start} cycles after the BNZ falls through), i.e. at the centre of data
; bit 0 to within about +-1.5 cycles. Every later sample is exactly
; {period} cycles after the previous one -- nothing between samples branches on
; pin data. The ONLY pin-dependent branches are the `sync`/`poll` handshake
; loops (wait for line high, wait for start edge) and the single post-stop-bit
; choice between re-arming at once and re-syncing, which is why the assembler's
; data-dependent-latency lint emits exactly three warnings for this program;
; all are start-edge/framing handshakes taken AFTER the last sample of a
; frame or BEFORE the first, never between samples (DR 0001 'Timing model').

"""

RX_BAUD_NOTE = {
    434: '; 434 cycles x 20 ns = 8.68 us = ~115,207 baud at the unconfirmed 50 MHz\n; nominal. Needs one outer-loop pass (nested WAIT): a bit period above 256.\n',
    5208: "; 5,208 cycles x 20 ns = 104.16 us = ~9,600.6 baud at the unconfirmed 50 MHz\n; nominal (DR 0001's 9,600-baud figure). Nested WAIT: 20 outer passes.\n",
}

TX_HEADERS = {
    434: """; uart_tx_115200.asm -- bit-banged 8N1 UART transmitter, 434 core cycles per bit.
;
; Issue #281 (rows 1 and 10, the 115,200-class transmit point). Same shape as
; `uart_tx_9600.asm` (compile-time-constant nested WAIT, fully unrolled, no
; instruction branches on pin data) with ONE outer pass per bit instead of 20:
; the same 258-cycle pass `uart_rx_115200.asm` uses (LDI 1; WAIT 255; SUB;
; BNZ) plus a remainder WAIT. 434 is hit exactly; OUT-to-OUT per bit:
;
;   data bit : SHF 1 + LDI 1 + 258 + (WAIT 170 = 171) + MOV/AND/OUT 3 = 434
;   first bit: LDI 1 + 258 + (WAIT 171 = 172) + MOV/AND/OUT 3         = 434
;   stop bit : LDI 1 + 258 + (WAIT 173 = 174) + OUT 1                 = 434
;   start bit: LDI 1 + 258 + (WAIT 171 = 172) + MOV/AND/OUT 3         = 434
;              (as the first bit: the start OUT is followed by the same LDI)
;
; firmware/build/uart_tx_115200.cycles.txt carries the per-instruction counts.
;
; BIT-PERIOD-CYCLES 434
;
; A core-cycle count, not a baud claim: 434 x 20 ns = 8.68 us = ~115,200 baud
; only at the unconfirmed 50 MHz nominal clock (target-spec row 4).
;
; TX pin: UO_OUT bit 0, idle HIGH. Frames 0x5A then 0xA5, LSB first.
; Registers: R0 payload, R1 constant 1, R2 scratch, R3 constant 0 outside
; delay loops / outer counter inside them (0 again on exit).

""",
    5208: """; uart_tx_9600.asm -- bit-banged 8N1 UART transmitter, 5208 core cycles per bit.
;
; Issue #91 (row 10, low-baud end). The outer-loop case `uart_tx.asm` could
; not reach: one WAIT covers at most 256 cycles, so a bit period above that
; uses a compile-time-constant nested loop (LDI count, WAIT 255, SUB, BNZ;
; 258 cycles per outer pass; DR 0001 'Timing model').
;
; BIT-PERIOD-CYCLES 5208
;
; 5,208 cycles x 20 ns = 104.16 us = ~9,600.6 baud at the unconfirmed 50 MHz
; nominal (DR 0001's 9,600-baud figure).
;
; TX pin: UO_OUT bit 0, idle HIGH. Frames 0x5A then 0xA5, LSB first. Fully
; unrolled (eight bit blocks) because the delay loop needs the fourth
; register; no instruction here ever branches on pin data.
; Registers: R0 payload, R1 constant 1, R2 scratch, R3 constant 0 outside
; delay loops / outer counter inside them (0 again on exit).

""",
}

# Idle gap (cycles, including the LDI) before the first frame and after each
# frame's stop bit. Not a function of the period: the 115200 point idles two
# cycles longer than 2 bit periods, the 9600 point exactly 2 (as committed).
TX_IDLE = {434: 870, 5208: 10416}

PROGRAMS = {
    "uart_rx_115200": ("rx", 434),
    "uart_rx_9600": ("rx", 5208),
    "uart_tx_115200": ("tx", 434),
    "uart_tx_9600": ("tx", 5208),
}


def delay(label, total, unit, plural_always):
    """LDI + WAIT-255 outer loop + remainder WAIT summing to `total` cycles.

    `unit` is the loop decrement (RX keeps 2 in R1, TX keeps 1), so the LDI
    literal is passes * unit. The remainder WAIT is 1..256 cycles."""
    passes = (total - 2) // PASS
    rem = total - 1 - PASS * passes
    assert passes >= 1 and 1 <= rem <= 256, (label, total, passes, rem)
    noun = "passes" if plural_always or passes != 1 else "pass"
    return [
        f"        LDI   R3, {passes * unit}            ; outer count (assemble-time literal)",
        f"{label}:",
        "        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass",
        "        SUB   R3, R1           ; count down (never pin data)",
        f"        BNZ   {label}          ; {passes} {noun} x {PASS} cycles; R3 == 0 on exit",
        f"        WAIT  {rem - 1}            ; {rem} cycles",
    ]


def build_rx(name, period):
    d_start = 3 * period // 2 - 5
    out = [RX_HEADER.format(name=name, period=period, d_start=d_start,
                            baud_note=RX_BAUD_NOTE[period]).rstrip("\n"), ""]
    out += [
        "        LDI   R1, 2",
        "        LDI   R3, 0",
        "        OUT   UO_OUT, R3       ; result register cleared",
        "        OUT   UIO_OUT, R3      ; marks and error flag cleared",
        "sync:",
        "        IN    R2, UI_IN        ; wait for an idle-high line",
        "        AND   R2, R1",
        "        BZ    sync",
        "poll:",
        "        IN    R2, UI_IN        ; start-edge detect: loop while the line is high",
        "        AND   R2, R1",
        "        BNZ   poll",
    ]
    out += delay("dly_start", d_start, 2, True)
    for k in range(8):
        out += [
            f"; ---- data bit {k}",
            "        IN    R2, UI_IN        ; SAMPLE (bit centre)",
            "        OUT   UIO_OUT, R1      ; sample mark high",
            "        AND   R2, R1",
            "        NOP                    ; RX is bit 1: six shifts reach bit 7; the NOP keeps the 7-cycle slot",
        ]
        out += ["        SHF   R2, LEFT         ; move the sampled bit up to bit 7"] * 6
        out += [
            "        SHF   R0, RIGHT        ; make room at bit 7",
            "        OR    R0, R2           ; insert",
            "        OUT   UIO_OUT, R3      ; sample mark low",
        ]
        if k == 7:
            out.append("        OUT   UO_OUT, R0       ; emit the received byte")
            out += delay("dly_stop", period - 14, 2, True)
        else:
            out += delay(f"dly_b{k}", period - 13, 2, True)
    out += [
        "; ---- stop bit",
        "        IN    R2, UI_IN        ; SAMPLE the stop bit",
        "        OUT   UIO_OUT, R1      ; sample mark high",
        "        AND   R2, R1",
        "        XOR   R2, R1           ; 1 when the stop bit read 0 (framing error)",
        "        SHF   R2, LEFT         ; -> UIO_OUT bit 2 (SHF leaves Z alone)",
        "        OUT   UIO_OUT, R2      ; also clears the mark",
        "        BZ    poll             ; clean stop bit: re-arm start detect at once",
        "        JMP   sync             ; stop bit read 0: wait for the line to go high first",
    ]
    return "\n".join(out) + "\n"


def build_tx(name, period):
    idle = TX_IDLE[period]
    out = [TX_HEADERS[period].rstrip("\n"), ""]
    out += [
        "        LDI   R1, 1",
        "        LDI   R3, 0",
        "        OUT   UO_OUT, R1       ; TX idles HIGH",
    ]
    out += delay("dly_idle0", idle, 1, False)
    for f, payload in enumerate((0x5A, 0xA5)):
        out += [
            "; ------------------------------------------------- "
            f"frame {f + 1}: 0x{payload:02X}",
            f"        LDI   R0, 0x{payload:02X}",
            "        OUT   UO_OUT, R3       ; START bit (anchor)",
        ]
        out += delay(f"dly_f{f}_start", period - 3, 1, False)
        for k in range(8):
            out += [
                f"        MOV   R2, R0           ; data bit {k}",
                "        AND   R2, R1",
                "        OUT   UO_OUT, R2       ; drive data bit (anchor)",
            ]
            if k < 7:
                out.append("        SHF   R0, RIGHT")
                out += delay(f"dly_f{f}_b{k}", period - 4, 1, False)
            else:
                out += delay(f"dly_f{f}_stop", period - 1, 1, False)
        out.append("        OUT   UO_OUT, R1       ; STOP bit")
        out += delay(f"dly_f{f}_idle", idle, 1, False)
    out.append("        HALT                   ; TX left idle HIGH")
    return "\n".join(out) + "\n"


def build(name):
    kind, period = PROGRAMS[name]
    return (build_rx if kind == "rx" else build_tx)(name, period)


def main(argv):
    check = "--check" in argv
    drift = False
    for name in PROGRAMS:
        text = build(name)
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
