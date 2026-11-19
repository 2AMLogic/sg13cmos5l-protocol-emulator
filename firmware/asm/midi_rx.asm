; midi_rx.asm -- MIDI 1.0 note-on, note-off and control-change monitor.
; BIT-PERIOD-CYCLES 1600
; RX on UI_IN[1]. UO_OUT idles at FF. A complete message emits
; status, data1, data2 on consecutive clocks, then returns to FF.
; R3 holds running status. PM_ADDR holds data1 (FF = empty).
; No program-memory read or write is needed. R0 collects the wire byte.

        LDI   R1, 2
        LDI   R3, 0
        LDI   R2, 0xFF
        OUT   UO_OUT, R2
        WCTL  PM_ADDR, R2
        OUT   UIO_OUT, R3      ; marks and error flag cleared
sync:
        IN    R2, UI_IN        ; wait for an idle-high line
        AND   R2, R1
        BZ    sync
poll:
        IN    R2, UI_IN        ; start-edge detect: loop while the line is high
        AND   R2, R1
        BNZ   poll
        LDI   R2, 18            ; outer count (assemble-time literal)
dly_start:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R2, R1           ; count down (never pin data)
        BNZ   dly_start          ; 9 passes x 258 cycles; R2 == 0 on exit
        WAIT  71            ; 72 cycles
; ---- data bit 0
        IN    R2, UI_IN        ; SAMPLE (bit centre)
        OUT   UIO_OUT, R1      ; sample mark high
        AND   R2, R1
        NOP                    ; RX is bit 1: six shifts reach bit 7; the NOP keeps the 7-cycle slot
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R0, RIGHT        ; make room at bit 7
        OR    R0, R2           ; insert
        LDI   R2, 0            ; preserve running status in R3
        OUT   UIO_OUT, R2      ; sample mark low
        LDI   R2, 12            ; outer count (assemble-time literal)
dly_b0:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R2, R1           ; count down (never pin data)
        BNZ   dly_b0          ; 6 passes x 258 cycles; R2 == 0 on exit
        WAIT  36            ; 37 cycles
; ---- data bit 1
        IN    R2, UI_IN        ; SAMPLE (bit centre)
        OUT   UIO_OUT, R1      ; sample mark high
        AND   R2, R1
        NOP                    ; RX is bit 1: six shifts reach bit 7; the NOP keeps the 7-cycle slot
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R0, RIGHT        ; make room at bit 7
        OR    R0, R2           ; insert
        LDI   R2, 0            ; preserve running status in R3
        OUT   UIO_OUT, R2      ; sample mark low
        LDI   R2, 12            ; outer count (assemble-time literal)
dly_b1:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R2, R1           ; count down (never pin data)
        BNZ   dly_b1          ; 6 passes x 258 cycles; R2 == 0 on exit
        WAIT  36            ; 37 cycles
; ---- data bit 2
        IN    R2, UI_IN        ; SAMPLE (bit centre)
        OUT   UIO_OUT, R1      ; sample mark high
        AND   R2, R1
        NOP                    ; RX is bit 1: six shifts reach bit 7; the NOP keeps the 7-cycle slot
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R0, RIGHT        ; make room at bit 7
        OR    R0, R2           ; insert
        LDI   R2, 0            ; preserve running status in R3
        OUT   UIO_OUT, R2      ; sample mark low
        LDI   R2, 12            ; outer count (assemble-time literal)
dly_b2:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R2, R1           ; count down (never pin data)
        BNZ   dly_b2          ; 6 passes x 258 cycles; R2 == 0 on exit
        WAIT  36            ; 37 cycles
; ---- data bit 3
        IN    R2, UI_IN        ; SAMPLE (bit centre)
        OUT   UIO_OUT, R1      ; sample mark high
        AND   R2, R1
        NOP                    ; RX is bit 1: six shifts reach bit 7; the NOP keeps the 7-cycle slot
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R0, RIGHT        ; make room at bit 7
        OR    R0, R2           ; insert
        LDI   R2, 0            ; preserve running status in R3
        OUT   UIO_OUT, R2      ; sample mark low
        LDI   R2, 12            ; outer count (assemble-time literal)
dly_b3:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R2, R1           ; count down (never pin data)
        BNZ   dly_b3          ; 6 passes x 258 cycles; R2 == 0 on exit
        WAIT  36            ; 37 cycles
; ---- data bit 4
        IN    R2, UI_IN        ; SAMPLE (bit centre)
        OUT   UIO_OUT, R1      ; sample mark high
        AND   R2, R1
        NOP                    ; RX is bit 1: six shifts reach bit 7; the NOP keeps the 7-cycle slot
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R0, RIGHT        ; make room at bit 7
        OR    R0, R2           ; insert
        LDI   R2, 0            ; preserve running status in R3
        OUT   UIO_OUT, R2      ; sample mark low
        LDI   R2, 12            ; outer count (assemble-time literal)
dly_b4:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R2, R1           ; count down (never pin data)
        BNZ   dly_b4          ; 6 passes x 258 cycles; R2 == 0 on exit
        WAIT  36            ; 37 cycles
; ---- data bit 5
        IN    R2, UI_IN        ; SAMPLE (bit centre)
        OUT   UIO_OUT, R1      ; sample mark high
        AND   R2, R1
        NOP                    ; RX is bit 1: six shifts reach bit 7; the NOP keeps the 7-cycle slot
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R0, RIGHT        ; make room at bit 7
        OR    R0, R2           ; insert
        LDI   R2, 0            ; preserve running status in R3
        OUT   UIO_OUT, R2      ; sample mark low
        LDI   R2, 12            ; outer count (assemble-time literal)
dly_b5:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R2, R1           ; count down (never pin data)
        BNZ   dly_b5          ; 6 passes x 258 cycles; R2 == 0 on exit
        WAIT  36            ; 37 cycles
; ---- data bit 6
        IN    R2, UI_IN        ; SAMPLE (bit centre)
        OUT   UIO_OUT, R1      ; sample mark high
        AND   R2, R1
        NOP                    ; RX is bit 1: six shifts reach bit 7; the NOP keeps the 7-cycle slot
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R0, RIGHT        ; make room at bit 7
        OR    R0, R2           ; insert
        LDI   R2, 0            ; preserve running status in R3
        OUT   UIO_OUT, R2      ; sample mark low
        LDI   R2, 12            ; outer count (assemble-time literal)
dly_b6:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R2, R1           ; count down (never pin data)
        BNZ   dly_b6          ; 6 passes x 258 cycles; R2 == 0 on exit
        WAIT  36            ; 37 cycles
; ---- data bit 7
        IN    R2, UI_IN        ; SAMPLE (bit centre)
        OUT   UIO_OUT, R1      ; sample mark high
        AND   R2, R1
        NOP                    ; RX is bit 1: six shifts reach bit 7; the NOP keeps the 7-cycle slot
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R2, LEFT         ; move the sampled bit up to bit 7
        SHF   R0, RIGHT        ; make room at bit 7
        OR    R0, R2           ; insert
        LDI   R2, 0            ; preserve running status in R3
        OUT   UIO_OUT, R2      ; sample mark low
        LDI   R2, 12            ; outer count (assemble-time literal)
dly_b7:
        WAIT  255              ; 256 cycles + SUB + BNZ = 258 per outer pass
        SUB   R2, R1           ; count down (never pin data)
        BNZ   dly_b7          ; 6 passes x 258 cycles; R2 == 0 on exit
        WAIT  36            ; 37 cycles
; ---- stop bit
        IN    R2, UI_IN        ; SAMPLE the stop bit
        OUT   UIO_OUT, R1      ; sample mark high
        AND   R2, R1
        XOR   R2, R1           ; 1 when the stop bit read 0 (framing error)
        SHF   R2, LEFT         ; -> UIO_OUT bit 2 (SHF leaves Z alone)
        OUT   UIO_OUT, R2      ; also clears the mark
        BZ    parse_byte       ; only a good stop reaches the message parser
        LDI   R3, 0            ; discard running status and the partial message
        JMP   sync             ; wait for idle high after a framing error

parse_byte:
        LDI   R2, 0x80
        AND   R2, R0
        BZ    data_byte
        LDI   R2, 0xF8
        AND   R2, R0
        LDI   R1, 0xF8
        SUB   R2, R1
        BZ    rearm            ; real-time bytes leave running status intact
        LDI   R2, 0xF0
        AND   R2, R0           ; channel voice family
        LDI   R1, 0x80
        SUB   R2, R1
        BZ    status           ; note-off
        LDI   R1, 0x10
        SUB   R2, R1
        BZ    status           ; note-on
        LDI   R1, 0x20
        SUB   R2, R1
        BZ    status           ; control change
        LDI   R3, 0            ; discard unsupported status and its data
        JMP   clear_first
status:
        MOV   R3, R0           ; retain channel as well as family
clear_first:
        LDI   R2, 0xFF
        WCTL  PM_ADDR, R2
rearm:
        LDI   R1, 2            ; restore RX mask / delay decrement
        JMP   poll

data_byte:
        OR    R3, R3
        BZ    rearm            ; stray data before a supported status
        RCTL  R2, PM_ADDR
        LDI   R1, 0x80
        AND   R1, R2
        BZ    publish          ; a saved 7-bit first byte
        WCTL  PM_ADDR, R0
        JMP   rearm
publish:
        LDI   R1, 0xFF
        OUT   UO_OUT, R3       ; status (also for running-status messages)
        OUT   UO_OUT, R2       ; key / controller
        OUT   UO_OUT, R0       ; velocity / value
        OUT   UO_OUT, R1       ; idle
        JMP   clear_first
