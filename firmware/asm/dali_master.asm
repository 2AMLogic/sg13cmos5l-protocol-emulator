; Single-control-gear DALI demo, short address 0. Send direct arc 0x54
; once, then repeatedly QUERY ACTUAL LEVEL. Only valid replies update RESULT.
; Click interface is non-inverting: low on TX sinks the bus, high releases it.
; R1 = 1 throughout (TX high / countdown step). PM_ADDR holds the second
; forward byte, then the RX shift register. No program-memory data access.
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

; The early polls take 250 cycles each: WAIT (244), IN, SHF, AND, branch, SUB,
; BNZ. RX = uio[1]. Ignore unrelated pads. Require idle throughout the stops
; and early settling period. Then accept a start low up to 22 Te after EOF,
; polling every 25 cycles so the start fall is seen at most 25 cycles late.
; That keeps the phase uncertainty of the sampling deadlines below to 25 cycles.
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
        LDI   R0, 50           ; 50 x 250 x 25 = the former 5 x 250 x 250
window_block:
        LDI   R2, 250
window_poll:
        WAIT  18
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BZ    start_low
        SUB   R2, R1
        BNZ   window_poll
        SUB   R0, R1
        BNZ   window_block
        WAIT  16               ; include the sample at the far edge of the window
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BNZ   query            ; timeout: leave RESULT untouched

start_low:
        WCTL  PM_ADDR, R1      ; leading one shifts out after eight data bits
        LDI   R2, 74           ; start detection can lag by one 25-cycle poll
        WAIT  159              ; last guard poll lands 18,660-18,685 cycles after
                               ; the fall: a 18,600 pulse is always caught, an
                               ; 18,940 (minimum) one never
low_guard:
        WAIT  243
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        BNZ   recover
        SUB   R2, R1
        BNZ   low_guard
        RCTL  R3, PM_ADDR      ; 1 after a start low, 0 after a final zero
        LDI   R2, 181          ; final zero: last sample ~23,159-23,194 cycles
                               ; after the fall, so a valid 23,148 rise is
                               ; seen and a 23,250 one never is
        OR    R3, R3
        BZ    rise_poll
        LDI   R2, 188          ; start low: last sample lands 23,150-23,200 cycles
                               ; after the fall (RTL-bracketed at phases 0, 75,
                               ; 150, 225; the start poll lag is 25 wide)
rise_poll:                     ; sample every 24 cycles near the rising edge
        WAIT  17
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

        LDI   R0, 1            ; start mid-bit rose: RX is high

; R0 bit 0 is the level after the last edge. Bit 1 marks a boundary edge:
; the next edge must then be a mid-bit one, exactly one sender half later.
; From a mid-bit edge, either a boundary at 1 Te or a mid-bit at 2 Te is legal.
; Compare every poll with the last level, including the forbidden intervals.
rx_run: LDI   R2, 74           ; 74 x 255 cycles before the 1 Te window
short_guard:
        WAIT  246
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        XOR   R3, R0
        AND   R3, R1
        BNZ   recover
        SUB   R2, R1
        BNZ   short_guard
        LDI   R2, 180          ; 180 x 24: end near 23,148 cycles
short_window:
        WAIT  15
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        XOR   R3, R0
        AND   R3, R1
        BNZ   short_edge
        SUB   R2, R1
        BNZ   short_window

        LDI   R3, 2
        AND   R3, R0
        BNZ   recover          ; boundary was seen, but no mid-bit edge followed
        LDI   R2, 57           ; 57 x 256 cycles before the 2 Te window
long_guard:
        WAIT  248
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        XOR   R3, R0           ; here R0 is just the previous mid-bit level
        BNZ   recover
        SUB   R2, R1
        BNZ   long_guard
        LDI   R2, 252          ; 252 x 34: end near 46,296 cycles
long_window:
        WAIT  26
        IN    R3, UIO_IN
        SHF   R3, RIGHT
        AND   R3, R1
        XOR   R3, R0
        BNZ   mid_edge
        SUB   R2, R1
        BNZ   long_window
        JMP   recover

short_edge:
        LDI   R3, 2
        AND   R3, R0
        BNZ   mid_edge         ; boundary to mid-bit: append the new level
        LDI   R3, 3            ; mid-bit to boundary: invert level and set bit 1
        XOR   R0, R3
        JMP   rx_run

mid_edge:
        XOR   R0, R1
        AND   R0, R1           ; new mid-bit level is the decoded data bit
        RCTL  R3, PM_ADDR
        LDI   R2, 0x80
        AND   R2, R3           ; has the leading one reached bit 7?
        SHF   R3, LEFT
        OR    R3, R0
        WCTL  PM_ADDR, R3
        OR    R2, R2
        BZ    rx_run
        MOV   R0, R3           ; complete byte, held until both stops pass
        LDI   R3, 0
        WCTL  PM_ADDR, R3      ; a final zero's stop rise goes to stop_high
        MOV   R3, R0
        AND   R3, R1
        LDI   R2, 74
        BZ    final_low        ; final zero: stop must rise after one half-bit

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

; Final zero: the fall was seen by a 24- or 34-cycle poll, so the last guard
; poll lands 18,816-18,859 cycles after it. A 18,600 stop-side low is always
; caught and the 18,940 minimum never is.
final_low:
        WAIT  255
        WAIT  42
        JMP   low_guard
