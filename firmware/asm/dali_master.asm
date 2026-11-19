; Single-control-gear DALI demo, short address 0. Send direct arc 0x54
; once, then repeatedly QUERY ACTUAL LEVEL. Only valid replies update RESULT.
; Click interface is non-inverting: low on TX sinks the bus, high releases it.
; R1 = 1 throughout (TX high / countdown step). PM_ADDR holds the second
; forward byte, then the RX bit count. No program-memory data access.
        LDI   R1, 1
        OUT   UIO_OUT, R1
        LDI   R3, 0
        WCTL  UIO_OD, R3
        WCTL  UIO_DIR, R1
        LDI   R3, 0x54
        JMP   forward
query:  LDI   R3, 0xA0
forward:
        WCTL  PM_ADDR, R3
        LDI   R0, 0x80         ; synthetic logical-one start bit in bit 7
        LDI   R2, 17
tx_bit: LDI   R3, 0x80
        AND   R3, R0
        BZ    tx_first_high
        LDI   R3, 0
        OUT   UIO_OUT, R3
        JMP   first_wait
tx_first_high:
        OUT   UIO_OUT, R1
first_wait:
        LDI   R3, 80
tx_a:   WAIT  255              ; TX first half: 80 x 258 plus the tail
        SUB   R3, R1
        BNZ   tx_a
        WAIT  185
        LDI   R3, 0x80
        AND   R3, R0
        BZ    tx_second_low
        OUT   UIO_OUT, R1
        JMP   second_wait
tx_second_low:
        LDI   R3, 0
        OUT   UIO_OUT, R3
second_wait:
        LDI   R3, 80
tx_b:   WAIT  255
        SUB   R3, R1
        BNZ   tx_b
        WAIT  178
        SUB   R2, R1
        BZ    tx_stop
        SHF   R0, LEFT
        LDI   R3, 16
        SUB   R3, R2
        BZ    tx_address
        LDI   R3, 8
        SUB   R3, R2
        BNZ   tx_bit
        RCTL  R0, PM_ADDR
        JMP   tx_bit
tx_address:
        RCTL  R0, PM_ADDR
        LDI   R3, 0x54
        SUB   R0, R3           ; zero = direct arc address 0
        BZ    tx_bit
        LDI   R0, 1            ; short address 0, command selector set
        JMP   tx_bit
tx_stop:
        OUT   UIO_OUT, R1      ; both demo payloads end low: stop rises
        RCTL  R3, PM_ADDR
        LDI   R2, 0x54
        SUB   R3, R2
        BNZ   arm_receiver
        LDI   R0, 21           ; 4 Te stop + at least 22 Te between forwards
direct_gap:
        LDI   R2, 100
direct_inner:
        WAIT  255
        SUB   R2, R1
        BNZ   direct_inner
        SUB   R0, R1
        BNZ   direct_gap
        JMP   query

; One poll is 250 cycles: WAIT (244), IN, SHF, AND, branch, SUB, BNZ.
; RX = uio[1]. Ignore unrelated pads. Require idle throughout the stops
; and early settling period. Then accept a start low up to 22 Te after EOF.
arm_receiver:
        LDI   R0, 4
early_block:
        LDI   R2, 229
early_poll:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BZ    recover
        SUB   R2, R1
        BNZ   early_poll
        SUB   R0, R1
        BNZ   early_block
        LDI   R0, 5
window_block:
        LDI   R2, 250
window_poll:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BZ    start_low
        SUB   R2, R1
        BNZ   window_poll
        SUB   R0, R1
        BNZ   window_block
        WAIT  249              ; include the sample at the far edge of the window
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BNZ   query            ; timeout: leave RESULT untouched

start_low:
        LDI   R0, 0
        LDI   R3, 8
        WCTL  PM_ADDR, R3
        LDI   R2, 72           ; reject a runt start or premature stop transition
low_guard:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BNZ   recover
        SUB   R2, R1
        BNZ   low_guard
        LDI   R2, 23
rise_poll:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BNZ   rose
        SUB   R2, R1
        BNZ   rise_poll
        JMP   recover
rose:   RCTL  R3, PM_ADDR
        OR    R3, R3           ; zero: last zero's second half just ended
        BZ    stop_high

; Synchronize each bit to the previous mid-bit edge. At 1.5 Te the next
; first half is stable across the allowed sender rates. Expect its complement
; near 2 Te (1.79..2.25 Te including polling quantization).
rx_bit: LDI   R2, 121
sample_wait:
        WAIT  255
        SUB   R2, R1
        BNZ   sample_wait
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BZ    first_low
        LDI   R2, 24
high_guard:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BZ    recover
        SUB   R2, R1
        BNZ   high_guard
        LDI   R2, 39
fall_poll:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BZ    got_bit
        SUB   R2, R1
        BNZ   fall_poll
        JMP   recover
first_low:
        LDI   R2, 24
data_low_guard:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BNZ   recover
        SUB   R2, R1
        BNZ   data_low_guard
        LDI   R2, 39
data_rise_poll:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BNZ   got_bit
        SUB   R2, R1
        BNZ   data_rise_poll
        JMP   recover
got_bit:
        SHF   R0, LEFT
        OR    R0, R3           ; normalized second half is the data bit
        RCTL  R3, PM_ADDR
        SUB   R3, R1
        WCTL  PM_ADDR, R3
        BNZ   rx_bit
        MOV   R3, R0
        AND   R3, R1
        LDI   R2, 72
        BZ    low_guard        ; final zero: stop must rise after one half-bit

; A last one has no visible stop edge. Check that final high half as well.
        LDI   R2, 93
last_high:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BZ    recover
        SUB   R2, R1
        BNZ   last_high
stop_high:
        LDI   R3, 2            ; two blocks of 188 x 250 (>= 4 slow Te)
        WCTL  PM_ADDR, R3
stop_block:
        LDI   R2, 188
stop_poll:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BZ    recover
        SUB   R2, R1
        BNZ   stop_poll
        RCTL  R3, PM_ADDR
        SUB   R3, R1
        WCTL  PM_ADDR, R3
        BNZ   stop_block
        OUT   UO_OUT, R0       ; publish only after both idle stop bits
        LDI   R0, 7            ; >= 22 nominal Te after backward EOF
reply_gap:
        LDI   R2, 254
gap_inner:
        WAIT  255
        SUB   R2, R1
        BNZ   gap_inner
        SUB   R0, R1
        BNZ   reply_gap
        JMP   query

; Bad frame: allow the gear to finish. Resume after 26 Te of continuous
; idle, regardless of where the error was seen. A held-low bus stays busy.
recover:
        LDI   R0, 9
idle_block:
        LDI   R2, 241
idle_poll:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BZ    recover
        SUB   R2, R1
        BNZ   idle_poll
        SUB   R0, R1
        BNZ   idle_block
        JMP   query
