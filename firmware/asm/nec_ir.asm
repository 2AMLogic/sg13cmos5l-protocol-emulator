; nec_ir.asm -- NEC infrared remote-control TRANSMITTER, firmware on the
; frozen ISA (issue #448; multi-protocol extra credit, catalog #443). No
; RTL change, no hardware assist: the 38 kHz carrier is a counted OUT/WAIT
; loop on one pin, and the pulse-distance coding is which of two exact
; space lengths follows each mark.
;
; What it sends, forever: one NEC frame every 128 ms (at row 4's nominal
; 50 MHz clock), then the 60 ms of silence NEC's frame cadence allows.
; A frame is the leader (9 ms mark + 4.5 ms space), 32 bits -- address,
; ~address, command, ~command, least significant bit first -- each a
; 562.5-us-class mark followed by a 562.5-us or a 1,687.5-us space, and a
; final mark. The receiving side (an external 38 kHz demodulating receiver
; module, idle high) sees the envelope of the carrier; a real remote's
; held-button repeat codes are not emitted -- this transmitter sends
; complete frames at the frame cadence, and the model accepts either.
;
; The carrier. One period is exactly 1316 cycles: 439 high (a 1/3 duty,
; the customary NEC choice) and 877 low. At row 4's target 50 MHz
; (unconfirmed; the claim is the cycle count) that is 37,994 Hz, 160 ppm
; below the 38 kHz nominal. A mark is N periods gated by the loop counter:
; the envelope a demodulator recovers runs from the first carrier rise to
; the last carrier fall, so a mark measures (N-1) x 1316 + 439 cycles:
;
;   leader mark   342 periods   449,195 cycles  8,983.90 us  (-0.18%)
;                               (two 171-period bursts, 8-bit counts: the
;                               junction completes its low, so every one of
;                               the 342 periods is exactly 1316 cycles)
;   bit/final mark 22 periods    28,075 cycles    561.50 us  (-0.18%)
;   carrier period              1,316 cycles      26.32 us  (-160 ppm)
;
; The spaces carry the data (pulse-distance coding), and are exact:
;
;   leader space               225,000 cycles   4,500.00 us  (exact)
;   space of a 0 bit            28,125 cycles     562.50 us  (exact)
;   space of a 1 bit            84,375 cycles   1,687.50 us  (exact)
;   inter-frame idle          3,000,000 cycles  60,000.00 us  (exact)
;
; Every NEC figure the model grades sits well inside its window (the
; model's stated tolerance is +-10%; the worst figure here is -0.18%), and
; every cycle count is an assemble-time literal or a fixed-trip-count
; loop: no WAIT's duration depends on the data (DR 0001 "Timing model").
; The one thing that does depend on the data is WHICH space length a bit
; gets -- that is the protocol's own encoding, not an accident: the branch
; that picks it is the assembler's second warning below, and both of its
; paths are padded to their exact totals.
;
; Where the bits come from. The ISA has four registers and no data memory,
; so a whole byte cannot survive a carrier burst (the burst needs all four
; registers: count, pin-high image, zero, one). The table after the code
; therefore holds ONE WORD PER BIT, the bit pre-isolated as the immediate
; of an LDI the program never executes:
;
;   bit = 1   ->  `LDI R0, 0x80`   (word 0x1080)
;   bit = 0   ->  `LDI R0, 0x00`   (word 0x1000)
;   end       ->  `HALT`           (word 0xF000, high byte 0xF0)
;
; Read with DR 0012's PM_DATA_*: the high byte tells bit word (0x10) from
; end marker (0xF0, bit 7 set), the low byte IS the bit (0x80 or 0x00),
; and PM_ADDR auto-increments on each low-byte read, so the table pointer
; is also the frame's bit counter. A host (the bench does) can replace
; the 32 bit words without touching a code word.
;
; Cycle accounting, edge to edge. A pin changes when its OUT retires, so
; an interval between two edges sums the first OUT's own cycle plus the
; instructions between the two OUTs. A carrier period: OUT(1) + WAIT 255 +
; WAIT 181 (438) to the fall OUT, SUB + BNZ + 3x WAIT 255 + WAIT 104 (873)
; + JMP back = 1316, high 439 (WAIT is imm8, so both the 439-cycle high and
; the 877-cycle low are chains of WAITs). A space: the fall OUT(1), SUB + BNZ + JMP(3) out of the
; burst, the space loops, then the 10 cycles of table-read head to the
; next rise OUT -- so each space loop below is padded to (space - 14)
; cycles of its own.
;
; Registers: R1 = 0x80 (the carrier-high image on IR_TX = uo_out[7] and
; the marker-test mask at once -- uo_out[7] is chosen so the pin image and
; the bit-7 mask are the same constant, the ws2812 trick), R2 = 0 (the
; carrier-low image; every OUT writes 0x00 or 0x80), R3 = 1 (the loop
; decrement), R0 the burst count / space counter / table byte. The other
; seven uo_out bits are driven 0 by construction. The program reads no
; pin: it is a transmitter (the receiver-module input pin, ui_in[4], is
; DR 0010's nec_ir_rx role, wired on the board but read by no committed
; image yet).
;
; All microsecond figures are arithmetic at target-spec row 4's
; **unconfirmed** 50 MHz core clock, the same stance as ws2812.asm and
; dmx512_tx.asm: the claim this program and its bench make is the cycle
; count; the us/kHz reading of it is conditional on row 4.
;
; Lint. The assembler reports exactly two data-dependent-branch warnings,
; both branches on table bytes (the RCTL PM_DATA_* reads taint their
; destination): the marker test `BNZ frame_end` and the bit test `BZ
; bit0`. The marker branch picks "one more code word or the end of the
; frame" and both targets are padded to the same 10-cycle rise offset, so
; the final bit's space measures like any other. The bit branch picks the
; bit's OWN space length -- 28,125 or 84,375 -- which is the pulse-distance
; encoding itself: each path is internally exact, and the difference
; between them is the protocol, not a latency leak.

; ------------------------------------------------------------------ setup
        LDI   R1, 0x80        ; 1   carrier-high image / bit-7 mask
        LDI   R2, 0           ; 1   carrier-low image
        OUT   UO_OUT, R2      ; 1   idle: no carrier (mark = carrier on)
        LDI   R3, 1           ; 1   the loop decrement
        LDI   R0, 131         ; 1   FRAME: word address of the bit table
        WCTL  PM_ADDR, R0     ; 1   PM_ADDR -> word 0 of the table

; ------------------------------------------- leader: 9 ms mark, 4.5 ms space
forever:
        LDI   R0, 171         ; 1   the first 171 of the 342 periods (the
                               ;     count is 8-bit: 342 does not fit, so
                               ;     the leader is two 171-period bursts)
ld_a:   OUT   UO_OUT, R1      ; 1   carrier rise
        WAIT  255             ; 256  high
        WAIT  181             ; 182  high 439 (WAIT is imm8: max 256)
        OUT   UO_OUT, R2      ; 1   carrier fall
        SUB   R0, R3          ; 1
        BNZ   ld_ap           ; 1
        WAIT  255             ; 256 complete this period's low, then reload
        WAIT  255             ; 256 (SUB + BNZ + 872 of WAIT + JMP + LDI
        WAIT  255             ; 256  + the rise OUT's own cycle = 877: the
        WAIT  103             ; 104  junction is a seamless 1316-cycle period)
        JMP   ld_j            ; 1
ld_ap:  WAIT  255             ; 256  low
        WAIT  255             ; 256
        WAIT  255             ; 256
        WAIT  104             ; 105  low 877
        JMP   ld_a            ; 1   1316 per period

ld_j:   LDI   R0, 171         ; 1   the second 171 periods: the junction is
                               ;     a seamless 1316-cycle period too
ld_b:   OUT   UO_OUT, R1      ; 1   carrier rise
        WAIT  255             ; 256  high
        WAIT  181             ; 182  high 439
        OUT   UO_OUT, R2      ; 1   carrier fall
        SUB   R0, R3          ; 1
        BNZ   ld_bp           ; 1
        JMP   ld_sp           ; 1   the 342nd fall ended the mark
ld_bp:  WAIT  255             ; 256  low
        WAIT  255             ; 256
        WAIT  255             ; 256
        WAIT  104             ; 105  low 877
        JMP   ld_b            ; 1   1316 per period

ld_sp:  LDI   R1, 4           ; 1   outer count
ld_so:  LDI   R0, 217         ; 1   inner count
.cyclesec nec_ir_leader_space
ld_si:   WAIT  255             ; 256
        SUB   R0, R3          ; 1
        BNZ   ld_si           ; 1   258 per inner iteration
.endcyclesec
        SUB   R1, R3          ; 1
        BNZ   ld_so           ; 1
        WAIT  255             ; 256  pad: 4 x (1 + 217x258 + 1 + 1)
        WAIT  255             ; 256  = 223,956, plus 4 x 256 + 4 below
        WAIT  255             ; 256  makes the loop 224,984; + LDI + JMP
        WAIT  255             ; 256
        WAIT  3               ; 4    = 224,986 = 225,000 - 1 - 3 - 10
        JMP   bit_loop        ; 1

; ------------------------------------------------------- the 32 frame bits
bit_loop:
        RCTL  R1, PM_DATA_HI  ; 2   0x10: a bit word; 0xF0: the marker
        LDI   R0, 0x80        ; 1
        AND   R0, R1          ; 1   0x80 only on the marker (Z on a bit)
        BNZ   frame_end       ; 1   marker: the final mark, then idle
        LDI   R1, 0x80        ; 1   restore the carrier-high image
        RCTL  R0, PM_DATA_LO  ; 1   the bit itself: 0x80 or 0x00; PM_ADDR++
        OR    R0, R0          ; 1   Z iff the bit is 0
        BZ    bit0            ; 1

; ------------- bit = 1: mark 28,075, then the 84,375-cycle space
b1:     LDI   R0, 22          ; 1   22 periods = 561.50 us of carrier
b1_b:   OUT   UO_OUT, R1      ; 1   carrier rise
        WAIT  255             ; 256  high
        WAIT  181             ; 182  high 439 (WAIT is imm8: max 256)
        OUT   UO_OUT, R2      ; 1   carrier fall
        SUB   R0, R3          ; 1
        BNZ   b1_p            ; 1
        JMP   b1_sp           ; 1   the 22nd fall ended the mark
b1_p:   WAIT  255             ; 256  low
        WAIT  255             ; 256
        WAIT  255             ; 256
        WAIT  104             ; 105  low 877
        JMP   b1_b            ; 1   1316 per period

b1_sp:  LDI   R1, 3           ; 1   outer count
b1_so:  LDI   R0, 108         ; 1   inner count
.cyclesec nec_ir_bit1_space
b1_si:   WAIT  255             ; 256
        SUB   R0, R3          ; 1
        BNZ   b1_si           ; 1   258 per inner iteration
.endcyclesec
        SUB   R1, R3          ; 1
        BNZ   b1_so           ; 1
        WAIT  255             ; 256  pad: 3 x (1 + 108x258 + 1 + 1)
        WAIT  255             ; 256  = 83,601, plus 2 x 256 + 246 below
        WAIT  245             ; 246  -> 84,361 = 84,375 - 1 - 3 - 10
        JMP   bit_loop        ; 1

; ------------- bit = 0: mark 28,075, then the 28,125-cycle space
bit0:   LDI   R0, 22          ; 1   22 periods
b0_b:   OUT   UO_OUT, R1      ; 1   carrier rise
        WAIT  255             ; 256  high
        WAIT  181             ; 182  high 439 (WAIT is imm8: max 256)
        OUT   UO_OUT, R2      ; 1   carrier fall
        SUB   R0, R3          ; 1
        BNZ   b0_p            ; 1
        JMP   b0_sp           ; 1
b0_p:   WAIT  255             ; 256  low
        WAIT  255             ; 256
        WAIT  255             ; 256
        WAIT  104             ; 105  low 877
        JMP   b0_b            ; 1   1316 per period

b0_sp:  LDI   R0, 108         ; 1   inner count
.cyclesec nec_ir_bit0_space
b0_si:   WAIT  255             ; 256
        SUB   R0, R3          ; 1
        BNZ   b0_si           ; 1   258 per iteration x 108 = 27,864
.endcyclesec
        WAIT  244             ; 246  pad: 1 + 27,864 + 245 + 1
        JMP   bit_loop        ; 1   = 28,111 = 28,125 - 1 - 3 - 10

; ------------------------- final mark (28,075), then the 60 ms inter-frame idle
frame_end:
        LDI   R1, 0x80        ; 1   restore (the marker read clobbered it)
        WAIT  2               ; 3   the marker path is 3 cycles shorter
                               ;     than the bit path; this pads it level
        LDI   R0, 22          ; 1   22 periods, the frame's last mark
fe_b:   OUT   UO_OUT, R1      ; 1   carrier rise
        WAIT  255             ; 256  high
        WAIT  181             ; 182  high 439 (WAIT is imm8: max 256)
        OUT   UO_OUT, R2      ; 1   carrier fall
        SUB   R0, R3          ; 1
        BNZ   fe_p            ; 1
        JMP   fe_sp           ; 1
fe_p:   WAIT  255             ; 256  low
        WAIT  255             ; 256
        WAIT  255             ; 256
        WAIT  104             ; 105  low 877
        JMP   fe_b            ; 1   1316 per period

fe_sp:  LDI   R1, 46          ; 1   outer count
fe_so:  LDI   R0, 252         ; 1   inner count
.cyclesec nec_ir_idle_space
fe_si:   WAIT  255             ; 256
        SUB   R0, R3          ; 1
        BNZ   fe_si           ; 1   258 per inner iteration
.endcyclesec
        SUB   R1, R3          ; 1
        BNZ   fe_so           ; 1   46 x 65,019 = 2,990,874
        LDI   R0, 35          ; 1   pad loop: 1 + 35 x 258 = 9,031
fe_pi:  WAIT  255             ; 256
        SUB   R0, R3          ; 1
        BNZ   fe_pi           ; 1
        WAIT  84              ; 85   pad to exactly 3,000,000 (measured at
                               ;     the pin: fall-to-rise, as the bench
                               ;     asserts it)
        LDI   R1, 0x80        ; 1   restore the carrier-high image (the
                               ;     idle's outer counter clobbered it)
        LDI   R0, 131         ; 1   FRAME: rewind the table
        WCTL  PM_ADDR, R0     ; 1
        JMP   forever         ; 1

; ------------------------------------------------------- the frame table
; Within each byte the first word sends bit 0 and the last sends bit 7.
; Address 0xA5 and command 0x3C each read the same in either direction.
; The RTL bench also loads asymmetric bytes to exercise the wire order.
frame:
        LDI   R0, 0x80        ; addr    0xA5 = 1010 0101
        LDI   R0, 0x00        ; 0
        LDI   R0, 0x80        ; 1
        LDI   R0, 0x00        ; 0
        LDI   R0, 0x00        ; 0
        LDI   R0, 0x80        ; 1
        LDI   R0, 0x00        ; 0
        LDI   R0, 0x80        ; 1
        LDI   R0, 0x00        ; ~addr   0x5A = 0101 1010
        LDI   R0, 0x80        ; 1
        LDI   R0, 0x00        ; 0
        LDI   R0, 0x80        ; 1
        LDI   R0, 0x80        ; 1
        LDI   R0, 0x00        ; 0
        LDI   R0, 0x80        ; 1
        LDI   R0, 0x00        ; 0
        LDI   R0, 0x00        ; cmd     0x3C = 0011 1100
        LDI   R0, 0x00        ;
        LDI   R0, 0x80        ;
        LDI   R0, 0x80        ;
        LDI   R0, 0x80        ;
        LDI   R0, 0x80        ;
        LDI   R0, 0x00        ;
        LDI   R0, 0x00        ;
        LDI   R0, 0x80        ; ~cmd    0xC3 = 1100 0011
        LDI   R0, 0x80        ;
        LDI   R0, 0x00        ;
        LDI   R0, 0x00        ;
        LDI   R0, 0x00        ;
        LDI   R0, 0x00        ;
        LDI   R0, 0x80        ;
        LDI   R0, 0x80        ;
        HALT                   ; end of frame (marker word 0xF000)
