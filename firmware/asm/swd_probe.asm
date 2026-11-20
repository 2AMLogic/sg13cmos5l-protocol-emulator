; swd_probe.asm -- SWD debug PROBE (host) on the frozen ISA (multi-protocol
; extra credit, issue #452; the protocol choice and the counted cost model are
; the dated note of 2026-11-19 in DR 0018, fourth revision, made after DR
; 0017's ISA freeze at 1696045bfa1a33f93c95a5bf6c29b05f4ea0d734).
;
; Firmware only: base DR 0001 instructions plus DR 0012's runtime pin mode
; (UIO_DIR). No DR 0015 primitive and no hardware assist of any kind.
;
; The role. The chip is the probe (host) and generates SWCLK; the target
; clocks its responses back on SWDIO. Pins (the standard I2C Pmod row, DR
; 0010's swd phase): SWCLK = uio[2] (mask 0x04), SWDIO = uio[3] (mask 0x08).
; Both are push-pull while the probe drives them (UIO_DIR = 0x0C); SWDIO is
; released (its UIO_DIR bit cleared) for the turnaround cycles and the whole
; target-driven response phase, as ADIv5 requires. The board supplies a
; pull-up on SWDIO.
;
; What it does (the agreed fallback of issue #452, measured in DR 0018):
;   1. line reset: >= 50 SWCLK cycles with SWDIO high;
;   2. JTAG-to-SWD switch sequence 0xE79E, LSB first, 16 bits;
;   3. a second line reset, then two idle clocks with SWDIO low;
;   4. a DP read of IDCODE (request 0xA5): 8 request bits, one turnaround
;      cycle, 36 response samples (3-bit ACK, 32 data bits, parity), a
;      second turnaround, SWDIO re-driven;
;   5. a second DP read (request 0xBD, the RDBUFF bank) through the same
;      shape;
;   6. eight trailing idle clocks with SWDIO low, then SWCLK stops (HALT).
; Each response sample is reported on uo_out as it is taken: the masked
; SWDIO byte (0x08 or 0x00), 36 per transaction, in transaction order --
; ACK 001, then the data bits LSB first, then the parity bit. The ACK is
; reported, not branched on: a real probe would check it first (DR 0018's
; note names the branch the legitimate handshake case and says the word
; margin absorbs it). WAIT/FAULT ACK values are therefore reported
; faithfully and not retried.
;
; What does not fit (recorded in DR 0018): the issue's full goal, one word
; of AP memory, needs probe-driven write transactions that do not fit this
; unrolled schedule; a table-driven shape is the recorded follow-up.
;
; Timing, in core cycles (DR 0001: every instruction is 1 cycle). At
; target-spec row 4's target clock of 50 MHz (unconfirmed) one cycle is
; 20 ns. Every SWCLK rising edge is one OUT; the phase widths below are the
; committed program's, and the bench measures them on the pads:
;
;   phase                     SWCLK high   SWCLK low   period
;   line reset / idle tail      1 cycle     3 cycles    4
;   switch / request bits       2 cycles    2 cycles    4
;   response sample loop        1 cycle     7 cycles    8
; SWDIO (probe-driven) changes only while SWCLK is low and is stable across
; every rising edge (one full cycle of setup before each rise). The
; response is sampled by IN in the SWCLK-low phase BEFORE the rise the
; target may advance SWDIO on (IHI 0031 section B4.3.1 permits a target to
; change or release SWDIO on any rising edge).
;
; Registers.
;   R0 = the SWCLK-low/SWDIO-high pin image 0x08; it doubles as the SWDIO
;        mask for the sample loop's AND
;   R1 = the SWCLK-high/SWDIO-high pin image 0x0C; it doubles as the
;        push-pull UIO_DIR mask
;   R2 = loop counter
;   R3 = pin-image / mask / decrement scratch
; Only bits 2 and 3 of an image reach a pad: UIO_DIR enables exactly SWCLK
; and SWDIO. There is no conditional branch on pin data, so the assembler's
; data-dependent-latency lint stays silent.
;
; 201 stored words of DR 0001's 256; 218 SWCLK rising edges; the run is
; 1181 instructions (1182 model edges with the run-phase entry priming
; edge), as DR 0018's note records.

; ------------------------------------------------------------- setup (5)
        LDI   R0, 0x08         ; image: SWCLK low, SWDIO high
        LDI   R1, 0x0C         ; image: SWCLK high, SWDIO high
        OUT   UIO_OUT, R0      ; SWDIO high while SWCLK is still low
        WCTL  UIO_DIR, R1      ; push-pull on SWCLK and SWDIO
        LDI   R3, 1            ; the decrement constant

; ------------------------- line reset: >= 50 cycles, SWDIO high (5)
        LDI   R2, 50
lr1:
        OUT   UIO_OUT, R1      ; SWCLK rises
        OUT   UIO_OUT, R0      ; SWCLK falls
        SUB   R2, R3
        BNZ   lr1

; ----------------- JTAG-to-SWD switch 0xE79E, LSB first (16 x 4 = 64)
; 0xE79E on the wire, bit 0 first: 0 1111 0011 1100 111
        LDI   R3, 0x00         ; bit 0 = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 1 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 2 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 3 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 4 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x00         ; bit 5 = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x00         ; bit 6 = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 7 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 8 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 9 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 10 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x00         ; bit 11 = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x00         ; bit 12 = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 13 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 14 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; bit 15 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise

; --------------- second line reset, SWDIO high, >= 50 cycles (7)
        OUT   UIO_OUT, R0      ; SWCLK falls; SWDIO stays high
        LDI   R2, 50
        LDI   R3, 1            ; reload the decrement constant
lr2:
        OUT   UIO_OUT, R1
        OUT   UIO_OUT, R0
        SUB   R2, R3
        BNZ   lr2

; ------------------------------ idle clocks x2, SWDIO low (10)
        LDI   R3, 0x00
        OUT   UIO_OUT, R3      ; SWDIO falls low
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; idle rise 1
        LDI   R3, 0x00
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; idle rise 2
        LDI   R3, 0x00
        OUT   UIO_OUT, R3      ; leave SWCLK and SWDIO low

; ------------- request 1: DP IDCODE read, 0xA5 LSB first (8 x 4 = 32)
; 0xA5 on the wire, bit 0 first: start 1, APnDP 0, RnW 1, A2 0, A3 0,
; parity 1 (even over APnDP/RnW/A2/A3: one one), stop 0, park 1
        LDI   R3, 0x08         ; start = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x00         ; APnDP = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; RnW = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x00         ; A2 = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x00         ; A3 = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; parity = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x00         ; stop = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; park = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise

; -------- turnaround 1 (5): release SWDIO, clock one turnaround cycle
        OUT   UIO_OUT, R0      ; park-bit fall (SWDIO image high, still driven)
        LDI   R3, 0x04         ; direction: SWCLK only
        WCTL  UIO_DIR, R3      ; release SWDIO for the target
        OUT   UIO_OUT, R1      ; the clocked turnaround cycle (rise)
        OUT   UIO_OUT, R0      ; SWCLK left low for sampling

; -------- sample loop 1 (9): ACK 3 + IDCODE 32 + parity 1, all in the
; -------- SWCLK-low phase before the rise the target may advance on
        LDI   R2, 36
s1:
        IN    R3, UIO_IN       ; sample while SWCLK is low
        AND   R3, R0           ; keep the SWDIO bit (R0 = 0x08)
        OUT   UO_OUT, R3       ; report the masked sample
        OUT   UIO_OUT, R1      ; rise (the target may advance SWDIO here)
        OUT   UIO_OUT, R0      ; fall
        LDI   R3, 1
        SUB   R2, R3
        BNZ   s1

; -------- turnaround after the read parity + re-drive SWDIO (4)
        OUT   UIO_OUT, R1      ; the second turnaround cycle (rise)
        OUT   UIO_OUT, R0      ; fall
        LDI   R3, 0x0C
        WCTL  UIO_DIR, R3      ; re-drive SWDIO push-pull

; ------------- request 2: DP RDBUFF-bank read, 0xBD LSB first (32)
; 0xBD on the wire, bit 0 first: start 1, APnDP 0, RnW 1, A2 1, A3 1,
; parity 1 (even over the four: three ones), stop 0, park 1
        LDI   R3, 0x08         ; start = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x00         ; APnDP = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; RnW = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; A2 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; A3 = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; parity = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x00         ; stop = 0
        OUT   UIO_OUT, R3
        LDI   R3, 0x04
        OUT   UIO_OUT, R3      ; rise
        LDI   R3, 0x08         ; park = 1
        OUT   UIO_OUT, R3
        LDI   R3, 0x0C
        OUT   UIO_OUT, R3      ; rise

; ------------------------------- turnaround 2 (5), same shape as turn 1
        OUT   UIO_OUT, R0      ; park-bit fall
        LDI   R3, 0x04
        WCTL  UIO_DIR, R3      ; release SWDIO
        OUT   UIO_OUT, R1      ; the clocked turnaround cycle (rise)
        OUT   UIO_OUT, R0      ; SWCLK left low for sampling

; --------------------- sample loop 2 (9): ACK 3 + value 32 + parity 1
        LDI   R2, 36
s2:
        IN    R3, UIO_IN
        AND   R3, R0
        OUT   UO_OUT, R3
        OUT   UIO_OUT, R1      ; rise
        OUT   UIO_OUT, R0      ; fall
        LDI   R3, 1
        SUB   R2, R3
        BNZ   s2

; ---------------------- final turnaround + SWDIO re-drive (4)
        OUT   UIO_OUT, R1      ; the second turnaround cycle (rise)
        OUT   UIO_OUT, R0      ; fall
        LDI   R3, 0x0C
        WCTL  UIO_DIR, R3      ; re-drive SWDIO push-pull

; --------------- trailing idle x8, SWDIO low before SWCLK stops (9)
        LDI   R0, 0x00         ; idle image: SWCLK low, SWDIO low
        LDI   R1, 0x04         ; idle image: SWCLK high, SWDIO low
        OUT   UIO_OUT, R0      ; SWDIO falls low (driven)
        LDI   R2, 8
        LDI   R3, 1
idle:
        OUT   UIO_OUT, R1      ; rise
        OUT   UIO_OUT, R0      ; fall
        SUB   R2, R3
        BNZ   idle

        HALT
