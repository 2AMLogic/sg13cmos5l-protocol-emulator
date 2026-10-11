; ws2812.asm -- WS2812 / WS2812B LED-strip controller (target-spec row 13,
; issue #141 part 2; the protocol choice is DR 0018, made after DR 0017's
; ISA freeze at merge commit 1696045bfa1a33f93c95a5bf6c29b05f4ea0d734).
;
; Firmware only: base DR 0001 instructions plus DR 0012's program-memory
; read (PM_ADDR / PM_DATA_HI / PM_DATA_LO). No DR 0015 primitive and no
; hardware assist of any kind.
;
; What it does. Sends N pixels of 24-bit GRB data (G7..G0 R7..R0 B7..B0,
; most significant bit first) on DIN = uo_out[7], holds DIN low for a reset
; of more than 280 us, and repeats the frame forever, as an LED refresh loop
; does. The other seven uo_out bits are always 0 (every OUT writes 0x00 or
; 0x80).
;
; Where the pixels come from. The frame is a table in program memory after
; the code, read with DR 0012's PM_DATA_* reads, one byte per word:
;
;   data byte b   ->  `LDI R0, b`   (word 0x10bb: high byte 0x10, bit 7 clear)
;   end of frame  ->  `HALT`        (word 0xF000: high byte 0xF0, bit 7 set)
;
; The assembler has no data directive (DR 0003), so the table is written as
; instructions the program never executes. A host can replace the table
; (the bench does) without touching a code word.
;
; Timing, in core cycles (DR 0001: every instruction is 1 cycle except
; WAIT imm8 = imm8 + 1, RCTL PM_DATA_HI = 2). At target-spec row 4's
; target clock of 50 MHz (unconfirmed), one cycle is 20 ns. The graded
; values are the WS2812B datasheet's (DR 0018, section 2):
;
;   pulse   cycles   ns at 20 ns   datasheet           window (ns)
;   T0H       20        400        0.40 us +- 150 ns   250 .. 550
;   T1H       40        800        0.80 us +- 150 ns   650 .. 950
;   T0L       43        860        0.85 us +- 150 ns   700 .. 1000
;   T1L       23        460        0.45 us +- 150 ns   300 .. 600
;   bit       63       1260        1.25 us +- 600 ns   650 .. 1850
;   reset  >= 15499  >= 309,980    above 50 us         >= 50,000
;
; Each pulse is the nominal +-10 ns, so every one has at least 140 ns of
; margin to its window edge. 63 cycles per bit is 793.7 kbit/s.
;
; How a bit is made. Without branching on the bit:
;
;   s0   OUT R2 (0x80)          DIN rises
;   s20  OUT R1 (= byte & 0x80) DIN falls here if the bit is 0, stays high if 1
;   s40  OUT R1 (= 0)           DIN falls here if the bit was 1
;   s63  next bit's s0
;
; The bit's value only selects which of two fixed instants DIN falls at.
; No instruction's latency depends on it (target-spec row 3), and nothing
; branches on it. The only branches in a frame are on the bit counter
; (every 8th bit) and on the table's end marker, and both paths through
; each are padded to the same 63 cycles.
;
; Registers: R0 the byte being sent (shifted left), R1 scratch, R2 the
; constant 0x80 (pin image and bit-7 mask at once), R3 the bit counter (a
; 1 shifted left; 8 shifts make it 0).

; ------------------------------------------------------------------ setup
        LDI   R2, 0x80         ; DIN-high pin image, and the bit-7 mask
        LDI   R1, 0
        OUT   UO_OUT, R1       ; DIN low

; ---------------------------------- reset (latch): hold DIN low > 280 us
latch:
        LDI   R3, 1            ; bit counter; also the loop decrement
        LDI   R1, 60           ; 60 x 258 = 15,480 cycles = 309.6 us
latch_loop:
        WAIT  255              ; 256
        SUB   R1, R3           ; 1   (constant trip count, never pin data)
        BNZ   latch_loop       ; 1
        LDI   R1, 35           ; FRAME: word address of the pixel table
        WCTL  PM_ADDR, R1
        RCTL  R1, PM_DATA_HI   ; 2 cycles: the entry's high byte (marker)
        RCTL  R0, PM_DATA_LO   ; 1 cycle: the data byte; PM_ADDR++
        AND   R1, R2           ; Z = 0 on the end marker
        BNZ   latch            ; an empty table: keep the line in reset

; ------------------------------------------------------- one bit, 63 cycles
bit:
.cyclesec ws2812_bit
        OUT   UO_OUT, R2       ; s0   DIN rises
        MOV   R1, R0           ; s1
        AND   R1, R2           ; s2   R1 = 0x80 if the bit is 1, else 0
        SHF   R0, LEFT         ; s3   next bit into bit 7
        WAIT  15               ; s4   16 cycles
        OUT   UO_OUT, R1       ; s20  T0H = 20: DIN falls if the bit is 0
        XOR   R1, R1           ; s21  R1 = 0
        WAIT  17               ; s22  18 cycles
        OUT   UO_OUT, R1       ; s40  T1H = 40: DIN falls if the bit is 1
        SHF   R3, LEFT         ; s41
        OR    R3, R3           ; s42  Z = 1 after the 8th bit of a byte
        BZ    next_byte        ; s43
        WAIT  17               ; s44  18 cycles
        JMP   bit              ; s62  -> s63 = the next bit's s0
.endcyclesec

; ---------- the 8th bit of a byte: fetch the next byte in the same 63 cycles
next_byte:
.cyclesec ws2812_byte_tail
        RCTL  R1, PM_DATA_HI   ; s44  2 cycles: the next entry's marker byte
        RCTL  R0, PM_DATA_LO   ; s46  the next data byte; PM_ADDR++
        AND   R1, R2           ; s47  Z = 0 on the end marker
        LDI   R3, 1            ; s48  bit counter for the new byte
        BNZ   latch            ; s49  end of frame -> reset, then repeat
        WAIT  11               ; s50  12 cycles
        JMP   bit              ; s62  -> s63
.endcyclesec

; ------------------------------------------------- the frame (address 35)
; Eight pixels, GRB, chosen so the bench sees both codes in every bit
; position, runs of each, and the byte boundaries between them.
frame:
        LDI   R0, 0x00         ; pixel 0  G   all zeros
        LDI   R0, 0x00         ;          R
        LDI   R0, 0x00         ;          B
        LDI   R0, 0xFF         ; pixel 1  G   all ones
        LDI   R0, 0xFF         ;          R
        LDI   R0, 0xFF         ;          B
        LDI   R0, 0xFF         ; pixel 2  G   green
        LDI   R0, 0x00         ;          R
        LDI   R0, 0x00         ;          B
        LDI   R0, 0x00         ; pixel 3  G   red
        LDI   R0, 0xFF         ;          R
        LDI   R0, 0x00         ;          B
        LDI   R0, 0x00         ; pixel 4  G   blue
        LDI   R0, 0x00         ;          R
        LDI   R0, 0xFF         ;          B
        LDI   R0, 0xAA         ; pixel 5  G   alternating bits
        LDI   R0, 0x55         ;          R
        LDI   R0, 0xA5         ;          B
        LDI   R0, 0x01         ; pixel 6  G   lone bits at each end
        LDI   R0, 0x80         ;          R
        LDI   R0, 0x7E         ;          B
        LDI   R0, 0x12         ; pixel 7  G
        LDI   R0, 0x34         ;          R
        LDI   R0, 0x56         ;          B
        HALT                   ; end of frame (marker word 0xF000)
