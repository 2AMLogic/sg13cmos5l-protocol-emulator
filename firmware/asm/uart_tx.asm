; uart_tx.asm -- bit-banged 8N1 UART transmitter (issue #71, part of #23).
;
; Implements the per-bit inner loop of `spec/decision-records/0001-isa.md`
; section "Per-protocol cycle-budget sketch -> UART (bit-banged, 8N1)":
;
;       MOV  Rtmp, Rshift      ; isolate next bit
;       AND  Rtmp, Rmask       ; Rmask = 0x01
;       OUT  UO_OUT, Rtmp      ; drive TX pin
;       SHF  Rshift, right     ; next bit into position
;       WAIT imm               ; pad to the exact bit period
;
; TX pin: UO_OUT bit 0 (the other seven dedicated outputs are driven 0 by
; construction -- every OUT in this program writes 0x00 or 0x01). The line
; idles HIGH, as asynchronous serial requires.
;
; Bit period: EXACTLY 50 core cycles per bit, which is DR 0001's
; 1,000,000-baud figure *at the target 50 MHz core clock of target-spec
; row 4*. The row-4 clock is unconfirmed on this program's own flow (see
; `verification/records/sta-corner-sweep/`), so the claim this program
; makes and its bench measures is the **cycle count**, not a baud rate:
; 50 cycles/bit, cycle-exact, no data dependence. Any baud figure is
; arithmetic at an unconfirmed clock.
;
; Cycle accounting of the 50-cycle period (DR 0001's opcode table: every
; instruction is 1 cycle except WAIT imm8 = imm8 + 1 cycles):
;
;   per-bit loop body   MOV 1 + AND 1 + OUT 1 + SHF 1 + SUB 1
;                     + WAIT 43 (= 44) + BNZ 1            = 50 cycles
;
; DR 0001's sketch quotes `WAIT 45` for the same 50-cycle period. That is
; the *unrolled* form: a 4-instruction body (MOV/AND/OUT/SHF) plus 46
; padding cycles. This program uses DR 0001's own blessed
; compile-time-constant-trip-count loop shape instead (LDI-loaded count,
; SUB + BNZ body -- the shape `verification/records/core-datapath/` already
; measured at exactly 3 cycles/iteration), so two of those 46 padding
; cycles are spent on SUB + BNZ and the WAIT immediate is 43 rather than
; 45. Same 50-cycle total; the sketch's arithmetic holds unchanged.
;
; Inter-bit alignment outside the loop is padded to the same 50 cycles:
;
;   START -> first data bit   OUT 1 + WAIT 46 (= 47) + MOV 1 + AND 1 = 50
;   last data bit -> STOP     OUT 1 + SHF 1 + SUB 1 + WAIT 43 (= 44)
;                             + BNZ 1 (falls through) + WAIT 1 (= 2) = 50
;
; Two frames are transmitted, 0x5A then 0xA5, so that both the
; last-data-bit-0 and last-data-bit-1 adjacencies to the stop bit are
; exercised and an independent receiver sees back-to-back framing rather
; than a single frame. Every trip count and every delay here is an
; assemble-time literal; nothing branches on pin data, so the frame is
; bit-accurate by construction (DR 0001 "Timing model").

; ---------------------------------------------------------------- setup
        LDI   R1, 1            ; 0x01: bit mask, TX-idle level, and the
                               ; loop decrement constant (no SUBI in the ISA)
        OUT   UO_OUT, R1       ; TX idles HIGH
        WAIT  255              ; 256 cycles of guaranteed idle (> 5 bit
                               ; periods) before the first start bit

; ------------------------------------------------------- frame 1: 0x5A
        LDI   R0, 0x5A         ; payload, shifted out LSB-first
        LDI   R3, 8            ; data-bit trip count (assemble-time literal)
        LDI   R2, 0            ; start-bit level
        OUT   UO_OUT, R2       ; START bit (anchor)
        WAIT  46               ; 47 cycles -> first data bit lands exactly
                               ; 50 cycles after the start bit
f1_bit:
.cyclesec uart_bit_frame1
        MOV   R2, R0           ; isolate next bit
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT        ; next bit into position
        SUB   R3, R1           ; count down (never pin data)
        WAIT  43               ; 44 cycles: pads the body to 50 cycles
        BNZ   f1_bit
.endcyclesec
        WAIT  1                ; 2 cycles -> STOP lands 50 cycles after D7
        OUT   UO_OUT, R1       ; STOP bit (high)
        WAIT  255              ; hold the line idle-high (> 5 bit periods)

; ------------------------------------------------------- frame 2: 0xA5
        LDI   R0, 0xA5
        LDI   R3, 8
        LDI   R2, 0
        OUT   UO_OUT, R2       ; START bit (anchor)
        WAIT  46
f2_bit:
.cyclesec uart_bit_frame2
        MOV   R2, R0
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        SUB   R3, R1
        WAIT  43
        BNZ   f2_bit
.endcyclesec
        WAIT  1
        OUT   UO_OUT, R1       ; STOP bit (high)
        WAIT  255              ; hold idle-high past the frame window
        HALT                   ; freeze the core with TX left idle HIGH
