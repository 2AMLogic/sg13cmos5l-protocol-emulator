; swd_probe.asm -- SWD debug PROBE (host) on the frozen ISA, reading one word
; of AP memory (multi-protocol extra credit, issues #452 and #500; the protocol
; choice and the counted cost model are the dated notes in DR 0018, made after
; DR 0017's ISA freeze at 1696045bfa1a33f93c95a5bf6c29b05f4ea0d734).
;
; Firmware only: base DR 0001 instructions plus DR 0012's runtime pin mode
; (UIO_DIR) and its program-memory read port (PM_ADDR / PM_DATA_*). No DR 0015
; primitive and no hardware assist of any kind.
;
; The role. The chip is the probe (host) and generates SWCLK; the target
; clocks its responses back on SWDIO. Pins (the standard I2C Pmod row, DR
; 0010's swd phase): SWCLK = uio[2] (mask 0x04), SWDIO = uio[3] (mask 0x08).
; Both are push-pull while the probe drives them (UIO_DIR = 0x0C); SWDIO is
; released (its UIO_DIR bit cleared) for the turnaround cycles and the whole
; target-driven response phase, as ADIv5 requires. The board supplies a
; pull-up on SWDIO.
;
; What it does (the follow-up #500 closes: DR 0018's recorded fallback, plus
; the probe-driven writes that did not fit the unrolled schedule):
;   1. line reset: >= 50 SWCLK cycles with SWDIO high;
;   2. JTAG-to-SWD switch sequence 0xE79E, LSB first, 16 bits;
;   3. a second line reset, then two idle clocks with SWDIO low;
;   4. five transactions, each an 8-bit request, one turnaround cycle, the
;      3-bit ACK, and then either 33 read bits (32 data + parity) from the
;      target or 33 write bits (32 data + parity) from the probe:
;        DP IDCODE read      request 0xA5
;        DP SELECT write     request 0xB1, data 0x00000000
;        AP TAR write        request 0x8B, data 0x20000004
;        AP DRW read         request 0x9F  (POSTED: returns the previous
;                                           read-buffer value, not the word)
;        DP RDBUFF read      request 0xBD  (returns the addressed word)
;   5. eight trailing idle clocks with SWDIO low, then SWCLK stops (HALT).
; Each response sample is reported on uo_out as it is taken: the masked
; SWDIO byte (0x08 or 0x00), in transaction order -- the ACK in wire order
; (OK = 1,0,0: numeric 0b001 sent LSB first; WAIT = 0,1,0; FAULT = 0,0,1),
; then, for a read with an OK, the 32 data bits LSB first and the parity bit.
; The probe branches on the first ACK bit (the one sanctioned handshake
; branch): a 1 is an OK and continues; a 0 is a WAIT or FAULT, which with
; CTRL/STAT.ORUNDETECT = 0 has no data phase (a rejected write sends no
; data), so the probe clocks the remaining two ACK slots and the return
; turnaround (SWDIO released), re-drives SWDIO low and ends the run with the
; eight trailing idle clocks. No retry. An error on any transaction ends the
; run there: the later transactions, and so the memory read, are not issued.
;
; Table-driven shape. The first fallback image (227 stored words) unrolled
; four words per request bit; a 33-bit write data phase did not fit beside
; it. This image keeps every probe-driven bit as DATA in program memory and
; sends it with one shared loop. The ISA has no data memory, but DR 0012's
; PM_ADDR / PM_DATA_HI / PM_DATA_LO read stored words, the way the NEC IR
; program reads its bit table. A table word is an LDI the program never
; executes (the assembler checks it like any other instruction):
;   bit 1  ->  LDI R2, 0x0C   (word 0x180C)      bit 0  ->  LDI R0, 0x04
; the HIGH byte (0x18 / 0x10) has bit 3 set only for a 1 -- ANDed with the
; SWDIO mask it IS the SWCLK-low pin image -- and the LOW byte is the
; SWCLK-high image. One word per bit; the loop is 8 words (txq) and serves
; the request bits and the write-data bits of every transaction. The table
; also carries the control words the engine reads between the passes:
;   start word  0x10xx  another transaction follows, xx = 8 request bits
;               0x18xx  the end of the table
;   after the request   0x10xx  a response follows, xx = the slots after the
;                               first ACK bit (35 for a read, 2 for a write)
;   after the response  0x10xx  write data follows, xx = 33 bits
;                       0x18xx  none: the transaction is complete
;   after write data    0x18xx  the transaction is complete
; so the sequence of transactions, their kind and their length are all data.
; The table pointer PM_ADDR advances on every low-byte read and is never
; written again after the table start.
;
; Timing, in core cycles (DR 0001: every instruction is 1 cycle; the PM_DATA_HI
; read is a fixed 2). At target-spec row 4's target clock of 50 MHz
; (unconfirmed) one cycle is 20 ns. Every SWCLK rising edge is one OUT; the
; widths are the committed program's, and the bench measures them on the pads:
;
;   phase                     SWCLK high   SWCLK low   period
;   line reset                  1 cycle     3 cycles    4
;   switch / request bits       7 cycles    2 cycles    9   (table loop)
;   write-data bits             7 cycles    2 cycles    9   (table loop)
;   idle tail                   2 cycles    2 cycles    4
;   response sample loop        1 cycle   4..7 cycles   5..8
; SWDIO (probe-driven) changes only while SWCLK is low, on the same OUT that
; lowers SWCLK, and is stable across every rising edge (2 cycles of setup).
; The response is sampled by IN in the SWCLK-low phase BEFORE the rise the
; target may advance SWDIO on (IHI 0031 section B4.3.1 permits a target to
; change or release SWDIO on any rising edge).
;
; Registers.
;   R0 = the SWCLK-low/SWDIO-high pin image 0x08; it doubles as the SWDIO
;        mask for the table loop and the sample loop's AND
;   R1 = the SWCLK-high/SWDIO-high pin image 0x0C; it doubles as the
;        push-pull UIO_DIR mask
;   R2 = loop counter / the count word read from the table
;   R3 = pin-image / table-byte / decrement scratch
; Only bits 2 and 3 of an image reach a pad: UIO_DIR enables exactly SWCLK
; and SWDIO.
;
; Lint. The assembler's data-dependent-latency lint reports six branches. One
; (BZ ackerr, after AND of an IN sample) reads the target's ACK from the pin:
; the documented handshake case. The other five branch on a table byte or on
; a loop count read from the table (BNZ tail, BNZ txn after the two control
; words, and the loop-count SUBs of txq and rx): the data is the program's own
; constant table, so the schedule is fixed at assemble time -- the NEC IR
; program's shape and the same documented reading of the lint.
;
; 245 stored words of DR 0001's 256 (105 code, 140 table); 356 SWCLK rising
; edges on the all-OK path; the last SWCLK fall is at core edge 2595. DR
; 0018's note recorded the 227-word fallback image this one replaces.

; ------------------------------------------------------------- setup (5)
        LDI   R0, 0x08         ; image: SWCLK low, SWDIO high; also the mask
        LDI   R1, 0x0C         ; image: SWCLK high, SWDIO high; also push-pull
        OUT   UIO_OUT, R0      ; SWDIO high while SWCLK is still low
        WCTL  UIO_DIR, R1      ; push-pull on SWCLK and SWDIO
        LDI   R2, 50

; ------------------------- line reset: >= 50 cycles, SWDIO high (5)
        LDI   R3, 1            ; the decrement constant
lr1:
        OUT   UIO_OUT, R1      ; SWCLK rises
        OUT   UIO_OUT, R0      ; SWCLK falls
        SUB   R2, R3
        BNZ   lr1

; ---- JTAG-to-SWD switch 0xE79E, LSB first, 16 table entries (3 + 8)
        LDI   R3, 116           ; word address of the first table entry
        WCTL  PM_ADDR, R3      ; the table pointer
        LDI   R2, 16
sw:
        RCTL  R3, PM_DATA_HI   ; 2  high byte: bit 3 = the SWDIO level
        AND   R3, R0           ; 0x00 or 0x08
        OUT   UIO_OUT, R3      ; SWCLK falls, SWDIO = the bit
        RCTL  R3, PM_DATA_LO   ; 1  low byte = the rise image; PM_ADDR++
        OUT   UIO_OUT, R3      ; SWCLK rises
        LDI   R3, 1
        SUB   R2, R3
        BNZ   sw

; --------------- second line reset, SWDIO high, >= 50 cycles (7)
        OUT   UIO_OUT, R0      ; SWCLK falls; SWDIO stays high
        LDI   R2, 50           ; R3 is still 1 from the switch loop's SUB
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

; ================== the transaction engine, one pass per transaction
; ---- start word: 0x10xx = another transaction (low byte = the request
; ---- bit count, 8), 0x18xx = the end of the table
txn:
        RCTL  R3, PM_DATA_HI
        RCTL  R2, PM_DATA_LO   ; R2 = 8 request bits
        AND   R3, R0
        BNZ   tail             ; the end word

; ---- the one transmit loop: request bits and write-data bits (8)
txq:
        RCTL  R3, PM_DATA_HI   ; 2  high byte: bit 3 = the SWDIO level
        AND   R3, R0           ; 0x00 or 0x08
        OUT   UIO_OUT, R3      ; SWCLK falls, SWDIO = the bit
        RCTL  R3, PM_DATA_LO   ; 1  low byte = the rise image; PM_ADDR++
        OUT   UIO_OUT, R3      ; SWCLK rises
        LDI   R3, 1
        SUB   R2, R3
        BNZ   txq

; ---- the word after a transmit pass: 0x10xx = a response follows (low
; ---- byte = the response samples after the first ACK bit: 35 for a read,
; ---- 2 for a write), 0x18xx = the transaction is complete
        RCTL  R3, PM_DATA_HI
        RCTL  R2, PM_DATA_LO
        AND   R3, R0
        BNZ   txn

; -------- turnaround 1 (5): release SWDIO, clock one turnaround cycle
        OUT   UIO_OUT, R0      ; park-bit fall (SWDIO image high, still driven)
        LDI   R3, 0x04         ; direction: SWCLK only
        WCTL  UIO_DIR, R3      ; release SWDIO for the target
        OUT   UIO_OUT, R1      ; the clocked turnaround cycle (rise)
        OUT   UIO_OUT, R0      ; SWCLK left low for sampling

; -------- ACK slot 0 (6): the first ACK bit decides the transaction. OK is
; -------- 1,0,0 on the wire (numeric 0b001 sent LSB first); WAIT is 0,1,0 and
; -------- FAULT 0,0,1, so a zero first bit is never OK. AND sets Z from it.
; -------- R2 still holds the word read after the request: 2 ACK slots remain.
        IN    R3, UIO_IN       ; sample while SWCLK is low
        AND   R3, R0           ; keep the SWDIO bit (R0 = 0x08); Z = not OK
        OUT   UO_OUT, R3       ; report the masked sample
        OUT   UIO_OUT, R1      ; rise (the target may advance SWDIO here)
        OUT   UIO_OUT, R0      ; fall
        BZ    ackerr           ; WAIT / FAULT: no data phase, end the transfer

; -------- ACK slots 1 and 2 (9): an OK is 1,0,0, so both must be ZERO. A
; -------- one here (a silent target leaves the pulled-up line at 1,1,1; 1,0,1
; -------- and 1,1,0 are not ACK codes) is a protocol error: no data is driven.
ackl:
        IN    R3, UIO_IN
        AND   R3, R0           ; Z = the bit is 0
        OUT   UO_OUT, R3       ; report the masked ACK sample
        OUT   UIO_OUT, R1      ; rise
        OUT   UIO_OUT, R0      ; fall
        BNZ   ackbad           ; not OK: keep SWDIO released, end the run
        LDI   R3, 1
        SUB   R2, R3
        BNZ   ackl

; ---- the word after the ACK (4): 0x18xx = a read, low byte = the 33 data
; ---- slots (32 + parity); 0x10xx = a write, low byte = the 33 write-data
; ---- bits that follow the turnaround
        RCTL  R3, PM_DATA_HI
        RCTL  R2, PM_DATA_LO
        AND   R3, R0
        BZ    ret              ; a write: no target data, straight to the turnaround

; -------- sample loop (8 per slot): a read's 32 data bits and the parity bit
rx:
        IN    R3, UIO_IN       ; sample while SWCLK is low
        AND   R3, R0
        OUT   UO_OUT, R3       ; report the masked sample
        OUT   UIO_OUT, R1      ; rise
        OUT   UIO_OUT, R0      ; fall
        LDI   R3, 1
        SUB   R2, R3
        BNZ   rx

; -------- turnaround after the last response bit + re-drive SWDIO (4)
ret:
        OUT   UIO_OUT, R1      ; the return turnaround cycle (rise)
        OUT   UIO_OUT, R0      ; fall
        LDI   R3, 0x0C
        WCTL  UIO_DIR, R3      ; re-drive SWDIO push-pull

; ---- R2 = 33 after a write (send its data bits), 0 after a read (done) (3)
        AND   R2, R2
        BNZ   txq              ; send the 33 write-data bits
        JMP   txn              ; a read is complete: the next transaction

; ------ not OK (any transaction): ackbad = ACK slot 1 or 2 was a one, so the
; ------ code is no ACK and the target may or may not drive a data phase; keep
; ------ SWDIO RELEASED for the rest of the ACK, the possible 33 data bits and
; ------ the turnaround (35 slots), drive nothing, issue no further request.
; ------ ackerr = WAIT / FAULT (any transaction): the target ends after its
; ------ three ACK bits (CTRL/STAT.ORUNDETECT = 0), so clock the two remaining
; ------ ACK slots (R2 = 2), the return turnaround with SWDIO still released,
; ------ re-drive SWDIO low and end the transfer. No retry (the agreed scope).
ackbad:
        LDI   R2, 35
        JMP   erl
ackerr:
erl:
        IN    R3, UIO_IN
        AND   R3, R0
        OUT   UO_OUT, R3       ; report the masked ACK sample
        OUT   UIO_OUT, R1      ; rise
        OUT   UIO_OUT, R0      ; fall
        LDI   R3, 1
        SUB   R2, R3
        BNZ   erl
        OUT   UIO_OUT, R1      ; the return turnaround cycle (rise), released
        OUT   UIO_OUT, R0      ; fall
        LDI   R3, 0x0C
        WCTL  UIO_DIR, R3      ; re-drive SWDIO push-pull

; --------------- trailing idle x8, SWDIO low before SWCLK stops (9)
tail:
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


; ===================================================================
; The table: one stored word per bit, an LDI the program never executes
; (the NEC IR program's shape). High byte 0x18 = LDI R2 (bit 3 set -> SWDIO
; 1), 0x10 = LDI R0 (bit 3 clear -> SWDIO 0); low byte = the SWCLK-high pin
; image (0x0C / 0x04). Control words: 0x10xx / 0x18xx as described above.
; ===================================================================
; ---- JTAG-to-SWD switch 0xE79E, LSB first (16)
        LDI   R0, 0x04         ; switch bit 0 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; switch bit 1 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; switch bit 2 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; switch bit 3 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; switch bit 4 = 1  (word 0x180C)
        LDI   R0, 0x04         ; switch bit 5 = 0  (word 0x1004)
        LDI   R0, 0x04         ; switch bit 6 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; switch bit 7 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; switch bit 8 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; switch bit 9 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; switch bit 10 = 1  (word 0x180C)
        LDI   R0, 0x04         ; switch bit 11 = 0  (word 0x1004)
        LDI   R0, 0x04         ; switch bit 12 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; switch bit 13 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; switch bit 14 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; switch bit 15 = 1  (word 0x180C)
; ---- DP IDCODE read: request 0xa5 LSB first
        LDI   R0, 8            ; start word: another transaction, 8 request bits
        LDI   R2, 0x0C         ; request bit 0 = 1  (word 0x180C)
        LDI   R0, 0x04         ; request bit 1 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; request bit 2 = 1  (word 0x180C)
        LDI   R0, 0x04         ; request bit 3 = 0  (word 0x1004)
        LDI   R0, 0x04         ; request bit 4 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; request bit 5 = 1  (word 0x180C)
        LDI   R0, 0x04         ; request bit 6 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; request bit 7 = 1  (word 0x180C)
        LDI   R0, 2            ; after the request: a response, 2 slots after the first ACK bit
        LDI   R2, 33           ; after the ACK: a read, 33 data slots (32 + parity)
; ---- DP SELECT write: request 0xb1 LSB first
        LDI   R0, 8            ; start word: another transaction, 8 request bits
        LDI   R2, 0x0C         ; request bit 0 = 1  (word 0x180C)
        LDI   R0, 0x04         ; request bit 1 = 0  (word 0x1004)
        LDI   R0, 0x04         ; request bit 2 = 0  (word 0x1004)
        LDI   R0, 0x04         ; request bit 3 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; request bit 4 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; request bit 5 = 1  (word 0x180C)
        LDI   R0, 0x04         ; request bit 6 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; request bit 7 = 1  (word 0x180C)
        LDI   R0, 2            ; after the request: a response, 2 slots after the first ACK bit
        LDI   R0, 33           ; after the ACK: a write, 33 data bits follow the turnaround
        LDI   R0, 0x04         ; data bit 0 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 1 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 2 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 3 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 4 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 5 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 6 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 7 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 8 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 9 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 10 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 11 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 12 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 13 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 14 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 15 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 16 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 17 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 18 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 19 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 20 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 21 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 22 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 23 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 24 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 25 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 26 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 27 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 28 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 29 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 30 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 31 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data parity = 0  (word 0x1004)
        LDI   R2, 0            ; after the write data: the transaction is complete
; ---- AP TAR write: request 0x8b LSB first
        LDI   R0, 8            ; start word: another transaction, 8 request bits
        LDI   R2, 0x0C         ; request bit 0 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; request bit 1 = 1  (word 0x180C)
        LDI   R0, 0x04         ; request bit 2 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; request bit 3 = 1  (word 0x180C)
        LDI   R0, 0x04         ; request bit 4 = 0  (word 0x1004)
        LDI   R0, 0x04         ; request bit 5 = 0  (word 0x1004)
        LDI   R0, 0x04         ; request bit 6 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; request bit 7 = 1  (word 0x180C)
        LDI   R0, 2            ; after the request: a response, 2 slots after the first ACK bit
        LDI   R0, 33           ; after the ACK: a write, 33 data bits follow the turnaround
        LDI   R0, 0x04         ; data bit 0 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 1 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; data bit 2 = 1  (word 0x180C)
        LDI   R0, 0x04         ; data bit 3 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 4 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 5 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 6 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 7 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 8 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 9 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 10 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 11 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 12 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 13 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 14 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 15 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 16 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 17 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 18 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 19 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 20 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 21 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 22 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 23 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 24 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 25 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 26 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 27 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 28 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; data bit 29 = 1  (word 0x180C)
        LDI   R0, 0x04         ; data bit 30 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data bit 31 = 0  (word 0x1004)
        LDI   R0, 0x04         ; data parity = 0  (word 0x1004)
        LDI   R2, 0            ; after the write data: the transaction is complete
; ---- AP DRW read (posted): request 0x9f LSB first
        LDI   R0, 8            ; start word: another transaction, 8 request bits
        LDI   R2, 0x0C         ; request bit 0 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; request bit 1 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; request bit 2 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; request bit 3 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; request bit 4 = 1  (word 0x180C)
        LDI   R0, 0x04         ; request bit 5 = 0  (word 0x1004)
        LDI   R0, 0x04         ; request bit 6 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; request bit 7 = 1  (word 0x180C)
        LDI   R0, 2            ; after the request: a response, 2 slots after the first ACK bit
        LDI   R2, 33           ; after the ACK: a read, 33 data slots (32 + parity)
; ---- DP RDBUFF read: request 0xbd LSB first
        LDI   R0, 8            ; start word: another transaction, 8 request bits
        LDI   R2, 0x0C         ; request bit 0 = 1  (word 0x180C)
        LDI   R0, 0x04         ; request bit 1 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; request bit 2 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; request bit 3 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; request bit 4 = 1  (word 0x180C)
        LDI   R2, 0x0C         ; request bit 5 = 1  (word 0x180C)
        LDI   R0, 0x04         ; request bit 6 = 0  (word 0x1004)
        LDI   R2, 0x0C         ; request bit 7 = 1  (word 0x180C)
        LDI   R0, 2            ; after the request: a response, 2 slots after the first ACK bit
        LDI   R2, 33           ; after the ACK: a read, 33 data slots (32 + parity)
; ---- end of the table
        LDI   R2, 0            ; start word: end
