; midi_tx.asm -- send note-on, modulation CC and note-off on MIDI channel 3.
; BIT-PERIOD-CYCLES 1600
        JMP   init             ; skip the inline byte table
        LDI   R0, 0x92         ; table data
        LDI   R0, 0x3C         ; table data
        LDI   R0, 0x55         ; table data
        LDI   R0, 0xB2         ; table data
        LDI   R0, 0x01         ; table data
        LDI   R0, 0x40         ; table data
        LDI   R0, 0x82         ; table data
        LDI   R0, 0x3C         ; table data
        LDI   R0, 0x00         ; table data
init:
        LDI   R1, 1            ; TX mask and first table address
        OUT   UO_OUT, R1       ; TX idles HIGH
        WCTL  PM_ADDR, R1
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_idle:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_idle          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  50            ; 51 cycles
next_byte:
        RCTL  R2, PM_DATA_HI   ; latch the low byte (2 cycles)
        RCTL  R0, PM_DATA_LO   ; payload, advance PM_ADDR
        OUT   UO_OUT, R3       ; START bit (anchor)
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_f0_start:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_start          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  47            ; 48 cycles
        MOV   R2, R0           ; data bit 0
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_f0_b0:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b0          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  46            ; 47 cycles
        MOV   R2, R0           ; data bit 1
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_f0_b1:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b1          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  46            ; 47 cycles
        MOV   R2, R0           ; data bit 2
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_f0_b2:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b2          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  46            ; 47 cycles
        MOV   R2, R0           ; data bit 3
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_f0_b3:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b3          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  46            ; 47 cycles
        MOV   R2, R0           ; data bit 4
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_f0_b4:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b4          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  46            ; 47 cycles
        MOV   R2, R0           ; data bit 5
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_f0_b5:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b5          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  46            ; 47 cycles
        MOV   R2, R0           ; data bit 6
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        SHF   R0, RIGHT
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_f0_b6:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_b6          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  46            ; 47 cycles
        MOV   R2, R0           ; data bit 7
        AND   R2, R1
        OUT   UO_OUT, R2       ; drive data bit (anchor)
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_f0_stop:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_f0_stop          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  49            ; 50 cycles
        OUT   UO_OUT, R1       ; STOP bit
        LDI   R3, 6            ; outer count (assemble-time literal)
dly_stop_hold:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R3, R1           ; count down (never pin data)
        BNZ   dly_stop_hold          ; 6 passes x 258 cycles; R3 == 0 on exit
        WAIT  42            ; 43 cycles
        RCTL  R0, PM_ADDR
        LDI   R2, 10           ; past the last table word
        SUB   R0, R2
        BNZ   next_byte
        HALT                   ; leave TX idle HIGH
