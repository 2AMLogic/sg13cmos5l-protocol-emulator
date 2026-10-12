; uart_tx_115200.asm -- bit-banged 8N1 UART transmitter, 434 core cycles per bit.
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

        LDI   R1, 1
        LDI   R3, 0
        OUT   UO_OUT, R1       ; TX idles HIGH
        LDI   R3, 3            ; outer count (assemble-time literal)
dly_idle0:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_idle0          ; 3 passes x 258 cycles; R3 == 0 on exit
        WAIT  94            ; 95 cycles
; ------------------------------------------------- frame 1: 0x5A
        LDI   R0, 0x5A
        OUT   UO_OUT, R3       ; START bit (anchor)
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f0_start:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_start          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  171            ; 172 cycles
        MOV   R2, R0           ; data bit 0
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f0_b0:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b0          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 1
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f0_b1:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b1          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 2
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f0_b2:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b2          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 3
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f0_b3:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b3          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 4
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f0_b4:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b4          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 5
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f0_b5:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b5          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 6
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f0_b6:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b6          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 7
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f0_stop:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_stop          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  173            ; 174 cycles
        OUT   UO_OUT, R1       ; STOP bit
        LDI   R3, 3            ; outer count (assemble-time literal)
dly_f0_idle:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_idle          ; 3 passes x 258 cycles; R3 == 0 on exit
        WAIT  94            ; 95 cycles
; ------------------------------------------------- frame 2: 0xA5
        LDI   R0, 0xA5
        OUT   UO_OUT, R3       ; START bit (anchor)
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f1_start:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_start          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  171            ; 172 cycles
        MOV   R2, R0           ; data bit 0
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f1_b0:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b0          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 1
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f1_b1:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b1          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 2
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f1_b2:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b2          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 3
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f1_b3:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b3          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 4
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f1_b4:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b4          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 5
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f1_b5:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b5          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 6
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f1_b6:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b6          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  170            ; 171 cycles
        MOV   R2, R0           ; data bit 7
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        LDI   R3, 1            ; outer count (assemble-time literal)
dly_f1_stop:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_stop          ; 1 pass x 258 cycles; R3 == 0 on exit
        WAIT  173            ; 174 cycles
        OUT   UO_OUT, R1       ; STOP bit
        LDI   R3, 3            ; outer count (assemble-time literal)
dly_f1_idle:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_idle          ; 3 passes x 258 cycles; R3 == 0 on exit
        WAIT  94            ; 95 cycles
        HALT                   ; TX left idle HIGH
