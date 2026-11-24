; i2s_tx.asm -- I2S (Philips) controller / transmitter: streams 16-bit
; stereo samples to a DAC (multi-protocol extra credit, issue #451; the
; catalog is #443, docs/protocols.md). Firmware only: base DR 0001
; instructions plus DR 0012's program-memory read and PM_ADDR (no DR 0015
; primitive, no hardware assist; the ISA is frozen by DR 0017).
;
; Pins (DR 0010's `i2s` phase; all three are push-pull uo_out bits and no
; pin is read):
;
;   SD    = uo_out[7]  (0x80)   serial data, MSB first
;   WS    = uo_out[5]  (0x20)   word select / LRCLK, low = left
;   BCLK  = uo_out[6]  (0x40)   bit clock
;
; Framing. Philips I2S, 16-bit samples in 32-BCLK slots (64 BCLK per
; frame): WS and SD change on BCLK's falling edge and are sampled by the
; receiver on its rising edge; WS changes one BCLK BEFORE the slot's MSB
; (so the MSB is sent one BCLK after the WS edge); each slot is 16 data
; bits then 16 zero pad bits; WS low = left.
;
; Timing, in core cycles (DR 0001: every instruction is 1 cycle except
; WAIT imm8 = imm8 + 1 and RCTL PM_DATA_HI = 2). One BCLK period is 16
; cycles, 8 low then 8 high, so a frame is 64 x 16 = 1,024 cycles. At
; target-spec row 4's target clock of 50 MHz (unconfirmed) a cycle is
; 20 ns: BCLK 3.125 MHz, fs = 50 MHz / 1,024 = 48,828.125 Hz (+1.73 %
; over 48 kHz; exactly 48 kHz needs 16.28 cycles per BCLK, which an integer
; cycle count cannot make).
;
; Structure. Every BCLK period is a code block whose first instruction is
; the OUT that drops BCLK (s0) and which has its second OUT, raising BCLK,
; at s8, and ends so that the next block's first OUT lands at s16. Which
; block runs is decided by branches on the bit counter only, never on
; sample data. Per channel, in time order:
;
;   a_*    1 period   WS has just changed, SD = 0 (the last pad bit)
;   hi_*   8 periods  sample bits 15..8, then fetch the low byte
;   lo_*   8 periods  sample bits 7..0
;   pad_* 15 periods  SD = 0, and fetch the next slot's high byte
;
; 1 + 8 + 8 + 15 = 32 BCLK per slot. Registers: R0 the byte being shifted
; out (bit 7 is SD), R1 the pin image for the next half-period, R2 scratch,
; R3 the period counter (a 1 shifted left in hi_/lo_, a down counter in
; pad_).
;
; The samples. A table of 16 stereo frames in the last 64 words of program
; memory (0xC0..0xFF), four words per frame: L high, L low, R high, R low.
; One byte per word, as `LDI R0, b` (the assembler has no data directive,
; DR 0003; the words are never executed), read with PM_DATA_HI / PM_DATA_LO.
; PM_ADDR post-increments on every PM_DATA_LO read; after the 64th table
; word it wraps to 0x00, and the wrap is undone branch-free by ORing 0xC0
; into PM_ADDR in every period of the right slot's pad (harmless once the
; address is already in the table). A host can replace the 64 table words
; without touching a code word (the bench does).
;
; Left: a 16-point sine of full-scale amplitude (one cycle per 16 frames,
; 3.05 kHz at fs); the trough is -32768 (0x8000) on purpose, so both
; extremes 0x7FFF and 0x8000 appear. Right: the same sine at twice the
; frequency (6.10 kHz) at half amplitude.

; ------------------------------------------------------------------ setup
        LDI   R1, 0x00
        OUT   UO_OUT, R1        ; idle: BCLK, WS, SD all low
        LDI   R1, 0xC0
        WCTL  PM_ADDR, R1       ; the table
        RCTL  R2, PM_DATA_HI    ; 2 cycles (the high byte of the entry: unused)
        RCTL  R0, PM_DATA_LO    ; frame 0's left high byte; PM_ADDR++
        LDI   R1, 0x00          ; a_l's pin image: WS low (left), SD 0

; =========================================================== left slot (WS = low)
a_l:
.cyclesec i2s_a_l
        OUT   UO_OUT, R1        ; s0   BCLK falls; WS = 0, SD = 0
        LDI   R2, 0x40          ; s1
        OR    R1, R2            ; s2   the rising-BCLK image
        WAIT  4                 ; s3   5 cycles
        OUT   UO_OUT, R1        ; s8   BCLK rises
        LDI   R1, 0x80          ; s9
        AND   R1, R0            ; s10  SD for the MSB (R0 = the high byte)
        LDI   R3, 1             ; s11   bit counter
        WAIT  3                 ; s12   4 cycles
.endcyclesec
; ---- hi byte: 8 periods
hi_l:
.cyclesec i2s_hi_l_bit
        OUT   UO_OUT, R1        ; s0   BCLK falls; SD/WS change here
        SHF   R3, LEFT          ; s1
        OR    R3, R3            ; s2   Z after the 8th period
        BZ    hi_l_tail       ; s3
        LDI   R2, 0x40          ; s4
        OR    R1, R2            ; s5   the rising-BCLK image
        SHF   R0, LEFT          ; s6   next bit to bit 7
        NOP                     ; s7
        OUT   UO_OUT, R1        ; s8   BCLK rises (the receiver samples SD)
        LDI   R1, 0x80          ; s9
        AND   R1, R0            ; s10  next SD
        WAIT  3                 ; s11  4 cycles
        JMP   hi_l            ; s15
.endcyclesec
hi_l_tail:
.cyclesec i2s_hi_l_tail
        LDI   R2, 0x40          ; s4
        OR    R1, R2            ; s5   the rising-BCLK image
        RCTL  R2, PM_DATA_HI    ; s6   2 cycles: the entry (low byte parked)
        OUT   UO_OUT, R1        ; s8   BCLK rises
        RCTL  R0, PM_DATA_LO    ; s9   the low byte; PM_ADDR++
        LDI   R3, 1             ; s10  bit counter
        LDI   R1, 0x80          ; s11
        AND   R1, R0            ; s12  SD for the low byte's MSB
        WAIT  2                 ; s13  3 cycles
.endcyclesec
; ---- lo byte: 8 periods
lo_l:
.cyclesec i2s_lo_l_bit
        OUT   UO_OUT, R1        ; s0   BCLK falls; SD/WS change here
        SHF   R3, LEFT          ; s1
        OR    R3, R3            ; s2   Z after the 8th period
        BZ    lo_l_tail       ; s3
        LDI   R2, 0x40          ; s4
        OR    R1, R2            ; s5   the rising-BCLK image
        SHF   R0, LEFT          ; s6   next bit to bit 7
        NOP                     ; s7
        OUT   UO_OUT, R1        ; s8   BCLK rises (the receiver samples SD)
        LDI   R1, 0x80          ; s9
        AND   R1, R0            ; s10  next SD
        WAIT  3                 ; s11  4 cycles
        JMP   lo_l            ; s15
.endcyclesec
lo_l_tail:
.cyclesec i2s_lo_l_tail
        LDI   R2, 0x40          ; s4
        OR    R1, R2            ; s5   the rising-BCLK image
        WAIT  1                 ; s6   2 cycles
        OUT   UO_OUT, R1        ; s8   BCLK rises
        LDI   R1, 0x00          ; s9   the pad image: SD 0, WS held
        LDI   R3, 15            ; s10  15 pad periods
        WAIT  4                 ; s11  5 cycles
.endcyclesec
; ---- pad: 15 periods of SD = 0 (the 16 data bits are followed by 15 zeros here,
; and the next slot's a_ period carries the 32nd)
pad_l:
.cyclesec i2s_pad_l_bit
        OUT   UO_OUT, R1        ; s0
        LDI   R2, 0x40          ; s1
        OR    R1, R2            ; s2
        LDI   R2, 1             ; s3
        SUB   R3, R2            ; s4   Z in the 15th period
        BZ    pad_l_last          ; s5
        WAIT  1                 ; s6   2 cycles
        OUT   UO_OUT, R1        ; s8
        LDI   R1, 0x00          ; s9   back to the pad image
        WAIT  4                 ; s10  5 cycles
        JMP   pad_l               ; s15
.endcyclesec
pad_l_last:
.cyclesec i2s_pad_l_last
        RCTL  R2, PM_DATA_HI    ; s6   2 cycles: the next slot's high byte
        OUT   UO_OUT, R1        ; s8
        RCTL  R0, PM_DATA_LO    ; s9   PM_ADDR++
        LDI   R1, 0x20          ; s10  the next a_ image: WS flips, SD 0
        WAIT  4                 ; s11  5 cycles
.endcyclesec

; =========================================================== right slot (WS = high)
a_r:
.cyclesec i2s_a_r
        OUT   UO_OUT, R1        ; s0   BCLK falls; WS = 1, SD = 0
        LDI   R2, 0x40          ; s1
        OR    R1, R2            ; s2   the rising-BCLK image
        WAIT  4                 ; s3   5 cycles
        OUT   UO_OUT, R1        ; s8   BCLK rises
        LDI   R1, 0x80          ; s9
        AND   R1, R0            ; s10  SD for the MSB (R0 = the high byte)
        LDI   R2, 0x20          ; s11
        OR    R1, R2            ; s12  + WS
        LDI   R3, 1             ; s13   bit counter
        WAIT  1                 ; s14   2 cycles
.endcyclesec
; ---- hi byte: 8 periods
hi_r:
.cyclesec i2s_hi_r_bit
        OUT   UO_OUT, R1        ; s0   BCLK falls; SD/WS change here
        SHF   R3, LEFT          ; s1
        OR    R3, R3            ; s2   Z after the 8th period
        BZ    hi_r_tail       ; s3
        LDI   R2, 0x40          ; s4
        OR    R1, R2            ; s5   the rising-BCLK image
        SHF   R0, LEFT          ; s6   next bit to bit 7
        NOP                     ; s7
        OUT   UO_OUT, R1        ; s8   BCLK rises (the receiver samples SD)
        LDI   R1, 0x80          ; s9
        AND   R1, R0            ; s10  next SD
        LDI   R2, 0x20          ; s11
        OR    R1, R2            ; s12  + WS
        WAIT  1                 ; s13  2 cycles
        JMP   hi_r            ; s15
.endcyclesec
hi_r_tail:
.cyclesec i2s_hi_r_tail
        LDI   R2, 0x40          ; s4
        OR    R1, R2            ; s5   the rising-BCLK image
        RCTL  R2, PM_DATA_HI    ; s6   2 cycles: the entry (low byte parked)
        OUT   UO_OUT, R1        ; s8   BCLK rises
        RCTL  R0, PM_DATA_LO    ; s9   the low byte; PM_ADDR++
        LDI   R3, 1             ; s10  bit counter
        LDI   R1, 0x80          ; s11
        AND   R1, R0            ; s12  SD for the low byte's MSB
        LDI   R2, 0x20          ; s13
        OR    R1, R2            ; s14  + WS
        NOP                     ; s15
.endcyclesec
; ---- lo byte: 8 periods
lo_r:
.cyclesec i2s_lo_r_bit
        OUT   UO_OUT, R1        ; s0   BCLK falls; SD/WS change here
        SHF   R3, LEFT          ; s1
        OR    R3, R3            ; s2   Z after the 8th period
        BZ    lo_r_tail       ; s3
        LDI   R2, 0x40          ; s4
        OR    R1, R2            ; s5   the rising-BCLK image
        SHF   R0, LEFT          ; s6   next bit to bit 7
        NOP                     ; s7
        OUT   UO_OUT, R1        ; s8   BCLK rises (the receiver samples SD)
        LDI   R1, 0x80          ; s9
        AND   R1, R0            ; s10  next SD
        LDI   R2, 0x20          ; s11
        OR    R1, R2            ; s12  + WS
        WAIT  1                 ; s13  2 cycles
        JMP   lo_r            ; s15
.endcyclesec
lo_r_tail:
.cyclesec i2s_lo_r_tail
        LDI   R2, 0x40          ; s4
        OR    R1, R2            ; s5   the rising-BCLK image
        WAIT  1                 ; s6   2 cycles
        OUT   UO_OUT, R1        ; s8   BCLK rises
        LDI   R1, 0x20          ; s9   the pad image: SD 0, WS held
        LDI   R3, 15            ; s10  15 pad periods
        WAIT  4                 ; s11  5 cycles
.endcyclesec
; ---- pad: 15 periods of SD = 0 (the 16 data bits are followed by 15 zeros here,
; and the next slot's a_ period carries the 32nd)
pad_r:
.cyclesec i2s_pad_r_bit
        OUT   UO_OUT, R1        ; s0
        LDI   R2, 0x40          ; s1
        OR    R1, R2            ; s2
        LDI   R2, 1             ; s3
        SUB   R3, R2            ; s4   Z in the 15th period
        BZ    pad_r_last          ; s5
        WAIT  1                 ; s6   2 cycles
        OUT   UO_OUT, R1        ; s8
        RCTL  R1, PM_ADDR       ; s9   undo the table-end wrap: PM_ADDR |= 0xC0
        LDI   R2, 0xC0          ; s10
        OR    R1, R2            ; s11
        WCTL  PM_ADDR, R1       ; s12
        LDI   R1, 0x20          ; s13  back to the pad image
        NOP                     ; s14
        JMP   pad_r               ; s15
.endcyclesec
pad_r_last:
.cyclesec i2s_pad_r_last
        RCTL  R2, PM_DATA_HI    ; s6   2 cycles: the next slot's high byte
        OUT   UO_OUT, R1        ; s8
        RCTL  R0, PM_DATA_LO    ; s9   PM_ADDR++
        LDI   R1, 0x00          ; s10  the next a_ image: WS flips, SD 0
        WAIT  3                 ; s11  4 cycles
        JMP   a_l               ; s15  next frame
.endcyclesec

; ------------------------------- alignment filler (words 154..191, never run)
; The table must start at 0xC0 so that `PM_ADDR |= 0xC0` is the wrap. The
; assembler has no .org (DR 0003), so the gap is NOPs after the last
; JMP; control never reaches them.
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP
        NOP

; ---------------------------------------------- the table (address 0xC0)
; 16 stereo frames, 4 words each: L high, L low, R high, R low.
table:
        LDI   R0, 0x00         ; frame  0  L      0 = 0x0000
        LDI   R0, 0x00
        LDI   R0, 0x00         ;           R      0 = 0x0000
        LDI   R0, 0x00
        LDI   R0, 0x30         ; frame  1  L  12539 = 0x30FB
        LDI   R0, 0xFB
        LDI   R0, 0x2D         ;           R  11585 = 0x2D41
        LDI   R0, 0x41
        LDI   R0, 0x5A         ; frame  2  L  23170 = 0x5A82
        LDI   R0, 0x82
        LDI   R0, 0x40         ;           R  16384 = 0x4000
        LDI   R0, 0x00
        LDI   R0, 0x76         ; frame  3  L  30273 = 0x7641
        LDI   R0, 0x41
        LDI   R0, 0x2D         ;           R  11585 = 0x2D41
        LDI   R0, 0x41
        LDI   R0, 0x7F         ; frame  4  L  32767 = 0x7FFF
        LDI   R0, 0xFF
        LDI   R0, 0x00         ;           R      0 = 0x0000
        LDI   R0, 0x00
        LDI   R0, 0x76         ; frame  5  L  30273 = 0x7641
        LDI   R0, 0x41
        LDI   R0, 0xD2         ;           R -11585 = 0xD2BF
        LDI   R0, 0xBF
        LDI   R0, 0x5A         ; frame  6  L  23170 = 0x5A82
        LDI   R0, 0x82
        LDI   R0, 0xC0         ;           R -16384 = 0xC000
        LDI   R0, 0x00
        LDI   R0, 0x30         ; frame  7  L  12539 = 0x30FB
        LDI   R0, 0xFB
        LDI   R0, 0xD2         ;           R -11585 = 0xD2BF
        LDI   R0, 0xBF
        LDI   R0, 0x00         ; frame  8  L      0 = 0x0000
        LDI   R0, 0x00
        LDI   R0, 0x00         ;           R      0 = 0x0000
        LDI   R0, 0x00
        LDI   R0, 0xCF         ; frame  9  L -12539 = 0xCF05
        LDI   R0, 0x05
        LDI   R0, 0x2D         ;           R  11585 = 0x2D41
        LDI   R0, 0x41
        LDI   R0, 0xA5         ; frame 10  L -23170 = 0xA57E
        LDI   R0, 0x7E
        LDI   R0, 0x40         ;           R  16384 = 0x4000
        LDI   R0, 0x00
        LDI   R0, 0x89         ; frame 11  L -30273 = 0x89BF
        LDI   R0, 0xBF
        LDI   R0, 0x2D         ;           R  11585 = 0x2D41
        LDI   R0, 0x41
        LDI   R0, 0x80         ; frame 12  L -32768 = 0x8000
        LDI   R0, 0x00
        LDI   R0, 0x00         ;           R      0 = 0x0000
        LDI   R0, 0x00
        LDI   R0, 0x89         ; frame 13  L -30273 = 0x89BF
        LDI   R0, 0xBF
        LDI   R0, 0xD2         ;           R -11585 = 0xD2BF
        LDI   R0, 0xBF
        LDI   R0, 0xA5         ; frame 14  L -23170 = 0xA57E
        LDI   R0, 0x7E
        LDI   R0, 0xC0         ;           R -16384 = 0xC000
        LDI   R0, 0x00
        LDI   R0, 0xCF         ; frame 15  L -12539 = 0xCF05
        LDI   R0, 0x05
        LDI   R0, 0xD2         ;           R -11585 = 0xD2BF
        LDI   R0, 0xBF
