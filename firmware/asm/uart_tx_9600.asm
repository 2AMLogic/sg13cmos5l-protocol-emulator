; uart_tx_9600.asm -- bit-banged 8N1 UART transmitter, 5208 core cycles per bit.
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

        LDI   R1, 1
        LDI   R3, 0
        OUT   UO_OUT, R1       ; TX idles HIGH
        LDI   R3, 40            ; outer count (assemble-time literal)
dly_idle0:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_idle0          ; 40 passes x 258 cycles; R3 == 0 on exit
        WAIT  94            ; 95 cycles
; ------------------------------------------------- frame 1: 0x5A
        LDI   R0, 0x5A
        OUT   UO_OUT, R3       ; START bit (anchor)
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f0_start:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_start          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  43            ; 44 cycles
        MOV   R2, R0           ; data bit 0
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f0_b0:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b0          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 1
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f0_b1:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b1          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 2
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f0_b2:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b2          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 3
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f0_b3:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b3          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 4
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f0_b4:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b4          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 5
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f0_b5:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b5          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 6
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f0_b6:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b6          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 7
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f0_stop:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_stop          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  45            ; 46 cycles
        OUT   UO_OUT, R1       ; STOP bit
        LDI   R3, 40            ; outer count (assemble-time literal)
dly_f0_idle:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_idle          ; 40 passes x 258 cycles; R3 == 0 on exit
        WAIT  94            ; 95 cycles
; ------------------------------------------------- frame 2: 0xA5
        LDI   R0, 0xA5
        OUT   UO_OUT, R3       ; START bit (anchor)
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f1_start:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_start          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  43            ; 44 cycles
        MOV   R2, R0           ; data bit 0
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f1_b0:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b0          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 1
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f1_b1:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b1          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 2
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f1_b2:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b2          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 3
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f1_b3:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b3          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 4
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f1_b4:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b4          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 5
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f1_b5:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b5          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 6
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f1_b6:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_b6          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        MOV   R2, R0           ; data bit 7
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        LDI   R3, 20            ; outer count (assemble-time literal)
dly_f1_stop:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_stop          ; 20 passes x 258 cycles; R3 == 0 on exit
        WAIT  45            ; 46 cycles
        OUT   UO_OUT, R1       ; STOP bit
        LDI   R3, 40            ; outer count (assemble-time literal)
dly_f1_idle:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f1_idle          ; 40 passes x 258 cycles; R3 == 0 on exit
        WAIT  94            ; 95 cycles
        HALT                   ; TX left idle HIGH
